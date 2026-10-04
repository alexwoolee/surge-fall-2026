"""Explicit remote destinations, bounded timeouts and secret-safe settings."""

import pytest

from backend.shared.settings import ControlSettings, WorkerEndpoint, WorkerSettings


def endpoints():
    return {"hydro": WorkerEndpoint("http://hydro.local:8001", "hydro-worker"),
            "flood": WorkerEndpoint("http://flood.local:8002", "flood-worker")}


@pytest.mark.parametrize("url,expected", [
    ("http://HYDRO.local:8001/", "http://hydro.local:8001"),
    ("https://192.168.1.12", "https://192.168.1.12"),
    ("http://[::1]:8001/", "http://[::1]:8001"),
])
def test_origin_normalization_preserves_explicit_destination(url, expected):
    assert WorkerEndpoint(url, "hydro-worker").url == expected


@pytest.mark.parametrize("url", [
    "", None, 123, "hydro.local:8001", "ftp://hydro.local", "http:///missing", "http://",
    "http://private-user:private-password@hydro.local", "http://@hydro.local", "http://hydro.local/task",
    "http://hydro.local//", "http://hydro.local?token=private-secret", "http://hydro.local?",
    "http://hydro.local#private-secret", "http://hydro.local#", "http://hydro.local:bad-port",
    "http://hydro.local:0", "http://hydro.local:65536", "http://hydro.local:", "http://bad\x7fhost", " http://hydro.local", "http://hydro.local\n",
    "http://hydro.local\\@other.local", "http://hydro%2Elocal", "http://[::1",
])
def test_invalid_destination_is_rejected_without_echoing_url(url):
    with pytest.raises(ValueError) as caught:
        WorkerEndpoint(url, "hydro-worker")
    assert "private-" not in str(caught.value)


@pytest.mark.parametrize("token", ["", " space", "space ", "two words", "line\r\nbreak",
                                    "tab\there", "\x00", "\x7f", "caf\u00e9", "a" * 513, 123])
def test_invalid_bearer_header_is_rejected_for_client_and_worker(token):
    for make in (lambda: WorkerEndpoint("http://hydro.local", "hydro-worker", token),
                 lambda: WorkerSettings(worker_token=token)):
        with pytest.raises(ValueError):
            make()


def test_tokens_are_not_exposed_in_nested_settings_repr():
    secret = "private-worker-secret"
    endpoint = WorkerEndpoint("http://hydro.local", "hydro-worker", secret)
    settings = ControlSettings(**{**endpoints(), "hydro": endpoint})
    assert settings.hydro.token == secret
    assert secret not in repr(endpoint)
    assert secret not in repr(settings)
    assert secret not in repr(WorkerSettings(worker_token=secret))


@pytest.mark.parametrize("overrides", [
    {"request_timeout": 0}, {"request_timeout": True}, {"request_timeout": "15"},
    {"request_timeout": float("nan")}, {"request_timeout": float("inf")},
    {"request_timeout": 121}, {"request_timeout": 10 ** 1000}, {"task_timeout": 3601}, {"task_timeout": -1},
    {"poll_interval": 0}, {"poll_interval": 31},
    {"max_response_bytes": 1023}, {"max_response_bytes": 32 * 1024 * 1024 + 1},
    {"max_response_bytes": True}, {"max_response_bytes": 2048.5},
    {"hydro": WorkerEndpoint("http://flood.local", "flood-worker")},
    {"flood": WorkerEndpoint("http://hydro.local", "hydro-worker")},
    {"hydro": "http://hydro.local"},
])
def test_control_settings_require_bounded_typed_values_and_matching_roles(overrides):
    with pytest.raises(ValueError):
        ControlSettings(**{**endpoints(), **overrides})


def test_environment_has_no_silent_destination_defaults(monkeypatch):
    monkeypatch.delenv("HYDRO_WORKER_URL", raising=False)
    monkeypatch.delenv("FLOOD_WORKER_URL", raising=False)
    with pytest.raises(ValueError):
        ControlSettings.from_env()
    monkeypatch.setenv("HYDRO_WORKER_URL", "http://hydro.local:8001")
    with pytest.raises(ValueError):
        ControlSettings.from_env()


def test_environment_loads_separate_destinations_tokens_and_limits(monkeypatch):
    values = {"HYDRO_WORKER_URL": "http://hydro.local:8001/", "FLOOD_WORKER_URL": "https://flood.local:8002",
              "HYDRO_WORKER_TOKEN": "private-hydro", "FLOOD_WORKER_TOKEN": "private-flood",
              "MESHMIND_REQUEST_TIMEOUT_SECONDS": "10", "MESHMIND_TASK_TIMEOUT_SECONDS": "120",
              "MESHMIND_POLL_INTERVAL_SECONDS": "0.25"}
    for name, value in values.items():
        monkeypatch.setenv(name, value)
    settings = ControlSettings.from_env()
    assert settings.hydro.url == "http://hydro.local:8001"
    assert settings.hydro.token == "private-hydro" and settings.flood.token == "private-flood"
    assert (settings.request_timeout, settings.task_timeout, settings.poll_interval) == (10, 120, 0.25)
    assert "private-" not in repr(settings)
    monkeypatch.setenv("MESHMIND_REQUEST_TIMEOUT_SECONDS", "private-not-a-number")
    with pytest.raises(ValueError) as caught:
        ControlSettings.from_env()
    assert "private-not-a-number" not in str(caught.value)


@pytest.mark.parametrize('value,normalized', [
    (None, None), ('127.0.0.1', '127.0.0.1'), ('100.100.3.5', '100.100.3.5'),
    ('::1', '::1'), ('2001:0db8:0:0::1', '2001:db8::1'),
])
def test_explicit_control_source_is_a_normalized_ip_literal(value, normalized):
    assert ControlSettings(**endpoints(), local_address=value).local_address == normalized


@pytest.mark.parametrize('value', [
    '', True, 123, 'control.local', '127.0.0.1:8002', '[::1]', '[::1]:8002',
    'fe80::1%utun8', 'http://127.0.0.1', 'user@127.0.0.1', '127.0.0.1/32',
    ' 127.0.0.1', '127.0.0.1\n',
])
def test_control_source_rejects_dns_ports_scopes_and_non_ip_inputs(value):
    with pytest.raises(ValueError, match='MESHMIND_CONTROL_SOURCE_IP'):
        ControlSettings(**endpoints(), local_address=value)


def test_control_source_environment_is_optional_and_never_guessed(monkeypatch):
    monkeypatch.setenv('HYDRO_WORKER_URL', 'http://hydro.local:8002')
    monkeypatch.setenv('FLOOD_WORKER_URL', 'http://flood.local:8003')
    monkeypatch.delenv('MESHMIND_CONTROL_SOURCE_IP', raising=False)
    assert ControlSettings.from_env().local_address is None
    monkeypatch.setenv('MESHMIND_CONTROL_SOURCE_IP', '')
    assert ControlSettings.from_env().local_address is None
    monkeypatch.setenv('MESHMIND_CONTROL_SOURCE_IP', '2001:0db8::1')
    assert ControlSettings.from_env().local_address == '2001:db8::1'
