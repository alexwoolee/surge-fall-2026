"""Privacy, cutoff and deterministic screening checks using minimal structural records."""

from copy import deepcopy
import json
from pathlib import Path
import time

from fastapi.testclient import TestClient
from pydantic import ValidationError
import pytest

from backend.shared.contracts import AnalysisTask
from backend.shared.dam_contracts import DamResult, DamTask
from backend.shared.dam_records import project_record
from backend.shared.settings import WorkerEndpoint, WorkerSettings
from backend.shared.worker_api import create_worker_app
from backend.workers.dam.main import create_app
from backend.workers.dam.service import analyze
from scripts import run_worker

FILES = {'operations': 'weekly_ops_logs.jsonl', 'supervision': 'se_reports.jsonl',
         'inspection': 'inspections_s10.jsonl', 'maintenance': 'maintenance_requests.jsonl',
         'instrumentation': 'instrumentation_log.jsonl'}
PRIVATE = 'SECRET_INSPECTOR_/private/path_source_marker'


def task(as_of='2019-07-31', **kwargs):
    return DamTask(task_id='dam-test', window='2015-2019', as_of=as_of, **kwargs)


def visit(day, **changes):
    result = {'dam_id': 'TODDBROOK', 'date': day, 'available_date': day,
              'pool_level_mOD': 185.5, 'aux_spillway_flowing': False,
              'observations': {'sealant_defects': False, 'seepage_at_crest_joint': False,
                               'relief_holes_blocked': False}}
    result.update(changes)
    return result


def write_records(root, rows):
    root.mkdir(parents=True, exist_ok=True)
    for key, name in FILES.items():
        (root / name).write_text(''.join(json.dumps(row) + '\n' for row in rows[key]))
    return root


def prepared_records(rows):
    return {category: [project_record(FILES[category], row) for row in values]
            for category, values in rows.items()}


@pytest.fixture
def records():
    return {'operations': [visit(day) for day in ('2019-07-20', '2019-07-25', '2019-07-31')],
            'supervision': [{'dam_id': 'TODDBROOK', 'date': '2019-05-01', 'available_date': '2019-05-02', 'piezometers_serviceable': True}],
            'inspection': [{'dam_id': 'TODDBROOK', 'date': '2018-11-15', 'available_date': '2019-04-04', 'grade_after': 'B', 'mios': []}],
            'maintenance': [{'dam_id': 'TODDBROOK', 'opened': '2017-01-01', 'available_date': '2017-01-01', 'closed_date': '2017-02-01', 'item_class': 'joint_sealant'}],
            'instrumentation': [{'dam_id': 'TODDBROOK', 'year': 2018, 'available_date': '2019-01-31', 'piezometer_readings_taken': True, 'piezometer_data_plotted': True}]}


def terminal(client, identity='dam-test'):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        value = client.get(f'/tasks/{identity}').json()
        if value['state'] in ('complete', 'partial', 'failed'):
            return value
        time.sleep(.005)
    pytest.fail('Worker did not finish.')


def test_complete_low_screening_is_reproducible_and_only_aggregates_leave_worker(tmp_path, records):
    path = write_records(tmp_path, records)
    result = analyze(task(), data_dir=path)
    assert result == analyze(task(), data_dir=path)
    assert result.summary.risk_level == 'low'
    assert result.summary.confidence_score == 1
    assert result.evidence.record_count == 7
    serialized = result.model_dump_json()
    for word in (PRIVATE, 'inspector_id', 'provenance', 'source_marker', 'request_id', str(tmp_path), 'summary_note'):
        assert word not in serialized
    assert all(ref.startswith('r_') and len(ref) == 26 for ref in result.evidence.record_refs)


def test_current_loading_plus_known_integrity_concern_triggers_alert(tmp_path, records):
    records['inspection'][0]['grade_after'] = 'D'
    records['operations'][-1].update(pool_level_mOD=186.0, aux_spillway_flowing=True)
    result = analyze(task(), data_dir=write_records(tmp_path, records))
    assert result.summary.risk_level == 'critical'
    assert result.summary.risk_score == 90 and result.summary.alert
    assert result.summary.hydraulic_loading == 'elevated'
    assert {rule.rule_id for rule in result.rules if rule.triggered} == {'D05', 'D06'}


def test_millimetric_datum_exceedance_does_not_trigger_hydraulic_alert(tmp_path, records):
    records['inspection'][0]['grade_after'] = 'D'
    records['operations'][-1]['pool_level_mOD'] = 185.673
    result = analyze(task(), data_dir=write_records(tmp_path, records))
    assert result.summary.risk_level == 'high'
    assert result.summary.hydraulic_loading == 'normal'


def test_both_event_and_availability_dates_gate_every_dated_record(tmp_path, records):
    records['operations'] += [visit('2019-07-30', available_date='2019-08-01'), visit('2019-08-01', available_date='2019-07-01')]
    records['inspection'][0]['available_date'] = '2019-08-01'
    records['inspection'][0]['grade_after'] = 'E'
    records['supervision'][0]['date'] = '2019-08-01'
    records['instrumentation'][0]['year'] = 2019
    records['maintenance'][0]['available_date'] = '2019-08-01'
    result = analyze(task(), data_dir=write_records(tmp_path, records))
    assert result.evidence.counts.model_dump() == {'operations': 3, 'supervision': 0, 'inspection': 0, 'maintenance': 0, 'instrumentation': 0}
    assert result.metrics.latest_inspection_grade is None


def test_future_closure_and_scheduling_never_close_current_maintenance(tmp_path, records):
    records['maintenance'][0].update(closed_date='2020-01-01', scheduled_for='2019-07-01')
    prepared = prepared_records(records)
    assert 'scheduled_for' not in prepared['maintenance'][0]
    result = analyze(task(), data_dir=write_records(tmp_path, prepared))
    assert result.metrics.open_maintenance_count == result.metrics.long_open_maintenance_count == 1
    assert '2020-01-01' not in result.model_dump_json()
    records['maintenance'][0]['closed_date'] = '2019-07-31'
    assert analyze(task(), data_dir=write_records(tmp_path, prepared_records(records))).metrics.open_maintenance_count == 0


def test_as_of_uses_available_inspection_not_future_grade(tmp_path, records):
    records['operations'] = [visit(day) for day in ('2019-03-20', '2019-03-25', '2019-04-03')]
    records['inspection'][0]['grade_after'] = 'D'
    before = analyze(task('2019-04-03'), data_dir=write_records(tmp_path, records))
    after = analyze(task('2019-04-04'), data_dir=tmp_path)
    assert before.metrics.latest_inspection_grade is None
    assert after.metrics.latest_inspection_grade == 'D'
    assert after.summary.risk_level == 'high'


def test_selected_window_does_not_use_previous_period_operations(tmp_path, records):
    records['operations'] += [visit('2007-12-09')]
    result = analyze(task(), data_dir=write_records(tmp_path, records))
    assert result.evidence.counts.operations == 3
    assert result.evidence.first_observation.isoformat() == '2019-07-20'


def test_no_or_stale_observations_are_unknown_not_low_risk(tmp_path, records):
    records['operations'] = [visit('2015-10-01')]
    result = analyze(task(), data_dir=write_records(tmp_path, records))
    assert result.summary.risk_level == 'unknown'
    assert result.summary.hydraulic_loading == 'unknown'
    assert result.metrics.current_spillway_flowing is None


def test_outside_coverage_does_not_open_local_files(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, 'read_bytes', lambda *_: pytest.fail('Read attempted outside coverage.'))
    result = analyze(DamTask(window='outside-coverage', as_of='2013-01-01'), data_dir=tmp_path)
    assert result.summary.risk_level == 'unknown' and result.summary.confidence_score == 0
    assert result.summary.risk_score is None
    assert result.evidence.record_count == 0


@pytest.mark.parametrize('changes', [
    {'as_of': '2019-08-01'}, {'as_of': '2019-07-31T00:00:00Z'}, {'as_of': 123},
    {'window': 'outside-coverage'}, {'site_id': 'another-reservoir'}, {'window': '2007-2008'},
    {'data_dir': '/private/path'}, {'analysis_type': 'surface_water_and_terrain'},
])
def test_dam_task_rejects_wrong_site_window_dates_or_file_selectors(changes):
    payload = {'window': '2015-2019', 'as_of': '2019-07-31', **changes}
    with pytest.raises(ValidationError):
        DamTask.model_validate(payload)


@pytest.mark.parametrize('mutate', [
    lambda rows: rows['operations'][0].update(pool_level_mOD=float('nan')),
    lambda rows: rows['operations'][0].update(pool_level_mOD='185.5'),
    lambda rows: rows['operations'][0]['observations'].update(sealant_defects='false'),
    lambda rows: rows['operations'][0].update(available_date='yesterday'),
    lambda rows: rows['instrumentation'][0].update(year=True),
    lambda rows: rows['instrumentation'][0].update(piezometer_readings_taken=False, piezometer_data_plotted='bad'),
    lambda rows: rows['maintenance'][0].update(closed_date='2016-01-01'),
    lambda rows: rows['inspection'][0].update(grade_after=PRIVATE),
    lambda rows: rows['operations'][0].update(provenance=PRIVATE),
    lambda rows: rows['operations'][0]['observations'].update(origin_label=PRIVATE),
    lambda rows: rows['inspection'][0].update(mios=[{'klass': 'spillway_hydraulic_integrity', 'source': PRIVATE}]),
    lambda rows: rows['maintenance'][0].update(request_id=PRIVATE),
])
def test_malformed_local_evidence_rejected_without_sensitive_errors(tmp_path, records, mutate):
    mutate(records)
    with pytest.raises(ValueError, match='^Local evidence could not be validated.$'):
        analyze(task(), data_dir=write_records(tmp_path, records))


def test_symlink_cannot_escape_private_dataset_root(tmp_path, records):
    root = write_records(tmp_path / 'root', records)
    original = root / FILES['operations']
    outside = tmp_path / 'outside.jsonl'
    original.rename(outside)
    try:
        original.symlink_to(outside)
    except OSError as error:
        if getattr(error, 'winerror', None) == 1314:
            pytest.skip('Windows account lacks symlink privilege.')
        raise
    with pytest.raises(ValueError, match='^Local evidence could not be validated.$'):
        analyze(task(), data_dir=root)


def test_non_allowlisted_files_are_never_opened_even_when_invalid(tmp_path, records, monkeypatch):
    root = write_records(tmp_path / 'runtime', records)
    before = analyze(task(), data_dir=root)
    for filename in ('real_timeline.csv', 'ground_truth_EVAL_ONLY.csv', 'event_timeline_EVAL_ONLY.csv', 'design_records.jsonl', 'build_dataset.py'):
        # Entirely invented invalid bytes: no actual evaluation data is read.
        (root / filename).write_bytes(b'\xff\x00NOT_JSON\nraise RuntimeError()')
    read_bytes, open_file = Path.read_bytes, Path.open
    accessed = set()
    allowed = {root / name for name in FILES.values()}
    def checked_read(path):
        assert path in allowed, 'Worker tried to read a non-runtime input.'
        accessed.add(path)
        return read_bytes(path)
    def checked_open(path, mode='r', *args, **kwargs):
        if 'r' in mode:
            assert path in allowed, 'Worker tried to open a non-runtime input.'
            accessed.add(path)
        return open_file(path, mode, *args, **kwargs)
    monkeypatch.setattr(Path, 'read_bytes', checked_read)
    monkeypatch.setattr(Path, 'open', checked_open)
    after = analyze(task(), data_dir=root)
    assert before == after
    assert accessed == allowed


@pytest.mark.parametrize('label', ['arbitrary-label-one', 'arbitrary-label-two', {'arbitrary': [1, 2, 'value']}])
def test_discarded_metadata_cannot_weight_filter_or_change_any_result(tmp_path, records, label):
    # The labels are invented test values, never classifications of owner data.
    records['inspection'][0]['mios'] = [{'klass': 'spillway_hydraulic_integrity'}]
    clean = prepared_records(records)
    before = analyze(task(), data_dir=write_records(tmp_path, clean))
    supplied = deepcopy(records)
    for rows in supplied.values():
        for row in rows:
            row.update(provenance=label, source=label, note=PRIVATE, origin_label=label)
    for row in supplied['operations']:
        row['observations']['origin_label'] = label
    supplied['inspection'][0]['mios'][0].update(source=label, notes=PRIVATE)
    prepared = prepared_records(supplied)
    assert prepared == clean
    assert PRIVATE not in json.dumps(prepared)
    assert all(len(prepared[key]) == len(supplied[key]) for key in supplied)
    after = analyze(task(), data_dir=write_records(tmp_path, prepared))
    assert after == before
    assert after.evidence.record_count == 7


def test_operational_changes_still_change_screening_with_identical_discarded_metadata(tmp_path, records):
    for rows in records.values():
        for row in rows:
            row['origin_label'] = 'constant-arbitrary-label'
    before = analyze(task(), data_dir=write_records(tmp_path, prepared_records(records)))
    records['inspection'][0]['grade_after'] = 'D'
    records['operations'][-1].update(pool_level_mOD=186.0, aux_spillway_flowing=True)
    after = analyze(task(), data_dir=write_records(tmp_path, prepared_records(records)))
    assert before.summary.risk_level == 'low' and after.summary.risk_level == 'critical'
    assert before.evidence.record_count == after.evidence.record_count


def test_default_runtime_directory_never_falls_back_to_original_archive(monkeypatch):
    monkeypatch.delenv('MESHMIND_DAM_DATA_DIR', raising=False)
    expected = Path(__file__).resolve().parents[1] / 'private_data/toddbrook_runtime/data'
    assert WorkerSettings().dam_data_dir == expected
    assert WorkerSettings.from_env().dam_data_dir == expected


def test_result_contract_rejects_raw_fields_and_altered_conclusions(tmp_path, records):
    raw = analyze(task(), data_dir=write_records(tmp_path, records)).model_dump(mode='json')
    for value in (dict(raw, records=[PRIVATE]), {**raw, 'summary': {**raw['summary'], 'risk_level': 'critical'}},
                  {**raw, 'site': {**raw['site'], 'name': PRIVATE}}):
        with pytest.raises(ValidationError):
            DamResult.model_validate(value)


def test_http_lifecycle_dashboard_and_schema_do_not_expose_records(tmp_path, records):
    app = create_app(WorkerSettings(dam_data_dir=write_records(tmp_path, records)))
    with TestClient(app) as client:
        assert client.get('/dashboard/state').json()['risk'] is None
        assert client.get('/clock').json()['worker_id'] == 'dam-worker'
        submitted = client.post('/tasks', json=task().model_dump(mode='json'), headers={'Authorization': 'invalid'})
        assert submitted.status_code == 202
        assert terminal(client)['state'] == 'complete'
        response = client.get('/tasks/dam-test/result')
        result = DamResult.model_validate(response.json())
        assert result.summary.risk_level == 'low'
        state = client.get('/dashboard/state').json()
        assert state['role'] == 'dam' and state['risk']['level'] == 'low'
        assert [event['state'] for event in state['events']] == ['task_received', 'dataset_located', 'processing', 'preparing_result', 'complete']
        for path in ('/status', '/clock', '/tasks/dam-test', '/tasks/dam-test/result', '/dashboard/state', '/openapi.json'):
            text = client.get(path).text
            assert PRIVATE not in text and str(tmp_path) not in text
            assert 'inspector_id' not in text and 'provenance' not in text
        invalid = client.post('/tasks', json={**task().model_dump(mode='json'), PRIVATE: PRIVATE})
        assert invalid.status_code == 422 and PRIVATE not in invalid.text
        assert client.get('/private_data/toddbrook_runtime/data/weekly_ops_logs.jsonl').status_code == 404


def test_failed_worker_redacts_errors_and_never_publishes_a_result():
    def runner(task, progress):
        raise ValueError(PRIVATE)
    with TestClient(create_worker_app('dam-worker', 'dam_risk', runner)) as client:
        assert client.post('/tasks', json=task().model_dump(mode='json')).status_code == 202
        state = terminal(client)
        assert state['state'] == 'failed' and PRIVATE not in json.dumps(state)
        assert client.get('/tasks/dam-test/result').status_code == 409
        assert client.get('/dashboard/state').json()['risk'] is None


def test_result_is_bound_to_the_accepted_cutoff(tmp_path, records):
    wrong = analyze(task('2019-07-30'), data_dir=write_records(tmp_path, records)).model_dump(mode='json')
    with TestClient(create_worker_app('dam-worker', 'dam_risk', lambda task, progress: wrong)) as client:
        client.post('/tasks', json=task().model_dump(mode='json'))
        assert terminal(client)['state'] == 'failed'
        assert client.get('/tasks/dam-test/result').status_code == 409


def test_dam_worker_uses_own_local_settings_and_dashboard(monkeypatch, tmp_path):
    monkeypatch.setenv('MESHMIND_DAM_DATA_DIR', str(tmp_path))
    assert WorkerSettings.from_env().dam_data_dir == tmp_path
    assert WorkerEndpoint('http://127.0.0.1:8004', 'dam-worker').expected_worker_id == 'dam-worker'
    captured = []
    def run(server):
        captured.append(server)
        server.started = True
    monkeypatch.setattr(run_worker.WorkerServer, 'run', run)
    assert run_worker.main(['dam']) == 0
    assert captured[0].config.app == 'backend.workers.dam.main:create_app'
    assert captured[0].config.port == 8004
    assert captured[0].dashboard_url == 'http://127.0.0.1:8004/dashboard'


@pytest.mark.parametrize('when,window,risk,grade', [
    ('2007-12-04', '2007-2008', 'moderate', 'B'), ('2007-12-09', '2007-2008', 'moderate', 'B'),
    ('2019-03-01', '2015-2019', 'high', 'C'), ('2019-07-26', '2015-2019', 'high', 'D'),
    ('2019-07-31', '2015-2019', 'critical', 'D'),
])
def test_locally_installed_periods_have_cutoff_specific_results(when, window, risk, grade):
    path = Path(__file__).parents[1] / 'private_data/toddbrook_runtime/data'
    if not path.is_dir():
        pytest.skip('Private dataset is not installed on this device.')
    result = analyze(DamTask(window=window, as_of=when), data_dir=path)
    assert result.summary.risk_level == risk and result.metrics.latest_inspection_grade == grade
    assert result.evidence.last_observation <= result.as_of
    assert result.summary.alert == (risk in ('high', 'critical'))


def test_future_records_cannot_change_even_opaque_reference_ids(tmp_path, records):
    before = analyze(task(), data_dir=write_records(tmp_path, records))
    records['operations'].insert(0, visit('2020-01-01', available_date='2020-01-01'))
    after = analyze(task(), data_dir=write_records(tmp_path, records))
    assert before == after


def test_annual_instrumentation_is_counted_only_after_year_end(tmp_path, records):
    records['instrumentation'] = [{'dam_id': 'TODDBROOK', 'year': 2019, 'available_date': '2019-07-01', 'piezometer_readings_taken': True, 'piezometer_data_plotted': True}]
    result = analyze(task(), data_dir=write_records(tmp_path, records))
    assert result.evidence.counts.instrumentation == 0
    assert any('calendar year ends' in text for text in result.limitations)


@pytest.mark.parametrize('role', ['hydro', 'flood'])
def test_existing_workers_accept_context_tasks_with_exact_result_binding(role):
    from backend.shared.context_contracts import ContextTask, ContextResult
    analysis = 'hydrometeorology' if role == 'hydro' else 'surface_water_and_terrain'
    requested = ContextTask(task_id='dam-test', analysis_type=analysis, location_id='somewhere',
                            bbox={'west': -2.01, 'south': 53.30, 'east': -1.97, 'north': 53.35},
                            as_of='2019-07-31', start_time='2019-07-30T00:00:00Z', end_time='2019-08-01T00:00:00Z')
    names = ['gpm', 'smap'] if role == 'hydro' else ['sentinel1', 'dem', 'hand']
    output = ContextResult(**requested.model_dump(), worker_id=role+'-worker', status='partial',
                           components=[{'component': name, 'availability': 'unavailable', 'reason': 'missing_local_data',
                                        'temporal_kind': 'static_context' if name in ('dem', 'hand') else 'observation'} for name in names])
    with TestClient(create_worker_app(role+'-worker', analysis, lambda task, progress: output.model_dump(mode='json'))) as client:
        assert client.post('/tasks', json=requested.model_dump(mode='json')).status_code == 202
        assert terminal(client)['state'] == 'partial'
        assert ContextResult.model_validate(client.get('/tasks/dam-test/result').json()) == output
    wrong = output.model_copy(update={'location_id': 'another-location'}).model_dump(mode='json')
    with TestClient(create_worker_app(role+'-worker', analysis, lambda task, progress: wrong)) as client:
        client.post('/tasks', json=requested.model_dump(mode='json'))
        assert terminal(client)['state'] == 'failed'
        assert client.get('/tasks/dam-test/result').status_code == 409


def test_old_geospatial_task_does_not_accept_dam_analysis():
    with pytest.raises(ValidationError):
        AnalysisTask.model_validate({'analysis_type': 'dam_risk', 'bbox': {'west': -2, 'south': 53, 'east': -1.9, 'north': 53.1},
                                     'start_time': '2019-07-30T00:00:00Z', 'end_time': '2019-07-31T00:00:00Z'})


def test_result_rejects_unbacked_support_counts_and_coerced_booleans(tmp_path, records):
    raw = analyze(task(), data_dir=write_records(tmp_path, records)).model_dump(mode='json')
    wrong_counts = deepcopy(raw)
    wrong_counts['rules'][0]['record_count'] += 1
    wrong_age = deepcopy(raw)
    wrong_age['metrics']['latest_visit_age_days'] = 1
    wrong_boolean = deepcopy(raw)
    wrong_boolean['metrics']['monitoring_gap'] = 'false'
    for value in (wrong_counts, wrong_age, wrong_boolean):
        with pytest.raises(ValidationError):
            DamResult.model_validate(value)
