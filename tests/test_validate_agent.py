"""The live validator is tested offline with strictly bounded fake responses."""

import asyncio
from copy import deepcopy
import json
import os

import pytest

from backend.control.openai_client import AgentAPIError
from scripts.validate import validate_agent
from test_agent import SECRET, ScriptedClient, explanation, fusion_inputs, hydro_result, plan, prepared
from test_agent_main import attempt_path, cli_files, install_client, read_json


def validator_argv(files):
    return ['--input', str(files['input']), '--config', str(files['config']),
            '--rules', str(files['rules']), '--env-file', str(files['env']), '--output', str(files['output'])]


def decline():
    return plan(name='decline_request', arguments={'reason': 'unsupported_analysis'})


def test_positive_and_declined_requests_preserve_evidence_and_use_three_calls(prepared, monkeypatch):
    case, evidence, policy = prepared
    snapshots, events = [], []

    def save(value):
        snapshots.append(deepcopy(value))
        events.append(('save', len(snapshots)))

    client = install_client(monkeypatch, ScriptedClient(plan(), explanation(), decline(), events=events))
    results, passed = asyncio.run(validate_agent.validate(evidence, case, policy, client, save))
    assert passed and all(results['checks'].values())
    assert len(client.calls) == 3 and events[0][0] == 'save'
    assert results['supported']['status'] == 'complete'
    assert results['unsupported']['status'] == 'rejected'
    assert results['supported']['deterministic'] == results['unsupported']['deterministic']
    assert all(snapshot['supported']['deterministic']['validation'] == 'PASS' for snapshot in snapshots)
    assert snapshots[-1] == results


def test_misclassified_unsupported_request_cannot_exceed_three_api_calls(prepared, monkeypatch):
    case, evidence, policy = prepared
    client = install_client(monkeypatch, ScriptedClient(plan(), explanation(), plan(), explanation()))
    results, passed = asyncio.run(validate_agent.validate(evidence, case, policy, client, lambda _value: None))
    assert not passed and len(client.calls) == 3
    assert results['unsupported']['status'] == 'degraded'
    assert results['unsupported']['error']['stage'] == 'explanation'
    assert results['unsupported']['explanation']['status'] == 'fallback'
    assert results['supported']['deterministic'] == results['unsupported']['deterministic']


@pytest.mark.parametrize('stage', ['positive_plan', 'positive_explanation', 'negative_plan'])
def test_partial_api_failure_retains_meaningful_completed_and_fallback_results(prepared, monkeypatch, stage):
    case, evidence, policy = prepared
    prefix = [] if stage == 'positive_plan' else [plan()] if stage == 'positive_explanation' else [plan(), explanation()]
    client = install_client(monkeypatch, ScriptedClient(*prefix, AgentAPIError('timeout')))
    snapshots = []
    results, passed = asyncio.run(validate_agent.validate(evidence, case, policy, client, lambda value: snapshots.append(deepcopy(value))))
    assert not passed and len(client.calls) == len(prefix) + 1
    assert results['supported']['deterministic']['validation'] == 'PASS'
    if stage == 'negative_plan':
        assert results['supported']['status'] == 'complete'
        assert results['unsupported']['explanation']['status'] == 'fallback'
        assert results['unsupported']['deterministic'] == results['supported']['deterministic']
    else:
        assert 'unsupported' not in results
        assert results['supported']['explanation']['status'] == 'fallback'
    assert snapshots[0]['supported']['deterministic']['validation'] == 'PASS'


def test_validator_main_records_pass_without_modifying_inputs_or_dispatching(cli_files, monkeypatch, capsys):
    originals = {key: cli_files[key].read_bytes() for key in ('input', 'config', 'rules', 'env')}
    client = install_client(monkeypatch, ScriptedClient(plan(), explanation(), decline()), validate_agent)
    assert validate_agent.main(validator_argv(cli_files)) == 0
    report, attempt = read_json(cli_files['output']), read_json(attempt_path(cli_files))
    assert report['validation'] == 'PASS' and report['phase_gate'] == 'PENDING_USER'
    assert report['input_unchanged'] and not report['new_worker_execution']
    assert report['attempt_id'] == attempt['attempt_id'] and attempt['validation'] == 'PASS'
    assert len(client.calls) == 3 and all(report['results']['checks'].values())
    assert originals == {key: cli_files[key].read_bytes() for key in originals}
    assert SECRET not in json.dumps(report) + json.dumps(attempt) + capsys.readouterr().out


@pytest.mark.parametrize('input_name', ['input', 'config', 'rules', 'env'])
@pytest.mark.parametrize('kind', ['same', 'hardlink'])
def test_validator_protects_evidence_config_policy_and_credentials_from_aliases(cli_files, monkeypatch, input_name, kind):
    client = install_client(monkeypatch, ScriptedClient(), validate_agent)
    original = cli_files[input_name].read_bytes()
    if kind == 'same':
        cli_files['output'] = cli_files[input_name]
    else:
        os.link(cli_files[input_name], cli_files['output'])
    assert validate_agent.main(validator_argv(cli_files)) == 2
    assert cli_files[input_name].read_bytes() == original and client.calls == []
    assert not attempt_path(cli_files).exists()


@pytest.mark.parametrize('collision', ['input', 'env', 'output'])
def test_validator_sidecar_cannot_overwrite_inputs_or_old_report(cli_files, monkeypatch, collision):
    client = install_client(monkeypatch, ScriptedClient(), validate_agent)
    if collision == 'output':
        cli_files['output'].write_text('original evidence', encoding='utf-8')
    target = cli_files[collision]
    original = target.read_bytes()
    os.link(target, attempt_path(cli_files))
    assert validate_agent.main(validator_argv(cli_files)) == 2
    assert target.read_bytes() == original and attempt_path(cli_files).read_bytes() == original
    assert client.calls == []


@pytest.mark.parametrize('bad_setup', ['input', 'config', 'rules', 'env', 'binding'])
def test_validator_bad_setup_keeps_previous_report_with_new_failed_sidecar(cli_files, monkeypatch, capsys, bad_setup):
    client = install_client(monkeypatch, ScriptedClient(), validate_agent)
    old = b'{"validation":"PASS","preserved":"earlier results"}\n'
    cli_files['output'].write_bytes(old)
    if bad_setup == 'binding':
        value = read_json(cli_files['input'])
        value['requests'][1]['reference_time'] = '2021-11-15T00:00:00Z'
        cli_files['input'].write_text(json.dumps(value), encoding='utf-8')
    else:
        cli_files[bad_setup].write_text(f'not valid: {SECRET}', encoding='utf-8')
    assert validate_agent.main(validator_argv(cli_files)) == 1
    assert cli_files['output'].read_bytes() == old and client.calls == []
    attempt = read_json(attempt_path(cli_files))
    assert attempt['validation'] == 'FAIL'
    assert SECRET not in json.dumps(attempt) + capsys.readouterr().out


def test_validator_output_write_failure_preserves_old_output_and_marks_sidecar_failed(cli_files, monkeypatch, capsys):
    client = install_client(monkeypatch, ScriptedClient(), validate_agent)
    old = b'{"previous":"valid measurements"}\n'
    cli_files['output'].write_bytes(old)
    real_write = validate_agent.write_review_report

    def write_with_failed_output(path, value):
        if path == cli_files['output']:
            raise OSError(SECRET)
        real_write(path, value)

    monkeypatch.setattr(validate_agent, 'write_review_report', write_with_failed_output)
    assert validate_agent.main(validator_argv(cli_files)) == 1
    assert cli_files['output'].read_bytes() == old and client.calls == []
    assert read_json(attempt_path(cli_files))['validation'] == 'FAIL'
    assert SECRET not in capsys.readouterr().out


def test_validator_partial_api_failure_retains_positive_report_and_marks_checkpoint_failed(cli_files, monkeypatch, capsys):
    client = install_client(monkeypatch, ScriptedClient(plan(), explanation(), AgentAPIError('authentication_error')), validate_agent)
    assert validate_agent.main(validator_argv(cli_files)) == 1
    report = read_json(cli_files['output'])
    assert report['validation'] == 'FAIL' and report['phase_gate'] == 'NOT_READY'
    assert report['results']['supported']['status'] == 'complete'
    assert report['results']['unsupported']['status'] == 'degraded'
    assert report['results']['unsupported']['deterministic'] == report['results']['supported']['deterministic']
    assert read_json(attempt_path(cli_files))['validation'] == 'FAIL'
    assert len(client.calls) == 3 and SECRET not in json.dumps(report) + capsys.readouterr().out


def test_validator_exception_after_positive_completion_preserves_it_without_raw_exception(cli_files, monkeypatch, capsys):
    client = install_client(monkeypatch, ScriptedClient(plan(), explanation(), RuntimeError(SECRET)), validate_agent)
    assert validate_agent.main(validator_argv(cli_files)) == 1
    report = read_json(cli_files['output'])
    assert report['validation'] == 'FAIL'
    assert report['results']['supported']['status'] == 'complete'
    assert report['results']['unsupported']['deterministic'] == report['results']['supported']['deterministic']
    assert report['results']['unsupported']['explanation']['status'] == 'fallback'
    assert len(client.calls) == 3 and SECRET not in json.dumps(report) + capsys.readouterr().out
