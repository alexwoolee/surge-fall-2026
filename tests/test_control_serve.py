"""Portable private startup configuration never executes shell assignments."""

import os

import pytest

from backend.control.serve import read_private_assignments, worker_settings


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
    assert settings.hydro.token == 'private-hydro'
    assert 'private-hydro' not in repr(settings)
    path.write_text(path.read_text() + 'MESHMIND_TASK_TIMEOUT_SECONDS=inf\n')
    with pytest.raises(ValueError, match='bounded configuration'):
        worker_settings(path)
