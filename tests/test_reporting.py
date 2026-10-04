"""Offline evidence review preserves inputs and never submits worker tasks."""

import asyncio
from copy import deepcopy
import hashlib
import json
import os

import httpx
import pytest

from backend.control import main as control_cli
from backend.control.alerts import load_policy
from backend.control.coordinator import run_analysis
from backend.control.main import make_tasks
from backend.control.reporting import (
    build_review_report, protect_inputs, read_evidence, write_review_report,
)
from backend.shared.contracts import CombinedAnalysis
from backend.shared.settings import ControlSettings, ROOT, WorkerEndpoint
from scripts.validate import validate_fusion as checkpoint
from test_contracts import hydro_result


@pytest.fixture
def evidence(hydro_result):
    config = json.loads((ROOT / 'config/test_case.example.json').read_text())
    config['bbox'] = list(hydro_result['bbox'].values())
    tasks = make_tasks(config, hydro_result['sources'][0]['resources_used'],
                       hydro_result['sources'][1]['resources_used'][0], hydro_result['task_id'])
    return {
        'requests': [task.model_dump(mode='json') for task in tasks],
        'combined': CombinedAnalysis(task_id=hydro_result['task_id'], hydro=hydro_result,
                                     errors=['Flood result was not returned.']).model_dump(mode='json'),
        'requested_window': {'start': config['event_start'], 'end': config['event_end']},
    }


@pytest.fixture
def policy():
    return load_policy(ROOT / 'config/rules.example.json')


def test_offline_review_preserves_valid_independent_result_and_does_not_echo_unknown_metadata(evidence, policy):
    original = deepcopy(evidence)
    evidence['worker_token'] = 'PRIVATE-DO-NOT-COPY'
    report = build_review_report(evidence, policy)
    assert report['validation'] == 'PASS'
    assert report['phase_gate'] == 'PENDING_USER'
    assert report['execution_repeated'] is False
    assert report['fusion']['source_results'] == original['combined']
    assert report['review']['not_assessable_count'] >= 2
    assert 'PRIVATE-DO-NOT-COPY' not in json.dumps(report, allow_nan=False)
    assert evidence['combined'] == original['combined']


@pytest.mark.parametrize('edit', ['missing_requests', 'missing_collection', 'bad_task', 'conflicting_window'])
def test_review_rejects_unbound_or_conflicting_evidence(evidence, policy, edit):
    if edit == 'missing_requests':
        del evidence['requests']
    elif edit == 'missing_collection':
        del evidence['combined']
    elif edit == 'bad_task':
        evidence['requests'][0]['task_id'] = 'different-task'
    window = {'start': '2021-11-15T00:00:00Z', 'end': '2021-11-15T01:00:00Z'} if edit == 'conflicting_window' else None
    with pytest.raises(ValueError):
        build_review_report(evidence, policy, requested_window=window)


@pytest.mark.parametrize('raw', ['{"value":NaN}', '{"value":Infinity}', '{"value":1e999}',
                                '{"a":{"value":1,"value":2}}', '[]'])
def test_reader_rejects_ambiguous_or_nonfinite_json(tmp_path, raw):
    source = tmp_path / 'input.json'
    source.write_text(raw)
    with pytest.raises(ValueError):
        read_evidence(source)


def test_reader_binds_exact_input_bytes_and_enforces_size_limit(tmp_path, monkeypatch):
    from backend.control import reporting
    source = tmp_path / 'input.json'
    raw = b'{"value": 1}\n'
    source.write_bytes(raw)
    value, digest = read_evidence(source)
    assert value == {'value': 1} and digest == hashlib.sha256(raw).hexdigest()
    monkeypatch.setattr(reporting, 'MAX_REPORT_BYTES', 8)
    with pytest.raises(ValueError, match='size limit'):
        read_evidence(source)


def test_input_protection_covers_hardlinks_and_normalized_aliases(tmp_path):
    source = tmp_path / 'input.json'
    source.write_text('{}')
    alias = tmp_path / 'alias.json'
    os.link(source, alias)
    for output in (source, tmp_path / '.' / 'input.json', alias):
        with pytest.raises(ValueError):
            protect_inputs(output, source)
    assert source.read_text() == '{}'


def test_atomic_report_write_is_strict_and_cleans_own_temporary_file(tmp_path, monkeypatch):
    from backend.control import reporting
    target = tmp_path / 'result.json'
    write_review_report(target, {'validation': 'PASS'})
    with pytest.raises(ValueError):
        write_review_report(target, {'value': float('inf')})
    assert json.loads(target.read_text()) == {'validation': 'PASS'}
    monkeypatch.setattr(reporting.os, 'replace', lambda *_: (_ for _ in ()).throw(OSError('locked')))
    with pytest.raises(OSError):
        write_review_report(target, {'validation': 'FAIL'})
    assert sorted(path.name for path in tmp_path.iterdir()) == ['result.json']


def test_offline_command_needs_no_worker_settings_and_keeps_input_bytes(evidence, tmp_path, monkeypatch):
    monkeypatch.setattr(ControlSettings, 'from_env', lambda: pytest.fail('Offline review must not configure workers.'))
    source, output = tmp_path / 'source.json', tmp_path / 'result.json'
    source.write_text(json.dumps(evidence))
    before = source.read_bytes()
    assert checkpoint.main(['--input', str(source), '--rules', str(ROOT / 'config/rules.example.json'),
                            '--output', str(output)]) == 0
    saved = json.loads(output.read_text())
    assert saved['source_sha256'] == hashlib.sha256(before).hexdigest()
    assert saved['execution_repeated'] is False and source.read_bytes() == before


def test_failed_attempt_replaces_stale_success_without_echoing_input(tmp_path, capsys):
    source, output = tmp_path / 'source.json', tmp_path / 'result.json'
    source.write_text('{"secret":"PRIVATE-DO-NOT-ECHO", "combined":null}')
    output.write_text('{"validation":"PASS"}')
    assert checkpoint.main(['--input', str(source), '--rules', str(ROOT / 'config/rules.example.json'),
                            '--output', str(output)]) == 1
    saved = output.read_text()
    assert json.loads(saved)['validation'] == 'FAIL'
    assert 'PRIVATE-DO-NOT-ECHO' not in saved + capsys.readouterr().out


def test_offline_command_refuses_to_overwrite_input(evidence, tmp_path):
    source = tmp_path / 'source.json'
    source.write_text(json.dumps(evidence))
    before = source.read_bytes()
    assert checkpoint.main(['--input', str(source), '--rules', str(ROOT / 'config/rules.example.json'),
                            '--output', str(source)]) == 2
    assert source.read_bytes() == before


def test_invalid_policy_rejected_before_any_live_dispatch(tmp_path, monkeypatch):
    policy = tmp_path / 'rules.json'
    policy.write_text('{"threshold": "PRIVATE-INVALID-POLICY"}')
    monkeypatch.setattr(ControlSettings, 'from_env', lambda: pytest.fail('Invalid policy must be rejected before networking.'))
    assert control_cli.main(['--gpm-resources', 'gpm.HDF5', '--smap-resource', 'smap.h5',
                             '--rules', str(policy), '--output', str(tmp_path / 'out.json')]) == 2


def test_live_configuration_failure_marks_latest_attempt_without_destroying_prior_results(tmp_path, monkeypatch):
    policy, output = tmp_path / 'rules.json', tmp_path / 'result.json'
    policy.write_text('{"purpose":"unsupported"}')
    prior = {'phase7': {'validation': 'PASS'}, 'dispatch': {'retained_evidence': 'older-run'}}
    output.write_text(json.dumps(prior))
    monkeypatch.setattr(ControlSettings, 'from_env', lambda: pytest.fail('Must not access worker settings.'))
    assert control_cli.main(['--gpm-resources', 'gpm.HDF5', '--smap-resource', 'smap.h5',
                             '--rules', str(policy), '--output', str(output)]) == 2
    latest = json.loads(output.with_name(output.name + '.phase7-attempt.json').read_text())
    assert latest['validation'] == 'FAIL' and latest['dispatch_attempted'] is False
    assert latest['failed_stage'] == 'configuration'
    assert json.loads(output.read_text()) == prior


def test_live_attempt_sidecar_cannot_alias_policy_input(tmp_path):
    output = tmp_path / 'result.json'
    policy = output.with_name(output.name + '.phase7-attempt.json')
    policy.write_text('{"must":"survive"}')
    before = policy.read_bytes()
    assert control_cli.main(['--gpm-resources', 'gpm.HDF5', '--smap-resource', 'smap.h5',
                             '--rules', str(policy), '--output', str(output)]) == 2
    assert policy.read_bytes() == before and not output.exists()


def test_live_cli_adds_review_without_discarding_failed_dispatch(tmp_path, monkeypatch):
    settings = ControlSettings(WorkerEndpoint('http://hydro.invalid', 'hydro-worker'),
                               WorkerEndpoint('http://flood.invalid', 'flood-worker'))

    async def unreachable(request):
        raise httpx.ConnectError('unreachable', request=request)

    async def dispatch(hydro, flood, configured, *, execution_mode):
        return await run_analysis(hydro, flood, configured, execution_mode=execution_mode,
                                  transport_factory=lambda endpoint: httpx.MockTransport(unreachable))

    monkeypatch.setattr(control_cli, 'run_analysis', dispatch)
    monkeypatch.setattr(ControlSettings, 'from_env', lambda: settings)
    output = tmp_path / 'result.json'
    assert control_cli.main(['--gpm-resources', 'gpm.HDF5', '--smap-resource', 'smap.h5',
                             '--rules', str(ROOT / 'config/rules.example.json'), '--output', str(output)]) == 1
    report = json.loads(output.read_text())
    assert report['dispatch']['hydro']['outcome'] == report['dispatch']['flood']['outcome'] == 'transport_error'
    assert report['phase7']['review']['triggered_count'] == report['phase7']['review']['not_triggered_count'] == 0
    assert report['phase7']['review']['not_assessable_count'] == 5
    assert report['phase7']['fusion']['source_results'] == report['dispatch']['combined']
    latest = json.loads(output.with_name(output.name + '.phase7-attempt.json').read_text())
    assert latest['attempt_id'] == report['phase7_attempt_id']
    assert latest['validation'] == 'PASS' and latest['dispatch_attempted'] is True
