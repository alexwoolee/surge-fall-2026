"""Model choices cannot replace configured tasks or deterministic evidence."""

import asyncio
from copy import deepcopy
from dataclasses import replace
import json

import pytest

from backend.control import agent
from backend.control.agent import INVESTIGATION, build_case, run_agent
from backend.control.alerts import load_policy
from backend.control.openai_client import AgentAPIError
from backend.control.reporting import build_review_report
from backend.control.state import DispatchRun
from backend.shared.settings import ControlSettings, ROOT, WorkerEndpoint
from test_fusion import fusion_inputs, hydro_result


SECRET = 'PRIVATE-MODEL-BOUNDARY-MARKER'
REQUEST = 'Review the configured historical case and its available environmental evidence.'


@pytest.fixture
def prepared(fusion_inputs):
    hydro, flood, combined = fusion_inputs
    config = {
        'id': 'configured-case', 'name': 'Configured historical case',
        'bbox': [hydro['bbox'][key] for key in ('west', 'south', 'east', 'north')],
        'event_start': '2021-11-14T00:00:00Z', 'event_end': '2021-11-16T23:59:59Z',
        'sentinel1_smoke_start': flood['start_time'], 'sentinel1_smoke_end': flood['end_time'],
    }
    case = build_case(config, hydro['gpm_resources'], hydro['smap_resource'], hydro['task_id'])
    evidence = {
        'requests': [task.model_dump(mode='json') for task in (case.hydro, case.flood)],
        'combined': combined, 'requested_window': case.requested_window.model_dump(mode='json'),
    }
    return case, evidence, load_policy(ROOT / 'config/rules.example.json')


def plan(*, arguments=None, name='investigate_case', **changes):
    if arguments is None:
        arguments = {'case_id': 'configured-case', 'investigation': INVESTIGATION}
    return {'status': 'completed', 'output': [
        {'type': 'function_call', 'name': name,
         'arguments': arguments if isinstance(arguments, str) else json.dumps(arguments),
         'status': 'completed', **changes},
    ]}


def explanation(selection=None, *, text=None):
    if text is None:
        selected = ['metric.gpm.mean_accumulation_mm'] if selection is None else selection
        text = json.dumps({'selected_fact_ids': selected})
    return {'status': 'completed', 'output': [
        {'type': 'message', 'role': 'assistant', 'status': 'completed',
         'content': [{'type': 'output_text', 'text': text}]},
    ]}


class ScriptedClient:
    def __init__(self, *responses, events=None):
        self.responses = list(responses)
        self.calls = []
        self.events = events

    async def create(self, **payload):
        self.calls.append(deepcopy(payload))
        if self.events is not None:
            self.events.append(('api', len(self.calls)))
        assert self.responses, 'No unbounded extra API calls are permitted.'
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return deepcopy(response)


def review(prepared, client, **kwargs):
    case, evidence, policy = prepared
    return asyncio.run(run_agent(REQUEST, case, policy, client, evidence=evidence, **kwargs))


def forbid_dispatch(monkeypatch):
    async def unexpected(*args, **kwargs):
        pytest.fail('Evidence review or rejected planning must not dispatch workers.')
    monkeypatch.setattr(agent, 'run_analysis', unexpected)


def control_settings():
    return ControlSettings(
        hydro=WorkerEndpoint('http://hydro.invalid:8002', 'hydro-worker', token=SECRET),
        flood=WorkerEndpoint('http://flood.invalid:8003', 'flood-worker', token=SECRET),
    )


def dispatch_result(case, evidence):
    """A valid retained Control run, without a worker server or network fixture."""
    start, end = '2026-01-01T00:00:00Z', '2026-01-01T00:00:01Z'
    records = {}
    for role in ('hydro', 'flood'):
        result = evidence['combined'][role]
        status = {
            'task_id': case.hydro.task_id, 'worker_id': result['worker_id'],
            'analysis_type': result['analysis_type'], 'state': result['status'],
            'received_at': start, 'started_at': start, 'completed_at': end,
        }
        records[role] = {
            'task_id': case.hydro.task_id, 'worker_id': result['worker_id'],
            'analysis_type': result['analysis_type'], 'outcome': result['status'],
            'control_started_at': start, 'control_completed_at': end, 'submitted_at': start,
            'accepted': True, 'task_status': status,
            'observations': [{'observed_at': end, 'status': status}], 'result': result,
        }
    return DispatchRun.model_validate({
        'task_id': case.hydro.task_id, 'execution_mode': 'parallel',
        'control_started_at': start, 'control_completed_at': end,
        **records, 'combined': evidence['combined'],
    })


def test_review_retains_exact_deterministic_evidence_without_worker_dispatch(prepared, monkeypatch):
    forbid_dispatch(monkeypatch)
    case, evidence, policy = prepared
    original = deepcopy(evidence)
    expected = build_review_report(evidence, policy, requested_window=case.requested_window.model_dump(mode='json'))
    client = ScriptedClient(plan(), explanation())
    result = review(prepared, client)
    assert result['status'] == 'complete' and result['validation'] == 'PASS'
    assert result['phase_gate'] == 'PENDING_USER' and result['mode'] == 'review'
    assert result['deterministic'] == expected
    assert result['worker_evidence'] is None
    assert not result['dispatch_attempted'] and not result['execution_repeated']
    assert evidence == original
    assert result['explanation']['measurements'] == expected['fusion']['metrics']
    assert len(client.calls) == 2
    first = client.calls[0]
    assert first['tool_choice'] == 'required' and first['parallel_tool_calls'] is False
    assert {tool['name'] for tool in first['tools']} == {'investigate_case', 'decline_request'}
    for tool in first['tools']:
        assert tool['strict'] is True
        assert tool['parameters']['additionalProperties'] is False
        assert set(tool['parameters']['required']) == set(tool['parameters']['properties'])
    assert client.calls[1]['text']['format']['strict'] is True


@pytest.mark.parametrize('field', ['reference_time', 'threshold_db', 'resources', 'requested_window', 'bbox'])
def test_saved_evidence_must_match_every_configured_field_before_api(prepared, field):
    case, evidence, policy = prepared
    if field == 'reference_time':
        evidence['requests'][1]['reference_time'] = '2021-11-15T00:00:00Z'
    elif field == 'threshold_db':
        evidence['requests'][1]['threshold_db'] = -18.0
    elif field == 'resources':
        evidence['requests'][0]['gpm_resources'] = ['invented.HDF5']
    elif field == 'requested_window':
        evidence['requested_window']['start'] = '2021-11-15T00:00:00Z'
    else:
        evidence['requests'][0]['bbox']['west'] += 0.01
    client = ScriptedClient()
    with pytest.raises(ValueError):
        review(prepared, client)
    assert client.calls == []


def test_case_revalidates_nested_models_before_api(prepared):
    case, evidence, policy = prepared
    # Frozen dataclasses do not freeze the Pydantic models within them.
    changed = case.flood.model_copy(update={'reference_time': case.flood.start_time})
    client = ScriptedClient()
    with pytest.raises(ValueError, match='configured investigation'):
        asyncio.run(run_agent(REQUEST, replace(case, flood=changed), policy, client, evidence=evidence))
    assert client.calls == []


@pytest.mark.parametrize('mode', ['review', 'execute'])
@pytest.mark.parametrize('reason', ['unsupported_location', 'unsupported_time', 'unsupported_analysis', 'needs_clarification'])
def test_model_decline_never_dispatches_or_calls_explainer(prepared, monkeypatch, mode, reason):
    forbid_dispatch(monkeypatch)
    case, evidence, policy = prepared
    client = ScriptedClient(plan(name='decline_request', arguments={'reason': reason}))
    kwargs = {'evidence': evidence} if mode == 'review' else {'execute': True, 'control_settings': control_settings()}
    result = asyncio.run(run_agent('Forecast another city and issue evacuation advice.', case, policy, client, **kwargs))
    assert result['status'] == 'rejected' and result['validation'] == 'REJECTED'
    assert result['error']['code'] == reason and result['phase_gate'] == 'NOT_READY'
    assert not result['dispatch_attempted'] and not result['execution_repeated']
    assert (result['deterministic'] is not None) == (mode == 'review')
    assert len(client.calls) == 1


@pytest.mark.parametrize('bad_plan', [
    plan(arguments={'case_id': 'invented-case', 'investigation': INVESTIGATION}),
    plan(arguments={'case_id': 'configured-case', 'investigation': 'forecast'}),
    plan(arguments={'case_id': 'configured-case', 'investigation': INVESTIGATION, 'resource': 'invented.HDF5'}),
    plan(arguments={'case_id': 'configured-case', 'investigation': INVESTIGATION, 'execute': True}),
    plan(arguments={'case_id': 'configured-case', 'investigation': INVESTIGATION, 'threshold_db': -5}),
    plan(arguments={'case_id': 'configured-case'}),
    plan(arguments='{"case_id":"configured-case","case_id":"other","investigation":"combined_environmental_review"}'),
    plan(arguments='{"case_id":NaN}'),
    plan(arguments='[]'),
    plan(name='run_shell', arguments={'command': SECRET}),
    plan(name='decline_request', arguments={'reason': 'new-invented-reason'}),
    plan(name='decline_request', arguments={'reason': 'unsupported_time', 'extra': SECRET}),
    plan(status='in_progress'),
    {'status': 'completed', 'output': []},
    {'status': 'completed', 'output': plan()['output'] * 2},
    explanation(),
])
def test_invalid_model_tools_preserve_replay_and_cannot_dispatch(prepared, monkeypatch, bad_plan):
    forbid_dispatch(monkeypatch)
    case, evidence, policy = prepared
    expected = build_review_report(evidence, policy, requested_window=case.requested_window.model_dump(mode='json'))
    client = ScriptedClient(bad_plan)
    result = review(prepared, client)
    assert result['status'] == 'degraded' and result['validation'] == 'FAIL'
    assert result['error']['stage'] == 'interpretation'
    assert result['deterministic'] == expected and result['explanation']['status'] == 'fallback'
    assert not result['dispatch_attempted'] and len(client.calls) == 1
    assert SECRET not in json.dumps(result)


@pytest.mark.parametrize('stage', ['interpretation', 'explanation'])
@pytest.mark.parametrize('code', ['timeout', 'authentication_error', 'rate_limited', 'refusal', 'incomplete_response'])
def test_model_api_failures_preserve_deterministic_measurements_and_rules(prepared, monkeypatch, stage, code):
    forbid_dispatch(monkeypatch)
    case, evidence, policy = prepared
    expected = build_review_report(evidence, policy, requested_window=case.requested_window.model_dump(mode='json'))
    replies = [AgentAPIError(code)] if stage == 'interpretation' else [plan(), AgentAPIError(code)]
    client = ScriptedClient(*replies)
    result = review(prepared, client)
    assert result['error'] == {'stage': stage, 'code': code}
    assert result['status'] == 'degraded' and result['phase_gate'] == 'NOT_READY'
    assert result['deterministic'] == expected
    assert result['explanation']['status'] == 'fallback'
    assert result['explanation']['measurements'] == expected['fusion']['metrics']
    assert len(result['explanation']['rule_outcomes']) == len(policy.rules)
    assert len(client.calls) == (1 if stage == 'interpretation' else 2)


@pytest.mark.parametrize('bad_explanation', [
    explanation([]), explanation(['invented.fact']),
    explanation(text='{"selected_fact_ids":null}'),
    explanation(['metric.gpm.mean_accumulation_mm'] * 2),
    explanation('metric.gpm.mean_accumulation_mm'), explanation([True]),
    explanation(text=json.dumps({'selected_fact_ids': ['metric.gpm.mean_accumulation_mm'], 'narrative': SECRET})),
    explanation(text='{"selected_fact_ids":[],"selected_fact_ids":["disclaimer"]}'),
    plan(),
    {'status': 'completed', 'output': explanation()['output'] * 2},
    {'status': 'completed', 'output': [{'type': 'message', 'role': 'assistant', 'content': [{'type': 'refusal', 'refusal': SECRET}]}]},
])
def test_malformed_explanation_cannot_replace_deterministic_fallback(prepared, bad_explanation):
    result = review(prepared, ScriptedClient(plan(), bad_explanation))
    assert result['status'] == 'degraded' and result['error']['stage'] == 'explanation'
    assert result['deterministic']['validation'] == 'PASS'
    assert result['explanation']['status'] == 'fallback'
    assert SECRET not in json.dumps(result)


def test_review_evidence_is_persisted_before_any_api_call_and_before_explanation(prepared):
    snapshots, events = [], []

    def persist(value):
        snapshots.append(value)
        events.append(('save', len(snapshots)))

    client = ScriptedClient(plan(), explanation(), events=events)
    result = review(prepared, client, persist=persist)
    assert events == [('save', 1), ('api', 1), ('save', 2), ('api', 2), ('save', 3)]
    assert snapshots[0]['deterministic'] == result['deterministic']
    assert snapshots[0]['plan'] is None and snapshots[0]['explanation']['status'] == 'fallback'
    assert snapshots[1]['plan']['tool'] == 'investigate_case'
    assert snapshots[1]['explanation']['status'] == 'fallback'
    assert snapshots[-1] == result


def test_persistence_failure_prevents_first_model_call(prepared):
    client = ScriptedClient()

    def persist(value):
        raise OSError('Cannot preserve evidence.')

    with pytest.raises(OSError):
        review(prepared, client, persist=persist)
    assert client.calls == []


def test_persist_callback_receives_detached_snapshots(prepared):
    def persist(value):
        value['requests'].clear()
        value['deterministic']['fusion']['metrics'].clear()

    result = review(prepared, ScriptedClient(plan(), explanation()), persist=persist)
    assert result['status'] == 'complete'
    assert len(result['requests']) == 2 and len(result['deterministic']['fusion']['metrics']) == 8


def test_new_execution_dispatches_exact_configured_tasks_once_and_persists_before_explanation(prepared, monkeypatch):
    case, evidence, policy = prepared
    settings = control_settings()
    run = dispatch_result(case, evidence)
    snapshots, events, calls = [], [], []

    def persist(value):
        snapshots.append(value)
        events.append(('save', len(snapshots)))

    async def execute(hydro, flood, configuration, **kwargs):
        calls.append((hydro, flood, configuration, kwargs))
        events.append(('dispatch', 1))
        assert snapshots[-1]['dispatch_attempted']
        assert snapshots[-1]['requests'] == evidence['requests']
        return run

    monkeypatch.setattr(agent, 'run_analysis', execute)
    client = ScriptedClient(plan(), explanation(), events=events)
    result = asyncio.run(run_agent(REQUEST, case, policy, client, execute=True,
                                  control_settings=settings, persist=persist))
    assert calls == [(case.hydro, case.flood, settings, {'execution_mode': 'parallel'})]
    assert result['status'] == 'complete' and result['mode'] == 'execute'
    assert result['dispatch_attempted'] and result['execution_repeated']
    assert result['worker_evidence']['dispatch'] == run.model_dump(mode='json')
    assert result['deterministic']['fusion']['source_results'] == run.combined.model_dump(mode='json')
    assert events == [('save', 1), ('api', 1), ('save', 2), ('save', 3), ('dispatch', 1),
                      ('save', 4), ('save', 5), ('api', 2), ('save', 6)]
    assert snapshots[3]['worker_evidence']['dispatch'] == run.model_dump(mode='json')
    assert snapshots[3]['deterministic'] is None
    assert snapshots[4]['deterministic'] == result['deterministic']
    assert snapshots[4]['explanation']['status'] == 'fallback'
    assert SECRET not in json.dumps(client.calls)


@pytest.mark.parametrize('fail_save,dispatches', [(1, 0), (2, 0), (3, 0), (4, 1), (5, 1)])
def test_execute_persistence_failure_stops_subsequent_side_effects(prepared, monkeypatch, fail_save, dispatches):
    case, evidence, policy = prepared
    run = dispatch_result(case, evidence)
    calls, saves = [], []

    async def execute(*args, **kwargs):
        calls.append(args)
        return run

    def persist(value):
        saves.append(value)
        if len(saves) == fail_save:
            raise OSError('Cannot preserve checkpoint.')

    monkeypatch.setattr(agent, 'run_analysis', execute)
    client = ScriptedClient(plan())
    with pytest.raises(OSError):
        asyncio.run(run_agent(REQUEST, case, policy, client, execute=True,
                              control_settings=control_settings(), persist=persist))
    assert len(calls) == dispatches
    assert len(client.calls) == (0 if fail_save == 1 else 1)


def test_explanation_failure_after_execution_keeps_new_raw_and_deterministic_evidence(prepared, monkeypatch):
    case, evidence, policy = prepared
    run = dispatch_result(case, evidence)
    calls = []

    async def execute(*args, **kwargs):
        calls.append(args)
        return run

    monkeypatch.setattr(agent, 'run_analysis', execute)
    result = asyncio.run(run_agent(REQUEST, case, policy, ScriptedClient(plan(), AgentAPIError('timeout')),
                                  execute=True, control_settings=control_settings()))
    assert result['status'] == 'degraded' and result['error']['stage'] == 'explanation'
    assert result['worker_evidence']['dispatch'] == run.model_dump(mode='json')
    assert result['deterministic']['fusion']['source_results'] == run.combined.model_dump(mode='json')
    assert result['explanation']['status'] == 'fallback' and len(calls) == 1


def test_raw_private_metadata_and_error_details_never_enter_model_context(prepared, monkeypatch):
    case, evidence, policy = prepared
    evidence['worker_token'] = SECRET
    evidence['combined']['errors'].append(SECRET)
    evidence['combined']['flood']['evidence']['sentinel1']['operator_note'] = SECRET
    policy.label = SECRET
    policy.rules[0].label = SECRET
    monkeypatch.setenv('OPENAI_API_KEY', SECRET)
    monkeypatch.setenv('HYDRO_WORKER_TOKEN', SECRET)
    client = ScriptedClient(plan(), explanation())
    result = review(prepared, client)
    assert result['status'] == 'complete'
    assert SECRET in json.dumps(result['deterministic'])
    assert SECRET not in json.dumps(client.calls)
    assert SECRET not in result['explanation']['narrative']
    assert case.hydro.smap_resource not in json.dumps(client.calls)
    assert case.hydro.gpm_resources[0] not in json.dumps(client.calls)


@pytest.mark.parametrize('kwargs', [{}, {'execute': True}, {'execute': 1}, {'execute': False, 'control_settings': 'not-settings'}])
def test_mode_and_execution_configuration_require_explicit_valid_selection(prepared, kwargs):
    case, evidence, policy = prepared
    client = ScriptedClient()
    with pytest.raises(ValueError):
        asyncio.run(run_agent(REQUEST, case, policy, client, **kwargs))
    assert client.calls == []


def test_execution_and_existing_evidence_cannot_be_selected_together(prepared):
    case, evidence, policy = prepared
    client = ScriptedClient()
    with pytest.raises(ValueError):
        asyncio.run(run_agent(REQUEST, case, policy, client, execute=True, evidence=evidence,
                              control_settings=control_settings()))
    assert client.calls == []


@pytest.mark.parametrize('bad_plan', [
    plan(arguments={'case_id': 'invented-case', 'investigation': INVESTIGATION}),
    plan(arguments={'case_id': 'configured-case', 'investigation': INVESTIGATION, 'worker_url': 'http://attacker.invalid'}),
    plan(name='run_shell', arguments={'command': SECRET}),
    {'status': 'completed', 'output': plan()['output'] * 2},
    AgentAPIError('timeout'),
])
def test_explicit_execute_still_requires_one_valid_allowlisted_plan(prepared, monkeypatch, bad_plan):
    forbid_dispatch(monkeypatch)
    case, evidence, policy = prepared
    client = ScriptedClient(bad_plan)
    result = asyncio.run(run_agent(REQUEST, case, policy, client, execute=True,
                                  control_settings=control_settings()))
    assert result['status'] == 'degraded' and result['error']['stage'] == 'interpretation'
    assert result['deterministic'] is None and result['worker_evidence'] is None
    assert not result['dispatch_attempted'] and not result['execution_repeated']
    assert len(client.calls) == 1 and SECRET not in json.dumps(result)


@pytest.mark.parametrize('request_text', ['', ' \n\t ', None, 5, 'é' * 2049, 'bad\x00request'])
def test_invalid_request_text_fails_before_model_or_worker(prepared, monkeypatch, request_text):
    forbid_dispatch(monkeypatch)
    case, evidence, policy = prepared
    client = ScriptedClient()
    with pytest.raises(ValueError):
        asyncio.run(run_agent(request_text, case, policy, client, evidence=evidence))
    assert client.calls == []
