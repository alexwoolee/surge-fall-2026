"""Bounded HTTP dispatch for public environmental and private aggregate tasks."""

import asyncio
from copy import deepcopy
from datetime import datetime, timezone
import time

import httpx
from pydantic import ValidationError

from backend.control.coordinator import WorkerClient, _ProtocolError, _ResponseCode
from backend.shared.contracts import TaskStatus, WorkerStatus
from backend.shared.context_contracts import ContextResult, ContextTask
from backend.shared.dam_contracts import DamResult, DamTask
from backend.shared.status import TERMINAL_STATES

_ORDER = {'task_received': 0, 'acquiring_data': 1, 'dataset_located': 2, 'processing': 3, 'preparing_result': 4,
          'complete': 5, 'partial': 5, 'failed': 5}


def stamp():
    return datetime.now(timezone.utc).isoformat()


def validate_record(record, task, role):
    """Check persisted lifecycle envelopes before exposing any of their text."""
    required = {'worker', 'task', 'started_at', 'completed_at', 'outcome', 'result',
                'status', 'events', 'error', 'accepted'}
    if not isinstance(record, dict) or set(record) != required or record['worker'] != role:
        raise ValueError('Invalid retained worker record.')
    if record['task'] != task.model_dump(mode='json') or type(record['accepted']) is not bool:
        raise ValueError('Retained worker task does not match its investigation.')
    def when(value):
        if not isinstance(value, str) or len(value) > 64:
            raise ValueError('Invalid lifecycle timestamp.')
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
            raise ValueError('Lifecycle timestamps require UTC.')
        return parsed
    start = when(record['started_at'])
    if record['completed_at'] is not None and when(record['completed_at']) < start:
        raise ValueError('Lifecycle interval is invalid.')
    if record['outcome'] not in {None, 'complete', 'partial', 'worker_failed', 'timed_out', 'transport_error', 'rejected', 'protocol_error'}:
        raise ValueError('Invalid retained worker outcome.')
    if record['error'] not in {None, 'Worker evidence could not be returned and validated; other branches are retained.'}:
        raise ValueError('Unrecognised worker error text.')
    if record['status'] is not None:
        status = TaskStatus.model_validate(record['status'])
        if status.task_id != task.task_id or status.worker_id != role + '-worker' or status.analysis_type != task.analysis_type:
            raise ValueError('Retained status does not match its task.')
        if status.error not in {None, 'Worker processing failed.'}:
            raise ValueError('Unrecognised status error text.')
    events = record['events']
    if not isinstance(events, list) or len(events) > 32:
        raise ValueError('Invalid retained event list.')
    previous = None
    for event in events:
        if (not isinstance(event, dict) or set(event) != {'stage', 'observed_at', 'state'}
                or event['stage'] not in {'preflight', 'submission', 'polling', 'result', 'finished'}
                or event['state'] not in {None, *_ORDER}):
            raise ValueError('Invalid retained lifecycle event.')
        current = when(event['observed_at'])
        if previous is not None and current < previous:
            raise ValueError('Retained lifecycle events are out of order.')
        previous = current
    return record


class ContextClient(WorkerClient):
    """Reuse bounded transport, while validating the new task/result contracts."""

    async def run_context(self, task, *, on_progress=None):
        cls = DamTask if isinstance(task, DamTask) else ContextTask
        task = cls.model_validate(task.model_dump(mode='json'))
        role = self.settings.expected_worker_id.removesuffix('-worker')
        expected_analysis = {'dam': 'dam_risk', 'hydro': 'hydrometeorology', 'flood': 'surface_water_and_terrain'}[role]
        if task.analysis_type != expected_analysis:
            raise ValueError('Task does not match this worker.')
        record = {'worker': role, 'task': task.model_dump(mode='json'), 'started_at': stamp(),
                  'completed_at': None, 'outcome': None, 'result': None,
                  'status': None, 'events': [], 'error': None, 'accepted': False}
        identity, previous = None, None

        def emit(stage, status=None):
            event = {'stage': stage, 'observed_at': stamp(),
                     'state': None if status is None else status.state.value}
            if not record['events'] or (record['events'][-1]['stage'], record['events'][-1]['state']) != (stage, event['state']):
                record['events'].append(event)
                del record['events'][:-32]
            if on_progress:
                on_progress(deepcopy(record))

        def check_identity(value):
            nonlocal identity
            found = (value.worker_id, value.analysis_type, value.execution_host, value.process_instance_id)
            if found[:2] != (self.settings.expected_worker_id, expected_analysis) or not all(found[2:]):
                raise _ProtocolError
            if identity is not None and found != identity:
                raise _ProtocolError
            identity = found

        def observe(raw):
            nonlocal previous
            value = TaskStatus.model_validate(raw)
            check_identity(value)
            if value.task_id != task.task_id:
                raise _ProtocolError
            if previous is not None:
                if (value.received_at != previous.received_at or _ORDER[value.state.value] < _ORDER[previous.state.value]
                        or previous.started_at is not None and value.started_at != previous.started_at
                        or previous.completed_at is not None and value.completed_at != previous.completed_at
                        or previous.state in TERMINAL_STATES and value.state != previous.state):
                    raise _ProtocolError
            previous = value
            record['status'] = value.model_dump(mode='json')
            if record['status']['error']:
                record['status']['error'] = 'Worker processing failed.'
            emit('polling', value)
            return value

        deadline = time.monotonic() + self.task_timeout
        emit('preflight')
        try:
            async with asyncio.timeout(self.task_timeout):
                transport = self.transport or httpx.AsyncHTTPTransport(local_address=self.local_address, trust_env=False)
                async with httpx.AsyncClient(base_url=self.settings.url, transport=transport,
                                            trust_env=False, follow_redirects=False,
                                            timeout=self.request_timeout, headers={'Accept': 'application/json'}) as client:
                    check_identity(WorkerStatus.model_validate(await self._json(client, 'GET', '/status', deadline)))
                    emit('submission')
                    status = observe(await self._json(client, 'POST', '/tasks', deadline,
                                                     body=task.model_dump(mode='json'), expected=202))
                    record['accepted'] = True
                    while status.state not in TERMINAL_STATES:
                        await asyncio.sleep(min(self.poll_interval, max(0, deadline - time.monotonic())))
                        status = observe(await self._json(client, 'GET', f'/tasks/{task.task_id}', deadline))
                    if status.state.value == 'failed':
                        record['outcome'] = 'worker_failed'
                    else:
                        emit('result', status)
                        raw = await self._json(client, 'GET', f'/tasks/{task.task_id}/result', deadline)
                        model = DamResult if role == 'dam' else ContextResult
                        result = model.model_validate(raw)
                        if result.task_id != task.task_id or result.worker_id != self.settings.expected_worker_id or result.status != status.state.value:
                            raise _ProtocolError
                        if role == 'dam':
                            if result.site.id != task.site_id or result.window != task.window or result.as_of != task.as_of:
                                raise _ProtocolError
                        else:
                            rebound = ContextTask.model_validate({key: result.model_dump(mode='json')[key] for key in ContextTask.model_fields})
                            if rebound != task:
                                raise _ProtocolError
                        observe(await self._json(client, 'GET', f'/tasks/{task.task_id}', deadline))
                        record.update(result=result.model_dump(mode='json'), outcome=result.status)
        except (TimeoutError, httpx.TimeoutException):
            record['outcome'] = 'timed_out'
        except httpx.RequestError:
            record['outcome'] = 'transport_error'
        except _ResponseCode:
            record['outcome'] = 'rejected'
        except (ValidationError, _ProtocolError, ValueError, TypeError, KeyError, OverflowError):
            record['outcome'] = 'protocol_error'
        record['completed_at'] = stamp()
        if record['outcome'] not in ('complete', 'partial'):
            record['error'] = 'Worker evidence could not be returned and validated; other branches are retained.'
        emit('finished', previous)
        return record
