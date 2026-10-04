"""Generic Control configures AI without contacting providers during startup."""

import pytest

from backend.control import serve
from backend.control.context_dispatch import ContextClient


SECRET = 'sk-test-DO-NOT-ECHO-STARTUP-KEY'


@pytest.fixture
def startup(tmp_path, monkeypatch):
    from backend.control import reservoir_web

    monkeypatch.delenv('OPENAI_API_KEY', raising=False)
    monkeypatch.delenv('OPENAI_MODEL', raising=False)
    workers = tmp_path / 'workers.env'
    workers.write_text('HYDRO_WORKER_URL=http://hydro.invalid:8002\n'
                       'FLOOD_WORKER_URL=http://flood.invalid:8003\n'
                       'DAM_WORKER_URL=http://dam.invalid:8004\n')
    history = tmp_path / 'history'
    args = ['--generic', '--worker-env-file', str(workers), '--history-dir', str(history)]
    apps, servers = [], []
    original = reservoir_web.create_reservoir_app

    def capture_app(service):
        app = original(service)
        apps.append(app)
        return app

    async def no_request(*args, **kwargs):
        pytest.fail('Configuration/startup must not dispatch a worker or contact OpenAI.')

    monkeypatch.setattr(reservoir_web, 'create_reservoir_app', capture_app)
    monkeypatch.setattr(serve.uvicorn, 'run', lambda app, **kwargs: servers.append((app, kwargs)))
    monkeypatch.setattr(serve.ResponsesClient, 'create', no_request)
    monkeypatch.setattr(ContextClient, 'run_context', no_request)
    return args, apps, servers, history


@pytest.mark.parametrize('check_only', [True, False])
def test_explicit_ai_file_enables_one_client_without_startup_requests(startup, tmp_path, capsys, check_only):
    args, apps, servers, history = startup
    config = tmp_path / 'model.env'
    config.write_text(f'OPENAI_API_KEY={SECRET}\nOPENAI_MODEL=gpt-5.4-mini\n')
    assert serve.main([*args, '--openai-env-file', str(config), *(['--check-config'] if check_only else [])]) == 0
    assert len(apps) == 1
    service = apps[0].state.control_service
    assert isinstance(service.synthesis_client, serve.ResponsesClient)
    assert service.synthesis_client.settings.model == 'gpt-5.4-mini'
    assert service.synthesis_client.settings.api_key == SECRET
    assert service.sessions == {} and service.job is None and not service.started
    assert not history.exists()
    if check_only:
        assert servers == []
    else:
        assert servers == [(apps[0], {'host': '127.0.0.1', 'port': 8001, 'workers': 1,
                                      'reload': False, 'access_log': False})]
    captured = capsys.readouterr()
    assert SECRET not in captured.out + captured.err


@pytest.mark.parametrize('check_only', [True, False])
def test_missing_optional_model_credentials_start_the_labeled_fallback(startup, capsys, check_only):
    args, apps, servers, history = startup
    assert serve.main([*args, *(['--check-config'] if check_only else [])]) == 0
    assert len(apps) == 1 and apps[0].state.control_service.synthesis_client is None
    assert len(servers) == (0 if check_only else 1)
    assert not history.exists()
    captured = capsys.readouterr()
    if not check_only:
        assert 'AI evidence synthesis: unavailable' in captured.out


def test_generic_control_can_use_explicit_environment_settings_without_a_file(startup, monkeypatch):
    args, apps, servers, _ = startup
    monkeypatch.setenv('OPENAI_API_KEY', SECRET)
    monkeypatch.setenv('OPENAI_MODEL', 'test-environment-model')
    assert serve.main([*args, '--check-config']) == 0
    assert apps[0].state.control_service.synthesis_client.settings.model == 'test-environment-model'
    assert servers == []


@pytest.mark.parametrize('contents', [
    None, '', f'OPENAI_API_KEY={SECRET}\n',
    f'OPENAI_API_KEY={SECRET}\nOPENAI_MODEL=invalid model\n',
    f'OPENAI_API_KEY="{SECRET}\nOPENAI_MODEL=gpt-5.4-mini\n',
    f'OPENAI_API_KEY={SECRET}\nOPENAI_MODEL=gpt-5.4-mini\nUNEXPECTED=secret\n',
])
def test_an_explicit_invalid_ai_file_fails_safely_instead_of_silent_fallback(startup, tmp_path, monkeypatch, capsys, contents):
    args, apps, servers, history = startup
    config = tmp_path / 'private-model.env'
    if contents is not None:
        config.write_text(contents)
    # Explicit bad files must not accidentally use some inherited account.
    monkeypatch.setenv('OPENAI_API_KEY', 'another-private-key')
    monkeypatch.setenv('OPENAI_MODEL', 'another-model')
    assert serve.main([*args, '--openai-env-file', str(config), '--check-config']) == 2
    assert apps == servers == [] and not history.exists()
    output = capsys.readouterr()
    assert 'configuration failed' in output.out
    assert all(value not in output.out + output.err for value in (
        SECRET, 'another-private-key', 'UNEXPECTED', str(config), 'Traceback'))
