"""The worker opens its own dashboard only after successful listener startup."""

import asyncio
import importlib
import os
from threading import Event, Thread
from types import SimpleNamespace

import pytest
import uvicorn

from scripts import run_worker


@pytest.fixture(autouse=True)
def private_worker_environment(monkeypatch):
    monkeypatch.setenv("MESHMIND_WORKER_TOKEN", "test-only-existing-worker-token")


@pytest.mark.parametrize("role,host,port", [("hydro", "100.100.3.2", 8002), ("flood", "100.100.3.4", 8003)])
def test_cli_uses_existing_factory_environment_and_own_dashboard(role, host, port, monkeypatch):
    monkeypatch.setenv("MESHMIND_WORKER_TOKEN", "private-existing-worker-token")
    monkeypatch.setenv("WEB_CONCURRENCY", "8")
    monkeypatch.setenv("MESHMIND_GPM_DIR", "/existing/local/data")
    before = dict(os.environ)
    captured = []

    def run(server):
        captured.append(server)
        server.started = True

    monkeypatch.setattr(run_worker.WorkerServer, "run", run)
    monkeypatch.setattr(run_worker.webbrowser, "open_new_tab", lambda _: pytest.fail("No actual startup occurred."))
    assert run_worker.main([role, "--host", host]) == 0
    server = captured[0]
    assert server.config.app == f"backend.workers.{role}.main:create_app"
    assert server.config.factory is True
    assert server.config.host == host
    assert server.config.port == port
    assert server.config.workers == 1 and server.config.reload is False
    assert server.dashboard_url == f"http://{host}:{port}/dashboard"
    assert dict(os.environ) == before


def test_headless_opt_out_and_explicit_port(monkeypatch):
    captured = []

    def run(server):
        captured.append(server)
        server.started = True

    monkeypatch.setattr(run_worker.WorkerServer, "run", run)
    assert run_worker.main(["flood", "--host", "::1", "--port", "9003", "--no-open-dashboard"]) == 0
    assert captured[0].dashboard_url is None
    assert captured[0].config.host == "::1" and captured[0].config.port == 9003


@pytest.mark.parametrize("args", [
    ["other"], ["hydro", "--host", "private.invalid/path"], ["hydro", "--host", "fe80::1%en0"],
    ["hydro", "--port", "0"], ["hydro", "--port", "65536"], ["hydro", "--port", "-1"],
    ["hydro", "--port", "1.5"], ["hydro", "--workers", "2"], ["hydro", "--reload"],
    ["hydro", "--dashboard-origin", "http://100.100.3.5:3001"],
    ["hydro", "--host", "user:private@localhost"], ["hydro", "--host", "localhost?token=private"],
    ["hydro", "--host", "localhost\n"], ["hydro", "--host", "a" * 2048],
])
def test_invalid_cli_never_starts_server(args, monkeypatch):
    monkeypatch.setattr(run_worker.WorkerServer, "run", lambda _: pytest.fail("Invalid CLI started a server."))
    with pytest.raises(SystemExit) as error:
        run_worker.main(args)
    assert error.value.code == 2


@pytest.mark.parametrize("token", [None, "", "private token", "private\nvalue", "private-\u2603", "x" * 513])
def test_missing_or_invalid_worker_token_cannot_start_server_or_browser(token, monkeypatch, capsys):
    if token is None:
        monkeypatch.delenv("MESHMIND_WORKER_TOKEN", raising=False)
    else:
        monkeypatch.setenv("MESHMIND_WORKER_TOKEN", token)
    monkeypatch.setattr(run_worker.WorkerServer, "run", lambda _: pytest.fail("Unauthenticated startup."))
    monkeypatch.setattr(run_worker.webbrowser, "open_new_tab", lambda _: pytest.fail("Unauthenticated browser opening."))
    with pytest.raises(SystemExit) as error:
        run_worker.main(["hydro"])
    assert error.value.code == 2
    assert "Set a valid nonempty MESHMIND_WORKER_TOKEN" in capsys.readouterr().err


@pytest.mark.parametrize("host,expected", [
    ("127.0.0.1", "http://127.0.0.1:8002/dashboard"),
    ("localhost", "http://localhost:8002/dashboard"),
    ("0.0.0.0", "http://127.0.0.1:8002/dashboard"),
    ("::", "http://[::1]:8002/dashboard"),
    ("::1", "http://[::1]:8002/dashboard"),
    ("fd7a:115c:a1e0::1", "http://[fd7a:115c:a1e0::1]:8002/dashboard"),
])
def test_cli_default_opens_own_listener_with_valid_browser_host(host, expected, monkeypatch):
    captured = []

    def run(server):
        captured.append(server)
        server.started = True

    monkeypatch.setattr(run_worker.WorkerServer, "run", run)
    assert run_worker.main(["hydro", "--host", host]) == 0
    assert captured[0].dashboard_url == expected
    assert captured[0].config.host == host


def test_import_has_no_server_or_browser_side_effects(monkeypatch):
    monkeypatch.setattr(uvicorn.Server, "run", lambda _: pytest.fail("Import started a server."))
    monkeypatch.setattr(run_worker.webbrowser, "open_new_tab", lambda _: pytest.fail("Import opened a browser."))
    importlib.reload(run_worker)


def _server(monkeypatch, *, url="http://100.100.3.2:8002/dashboard", failed_lifespan=False):
    async def unused_app(scope, receive, send):
        pass

    config = uvicorn.Config(unused_app, log_config=None)
    config.load()
    server = run_worker.WorkerServer(config, url)
    phases = []

    async def startup():
        phases.append("lifespan")

    async def shutdown():
        phases.append("shutdown")

    server.lifespan = SimpleNamespace(startup=startup, shutdown=shutdown,
                                      should_exit=failed_lifespan, state={})
    monkeypatch.setattr(server, "_log_started_message", lambda _: phases.append("listening"))
    return server, phases


def _immediate_browser_thread(monkeypatch, phases):
    class BrowserThread:
        def __init__(self, target, args, name, daemon):
            assert daemon is True
            self.target, self.args = target, args

        def start(self):
            phases.append("browser")
            self.target(*self.args)

    monkeypatch.setattr(run_worker, "Thread", BrowserThread)


def test_browser_opens_once_after_real_uvicorn_startup(monkeypatch):
    server, phases = _server(monkeypatch)
    urls = []
    monkeypatch.setattr(run_worker.webbrowser, "open_new_tab", lambda url: urls.append(url) or True)
    _immediate_browser_thread(monkeypatch, phases)

    async def scenario():
        async def listen(*args, **kwargs):
            assert not urls
            phases.append("bind")
            return SimpleNamespace(sockets=[object()])

        monkeypatch.setattr(asyncio.get_running_loop(), "create_server", listen)
        await server.startup()
        assert server.started
        assert phases == ["lifespan", "bind", "listening", "browser"]
        # Re-entering startup cannot create a second browser tab.
        async def already_started(_server, sockets=None):
            assert _server.started
        monkeypatch.setattr(uvicorn.Server, "startup", already_started)
        await server.startup()

    asyncio.run(scenario())
    assert urls == ["http://100.100.3.2:8002/dashboard"]


@pytest.mark.parametrize("failure", ["lifespan", "bind"])
def test_failed_actual_uvicorn_startup_never_opens_browser(failure, monkeypatch):
    server, phases = _server(monkeypatch, failed_lifespan=failure == "lifespan")
    monkeypatch.setattr(run_worker.webbrowser, "open_new_tab", lambda _: pytest.fail("Failed startup opened a browser."))
    _immediate_browser_thread(monkeypatch, phases)

    async def scenario():
        async def failed_bind(*args, **kwargs):
            phases.append("bind")
            raise OSError("Representative bind failure")

        monkeypatch.setattr(asyncio.get_running_loop(), "create_server", failed_bind)
        with pytest.raises(SystemExit):
            await server.startup()

    asyncio.run(scenario())
    assert not server.started and "browser" not in phases
    assert phases == (["lifespan"] if failure == "lifespan" else ["lifespan", "bind", "shutdown"])


@pytest.mark.parametrize("url,exiting", [(None, False), ("http://localhost:8002/dashboard", True)])
def test_headless_or_exiting_startup_never_opens_browser(url, exiting, monkeypatch):
    server, phases = _server(monkeypatch, url=url)

    async def started(instance, sockets=None):
        instance.started = True
        instance.should_exit = exiting

    monkeypatch.setattr(uvicorn.Server, "startup", started)
    monkeypatch.setattr(run_worker.webbrowser, "open_new_tab", lambda _: pytest.fail("Unrequested browser opening."))
    _immediate_browser_thread(monkeypatch, phases)
    asyncio.run(server.startup())
    assert "browser" not in phases


@pytest.mark.parametrize("failure", ["false", "exception", "thread"])
def test_browser_failures_leave_server_running_with_safe_fallback(failure, monkeypatch, capsys):
    server, phases = _server(monkeypatch)

    async def started(instance, sockets=None):
        instance.started = True

    def opener(_url):
        if failure == "exception":
            raise OSError("private-desktop-error")
        return False

    monkeypatch.setattr(uvicorn.Server, "startup", started)
    monkeypatch.setattr(run_worker.webbrowser, "open_new_tab", opener)
    if failure == "thread":
        def cannot_start(**kwargs):
            raise RuntimeError("private-thread-error")
        monkeypatch.setattr(run_worker, "Thread", cannot_start)
    else:
        _immediate_browser_thread(monkeypatch, phases)
    asyncio.run(server.startup())
    assert server.started and not server.should_exit
    captured = capsys.readouterr()
    assert "http://100.100.3.2:8002/dashboard" in captured.err
    assert "could not open automatically" in captured.err
    assert "private" not in captured.out + captured.err


def test_slow_desktop_does_not_block_worker_startup(monkeypatch):
    server, _phases = _server(monkeypatch)
    entered, release = Event(), Event()
    threads = []

    async def started(instance, sockets=None):
        instance.started = True

    def opener(_url):
        entered.set()
        release.wait(5)
        return True

    def browser_thread(**kwargs):
        thread = Thread(**kwargs)
        threads.append(thread)
        return thread

    monkeypatch.setattr(uvicorn.Server, "startup", started)
    monkeypatch.setattr(run_worker.webbrowser, "open_new_tab", opener)
    monkeypatch.setattr(run_worker, "Thread", browser_thread)
    try:
        asyncio.run(server.startup())
        assert entered.wait(1)
        assert not release.is_set() and server.started and not server.should_exit
    finally:
        release.set()
        for thread in threads:
            thread.join(2)


def test_unsuccessful_run_is_not_reported_as_success(monkeypatch):
    monkeypatch.setattr(run_worker.WorkerServer, "run", lambda _: None)
    assert run_worker.main(["hydro"]) == 1
