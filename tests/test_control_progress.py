"""UI progress is observed, detached, and persisted before possible dispatch."""

import asyncio
from copy import deepcopy
import json

import httpx
import pytest

from backend.control import agent
from backend.control.agent import run_agent
from backend.control.coordinator import run_analysis
from backend.shared.contracts import AnalysisTask
from backend.shared.settings import ControlSettings, WorkerEndpoint
from test_contracts import hydro_result, flood_resources, flood_result
from test_coordinator import INSTANCE, ScriptedWorker, task_for
from test_agent import prepared, fusion_inputs, ScriptedClient, plan, explanation, REQUEST, dispatch_result, control_settings


def test_progress_is_real_status_and_completion_is_detached(hydro_result):
    worker = ScriptedWorker(hydro_result)
    events = []

    def observe(event):
        if event['stage'] == 'submission':
            assert all(method != 'POST' for method, _, _ in worker.calls)
        events.append(deepcopy(event))
        if event['status']:
            event['status']['worker_id'] = 'mutated-by-caller'
        if event['record']:
            event['record']['result'].clear()

    result = asyncio.run(worker.client().run(task_for(hydro_result), on_progress=observe))
    assert [event['stage'] for event in events] == [
        'preflight', 'submission', 'polling', 'polling', 'polling', 'result', 'finished']
    assert [event['status']['state'] for event in events if event['stage'] == 'polling'] == [
        'task_received', 'processing', 'complete']
    assert events[-1]['record'] == result.model_dump(mode='json')
    assert result.result.model_dump(mode='json') == hydro_result
    assert 'configured-token' not in json.dumps(events)
    assert 'http://worker.invalid' not in json.dumps(events)


@pytest.mark.parametrize('failed_stage', ['preflight', 'submission'])
def test_progress_write_failure_before_post_stops_dispatch(hydro_result, failed_stage):
    worker = ScriptedWorker(hydro_result)

    def fail(event):
        if event['stage'] == failed_stage:
            raise ValueError('PRIVATE storage path error')

    with pytest.raises(RuntimeError, match='Control could not persist worker progress') as error:
        asyncio.run(worker.client().run(task_for(hydro_result), on_progress=fail))
    assert 'PRIVATE' not in str(error.value)
    assert not any(method == 'POST' for method, _, _ in worker.calls)


def test_independent_completion_is_delivered_while_other_worker_still_processing(fusion_inputs):
    hydro_task, flood_task, combined = fusion_inputs
    hydro_result, flood_result = combined['hydro'], combined['flood']
    observed = []

    async def scenario():
        hydro_finished = asyncio.Event()

        async def pause_flood(request):
            if request.url.path.endswith('/result'):
                await asyncio.wait_for(hydro_finished.wait(), timeout=1)

        workers = {'hydro-worker': ScriptedWorker(hydro_result),
                   'flood-worker': ScriptedWorker(flood_result, override=pause_flood)}

        def persist(event):
            observed.append(event)
            if event['worker'] == 'hydro' and event['stage'] == 'finished':
                assert event['record']['result'] == hydro_result
                assert not any(item['worker'] == 'flood' and item['stage'] == 'finished' for item in observed)
                hydro_finished.set()

        settings = ControlSettings(
            hydro=WorkerEndpoint('http://hydro.invalid', 'hydro-worker'),
            flood=WorkerEndpoint('http://flood.invalid', 'flood-worker'), poll_interval=0.01)
        return await run_analysis(AnalysisTask.model_validate(hydro_task), AnalysisTask.model_validate(flood_task), settings,
            execution_mode='parallel', on_progress=persist,
            transport_factory=lambda endpoint: httpx.MockTransport(workers[endpoint.expected_worker_id].handle))

    result = asyncio.run(scenario())
    assert result.hydro.result is not None and result.flood.result is not None
    assert len([event for event in observed if event['stage'] == 'finished']) == 2


@pytest.mark.parametrize('identity', [
    {'expected_process_instance_id': '22222222-2222-2222-2222-222222222222'},
    {'expected_execution_host': 'different-host'},
])
def test_retry_identity_fence_rejects_restarted_or_replaced_worker_before_post(hydro_result, identity):
    worker = ScriptedWorker(hydro_result)
    record = asyncio.run(worker.client().run(task_for(hydro_result), **identity))
    assert record.outcome == 'protocol_error' and record.submitted_at is None
    assert [(method, path) for method, path, _ in worker.calls] == [('GET', '/status')]


def test_matching_retry_identity_uses_same_task_once(hydro_result):
    worker = ScriptedWorker(hydro_result)
    record = asyncio.run(worker.client().run(task_for(hydro_result),
        expected_process_instance_id=INSTANCE, expected_execution_host='hydro-worker-host'))
    assert record.outcome == 'complete'
    posts = [request for method, _, request in worker.calls if method == 'POST']
    assert len(posts) == 1 and json.loads(posts[0].content)['task_id'] == hydro_result['task_id']


def test_agent_forwards_progress_only_for_authorized_execute(prepared, monkeypatch):
    case, evidence, policy = prepared
    received = []
    run = dispatch_result(case, evidence)

    async def dispatch(hydro, flood, settings, *, execution_mode, on_progress):
        event = {'worker': 'hydro', 'stage': 'finished', 'status': None,
                 'record': run.hydro.model_dump(mode='json')}
        on_progress(event)
        return run

    monkeypatch.setattr(agent, 'run_analysis', dispatch)
    result = asyncio.run(run_agent(REQUEST, case, policy, ScriptedClient(plan(), explanation()),
        execute=True, control_settings=control_settings(), on_progress=received.append))
    assert result['status'] == 'complete' and len(received) == 1
    received.clear()
    asyncio.run(run_agent(REQUEST, case, policy, ScriptedClient(plan(), explanation()),
        evidence=evidence, on_progress=received.append))
    assert received == []
