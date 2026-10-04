"""Observed worker identity follows every task without implying physical proof."""

import re
import socket
from uuid import UUID

from fastapi.testclient import TestClient
from pydantic import ValidationError
import pytest

from backend.shared.contracts import TaskStatus, WorkerStatus
from backend.shared.worker_api import create_worker_app
from test_contracts import hydro_result
from test_worker_api import app_for, hydro_task, terminal


def test_actual_host_and_instance_are_stable_in_worker_and_task_status(hydro_result):
    with TestClient(app_for(hydro_result)) as client:
        initial = client.get("/status").json()
        expected = re.sub(r"[^A-Za-z0-9_.-]", "_", socket.gethostname())[:253] or None
        assert initial["execution_host"] == expected
        assert UUID(initial["process_instance_id"]).version == 4
        accepted = client.post("/tasks", json=hydro_task(hydro_result)).json()
        completed = terminal(client)
        subsequent = client.get("/status").json()
        for data in (accepted, completed, subsequent):
            assert data["execution_host"] == initial["execution_host"]
            assert data["process_instance_id"] == initial["process_instance_id"]
        assert completed["state"] == "complete"


def test_instance_changes_on_startup_and_does_not_claim_separate_host(hydro_result):
    app = app_for(hydro_result)
    with TestClient(app) as client:
        first = client.get("/status").json()
    with TestClient(app) as client:
        second = client.get("/status").json()
    assert first["execution_host"] == second["execution_host"]
    assert first["process_instance_id"] != second["process_instance_id"]


def test_hostname_is_observed_at_startup_sanitized_and_ignores_environment(hydro_result, monkeypatch):
    monkeypatch.setenv("MESHMIND_EXECUTION_HOST", "fake-host")
    app = app_for(hydro_result)
    monkeypatch.setattr("backend.shared.worker_api.socket.gethostname", lambda: "real\r\n\u2603.host" + "x" * 300)
    with TestClient(app) as client:
        host = client.get("/status").json()["execution_host"]
    assert host.startswith("real___.host") and len(host) == 253
    assert "fake-host" not in host


def test_failed_task_retains_actual_execution_identity():
    def fail(task, progress):
        raise RuntimeError("private-source-details")
    app = create_worker_app("hydro-worker", "hydrometeorology", fail)
    task = {"task_id": "api-task", "analysis_type": "hydrometeorology",
            "bbox": {"west": 0, "south": 0, "east": 1, "north": 1},
            "gpm_resources": ["gpm.h5"], "smap_resource": "smap.h5"}
    with TestClient(app) as client:
        worker = client.get("/status").json()
        client.post("/tasks", json=task)
        failed = terminal(client)
    assert failed["state"] == "failed"
    assert failed["execution_host"] == worker["execution_host"]
    assert failed["process_instance_id"] == worker["process_instance_id"]
    assert "private-source-details" not in str(failed)


@pytest.mark.parametrize("field,value", [
    ("execution_host", "invalid\r\nhost"), ("execution_host", "x" * 254),
    ("execution_host", "https://not-a-host"), ("execution_host", ""),
    ("process_instance_id", "fake-id"), ("process_instance_id", True),
])
def test_identity_contract_rejects_unbounded_or_malformed_values(field, value):
    raw = {"worker_id": "hydro-worker", "analysis_type": "hydrometeorology",
           "status": "idle", "retained_tasks": 0, "capacity": 128, field: value}
    with pytest.raises(ValidationError):
        WorkerStatus.model_validate(raw)
    task = {"worker_id": "hydro-worker", "analysis_type": "hydrometeorology",
            "task_id": "task", "state": "task_received", "received_at": "2021-11-15T00:00:00Z", field: value}
    with pytest.raises(ValidationError):
        TaskStatus.model_validate(task)


def test_legacy_status_can_still_be_read_without_identity():
    status = WorkerStatus(worker_id="hydro-worker", analysis_type="hydrometeorology",
                          status="idle", retained_tasks=0, capacity=128)
    assert status.execution_host is None and status.process_instance_id is None
