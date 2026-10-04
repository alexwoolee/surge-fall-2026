"""Prompt-scoped Control sessions; all data access remains on remote workers."""

import asyncio
from contextlib import asynccontextmanager
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timedelta
import os
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse

from backend.control.briefing import render_briefing_html
from backend.control.context_dispatch import ContextClient, stamp
from backend.control.investigation_plan import EXAMPLES, PlanningError, resolve_prompt
from backend.control.reporting import read_evidence, write_review_report
from backend.control.reservoir_review import NAMES, build_reservoir_review, checked_results
from backend.control.sessions import SessionError, canonical_id
from backend.control.web import SessionRequest, RetryRequest
from backend.shared.settings import ROOT, ControlSettings, WorkerEndpoint
from backend.shared.worker_api import _RequestGuard


_SESSION_ERRORS = (
    'Some worker activity could not be retained; remaining validated evidence is preserved.',
    'Control could not assemble a validated review; retained evidence remains available.',
)
_SESSION_FIELDS = {'schema_version', 'id', 'request_id', 'prompt', 'plan', 'created_at',
                   'state', 'records', 'risk', 'briefing', 'error'}


def _validate_session_metadata(value):
    """Only bounded timestamps and fixed operational errors reach presentation."""
    if set(value) != _SESSION_FIELDS or value['error'] not in (None, *_SESSION_ERRORS):
        raise ValueError('Invalid retained investigation metadata.')
    stamp = value['created_at']
    if not isinstance(stamp, str) or len(stamp) > 64:
        raise ValueError('Invalid retained investigation timestamp.')
    parsed = datetime.fromisoformat(stamp.replace('Z', '+00:00'))
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise ValueError('Investigation timestamps require UTC.')


@dataclass(frozen=True)
class ReservoirSettings:
    control: ControlSettings
    dam: WorkerEndpoint


def load_settings(path=None):
    from backend.control.serve import _WORKER_KEYS, read_private_assignments
    tokens = {'HYDRO_WORKER_TOKEN', 'FLOOD_WORKER_TOKEN', 'DAM_WORKER_TOKEN'}
    allowed = _WORKER_KEYS | {'DAM_WORKER_URL', 'DAM_WORKER_TOKEN'}
    values = os.environ if path is None else read_private_assignments(path, allowed, ignored=tokens)
    control = ControlSettings(
        hydro=WorkerEndpoint(values.get('HYDRO_WORKER_URL') or 'http://127.0.0.1:8002', 'hydro-worker'),
        flood=WorkerEndpoint(values.get('FLOOD_WORKER_URL') or 'http://127.0.0.1:8003', 'flood-worker'),
        local_address=values.get('MESHMIND_CONTROL_SOURCE_IP') or None,
        request_timeout=float(values.get('MESHMIND_REQUEST_TIMEOUT_SECONDS', '15')),
        task_timeout=float(values.get('MESHMIND_TASK_TIMEOUT_SECONDS', '600')),
        poll_interval=float(values.get('MESHMIND_POLL_INTERVAL_SECONDS', '0.5')),
    )
    dam = WorkerEndpoint(values.get('DAM_WORKER_URL') or 'http://127.0.0.1:8004', 'dam-worker')
    if len({control.hydro.url, control.flood.url, dam.url}) != 3:
        raise ValueError('Each worker requires its own HTTP origin.')
    return ReservoirSettings(control, dam)


class ReservoirService:
    def __init__(self, settings, *, history_dir=ROOT / 'outputs/debug/reservoir/history',
                 max_sessions=100, client_factory=ContextClient):
        if not isinstance(settings, ReservoirSettings) or type(max_sessions) is not int or not 1 <= max_sessions <= 1000:
            raise ValueError('Use explicit bounded worker settings.')
        self.settings, self.history_dir = settings, Path(history_dir)
        self.max_sessions, self.client_factory = max_sessions, client_factory
        self.sessions, self.job, self.lock, self.started = {}, None, asyncio.Lock(), False

    @property
    def busy(self):
        return self.job is not None and not self.job.done()

    def save(self, session):
        write_review_report(self.history_dir / (session['id'] + '.json'), session)

    async def start(self):
        self.history_dir.mkdir(parents=True, exist_ok=True)
        self.history_dir.chmod(0o700)
        loaded, identifiers = {}, set()
        for path in sorted(self.history_dir.glob('*.json')):
            if path.is_symlink():
                raise ValueError('History cannot contain symlinks.')
            value, _ = read_evidence(path)
            try:
                _validate_session_metadata(value)
                identifier = canonical_id(value['id'])
                request = canonical_id(value['request_id'])
                if (value['schema_version'] != 'reservoir-v1' or path.name != identifier + '.json'
                        or request in identifiers or value['state'] not in {'queued', 'running', 'finished', 'interrupted'}):
                    raise ValueError
                plan = resolve_prompt(value['prompt'])
                if plan.public() != value['plan']:
                    raise ValueError
                checked_results(plan, value['records'], identifier)
                if value['state'] in {'queued', 'running'}:
                    value['state'] = 'interrupted'
                    self.save(value)
                # Cached presentation is never authority. Rebuild from checked aggregates.
                if value['state'] == 'finished' and value['records']:
                    value['risk'], value['briefing'] = build_reservoir_review(plan, value['records'], identifier, value['prompt'])
                else:
                    value['risk'], value['briefing'] = None, None
                identifiers.add(request)
                loaded[identifier] = value
                if len(loaded) > self.max_sessions:
                    raise ValueError
            except (KeyError, TypeError, ValueError):
                raise ValueError('Invalid bounded investigation history.') from None
        self.sessions, self.started = loaded, True

    async def close(self):
        self.started = False
        if self.busy:
            self.job.cancel()
            try:
                await self.job
            except asyncio.CancelledError:
                pass

    def get(self, identifier):
        try:
            identifier = canonical_id(identifier)
        except ValueError:
            raise SessionError(404, 'Investigation was not found.') from None
        if identifier not in self.sessions:
            raise SessionError(404, 'Investigation was not found.')
        return self.sessions[identifier]

    async def submit(self, prompt, request_id):
        request_id = canonical_id(request_id)
        async with self.lock:
            for value in self.sessions.values():
                if value['request_id'] == request_id:
                    if value['prompt'] != prompt:
                        raise SessionError(409, 'Request ID belongs to another request.')
                    return value['id']
            if not self.started:
                raise SessionError(503, 'Control is not ready.')
            if self.busy:
                raise SessionError(409, 'An investigation is already running.')
            if len(self.sessions) >= self.max_sessions:
                raise SessionError(429, 'Investigation history is full.')
            try:
                plan = resolve_prompt(prompt)
            except PlanningError as error:
                raise SessionError(422, str(error)) from None
            identifier = str(uuid4())
            session = {'schema_version': 'reservoir-v1', 'id': identifier, 'request_id': request_id,
                       'prompt': prompt, 'plan': plan.public(), 'created_at': stamp(), 'state': 'queued',
                       'records': {}, 'risk': None, 'briefing': None, 'error': None}
            self.save(session)
            self.sessions[identifier] = session
            self.job = asyncio.create_task(self.run(session, plan), name='environmental-investigation')
            return identifier

    async def run(self, session, plan):
        try:
            session['state'] = 'running'
            self.save(session)
            tasks = plan.tasks(session['id'])
            settings = self.settings.control

            async def dispatch(role, task):
                endpoint = self.settings.dam if role == 'dam' else getattr(settings, role)
                client = self.client_factory(endpoint, request_timeout=settings.request_timeout,
                                             task_timeout=settings.task_timeout, poll_interval=settings.poll_interval,
                                             max_response_bytes=settings.max_response_bytes, local_address=settings.local_address)
                def progress(record):
                    session['records'][role] = record
                    self.save(session)
                record = await client.run_context(task, on_progress=progress)
                session['records'][role] = record
                self.save(session)
            # Expected network/worker failures become independent records.
            outcomes = await asyncio.gather(*(dispatch(role, task) for role, task in tasks.items()), return_exceptions=True)
            if any(isinstance(item, BaseException) for item in outcomes):
                session['error'] = _SESSION_ERRORS[0]
            session['risk'], session['briefing'] = build_reservoir_review(plan, session['records'], session['id'], session['prompt'])
            session['state'] = 'finished'
            self.save(session)
        except asyncio.CancelledError:
            session['state'] = 'interrupted'
            self.save(session)
            raise
        except Exception:
            session.update(state='finished', error=_SESSION_ERRORS[1], risk=None, briefing=None)
            self.save(session)

    def public(self, session):
        plan = resolve_prompt(session['prompt'])
        running = session['state'] in {'queued', 'running'}
        workers = {}
        for role in plan.tasks(session['id']):
            record = session['records'].get(role) or {}
            status = record.get('status') or {}
            returned = record.get('result') is not None
            outcome = record.get('outcome')
            state = ('complete' if returned else 'down' if outcome in {'transport_error', 'timed_out'} else
                     'failed' if outcome else 'active' if record and running else 'unknown')
            detail = ('Checked ' + ('partial ' if outcome == 'partial' else '') + 'evidence returned.' if returned else
                      'Worker evidence is unavailable.' if outcome else 'No activity observed yet.' if not record else 'Worker is processing the resolved investigation.')
            steps = [{'id': label, 'label': label.title(), 'state': 'complete' if returned else 'pending'}
                     for label in ('accepted', 'processing', 'returned', 'validated')]
            if not returned and status:
                steps[0]['state'] = 'complete'
                steps[1]['state'] = 'failed' if outcome else 'active' if running else 'pending'
            workers[role] = {'id': role, 'name': NAMES[role], 'location': 'Independent ' + role.title() + ' worker',
                             'status': state, 'steps': steps, 'summary': detail,
                             'resources': {'hydro': ['GPM rainfall', 'SMAP soil moisture'], 'flood': ['Sentinel-1', 'DEM', 'HAND'], 'dam': ['Site-specific owner records']}[role],
                             'returned': returned, 'validated': returned}
        briefing = session.get('briefing')
        status = 'running' if running else 'partial' if briefing and briefing['partial'] else 'briefing-ready' if briefing else 'failed'
        description = ('Independent workers are processing the same location and historical cutoff.' if running else
                       'Combined evidence, screening concern and confidence are available.' if briefing else
                       session.get('error') or 'Investigation was interrupted; no completed review is claimed.')
        control = 'active' if running else 'complete' if briefing else 'failed'
        return {'id': session['id'], 'title': plan.name, 'createdAt': session['created_at'],
                'status': status, 'description': description, 'prompt': session['prompt'],
                'phase': 'processing' if running else 'complete', 'studyArea': plan.name,
                'requestedWindow': f'{plan.start.date()} through {plan.as_of}',
                'actualCoverage': briefing['actualCoverage'] if briefing else 'Coverage is being checked.',
                'control': control, 'workers': workers,
                'activities': [{'id': 'control', 'name': 'Control', 'location': 'Investigation coordinator', 'status': control, 'events': [description]}] +
                              [{'id': role, 'name': worker['name'], 'location': worker['location'], 'status': worker['status'], 'events': [worker['summary']]} for role, worker in workers.items()],
                'reviewConditions': briefing['reviewConditions'] if briefing else [],
                'validationFailures': [{'title': 'Incomplete investigation', 'detail': session['error']}] if session.get('error') else [],
                'briefing': deepcopy(briefing), 'risk': deepcopy(session.get('risk')), 'isDemo': False,
                'executionMode': 'execute', 'executionNotice': 'Historical screening. Hydro and Flood always participate; site-specific records are used only for their registered location.',
                'retryableWorkers': [], 'retrying': False}


def create_reservoir_app(service):
    @asynccontextmanager
    async def lifespan(app):
        await service.start()
        try:
            yield
        finally:
            await service.close()
    app = FastAPI(title='MeshMind Control', lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(_RequestGuard)
    app.state.control_service = service

    @app.exception_handler(SessionError)
    async def session_error(request, error):
        return JSONResponse({'detail': error.message}, status_code=error.status)

    @app.exception_handler(RequestValidationError)
    async def invalid(request, error):
        return JSONResponse({'detail': 'Invalid bounded request.'}, status_code=422)

    @app.middleware('http')
    async def safe_response(request, call_next):
        try:
            response = await call_next(request)
        except (OSError, ValueError, RuntimeError):
            response = JSONResponse({'detail': 'Control could not complete the bounded request.'}, status_code=503)
        response.headers.update({'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff'})
        return response

    @app.get('/config')
    async def config():
        example = resolve_prompt(EXAMPLES[-1])
        return {'mode': 'execute', 'routingMode': 'prompt', 'examples': EXAMPLES,
                'availableWorkers': ['hydro', 'flood', 'dam'], 'canStart': not service.busy and len(service.sessions) < service.max_sessions,
                'case': {'case_id': 'prompt-location', 'name': 'Location and historical dates from your request',
                         'bbox': example.bbox.model_dump(mode='json'),
                         'requested_window': {'start': example.start.isoformat(), 'end': example.end.isoformat()}},
                'notice': 'Hydro and Flood always run for your resolved location. Toddbrook Reservoir additionally uses its private dam worker. Use ISO dates; for another unregistered place include bbox=[west,south,east,north].'}

    @app.get('/sessions')
    async def sessions():
        views = [service.public(item) for item in sorted(service.sessions.values(), key=lambda item: item['created_at'], reverse=True)]
        return {'sessions': [{key: item[key] for key in ('id', 'title', 'createdAt', 'status', 'description')} for item in views]}

    @app.post('/sessions', status_code=202)
    async def submit(body: SessionRequest):
        return {'id': await service.submit(body.prompt, body.requestId)}

    @app.get('/sessions/{identifier}')
    async def session(identifier: str):
        return service.public(service.get(identifier))

    @app.post('/sessions/{identifier}/retry', status_code=202)
    async def retry(identifier: str, body: RetryRequest):
        service.get(identifier)
        raise SessionError(409, 'Retry is not enabled for this investigation; check worker completion before creating a new request.')

    @app.get('/sessions/{identifier}/briefing', response_class=HTMLResponse)
    async def briefing(identifier: str):
        value = service.get(identifier)
        if value['state'] != 'finished' or value.get('briefing') is None:
            raise HTTPException(409, 'A checked briefing is not available.')
        return HTMLResponse(render_briefing_html(value['briefing']), headers={
            'Content-Disposition': f'attachment; filename="meshmind-{value["id"]}.html"',
            'Content-Security-Policy': "default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'"})

    @app.get('/viewer/{role}')
    async def viewer(role: str):
        if role not in NAMES:
            raise HTTPException(404, 'Worker view unavailable.')
        candidates = [value for value in service.sessions.values() if role in resolve_prompt(value['prompt']).tasks(value['id'])]
        if not candidates:
            return {'session': None, 'worker': None, 'observedAt': None, 'events': []}
        value = max(candidates, key=lambda item: (item['created_at'], item['id']))
        view = service.public(value)
        record = value['records'].get(role) or {}
        events = [{'id': str(index), 'observedAt': event['observed_at'], 'label': (event['state'] or event['stage']).replace('_', ' ')}
                  for index, event in enumerate(record.get('events', []))]
        return {'session': {key: view[key] for key in ('id', 'title', 'createdAt', 'executionNotice', 'status')},
                'worker': view['workers'][role], 'observedAt': events[-1]['observedAt'] if events else None, 'events': events}
    return app
