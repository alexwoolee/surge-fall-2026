"""The opt-in CLI preserves evidence and isolates private API configuration."""

from hashlib import sha256
import json
import os

import pytest

from backend.control import agent, agent_main
from backend.control.openai_client import AgentAPIError
from backend.control.reporting import build_review_report
from test_agent import (
    REQUEST, SECRET, ScriptedClient, control_settings, dispatch_result, explanation,
    forbid_dispatch, fusion_inputs, hydro_result, plan, prepared,
)


@pytest.fixture
def cli_files(prepared, tmp_path):
    case, evidence, policy = prepared
    config = {
        'id': case.case_id, 'name': case.name, 'bbox': list(case.hydro.bbox.as_tuple()),
        'event_start': case.requested_window.start.isoformat(),
        'event_end': case.requested_window.end.isoformat(),
        'sentinel1_smoke_start': case.flood.start_time.isoformat(),
        'sentinel1_smoke_end': case.flood.end_time.isoformat(),
    }
    files = {name: tmp_path / f'{name}.json' for name in ('input', 'config', 'rules', 'output')}
    for name, value in (('input', evidence), ('config', config), ('rules', policy.model_dump(mode='json'))):
        files[name].write_text(json.dumps(value), encoding='utf-8')
    files['env'] = tmp_path / '.env.phase8.local'
    files['env'].write_text(f'OPENAI_API_KEY={SECRET}\nOPENAI_MODEL=test-model\n', encoding='utf-8')
    return files


def cli_argv(files):
    return ['--input', str(files['input']), '--config', str(files['config']),
            '--rules', str(files['rules']), '--env-file', str(files['env']),
            '--output', str(files['output']), '--request', REQUEST]


def attempt_path(files):
    output = files['output']
    return output.with_name(output.name + '.phase8-attempt.json')


def read_json(path):
    return json.loads(path.read_text(encoding='utf-8'))


def install_client(monkeypatch, client, module=agent_main):
    forbid_dispatch(monkeypatch)
    monkeypatch.setattr(module, 'ResponsesClient', lambda _settings: client)
    return client


def test_complete_replay_saves_checked_measurements_sidecar_and_input_digest(cli_files, prepared, monkeypatch, capsys):
    originals = {name: cli_files[name].read_bytes() for name in ('input', 'config', 'rules', 'env')}
    client = install_client(monkeypatch, ScriptedClient(plan(), explanation()))
    assert agent_main.main(cli_argv(cli_files)) == 0
    report, attempt = read_json(cli_files['output']), read_json(attempt_path(cli_files))
    case, evidence, policy = prepared
    assert report['deterministic'] == build_review_report(evidence, policy, requested_window=case.requested_window.model_dump(mode='json'))
    assert report['status'] == 'complete' and report['validation'] == 'PASS'
    assert report['phase_gate'] == 'PENDING_USER'
    assert report['source_sha256'] == sha256(originals['input']).hexdigest()
    assert report['attempt_id'] == attempt['attempt_id'] and attempt['validation'] == 'PASS'
    assert report['model'] == 'test-model' and report['api'] == 'OpenAI Responses'
    assert not report['dispatch_attempted'] and len(client.calls) == 2
    assert SECRET not in json.dumps(report) + json.dumps(attempt) + json.dumps(client.calls) + capsys.readouterr().out
    assert REQUEST not in json.dumps(report)
    assert originals == {name: cli_files[name].read_bytes() for name in originals}


@pytest.mark.parametrize('failure_stage', [None, 'interpretation', 'explanation'])
def test_include_request_cli_flag_persists_context_in_complete_and_fallback_reports(cli_files, monkeypatch, failure_stage):
    replies = ([AgentAPIError('timeout')] if failure_stage == 'interpretation' else
               [plan(), AgentAPIError('timeout')] if failure_stage == 'explanation' else
               [plan(), explanation()])
    client = install_client(monkeypatch, ScriptedClient(*replies))
    assert agent_main.main(cli_argv(cli_files) + ['--include-request']) == (0 if failure_stage is None else 1)
    report = read_json(cli_files['output'])
    assert REQUEST in json.dumps(report['explanation'])
    assert 'untrusted' in report['explanation']['narrative'].lower()
    assert not report['dispatch_attempted']
    assert len(client.calls) == (1 if failure_stage == 'interpretation' else 2)
    assert SECRET not in json.dumps(report)
    assert REQUEST not in json.dumps(read_json(attempt_path(cli_files)))


def test_include_request_cli_help_explains_local_privacy_opt_in(capsys):
    with pytest.raises(SystemExit) as stopped:
        agent_main.main(['--help'])
    assert stopped.value.code == 0
    help_text = ' '.join(capsys.readouterr().out.split())
    assert '--include-request' in help_text
    assert 'untrusted user context' in help_text
    assert 'Omitted by default for privacy' in help_text


def test_explicit_execute_dispatches_configured_tasks_once_without_real_network(cli_files, prepared, monkeypatch, capsys):
    case, evidence, _policy = prepared
    run = dispatch_result(case, evidence)
    client = install_client(monkeypatch, ScriptedClient(plan(), explanation()))
    settings, calls = control_settings(), []
    monkeypatch.setattr(agent_main.ControlSettings, 'from_env', lambda: settings)

    async def dispatch(hydro, flood, configuration, **kwargs):
        calls.append((hydro, flood, configuration, kwargs))
        recorded = read_json(cli_files['output'])
        assert recorded['dispatch_attempted'] and recorded['requests'] == evidence['requests']
        return run

    monkeypatch.setattr(agent, 'run_analysis', dispatch)
    args = cli_argv(cli_files)[2:] + ['--execute', '--gpm-resources', *case.hydro.gpm_resources,
                                    '--smap-resource', case.hydro.smap_resource,
                                    '--task-id', case.hydro.task_id]
    assert agent_main.main(args) == 0
    report = read_json(cli_files['output'])
    assert calls == [(case.hydro, case.flood, settings, {'execution_mode': 'parallel'})]
    assert report['mode'] == 'execute' and report['dispatch_attempted'] and report['execution_repeated']
    assert report['worker_evidence']['dispatch'] == run.model_dump(mode='json')
    assert report['source_sha256'] is None and len(client.calls) == 2
    assert read_json(attempt_path(cli_files))['dispatch_attempted']
    assert SECRET not in json.dumps(report) + json.dumps(client.calls) + capsys.readouterr().out


@pytest.mark.parametrize('missing', ['file', 'key', 'model', 'exported'])
def test_missing_api_configuration_keeps_deterministic_fallback_without_network(cli_files, monkeypatch, capsys, missing):
    forbid_dispatch(monkeypatch)
    monkeypatch.setattr(agent_main, 'ResponsesClient', lambda _settings: pytest.fail('Missing API settings must not create a network client.'))
    args = cli_argv(cli_files)
    if missing == 'file':
        cli_files['env'].unlink()
    elif missing == 'key':
        cli_files['env'].write_text('OPENAI_MODEL=test-model\n', encoding='utf-8')
    elif missing == 'model':
        cli_files['env'].write_text(f'OPENAI_API_KEY={SECRET}\n', encoding='utf-8')
    else:
        index = args.index('--env-file')
        del args[index:index + 2]
        monkeypatch.delenv('OPENAI_API_KEY', raising=False)
        monkeypatch.delenv('OPENAI_MODEL', raising=False)
    assert agent_main.main(args) == 1
    report = read_json(cli_files['output'])
    assert report['status'] == 'degraded' and report['validation'] == 'FAIL'
    assert report['error']['code'] == 'configuration_error'
    assert report['deterministic']['validation'] == 'PASS'
    assert report['explanation']['status'] == 'fallback'
    assert report['explanation']['measurements'] == report['deterministic']['fusion']['metrics']
    assert read_json(attempt_path(cli_files))['validation'] == 'FAIL'
    assert SECRET not in json.dumps(report) + capsys.readouterr().out


@pytest.mark.parametrize('input_name', ['input', 'config', 'rules', 'env'])
@pytest.mark.parametrize('alias_kind', ['same', 'hardlink'])
def test_output_cannot_alias_any_input_including_private_configuration(cli_files, monkeypatch, input_name, alias_kind):
    client = install_client(monkeypatch, ScriptedClient())
    original = cli_files[input_name].read_bytes()
    if alias_kind == 'same':
        cli_files['output'] = cli_files[input_name]
    else:
        os.link(cli_files[input_name], cli_files['output'])
    assert agent_main.main(cli_argv(cli_files)) == 2
    assert cli_files[input_name].read_bytes() == original
    assert client.calls == []
    assert not attempt_path(cli_files).exists()


@pytest.mark.parametrize('collision', ['input', 'env', 'output'])
def test_attempt_sidecar_cannot_alias_input_credentials_or_previous_output(cli_files, monkeypatch, collision):
    client = install_client(monkeypatch, ScriptedClient())
    if collision == 'output':
        cli_files['output'].write_text('previous completed result', encoding='utf-8')
    target = cli_files[collision]
    original = target.read_bytes()
    os.link(target, attempt_path(cli_files))
    assert agent_main.main(cli_argv(cli_files)) == 2
    assert target.read_bytes() == original and attempt_path(cli_files).read_bytes() == original
    assert client.calls == []


def test_output_symlink_to_input_is_rejected_when_platform_permits_symlinks(cli_files, monkeypatch):
    try:
        cli_files['output'].symlink_to(cli_files['input'])
    except OSError as error:
        if getattr(error, 'winerror', None) == 1314:
            pytest.skip('Windows symlink privilege is unavailable.')
        raise
    original = cli_files['input'].read_bytes()
    client = install_client(monkeypatch, ScriptedClient())
    assert agent_main.main(cli_argv(cli_files)) == 2
    assert cli_files['input'].read_bytes() == original and client.calls == []


@pytest.mark.parametrize('bad_setup', ['config', 'rules', 'input', 'evidence_binding', 'oversized_request'])
def test_invalid_setup_preserves_previous_output_and_records_latest_failed_attempt(cli_files, monkeypatch, capsys, bad_setup):
    client = install_client(monkeypatch, ScriptedClient())
    old = b'{"validation":"PASS","previous_evidence":"keep me"}\n'
    cli_files['output'].write_bytes(old)
    args = cli_argv(cli_files)
    if bad_setup in {'config', 'rules', 'input'}:
        cli_files[bad_setup].write_text(f'not-json {SECRET}', encoding='utf-8')
    elif bad_setup == 'evidence_binding':
        evidence = read_json(cli_files['input'])
        evidence['requests'][1]['reference_time'] = '2021-11-15T00:00:00Z'
        cli_files['input'].write_text(json.dumps(evidence), encoding='utf-8')
    else:
        args[-1] = SECRET * 4096
    assert agent_main.main(args) == 2
    assert cli_files['output'].read_bytes() == old and client.calls == []
    attempt = read_json(attempt_path(cli_files))
    assert attempt['validation'] == 'FAIL' and not attempt['dispatch_attempted']
    assert SECRET not in json.dumps(attempt) + capsys.readouterr().out


@pytest.mark.parametrize('failure', [AgentAPIError('timeout'), ValueError(SECRET)])
def test_api_failure_retains_measurements_without_persisting_raw_errors(cli_files, monkeypatch, capsys, failure):
    client = install_client(monkeypatch, ScriptedClient(plan(), failure))
    assert agent_main.main(cli_argv(cli_files)) == 1
    report = read_json(cli_files['output'])
    assert report['deterministic']['validation'] == 'PASS'
    assert report['explanation']['status'] == 'fallback'
    assert report['error']['stage'] == 'explanation'
    assert read_json(attempt_path(cli_files))['validation'] == 'FAIL'
    assert len(client.calls) == 2
    assert SECRET not in json.dumps(report) + capsys.readouterr().out


def test_failed_output_write_preserves_previous_output_and_updates_writable_sidecar(cli_files, monkeypatch, capsys):
    old = b'{"previous":"evidence"}\n'
    cli_files['output'].write_bytes(old)
    client = install_client(monkeypatch, ScriptedClient())
    real_write = agent_main.write_review_report

    def failing_write(path, value):
        if path == cli_files['output']:
            raise OSError(SECRET)
        real_write(path, value)

    monkeypatch.setattr(agent_main, 'write_review_report', failing_write)
    assert agent_main.main(cli_argv(cli_files)) == 2
    assert cli_files['output'].read_bytes() == old and client.calls == []
    assert read_json(attempt_path(cli_files))['validation'] == 'FAIL'
    assert SECRET not in capsys.readouterr().out


def test_late_persistence_failure_keeps_new_deterministic_evidence_and_blocks_more_api_calls(cli_files, monkeypatch, capsys):
    client = install_client(monkeypatch, ScriptedClient(plan(), explanation()))
    real_write = agent_main.write_review_report
    writes = 0

    def fail_after_plan(path, value):
        nonlocal writes
        if path == cli_files['output']:
            writes += 1
            if writes == 2:
                raise OSError(SECRET)
        real_write(path, value)

    monkeypatch.setattr(agent_main, 'write_review_report', fail_after_plan)
    assert agent_main.main(cli_argv(cli_files)) == 2
    report = read_json(cli_files['output'])
    assert report['validation'] == 'FAIL' and report['deterministic']['validation'] == 'PASS'
    assert report['explanation']['status'] == 'fallback' and len(client.calls) == 1
    assert read_json(attempt_path(cli_files))['validation'] == 'FAIL'
    assert SECRET not in json.dumps(report) + capsys.readouterr().out


@pytest.mark.parametrize('contents', [
    'OPENAI_API_KEY=one\nOPENAI_API_KEY=two\nOPENAI_MODEL=model\n',
    'OPENAI_API_KEY=one\nOPENAI_MODEL=model\nMESHMIND_WORKER_TOKEN=private\n',
    'export OPENAI_API_KEY=one\nOPENAI_MODEL=model\n',
    'OPENAI_API_KEY="unterminated\nOPENAI_MODEL=model\n',
    'OPENAI_API_KEY=one\nOPENAI_MODEL=\n',
    'x' * 8193,
])
def test_private_config_parser_rejects_ambiguous_or_unbounded_input_without_echo(cli_files, contents):
    cli_files['env'].write_text(contents, encoding='utf-8')
    with pytest.raises(AgentAPIError) as error:
        agent_main.load_openai_settings(cli_files['env'])
    assert error.value.code == 'configuration_error'
    assert str(error.value) == 'OpenAI configuration is missing or invalid.'


def test_private_config_file_is_literal_does_not_execute_shell_or_modify_environment(cli_files, monkeypatch):
    monkeypatch.setenv('OPENAI_API_KEY', 'exported-key')
    monkeypatch.setenv('OPENAI_MODEL', 'exported-model')
    cli_files['env'].write_text('# private settings\nOPENAI_API_KEY="$(literal)"\nOPENAI_MODEL=local-model\n', encoding='utf-8')
    settings = agent_main.load_openai_settings(cli_files['env'])
    assert settings.api_key == '$(literal)' and settings.model == 'local-model'
    assert os.environ['OPENAI_API_KEY'] == 'exported-key'
    assert os.environ['OPENAI_MODEL'] == 'exported-model'


@pytest.mark.parametrize('extra', [ ['--execute'], ['--gpm-resources', 'gpm.HDF5'], ['--task-id', 'new-task'] ])
def test_cli_rejects_ambiguous_modes_or_replay_resource_overrides(cli_files, extra):
    with pytest.raises(SystemExit) as error:
        agent_main.main(cli_argv(cli_files) + extra)
    assert error.value.code == 2
    assert not cli_files['output'].exists() and not attempt_path(cli_files).exists()
