"""Location isolation, aggregate-only dispatch and durable Control review checks."""

import asyncio
from datetime import date, timedelta
import json
from pathlib import Path
import time
from uuid import uuid4

from fastapi.testclient import TestClient
import httpx
import pytest
from pydantic import ValidationError

from backend.control.context_dispatch import ContextClient
from backend.control.investigation_plan import EXAMPLES, PlanningError, TODDBROOK_BBOX, resolve_prompt
from backend.control.reservoir_review import checked_results
from backend.control.reservoir_web import ReservoirService, ReservoirSettings, create_reservoir_app
from backend.shared.context_contracts import (
    ContextComponent, ContextResult, ContextTask, RainMetrics, SoilMetrics, unavailable,
)
from backend.shared.dam_contracts import (
    DamCounts, DamEvidence, DamMetrics, DamResult, DamRule, DamTask, LIMITATIONS,
    RULE_CRITERIA, WINDOWS, expected_rules, expected_summary, window_for_date,
)
from backend.shared.settings import ControlSettings, WorkerEndpoint

TOD = 'Assess flood risk at Toddbrook Reservoir, Whaley Bridge, Derbyshire, England as of 2019-07-31.'
OTHER = 'Assess flood risk at another reservoir bbox=[-115.0,36.0,-114.9,36.1] as of 2007-12-09.'
PRIVATE = 'SECRET_RAW_INSPECTOR_/private_data/records_PROVENANCE'
MOMENT = '2026-10-01T12:00:00Z'
PROCESS = '11111111-1111-4111-8111-111111111111'


def dam_result(request):
    known = request.window != 'outside-coverage'
    last_observation = min(request.as_of, WINDOWS[request.window][1]) if known else None
    counts = DamCounts(operations=3 if known else 0, supervision=1 if known else 0,
                       inspection=1 if known else 0, maintenance=0, instrumentation=1 if known else 0)
    metrics = DamMetrics(recent_visit_count=3 if known else 0, full_pool_visit_count=3 if known else 0,
                         latest_pool_level_mod=186.0 if known else None,
                         latest_pool_departure_m=.33 if known else None,
                         latest_visit_age_days=(request.as_of - last_observation).days if known else None,
                         latest_supervision_age_days=30 if known else None,
                         latest_instrumentation_age_days=30 if known else None,
                         sealant_defect_fraction=1.0 if known else None,
                         blocked_relief_fraction=1.0 if known else None,
                         seepage_at_full_pool_fraction=1.0 if known else None,
                         current_spillway_flowing=True if known else None,
                         open_maintenance_count=0, long_open_maintenance_count=0,
                         latest_inspection_grade='D' if known else None,
                         known_integrity_action=known, monitoring_gap=True)
    evidence = DamEvidence(record_count=6 if known else 0,
                           record_refs=[f'r_{n:024x}' for n in range(6)] if known else [], counts=counts,
                           first_observation=last_observation, last_observation=last_observation)
    support = {'D01': 3, 'D02': 3, 'D03': 3, 'D04': 0, 'D05': 1, 'D06': 1, 'D07': 2} if known else dict.fromkeys(RULE_CRITERIA, 0)
    return DamResult(task_id=request.task_id, window=request.window, as_of=request.as_of,
                     metrics=metrics, evidence=evidence, summary=expected_summary(metrics, counts),
                     rules=[DamRule(rule_id=key, criterion=RULE_CRITERIA[key], triggered=value, record_count=support[key])
                            for key, value in expected_rules(metrics).items()], limitations=list(LIMITATIONS))


def context_result(request, *, measured=False):
    hydro = request.analysis_type == 'hydrometeorology'
    names = ['gpm', 'smap'] if hydro else ['sentinel1', 'dem', 'hand']
    components = [unavailable(name, 'source_unavailable') for name in names]
    if measured and hydro:
        hours = (request.end_time - request.start_time).total_seconds() / 3600
        timestamp = request.start_time + timedelta(hours=1.5)
        components = [
            ContextComponent(component='gpm', availability='available', reason='measured', temporal_kind='observation',
                             observed_start=request.start_time, observed_end=request.end_time,
                             metrics=RainMetrics(area_mean_total_accumulation_mm=60, max_cell_total_accumulation_mm=70,
                                                 covered_hours=hours, requested_hours=hours, granule_count=int(hours*2),
                                                 temporal_coverage_fraction=1, valid_fraction=1)),
            ContextComponent(component='smap', availability='available', reason='measured', temporal_kind='observation',
                             observed_start=request.start_time, observed_end=request.start_time+timedelta(hours=3),
                             metrics=SoilMetrics(timestamp_utc=timestamp, surface_mean_m3_m3=.5, surface_max_m3_m3=.6,
                                                 rootzone_mean_m3_m3=.4, rootzone_max_m3_m3=.5,
                                                 surface_valid_fraction=1, rootzone_valid_fraction=1)),
        ]
    return ContextResult(**request.model_dump(), worker_id='hydro-worker' if hydro else 'flood-worker',
                         status='complete' if measured and hydro else 'partial', components=components)


def settings():
    return ReservoirSettings(ControlSettings(WorkerEndpoint('http://hydro.test:8002', 'hydro-worker'),
                                               WorkerEndpoint('http://flood.test:8003', 'flood-worker'),
                                               request_timeout=.2, task_timeout=2, poll_interval=.01),
                             WorkerEndpoint('http://dam.test:8004', 'dam-worker'))


def factory_with_workers(*, fail=(), mutation=None, measured=False):
    accepted, requests = [], []
    def factory(endpoint, **kwargs):
        role = endpoint.expected_worker_id.removesuffix('-worker')
        analysis = {'hydro': 'hydrometeorology', 'flood': 'surface_water_and_terrain', 'dam': 'dam_risk'}[role]
        identity = {'worker_id': endpoint.expected_worker_id, 'analysis_type': analysis,
                    'execution_host': role+'-host', 'process_instance_id': PROCESS}
        state = {}
        def handler(request):
            requests.append((role, request.method, request.url.path))
            assert 'authorization' not in request.headers
            if role in fail:
                raise httpx.ConnectError(PRIVATE, request=request)
            if request.url.path == '/status':
                return httpx.Response(200, json={**identity, 'status': 'idle', 'active_task_id': None, 'retained_tasks': 0, 'capacity': 128})
            if request.method == 'POST':
                model = DamTask if role == 'dam' else ContextTask
                task = model.model_validate(json.loads(request.content))
                state['task'] = task
                state['result'] = dam_result(task) if role == 'dam' else context_result(task, measured=measured)
                accepted.append((role, task))
                return httpx.Response(202, json={**identity, 'task_id': task.task_id, 'state': 'task_received', 'received_at': MOMENT})
            task = state['task']
            if request.url.path.endswith('/result'):
                result = state['result'].model_dump(mode='json')
                if mutation:
                    mutation(role, result)
                return httpx.Response(200, json=result)
            status = {**identity, 'task_id': task.task_id, 'state': state['result'].status,
                      'received_at': MOMENT, 'started_at': MOMENT, 'completed_at': MOMENT}
            if mutation and mutation.__name__ == 'change_process':
                status['process_instance_id'] = '22222222-2222-4222-8222-222222222222'
            return httpx.Response(200, json=status)
        return ContextClient(endpoint, transport=httpx.MockTransport(handler), **kwargs)
    return factory, accepted, requests


def wait_finished(client, identifier):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        response = client.get('/sessions/' + identifier)
        assert response.status_code == 200, response.text
        value = response.json()
        if value['status'] != 'running':
            return value
        time.sleep(.01)
    pytest.fail('Control did not finish.')


def submit(client, prompt=TOD, request_id=None):
    response = client.post('/sessions', json={'prompt': prompt, 'requestId': request_id or str(uuid4())})
    assert response.status_code == 202, response.text
    return response.json()['id']


@pytest.mark.parametrize('prompt', [OTHER, 'Review Abbotsford as of 2021-11-15.',
    'Review another area bbox=[-2.10,53.25,-1.85,53.40] as of 2019-07-31.',
    'Compare Toddbrook Reservoir with another location bbox=[-115.0,36.0,-114.9,36.1] as of 2019-07-31.'])
def test_only_the_registered_toddbrook_target_can_dispatch_private_records(prompt):
    plan = resolve_prompt(prompt)
    tasks = plan.tasks('scope-test')
    assert set(tasks) == {'hydro', 'flood'}
    assert tasks['hydro'].bbox == tasks['flood'].bbox == plan.bbox
    assert tasks['hydro'].as_of == tasks['flood'].as_of == plan.as_of


@pytest.mark.parametrize('prompt', EXAMPLES)
def test_toddbrook_dispatches_three_workers_for_the_exact_historical_date(prompt):
    plan = resolve_prompt(prompt)
    tasks = plan.tasks('same-case')
    assert set(tasks) == {'hydro', 'flood', 'dam'}
    assert plan.bbox.as_tuple() == TODDBROOK_BBOX
    assert len({value.as_of for value in tasks.values()}) == 1
    assert tasks['hydro'].start_time.date() == plan.as_of
    assert tasks['hydro'].end_time - tasks['hydro'].start_time == timedelta(days=1)
    assert tasks['hydro'].bbox == tasks['flood'].bbox
    assert tasks['dam'].site_id == 'toddbrook'


@pytest.mark.parametrize('as_of,expected_window', [
    ('2007-09-02', 'outside-coverage'), ('2007-09-03', '2007-2008'),
    ('2007-12-09', '2007-2008'), ('2008-02-29', '2007-2008'),
    ('2008-03-01', '2007-2008'), ('2008-03-07', '2007-2008'),
    ('2008-03-08', 'outside-coverage'), ('2013-01-01', 'outside-coverage'),
    ('2015-09-30', 'outside-coverage'), ('2015-10-01', '2015-2019'),
    ('2019-07-31', '2015-2019'), ('2019-08-01', '2015-2019'),
    ('2019-08-07', '2015-2019'), ('2019-08-08', 'outside-coverage'),
])
def test_prompt_and_dam_contract_agree_on_observed_period_and_seven_day_tail(as_of, expected_window):
    selected = date.fromisoformat(as_of)
    plan = resolve_prompt(f'Assess flood risk at Toddbrook Reservoir as of {as_of}.')
    tasks = plan.tasks('date-boundary')
    assert window_for_date(selected) == expected_window
    assert tasks['dam'].window == expected_window
    assert {task.as_of for task in tasks.values()} == {selected}
    for role in ('hydro', 'flood'):
        assert tasks[role].start_time.date() == selected
        assert tasks[role].end_time - tasks[role].start_time == timedelta(days=1)
    for wrong in {'2007-2008', '2015-2019', 'outside-coverage'} - {expected_window}:
        with pytest.raises(ValidationError):
            DamTask(window=wrong, as_of=as_of)


@pytest.mark.parametrize('as_of,observed,age', [
    ('2008-03-01', '2008-02-29', 1), ('2008-03-07', '2008-02-29', 7),
    ('2019-08-01', '2019-07-31', 1), ('2019-08-07', '2019-07-31', 7),
])
def test_tail_evidence_retains_observed_endpoint_and_true_age(as_of, observed, age):
    task = resolve_prompt(f'Review Toddbrook Reservoir as of {as_of}.').tasks('aged-records')['dam']
    result = dam_result(task)
    assert result.as_of.isoformat() == as_of
    assert result.evidence.last_observation.isoformat() == observed
    assert result.metrics.latest_visit_age_days == age
    assert len(result.limitations) == 8
    assert any('last-known records' in item for item in result.limitations)

    # A caller cannot relabel the last supplied observation as fresh on the
    # assessment date, even when the age and coverage fields agree with the lie.
    fresh = result.model_dump(mode='json')
    fresh['evidence']['first_observation'] = as_of
    fresh['evidence']['last_observation'] = as_of
    fresh['metrics']['latest_visit_age_days'] = 0
    with pytest.raises(ValidationError, match='Observation coverage'):
        DamResult.model_validate(fresh)
    wrong_age = result.model_dump(mode='json')
    wrong_age['metrics']['latest_visit_age_days'] = 0
    with pytest.raises(ValidationError, match='Observation age'):
        DamResult.model_validate(wrong_age)


@pytest.mark.parametrize('prompt', [
    'Do not investigate flood risk at Toddbrook Reservoir as of 2019-07-31.',
    'Assess flood risk at Toddbrook Reservoir, California as of 2019-07-31.',
    'Assess flood risk at Toddbrook Reservoir bbox=[-115,36,-114.9,36.1] as of 2019-07-31.',
    'Assess Toddbrook Reservoir versus Other Reservoir as of 2019-07-31.',
    'Assess flood risk at Toddbrook Reservoir as of 1800-01-01.',
    'Assess flood risk at Toddbrook Reservoir as of 2199-01-01.',
    'Assess flood risk at Toddbrook Reservoir as of 2019-02-30.',
    'Assess flood risk at Toddbrook Reservoir from 2019-07-31 through 2019-07-01.',
    'Assess flood risk at Toddbrook Reservoir from 2019-07-01 through 2019-07-31.',
    'Assess flood risk at an unknown reservoir as of 2019-07-31.',
    'Assess flood risk bbox=[nan,53,-1,54] as of 2019-07-31.',
])
def test_ambiguous_targets_invalid_areas_and_dates_are_rejected_before_dispatch(prompt):
    with pytest.raises(PlanningError):
        resolve_prompt(prompt)


def test_inclusive_historical_range_is_preserved_instead_of_using_latest_hours():
    plan = resolve_prompt('Review bbox=[10,45,10.1,45.1] from 1995-04-01 through 1995-04-07.')
    tasks = plan.tasks('old-period')
    assert plan.as_of == date(1995, 4, 7)
    for task in tasks.values():
        assert task.start_time.isoformat() == '1995-04-01T00:00:00+00:00'
        assert task.end_time.isoformat() == '1995-04-08T00:00:00+00:00'


@pytest.mark.parametrize('prompt,roles', [
    (TOD, {'hydro','flood','dam'}),
    (EXAMPLES[1], {'hydro','flood','dam'}),
    (OTHER, {'hydro','flood'}),
])
def test_http_dispatch_respects_scope_and_never_reads_private_data(tmp_path, monkeypatch, prompt, roles):
    factory, accepted, requests = factory_with_workers()
    service = ReservoirService(settings(), history_dir=tmp_path, client_factory=factory)
    original = Path.open
    def guarded(path, *args, **kwargs):
        assert 'private_data' not in Path(path).parts, 'Control attempted a private data read.'
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'open', guarded)
    with TestClient(create_reservoir_app(service)) as client:
        identifier = submit(client, prompt)
        view = wait_finished(client, identifier)
        assert {role for role, _ in accepted} == roles
        assert set(view['workers']) == roles
        assert set(service.sessions[identifier]['records']) == roles
        assert all(task.task_id == identifier for _, task in accepted)
        assert len({task.as_of for _, task in accepted}) == 1
        assert PRIVATE not in json.dumps(view)
        if roles == {'hydro','flood'}:
            assert all(role != 'dam' for role, _, _ in requests)
            assert client.get('/viewer/dam').json()['session'] is None


def test_high_private_concern_is_retained_with_partial_public_evidence_and_grounded_html(tmp_path):
    factory, _, _ = factory_with_workers()
    with TestClient(create_reservoir_app(ReservoirService(settings(), history_dir=tmp_path, client_factory=factory))) as client:
        identifier = submit(client)
        view = wait_finished(client, identifier)
        assert view['status'] == 'briefing-ready'
        assert view['risk']['level'] == 'critical' and view['risk']['alert']
        assert view['risk']['score'] == 90
        assert view['risk']['confidenceScore'] == .36  # .60 times the fixture's .60 evidence score.
        briefing = view['briefing']
        assert any(condition['id'] == 'D05' and condition['status'] == 'triggered' for condition in briefing['reviewConditions'])
        assert any('not' in limit and 'probability' in limit for limit in briefing['limitations'])
        assert any(source['dataset'] == 'Toddbrook dam records' and 'r_' in source['resources'] for source in briefing['sourceProvenance'])
        html = client.get(f'/sessions/{identifier}/briefing')
        assert html.status_code == 200
        assert 'critical' in html.text.lower() and 'confidence' in html.text.lower()
        assert PRIVATE not in html.text
        assert 'default-src' in html.headers['content-security-policy']


@pytest.mark.parametrize('failure', ['hydro', 'flood', 'dam'])
def test_one_missing_worker_never_discards_other_validated_evidence(tmp_path, failure):
    factory, accepted, _ = factory_with_workers(fail={failure})
    service = ReservoirService(settings(), history_dir=tmp_path, client_factory=factory)
    with TestClient(create_reservoir_app(service)) as client:
        identifier = submit(client)
        view = wait_finished(client, identifier)
        assert view['status'] == 'briefing-ready'
        assert view['workers'][failure]['status'] == 'down'
        assert {role for role, _ in accepted} == {'hydro','flood','dam'} - {failure}
        records = service.sessions[identifier]['records']
        assert records[failure]['outcome'] == 'transport_error'
        assert all(records[role]['result'] is not None for role in {'hydro','flood','dam'} - {failure})
        assert PRIVATE not in json.dumps(view)
        if failure != 'dam':
            assert view['risk']['level'] == 'critical'


@pytest.mark.parametrize('field', ['task_id', 'bbox', 'as_of', 'location_id', 'process'])
def test_context_dispatch_rejects_result_or_process_identity_mismatch(field):
    def mutate(role, result):
        if field == 'task_id': result['task_id'] = 'different-task'
        elif field == 'bbox': result['bbox']['west'] -= .01
        elif field == 'as_of': result['as_of'] = '2019-07-30'
        elif field == 'location_id': result['location_id'] = 'unrelated'
    if field == 'process': mutate.__name__ = 'change_process'
    factory, _, _ = factory_with_workers(mutation=mutate)
    task = resolve_prompt(TOD).tasks('binding-test')['hydro']
    record = asyncio.run(factory(settings().control.hydro, poll_interval=.01, task_timeout=2).run_context(task))
    assert record['outcome'] == 'protocol_error' and record['result'] is None
    assert PRIVATE not in json.dumps(record)


def test_session_ids_are_idempotent_and_finished_history_restores_without_dispatch(tmp_path):
    factory, accepted, _ = factory_with_workers()
    service = ReservoirService(settings(), history_dir=tmp_path, client_factory=factory)
    request = str(uuid4())
    with TestClient(create_reservoir_app(service)) as client:
        identifier = submit(client, request_id=request)
        expected = wait_finished(client, identifier)
        assert submit(client, request_id=request) == identifier
        conflict = client.post('/sessions', json={'prompt': OTHER, 'requestId': request})
        assert conflict.status_code == 409
        assert len(accepted) == 3
        assert client.get('/sessions').json()['sessions'][0]['id'] == identifier
    def forbidden(*args, **kwargs):
        pytest.fail('Restoring history must not dispatch new work.')
    restored = ReservoirService(settings(), history_dir=tmp_path, client_factory=forbidden)
    with TestClient(create_reservoir_app(restored)) as client:
        observed = client.get('/sessions/'+identifier).json()
        assert observed['risk'] == expected['risk']
        assert observed['briefing'] == expected['briefing']
        assert client.get('/viewer/dam').json()['worker']['validated'] is True


def test_outside_private_coverage_remains_unknown_when_public_evidence_is_missing(tmp_path):
    factory, accepted, _ = factory_with_workers()
    with TestClient(create_reservoir_app(ReservoirService(settings(), history_dir=tmp_path, client_factory=factory))) as client:
        identifier = submit(client, 'Assess flood risk at Toddbrook Reservoir as of 2013-01-01.')
        view = wait_finished(client, identifier)
        assert {role for role, _ in accepted} == {'hydro','flood','dam'}
        assert next(task for role, task in accepted if role == 'dam').window == 'outside-coverage'
        assert view['risk']['level'] == 'unknown' and view['risk']['score'] is None
        assert view['risk']['alert'] is False and view['risk']['confidenceScore'] == 0


def test_public_rainfall_and_soil_can_trigger_an_alert_without_private_site_access(tmp_path):
    factory, accepted, _ = factory_with_workers(measured=True)
    with TestClient(create_reservoir_app(ReservoirService(settings(), history_dir=tmp_path, client_factory=factory))) as client:
        identifier = submit(client, OTHER.replace('2007-12-09', '2019-07-31'))
        view = wait_finished(client, identifier)
        assert {role for role, _ in accepted} == {'hydro','flood'}
        assert view['risk']['level'] == 'high' and view['risk']['alert'] is True
        assert view['risk']['confidenceScore'] == .32
        assert any(row['id'] == 'H01' and row['status'] == 'triggered' for row in view['reviewConditions'])


def test_non_toddbrook_review_rejects_an_unrelated_private_result():
    plan = resolve_prompt(OTHER)
    wrong = dam_result(resolve_prompt(TOD).tasks('unrelated')['dam']).model_dump(mode='json')
    with pytest.raises(ValueError, match='unrelated worker'):
        checked_results(plan, {'dam': {'result': wrong}}, 'unrelated')


@pytest.mark.parametrize('field', ['event', 'record_error', 'result_extra', 'session_error', 'created_at', 'contradictory_outcome'])
def test_retained_history_cannot_publish_private_text_or_contradictory_evidence(tmp_path, field):
    factory, _, _ = factory_with_workers()
    service = ReservoirService(settings(), history_dir=tmp_path, client_factory=factory)
    with TestClient(create_reservoir_app(service)) as client:
        identifier = submit(client)
        wait_finished(client, identifier)
    path = tmp_path / (identifier + '.json')
    saved = json.loads(path.read_text())
    if field == 'event': saved['records']['dam']['events'][0]['stage'] = PRIVATE
    elif field == 'record_error': saved['records']['dam']['error'] = PRIVATE
    elif field == 'result_extra': saved['records']['dam']['result']['raw_records'] = [PRIVATE]
    elif field == 'session_error': saved['error'] = PRIVATE
    elif field == 'created_at': saved['created_at'] = PRIVATE
    elif field == 'contradictory_outcome': saved['records']['dam']['outcome'] = 'protocol_error'
    path.write_text(json.dumps(saved))
    restored = ReservoirService(settings(), history_dir=tmp_path, client_factory=factory)
    try:
        asyncio.run(restored.start())
    except ValueError as error:
        assert PRIVATE not in str(error)
        return
    if field == 'contradictory_outcome':
        pytest.fail('Contradictory retained result was accepted as valid evidence.')
    assert PRIVATE not in json.dumps(restored.public(restored.get(identifier)))


def test_cached_briefing_and_risk_are_rebuilt_from_checked_aggregates(tmp_path):
    factory, _, _ = factory_with_workers()
    with TestClient(create_reservoir_app(ReservoirService(settings(), history_dir=tmp_path, client_factory=factory))) as client:
        identifier = submit(client)
        original = wait_finished(client, identifier)
    path = tmp_path / (identifier + '.json')
    saved = json.loads(path.read_text())
    saved.update(risk={'level': 'low', 'summary': PRIVATE}, briefing={'originalRequest': PRIVATE})
    path.write_text(json.dumps(saved))
    restored = ReservoirService(settings(), history_dir=tmp_path, client_factory=factory)
    with TestClient(create_reservoir_app(restored)) as client:
        view = client.get('/sessions/' + identifier).json()
        assert view['risk'] == original['risk'] and view['briefing'] == original['briefing']
        assert PRIVATE not in json.dumps(view)


def test_three_worker_submissions_overlap_instead_of_waiting_for_each_result(tmp_path):
    base_factory, accepted, _ = factory_with_workers()
    gate, arrivals = [], set()
    def factory(endpoint, **kwargs):
        client = base_factory(endpoint, **kwargs)
        original = client.transport
        if not gate:
            gate.append(asyncio.Event())
        async def handler(request):
            if request.method == 'POST' and request.url.path == '/tasks':
                arrivals.add(endpoint.expected_worker_id)
                if len(arrivals) == 3:
                    gate[0].set()
                await gate[0].wait()
            return await original.handle_async_request(request)
        client.transport = httpx.MockTransport(handler)
        return client
    with TestClient(create_reservoir_app(ReservoirService(settings(), history_dir=tmp_path, client_factory=factory))) as client:
        identifier = submit(client)
        view = wait_finished(client, identifier)
        assert len(accepted) == 3
        assert all(worker['returned'] for worker in view['workers'].values())


def test_dam_client_rejects_a_valid_result_from_a_different_cutoff():
    request = resolve_prompt(TOD).tasks('cutoff-check')['dam']
    other = DamTask(task_id=request.task_id, window=request.window, as_of=request.as_of-timedelta(days=1))
    def mutate(role, result):
        assert role == 'dam'
        result.clear()
        result.update(dam_result(other).model_dump(mode='json'))
    factory, _, _ = factory_with_workers(mutation=mutate)
    record = asyncio.run(factory(settings().dam, poll_interval=.01, task_timeout=2).run_context(request))
    assert record['outcome'] == 'protocol_error' and record['result'] is None


@pytest.mark.parametrize('reason,text', [
    ('authentication_unavailable', 'authenticate'),
    ('provider_timeout', 'deadline'),
    ('download_limit', 'acquisition limit'),
    ('no_matching_observations', 'no eligible observations'),
])
def test_external_acquisition_failures_have_safe_report_explanations(tmp_path, reason, text):
    def mutate(role, result):
        if role == 'hydro':
            for component in result['components']:
                component['reason'] = reason
    factory, _, _ = factory_with_workers(mutation=mutate)
    with TestClient(create_reservoir_app(ReservoirService(settings(), history_dir=tmp_path, client_factory=factory))) as client:
        identifier = submit(client)
        view = wait_finished(client, identifier)
        assert view['risk']['level'] == 'critical'
        assert any(text in row['coverage'] for row in view['briefing']['sourceProvenance'])
        assert any('reprocessed NASA' in limit and 'not asserted' in limit for limit in view['briefing']['limitations'])
        assert PRIVATE not in json.dumps(view)


@pytest.mark.parametrize('mutation', ['not_accepted', 'unfinished', 'wrong_status', 'error_on_success'])
def test_successful_retained_result_requires_a_consistent_terminal_lifecycle(tmp_path, mutation):
    factory, _, _ = factory_with_workers()
    with TestClient(create_reservoir_app(ReservoirService(settings(), history_dir=tmp_path, client_factory=factory))) as client:
        identifier = submit(client)
        wait_finished(client, identifier)
    path = tmp_path / (identifier + '.json')
    saved = json.loads(path.read_text())
    record = saved['records']['dam']
    if mutation == 'not_accepted': record['accepted'] = False
    elif mutation == 'unfinished': record['completed_at'] = None
    elif mutation == 'wrong_status': record['status']['state'] = 'failed'
    elif mutation == 'error_on_success': record['error'] = 'Worker evidence could not be returned and validated; other branches are retained.'
    path.write_text(json.dumps(saved))
    restored = ReservoirService(settings(), history_dir=tmp_path, client_factory=factory)
    with pytest.raises(ValueError, match='^Invalid bounded investigation history.$'):
        asyncio.run(restored.start())
