"""The worker's own read-only dashboard reports genuine bounded lifecycle events."""

from copy import deepcopy
from datetime import datetime
import json
from threading import Event

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from backend.shared import worker_dashboard
from backend.shared.worker_api import _RequestGuard
from test_worker_api import (
    app_for, flood_resources, flood_result, flood_task, hydro_result, hydro_task,
    make_runner, make_runner_without_progress, terminal,
)


TOKEN = "private-worker-api-token"
AUTH = {"Authorization": "Bearer " + TOKEN}
PRIVATE = "PRIVATE_ERROR http://100.100.3.2:8002/private?token=SECRET"
PUBLIC_PATHS = ("/dashboard", "/dashboard/state", "/dashboard/dashboard.css", "/dashboard/dashboard.js")


@pytest.fixture
def assets(tmp_path, monkeypatch):
    directory = tmp_path / "fixed-assets"
    directory.mkdir()
    (directory / "index.html").write_text('<!doctype html><script src="/dashboard/dashboard.js" defer></script>')
    (directory / "dashboard.css").write_text("body { color: white; }")
    (directory / "dashboard.js").write_text('fetch("/dashboard/state");')
    monkeypatch.setattr(worker_dashboard, "_ASSET_ROOT", directory)
    return directory


def snapshot(client):
    response = client.get("/dashboard/state", headers={"Authorization": ""})
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.parametrize("role", ["hydro", "flood"])
def test_fresh_worker_dashboard_is_idle_and_readable_without_credentials(role, hydro_result, flood_result, assets):
    result = hydro_result if role == "hydro" else flood_result
    with TestClient(app_for(result, token=TOKEN)) as client:
        for path, content_type in (("/dashboard", "text/html"), ("/dashboard/state", "application/json"),
                                   ("/dashboard/dashboard.css", "text/css"), ("/dashboard/dashboard.js", "application/javascript")):
            response = client.get(path)
            assert response.status_code == 200
            assert content_type in response.headers["content-type"]
            assert response.headers["cache-control"] == "no-store"
            assert response.headers["x-content-type-options"] == "nosniff"
            assert response.headers["referrer-policy"] == "no-referrer"
            assert "www-authenticate" not in response.headers
            assert TOKEN not in response.text
        state = snapshot(client)
        assert set(state) == {"role", "name", "status", "task", "events", "notice"}
        assert state["role"] == role and state["status"] == "idle"
        assert state["task"] is None and state["events"] == []
        assert "reset when the worker restarts" in state["notice"]
        assert "Control review and fusion are separate" in state["notice"]
        csp = client.get("/dashboard").headers["content-security-policy"]
        assert "script-src 'self'" in csp and "style-src 'self'" in csp
        assert "frame-ancestors 'none'" in csp and "'unsafe-inline'" not in csp


@pytest.mark.parametrize("path,expected", [
    ("/status", 200), ("/clock", 200), ("/tasks/unknown", 404), ("/tasks/unknown/result", 404),
    ("/docs", 200), ("/openapi.json", 200), ("/dashboard/", 307), ("/dashboard/index.html", 404),
    ("/dashboard/arbitrary.js", 404), ("/dashboard/state/", 307),
    ("/dashboard/%2e%2e/worker_api.py", 404), ("/dash%62oard", 200), ("/dashboard/%73tate", 200), ("/unknown", 404),
])
def test_worker_routes_and_fixed_dashboard_assets_remain_bounded(hydro_result, assets, path, expected):
    with TestClient(app_for(hydro_result, token=TOKEN), follow_redirects=False) as client:
        response = client.get(path)
        assert response.status_code == expected
        assert "www-authenticate" not in response.headers


@pytest.mark.parametrize("method", ["POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"])
def test_public_dashboard_never_accepts_mutations_or_other_methods(hydro_result, method):
    with TestClient(app_for(hydro_result, token=TOKEN), follow_redirects=False) as client:
        for path in PUBLIC_PATHS:
            assert client.request(method, path, json={}).status_code == 405
            assert client.request(method, path, json={}, headers=AUTH).status_code == 405
        assert client.post("/tasks", json={}).status_code == 422
        assert client.get("/status", headers=AUTH).json()["retained_tasks"] == 0


def test_exact_paths_do_not_accept_task_or_file_selectors(hydro_result, assets):
    with TestClient(app_for(hydro_result, token=TOKEN)) as client:
        for path in PUBLIC_PATHS:
            response = client.get(path + "?task_id=private&file=../../secret")
            assert response.status_code == 400
            assert "private" not in response.text and "secret" not in response.text
            assert response.headers["cache-control"] == "no-store"
        assert snapshot(client)["task"] is None


def test_default_request_guard_ignores_legacy_credentials():
    app = FastAPI()
    app.add_middleware(_RequestGuard, token=TOKEN)
    @app.get("/dashboard")
    async def protected():
        return {"private": True}
    with TestClient(app) as client:
        assert client.get("/dashboard").status_code == 200
        assert client.get("/dashboard", headers=AUTH).json() == {"private": True}


@pytest.mark.parametrize("role", ["hydro", "flood"])
def test_fast_completion_retains_all_genuine_states_without_polling_timers(role, hydro_result, flood_result):
    result = hydro_result if role == "hydro" else flood_result
    task = hydro_task(result) if role == "hydro" else flood_task(result)
    calls = []
    def runner(request, progress):
        calls.append(request.task_id)
        for state in ("dataset_located", "dataset_located", "processing", "processing", "preparing_result"):
            progress(state)
        return make_runner_without_progress(result, request.task_id)
    with TestClient(app_for(result, runner, token=TOKEN), headers=AUTH) as client:
        assert client.post("/tasks", json=task).status_code == 202
        completed = terminal(client)
        first = snapshot(client)  # No dashboard polling occurred during the fast task.
        assert first["status"] == "complete" and first["task"]["state"] == "complete"
        assert [event["state"] for event in first["events"]] == [
            "task_received", "dataset_located", "processing", "preparing_result", "complete",
        ]
        assert len(first["events"]) <= worker_dashboard.MAX_DASHBOARD_EVENTS
        assert first["events"][0]["observedAt"] == first["task"]["receivedAt"]
        assert first["events"][-1]["observedAt"] == first["task"]["completedAt"]
        start = datetime.fromisoformat(completed["started_at"].replace("Z", "+00:00"))
        end = datetime.fromisoformat(completed["completed_at"].replace("Z", "+00:00"))
        assert first["task"]["durationSeconds"] == (end - start).total_seconds()
        assert all(datetime.fromisoformat(event["observedAt"]).utcoffset().total_seconds() == 0 for event in first["events"])
        assert snapshot(client) == first  # Viewing adds no synthetic events or duration.
        assert client.post("/tasks", json=task).status_code == 202
        assert snapshot(client) == first and calls == [task["task_id"]]


def test_skipped_processor_progress_is_not_invented(hydro_result):
    def runner(task, progress):
        return make_runner_without_progress(hydro_result, task.task_id)
    with TestClient(app_for(hydro_result, runner, token=TOKEN), headers=AUTH) as client:
        client.post("/tasks", json=hydro_task(hydro_result))
        terminal(client)
        assert [item["state"] for item in snapshot(client)["events"]] == ["task_received", "preparing_result", "complete"]


def test_live_snapshot_has_real_active_state_but_no_invented_elapsed_timer(hydro_result):
    started, release = Event(), Event()
    def runner(task, progress):
        progress("processing")
        started.set()
        assert release.wait(5)
        return make_runner_without_progress(hydro_result, task.task_id)
    with TestClient(app_for(hydro_result, runner, token=TOKEN), headers=AUTH) as client:
        try:
            client.post("/tasks", json=hydro_task(hydro_result))
            assert started.wait(2)
            active = snapshot(client)
            assert active["status"] == "active" and active["task"]["state"] == "processing"
            assert active["task"]["startedAt"] and active["task"]["completedAt"] is None
            assert active["task"]["durationSeconds"] is None
            assert snapshot(client) == active
        finally:
            release.set()
        assert terminal(client)["state"] == "complete"


def test_latest_new_task_follows_automatically_and_old_duplicate_does_not_switch_display(hydro_result):
    with TestClient(app_for(hydro_result, token=TOKEN), headers=AUTH) as client:
        first = hydro_task(hydro_result, "first-task")
        second = hydro_task(hydro_result, "second-task")
        client.post("/tasks", json=first)
        terminal(client, "first-task")
        client.post("/tasks", json=second)
        terminal(client, "second-task")
        saved = snapshot(client)
        assert saved["task"]["id"] == "second-task"
        client.post("/tasks", json=first)
        assert snapshot(client) == saved
        assert client.get("/tasks/first-task/result").status_code == 200


def test_runtime_failure_public_snapshot_is_fixed_text_and_has_no_private_payload(hydro_result, monkeypatch):
    monkeypatch.setattr("backend.shared.worker_api.socket.gethostname", lambda: "PRIVATE_WORKER_HOST")
    def runner(task, progress):
        progress("dataset_located")
        raise RuntimeError(PRIVATE)
    with TestClient(app_for(hydro_result, runner, token=TOKEN), headers=AUTH) as client:
        client.post("/tasks", json=hydro_task(hydro_result))
        terminal(client)
        state = snapshot(client)
        assert state["status"] == "failed" and state["task"]["state"] == "failed"
        assert [event["state"] for event in state["events"]] == ["task_received", "dataset_located", "failed"]
        text = json.dumps(state)
        assert all(value not in text for value in (TOKEN, "PRIVATE", "http://", "https://", "SECRET", "100.100.",
            hydro_result["sources"][0]["resources_used"][0], hydro_result["sources"][1]["resources_used"][0]))
        assert set(state["task"]) == {"id", "state", "receivedAt", "startedAt", "completedAt", "durationSeconds"}
        assert all(set(event) == {"state", "observedAt", "label"} for event in state["events"])


@pytest.mark.parametrize("failed", [{"dem"}, {"sentinel1", "dem", "hand"}])
def test_partial_and_failed_result_envelopes_keep_their_actual_terminal_state(flood_result, failed):
    result = deepcopy(flood_result)
    keys = {"sentinel1": "surface_water", "dem": "elevation", "hand": "hand"}
    for component in failed:
        result["evidence"].pop(component)
        result["coverage"].pop(component)
        result["summary"].pop(keys[component])
    result["sources"] = [source for source in result["sources"] if source["component"] not in failed]
    result["errors"] = [{"component": component, "code": "processing_failed", "message": PRIVATE} for component in sorted(failed)]
    result["status"] = "failed" if len(failed) == 3 else "partial"
    with TestClient(app_for(result, token=TOKEN), headers=AUTH) as client:
        client.post("/tasks", json=flood_task(result))
        terminal(client)
        state = snapshot(client)
        assert state["status"] == result["status"]
        assert state["events"][-1]["state"] == result["status"]
        assert PRIVATE not in json.dumps(state)


def test_new_worker_process_starts_idle_without_retained_task_history(hydro_result):
    with TestClient(app_for(hydro_result, token=TOKEN), headers=AUTH) as client:
        client.post("/tasks", json=hydro_task(hydro_result))
        terminal(client)
        assert snapshot(client)["status"] == "complete"
    with TestClient(app_for(hydro_result, token=TOKEN), headers=AUTH) as restarted:
        assert snapshot(restarted)["status"] == "idle"
        assert snapshot(restarted)["task"] is None and snapshot(restarted)["events"] == []
        assert restarted.get("/tasks/api-task").status_code == 404


def test_missing_asset_fails_with_fixed_text_without_filesystem_details(hydro_result, assets):
    (assets / "dashboard.js").unlink()
    with TestClient(app_for(hydro_result, token=TOKEN)) as client:
        response = client.get("/dashboard/dashboard.js")
        assert response.status_code == 503
        assert response.text == "Worker dashboard is unavailable."
        assert str(assets) not in response.text
        assert response.headers["cache-control"] == "no-store"
        assert snapshot(client)["status"] == "idle"
