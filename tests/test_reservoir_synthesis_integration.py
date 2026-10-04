"""Control combines independent checked inputs before writing its readable report."""

import json
import pytest
from fastapi.testclient import TestClient

from backend.control.reservoir_web import ReservoirService, create_reservoir_app
from backend.shared.dam_contracts import DamCounts, DamMetrics, DamResult, expected_rules, expected_summary
from test_reservoir_control import factory_with_workers, settings, submit, wait_finished, TOD, MOMENT
from backend.control.openai_client import AgentAPIError


class Model:
    def __init__(self, level):
        self.level, self.calls = level, []

    async def create(self, **payload):
        self.calls.append(payload)
        catalog = json.loads(payload['input'][0]['content'])
        value = {'level': self.level, 'title': self.level.title() + ' flood-risk screening concern',
                 'summary': {'low': 'The observations support routine monitoring and maintenance.',
                             'moderate': 'The observed conditions warrant continued maintenance attention.',
                             'high': 'Rainfall pressure combined with the recorded dam condition warrants heightened concern.',
                             'critical': 'The recorded dam condition is a serious concern even without a strong rainfall contribution.'}[self.level],
                 'basis': 'This interpretation considers the rainfall and site condition together.',
                 'reasons': [{'text': 'The rainfall measurement and the recorded condition jointly inform the assessment.',
                              'field_refs': ['gpm.metrics.area_mean_total_accumulation_mm',
                                             'dam.summary.integrity_concern', 'dam.summary.risk_level']}],
                 'evidence_digest': catalog['evidence_digest']}
        return {'status': 'completed', 'output': [{'type': 'message', 'role': 'assistant',
                                                  'content': [{'type': 'output_text', 'text': json.dumps(value)}]}]}


def scenario(tmp_path, rainfall, integrity, level):
    def mutate(role, result):
        if role == 'hydro':
            rain, soil = result['components']
            rain['metrics'].update(area_mean_total_accumulation_mm=rainfall,
                                   max_cell_total_accumulation_mm=rainfall)
            soil['metrics'].update(surface_mean_m3_m3=.25, surface_max_m3_m3=.30)
        elif role == 'dam' and integrity != 'critical':
            result['metrics'].update(
                latest_pool_level_mod=185.0, latest_pool_departure_m=-.67,
                current_spillway_flowing=False, sealant_defect_fraction=1.0 if integrity == 'moderate' else 0.0,
                blocked_relief_fraction=0.0, seepage_at_full_pool_fraction=0.0,
                latest_inspection_grade='B', known_integrity_action=False, monitoring_gap=False,
            )
            metrics = DamMetrics.model_validate(result['metrics'])
            counts = DamCounts.model_validate(result['evidence']['counts'])
            result['summary'] = expected_summary(metrics, counts).model_dump(mode='json')
            triggered = expected_rules(metrics)
            for rule in result['rules']:
                rule['triggered'] = triggered[rule['rule_id']]
            DamResult.model_validate(result)
    factory, _, _ = factory_with_workers(mutation=mutate, measured=True)
    model = Model(level)
    service = ReservoirService(settings(), history_dir=tmp_path, client_factory=factory, synthesis_client=model)
    with TestClient(create_reservoir_app(service)) as client:
        identifier = submit(client)
        view = wait_finished(client, identifier)
        report = client.get(f'/sessions/{identifier}/briefing').text
        assert submit(client, request_id=service.sessions[identifier]['request_id']) == identifier
        assert len(model.calls) == 1
        assert view['validationFailures'] == []
    # Reload retains the exact AI result without another model or worker call.
    restored = ReservoirService(settings(), history_dir=tmp_path, client_factory=factory, synthesis_client=model)
    with TestClient(create_reservoir_app(restored)) as client:
        assert client.get('/sessions/' + identifier).json()['risk'] == view['risk']
    assert len(model.calls) == 1
    catalog = json.loads(model.calls[0]['input'][0]['content'])
    assert catalog['facts']['gpm.metrics.area_mean_total_accumulation_mm']['value'] == rainfall
    assert 'Toddbrook' not in json.dumps(catalog) and '/private_data/' not in json.dumps(catalog)
    return view, report


@pytest.mark.parametrize('rainfall,integrity,expected', [
    (5.0, 'low', 'low'),
    (30.0, 'low', 'moderate'),
    (5.0, 'moderate', 'moderate'),
    (30.0, 'moderate', 'high'),
    (5.0, 'critical', 'critical'),
])
def test_http_report_distinguishes_routine_combined_and_independent_concern(tmp_path, rainfall, integrity, expected):
    view, report = scenario(tmp_path, rainfall, integrity, expected)
    assert view['status'] == 'briefing-ready'
    assert view['risk']['level'] == expected
    assert view['risk']['alert'] == (expected in {'high', 'critical'})
    assert view['risk']['summary'] in report
    assert report.index(view['risk']['summary']) < report.index('Environmental measurements')
    assert 'above normal' not in view['risk']['summary'].lower()
    assert any(row['label'].endswith('Area-mean rainfall accumulation') for row in view['briefing']['metrics'])
    assert all(worker['returned'] and worker['validated'] for worker in view['workers'].values())
    if rainfall == 30.0 and integrity == 'moderate':
        assert any(row['id'] == 'synthesis' for row in view['briefing']['sections'])
        assert 'combined' in view['risk']['summary']


def test_same_inputs_do_not_force_a_new_hand_coded_interaction_threshold(tmp_path):
    moderate, _ = scenario(tmp_path / 'moderate', 30.0, 'moderate', 'moderate')
    high, _ = scenario(tmp_path / 'high', 30.0, 'moderate', 'high')
    assert moderate['risk']['level'] == 'moderate' and high['risk']['level'] == 'high'
    assert moderate['briefing']['metrics'] == high['briefing']['metrics']


def test_model_failure_keeps_worker_results_and_reports_the_fallback(tmp_path):
    class Unavailable:
        calls = 0
        async def create(self, **payload):
            self.calls += 1
            raise AgentAPIError('timeout')
    model = Unavailable()
    factory, _, _ = factory_with_workers(measured=True)
    service = ReservoirService(settings(), history_dir=tmp_path, client_factory=factory, synthesis_client=model)
    with TestClient(create_reservoir_app(service)) as client:
        identifier = submit(client)
        view = wait_finished(client, identifier)
    assert model.calls == 1 and view['status'] == 'briefing-ready'
    assert view['risk']['level'] == 'critical'
    assert 'AI synthesis is unavailable' in view['risk']['basis']
    assert all(record['result'] is not None for record in service.sessions[identifier]['records'].values())
    assert view['validationFailures']


@pytest.mark.parametrize('state,active_step,phrase', [
    ('acquiring_data', 'acquisition', 'Finding and downloading'),
    ('processing', 'processing', 'Analyzing'),
    ('preparing_result', 'returned', 'Preparing'),
])
def test_control_shows_the_actual_hydro_stage(state, active_step, phrase, tmp_path):
    service = ReservoirService(settings(), history_dir=tmp_path)
    session = {'id': '11111111-1111-4111-8111-111111111111', 'prompt': TOD,
               'created_at': MOMENT, 'state': 'running', 'error': None,
               'records': {'hydro': {'status': {'state': state}, 'outcome': None, 'result': None}}}
    worker = service.public(session)['workers']['hydro']
    assert worker['status'] == 'active'
    assert phrase in worker['summary']
    assert [step['id'] for step in worker['steps'] if step['state'] == 'active'] == [active_step]
    assert all(step['state'] == 'pending' for step in worker['steps']
               if step['id'] == 'validated')


def test_control_does_not_invent_an_acquisition_milestone(tmp_path):
    service = ReservoirService(settings(), history_dir=tmp_path)
    session = {'id': '11111111-1111-4111-8111-111111111111', 'prompt': TOD,
               'created_at': MOMENT, 'state': 'running', 'error': None,
               'records': {'hydro': {'status': {'state': 'processing'}, 'outcome': None,
                                      'result': None, 'events': []}}}
    worker = service.public(session)['workers']['hydro']
    assert 'acquisition' not in [step['id'] for step in worker['steps']]
