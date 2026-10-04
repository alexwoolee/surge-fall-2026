"""Portable private startup configuration never executes shell assignments."""

import os

import pytest

from backend.control import serve
from backend.control.serve import read_private_assignments, viewer_tokens, worker_settings
from test_agent_main import cli_files, prepared, fusion_inputs, hydro_result


def test_literal_private_configuration_preserves_environment(tmp_path, monkeypatch):
    path = tmp_path / '.env.local'
    path.write_text('export TOKEN="$(do-not-execute)"\nMODEL=small\n')
    monkeypatch.setenv('TOKEN', 'existing')
    assert read_private_assignments(path, {'TOKEN', 'MODEL'}) == {'TOKEN': '$(do-not-execute)', 'MODEL': 'small'}
    assert os.environ['TOKEN'] == 'existing'


@pytest.mark.parametrize('contents', ['TOKEN=one\nTOKEN=two', 'OTHER=private', 'TOKEN="bad', 'bad', 'x' * 16385])
def test_invalid_private_configuration_does_not_echo_contents(tmp_path, contents):
    path = tmp_path / 'private.env'
    path.write_text(contents)
    with pytest.raises(ValueError) as error:
        read_private_assignments(path, {'TOKEN'})
    assert 'private' not in str(error.value).lower() or str(error.value).startswith('Private configuration must')
    assert 'OTHER' not in str(error.value) and 'TOKEN=' not in str(error.value)


def test_worker_file_is_explicit_and_bounded(tmp_path):
    path = tmp_path / 'private.env'
    path.write_text('HYDRO_WORKER_URL=http://hydro.invalid:8002\nHYDRO_WORKER_TOKEN=private-hydro\n'
                    'FLOOD_WORKER_URL=http://flood.invalid:8003\nFLOOD_WORKER_TOKEN=private-flood\n'
                    'MESHMIND_POLL_INTERVAL_SECONDS=1\n')
    settings = worker_settings(path)
    assert settings.poll_interval == 1
    assert settings.hydro.token is None
    assert 'private-hydro' not in repr(settings)
    path.write_text(path.read_text() + 'MESHMIND_TASK_TIMEOUT_SECONDS=inf\n')
    with pytest.raises(ValueError, match='bounded configuration'):
        worker_settings(path)


def test_legacy_viewer_environment_is_ignored(monkeypatch):
    monkeypatch.setenv('MESHMIND_VIEWER_HYDRO_TOKEN', 'h' * 40)
    monkeypatch.setenv('MESHMIND_VIEWER_FLOOD_TOKEN', 'f' * 40)
    assert viewer_tokens() is None


def test_legacy_viewer_file_is_ignored_without_environment_changes(tmp_path, monkeypatch):
    path = tmp_path / 'viewers.env'
    path.write_text('MESHMIND_VIEWER_HYDRO_TOKEN=' + 'h' * 40 + '\n'
                    'MESHMIND_VIEWER_FLOOD_TOKEN=' + 'f' * 40 + '\n')
    monkeypatch.delenv('MESHMIND_VIEWER_HYDRO_TOKEN', raising=False)
    assert viewer_tokens(path) is None
    assert 'MESHMIND_VIEWER_HYDRO_TOKEN' not in os.environ


@pytest.mark.parametrize('contents', [
    '', 'MESHMIND_VIEWER_HYDRO_TOKEN=' + 'h' * 40,
    'MESHMIND_CONTROL_API_TOKEN=' + 'p' * 40,
])
def test_malformed_legacy_viewer_files_are_ignored(tmp_path, contents):
    path = tmp_path / 'viewers.env'
    path.write_text(contents)
    assert viewer_tokens(path) is None
    assert viewer_tokens(tmp_path / "missing.env") is None


@pytest.mark.parametrize("legacy_files", ["omitted", "missing", "malformed"])
def test_control_startup_ignores_legacy_internal_credential_files(cli_files, tmp_path, monkeypatch, legacy_files):
    monkeypatch.delenv("MESHMIND_CONTROL_API_TOKEN", raising=False)
    monkeypatch.setattr(serve.uvicorn, "run", lambda *args, **kwargs: pytest.fail("Check-config started a server."))
    monkeypatch.setattr(serve.ResponsesClient, "create", lambda *args, **kwargs: pytest.fail("Check-config called OpenAI."))
    args = ["--input", str(cli_files["input"]), "--config", str(cli_files["config"]),
            "--rules", str(cli_files["rules"]), "--openai-env-file", str(cli_files["env"]),
            "--history-dir", str(tmp_path / "history"), "--check-config"]
    if legacy_files != "omitted":
        path = tmp_path / "obsolete.env"
        if legacy_files == "malformed":
            path.write_bytes(b"\xffPRIVATE_NOT_CONFIG\x00")
        args.extend(["--control-env-file", str(path), "--viewer-env-file", str(path)])
    assert serve.main(args) == 0
    # The external model provider still requires its own valid credentials.
    cli_files["env"].write_text("OPENAI_API_KEY=\nOPENAI_MODEL=test-model\n")
    assert serve.main(args) == 2


@pytest.mark.parametrize("obsolete", [
    b"HYDRO_WORKER_TOKEN=\"unterminated\nFLOOD_WORKER_TOKEN='bad\n",
    b"HYDRO_WORKER_TOKEN=one\nHYDRO_WORKER_TOKEN=two\nFLOOD_WORKER_TOKEN\n",
    b"export HYDRO_WORKER_TOKEN=\xff\x00\nFLOOD_WORKER_TOKEN=arbitrary value\n",
])
def test_worker_file_discards_invalid_legacy_token_assignments_before_parsing(tmp_path, obsolete):
    path = tmp_path / "worker.env"
    base = b"HYDRO_WORKER_URL=http://hydro.invalid:8002\nFLOOD_WORKER_URL=http://flood.invalid:8003\n"
    path.write_bytes(base + obsolete)
    settings = worker_settings(path)
    assert settings.hydro.url == "http://hydro.invalid:8002"
    assert settings.hydro.token is None and settings.flood.token is None
    path.write_bytes(base + obsolete + b"MESHMIND_REQUEST_TIMEOUT_SECONDS=inf\n")
    with pytest.raises(ValueError):
        worker_settings(path)
