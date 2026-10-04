"""Read-only clock observations remain available while a worker processes."""

from datetime import datetime, timedelta, timezone
from threading import Event

from fastapi.testclient import TestClient
from pydantic import ValidationError
import pytest

from backend.shared.contracts import WorkerClock
from backend.shared import worker_api
from backend.shared.worker_api import create_worker_app
from test_contracts import flood_resources, flood_result
from test_worker_api import app_for, flood_task, make_runner_without_progress, terminal


TOKEN = "worker-clock-test-token-keep-private"
AUTH = {"Authorization": f"Bearer {TOKEN}"}
IDENTITY = {
    "execution_host": "test-worker",
    "process_instance_id": "12345678-1234-1234-1234-123456789abc",
    "worker_id": "hydro-worker",
    "analysis_type": "hydrometeorology",
}


def test_clock_contract_round_trip_preserves_microseconds_and_normalizes_utc():
    clock = WorkerClock(**IDENTITY, sampled_at="2026-10-03T20:00:01.123456-07:00")
    assert clock.sampled_at == datetime(2026, 10, 4, 3, 0, 1, 123456, tzinfo=timezone.utc)
    assert clock.sampled_at.tzinfo is timezone.utc
    assert WorkerClock.model_validate_json(clock.model_dump_json()) == clock


@pytest.mark.parametrize("changes", [
    {"sampled_at": "2026-10-04T03:00:01.123456"},
    {"sampled_at": datetime(2026, 10, 4, 3, 0, 1)},
    {"sampled_at": 1791082801.123456},
    {"sampled_at": None},
    {"execution_host": None},
    {"execution_host": "https://private.example/"},
    {"process_instance_id": None},
    {"process_instance_id": "not-a-uuid"},
    {"analysis_type": "surface_water_and_terrain"},
    {"token": TOKEN},
])
def test_clock_contract_rejects_invalid_observations(changes):
    with pytest.raises(ValidationError):
        WorkerClock.model_validate({
            **IDENTITY, "sampled_at": "2026-10-04T03:00:01.123456Z", **changes,
        })


@pytest.mark.parametrize("worker_id, analysis_type", [
    ("hydro-worker", "hydrometeorology"),
    ("flood-worker", "surface_water_and_terrain"),
])
def test_clock_ignores_internal_credentials_and_preserves_identity(worker_id, analysis_type):
    def must_not_run(task, progress):
        pytest.fail("Reading the clock must not execute a task.")

    app = create_worker_app(worker_id, analysis_type, must_not_run, token=TOKEN)
    with TestClient(app) as client:
        for headers in ({}, {"Authorization": "Bearer wrong-token"}):
            response = client.get("/clock", headers=headers)
            assert response.status_code == 200
            assert "WWW-Authenticate" not in response.headers
            assert WorkerClock.model_validate(response.json()).worker_id == worker_id
            assert TOKEN not in response.text
        before = client.get("/status", headers=AUTH).json()
        sent_at = datetime.now(timezone.utc)
        response = client.get("/clock", headers=AUTH)
        read_at = datetime.now(timezone.utc)
        assert response.status_code == 200
        clock = WorkerClock.model_validate(response.json())
        assert sent_at <= clock.sampled_at <= read_at
        assert clock.sampled_at.tzinfo is timezone.utc
        assert set(response.json()) == {*IDENTITY, "sampled_at"}
        for key in IDENTITY:
            assert getattr(clock, key) == before[key]
        assert TOKEN not in response.text
        assert client.get("/status", headers=AUTH).json() == before
        assert before["retained_tasks"] == 0


def test_clock_is_sampled_fresh_for_each_request(monkeypatch):
    times = [
        datetime(2026, 10, 4, 3, 0, 1, 123456, tzinfo=timezone.utc),
        datetime(2026, 10, 4, 3, 0, 1, 123457, tzinfo=timezone.utc),
    ]
    ticks = iter(times)
    monkeypatch.setattr(worker_api, "_now", lambda: next(ticks))
    app = create_worker_app("hydro-worker", "hydrometeorology", lambda *_: None, token=TOKEN)
    with TestClient(app) as client:
        first = WorkerClock.model_validate(client.get("/clock", headers=AUTH).json())
        second = WorkerClock.model_validate(client.get("/clock", headers=AUTH).json())
    assert first.sampled_at == times[0]
    assert second.sampled_at == times[1]
    assert second.sampled_at - first.sampled_at == timedelta(microseconds=1)
    assert first.process_instance_id == second.process_instance_id


def test_clock_without_startup_identity_is_unavailable():
    app = create_worker_app("hydro-worker", "hydrometeorology", lambda *_: None, token=TOKEN)
    # Omitting the context manager deliberately omits lifespan startup.
    client = TestClient(app)
    try:
        response = client.get("/clock", headers=AUTH)
        assert response.status_code == 503
        assert response.json() == {"detail": "Worker clock is not ready."}
    finally:
        client.close()


def test_clock_remains_responsive_and_read_only_during_processing(flood_result):
    started, release = Event(), Event()

    def runner(task, progress):
        progress("dataset_located")
        progress("processing")
        started.set()
        assert release.wait(5), "Clock request blocked until the task timed out."
        return make_runner_without_progress(flood_result, task.task_id)

    with TestClient(app_for(flood_result, runner, token=TOKEN), headers=AUTH) as client:
        try:
            submitted = client.post("/tasks", json=flood_task(flood_result))
            assert submitted.status_code == 202
            assert started.wait(2)
            before = client.get("/status").json()
            assert before["status"] == "busy"
            response = client.get("/clock")
            assert response.status_code == 200
            clock = WorkerClock.model_validate(response.json())
            assert clock.process_instance_id == before["process_instance_id"]
            assert clock.execution_host == before["execution_host"]
            assert client.get("/status").json() == before
            assert client.get("/tasks/api-task").json()["state"] == "processing"
            assert not release.is_set()
        finally:
            release.set()
        assert terminal(client)["state"] == "complete"
