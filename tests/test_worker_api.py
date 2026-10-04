"""HTTP task lifecycle tests with actual small deterministic result fixtures."""

from copy import deepcopy
import json
from threading import Event
import time

from fastapi.testclient import TestClient
import pytest

from backend.shared.contracts import FloodResult, HydroResult, TaskStatus, WorkerStatus
from backend.shared.worker_api import MAX_REQUEST_BYTES, create_worker_app
from test_contracts import flood_resources, flood_result, hydro_result


def flood_task(result, task_id="api-task"):
    return {
        "task_id": task_id, "analysis_type": "surface_water_and_terrain", "bbox": result["bbox"],
        "start_time": "2021-11-13T00:00:00Z", "end_time": "2021-11-18T23:59:59Z",
        "reference_time": "2021-11-15T00:00:00Z",
    }


def hydro_task(result, task_id="api-task"):
    return {
        "task_id": task_id, "analysis_type": "hydrometeorology", "bbox": result["bbox"],
        "gpm_resources": result["sources"][0]["resources_used"],
        "smap_resource": result["sources"][1]["resources_used"][0],
    }


def make_runner(result):
    def runner(task, progress):
        progress("dataset_located")
        progress("processing")
        data = deepcopy(result)
        data["task_id"] = task.task_id
        return data
    return runner


def app_for(result, runner=None, **kwargs):
    return create_worker_app(
        result["worker_id"], result["analysis_type"], runner or make_runner(result), **kwargs,
    )


def terminal(client, task_id="api-task"):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        response = client.get(f"/tasks/{task_id}")
        assert response.status_code == 200
        status = response.json()
        if status["state"] in {"complete", "partial", "failed"}:
            TaskStatus.model_validate(status)
            return status
        time.sleep(0.005)
    pytest.fail("Worker did not reach a terminal state.")


@pytest.mark.parametrize("kind", ["hydro", "flood"])
def test_success_returns_typed_serializable_result_and_actual_timestamps(kind, hydro_result, flood_result):
    result, task, model = ((hydro_result, hydro_task(hydro_result), HydroResult) if kind == "hydro"
                           else (flood_result, flood_task(flood_result), FloodResult))
    with TestClient(app_for(result)) as client:
        submitted = client.post("/tasks", json=task)
        assert submitted.status_code == 202
        assert submitted.json()["state"] == "task_received"
        assert submitted.json()["started_at"] is None
        status = terminal(client)
        assert status["state"] == "complete"
        assert status["received_at"] <= status["started_at"] <= status["completed_at"]
        response = client.get("/tasks/api-task/result")
        assert response.status_code == 200
        expected = deepcopy(result)
        expected["task_id"] = task["task_id"]
        assert response.json() == model.model_validate(expected).model_dump(mode="json")
        worker = WorkerStatus.model_validate(client.get("/status").json())
        assert worker.status == "idle" and worker.active_task_id is None and worker.retained_tasks == 1
        assert client.get("/openapi.json").status_code == 200


def test_status_stays_responsive_while_one_task_executes_and_duplicates_never_rerun(flood_result):
    started, release = Event(), Event()
    executions = []

    def runner(task, progress):
        executions.append(task.task_id)
        progress("dataset_located")
        progress("processing")
        started.set()
        assert release.wait(5)
        return make_runner_without_progress(flood_result, task.task_id)

    task = flood_task(flood_result)
    with TestClient(app_for(flood_result, runner)) as client:
        try:
            assert client.post("/tasks", json=task).status_code == 202
            assert started.wait(2)
            worker = client.get("/status").json()
            assert worker["status"] == "busy" and worker["active_task_id"] == "api-task"
            status = client.get("/tasks/api-task").json()
            assert status["state"] == "processing" and status["started_at"] is not None
            assert client.get("/tasks/api-task/result").status_code == 409
            duplicate = client.post("/tasks", json=task)
            assert duplicate.status_code == 202 and duplicate.json()["state"] == "processing"
            assert client.post("/tasks", json={**task, "threshold_db": -18.0}).status_code == 409
            assert client.post("/tasks", json={**task, "task_id": "second"}).status_code == 429
        finally:
            release.set()
        assert terminal(client)["state"] == "complete"
        assert client.post("/tasks", json=task).json()["state"] == "complete"
        assert executions == ["api-task"]


def make_runner_without_progress(result, task_id):
    result = deepcopy(result)
    result["task_id"] = task_id
    return result


def test_retention_full_rejects_new_work_without_evicting_results(flood_result):
    with TestClient(app_for(flood_result, capacity=1)) as client:
        task = flood_task(flood_result)
        assert client.post("/tasks", json=task).status_code == 202
        assert terminal(client)["state"] == "complete"
        saved = client.get("/tasks/api-task/result").json()
        assert client.post("/tasks", json={**task, "task_id": "second"}).status_code == 503
        assert client.post("/tasks", json=task).status_code == 202
        assert client.get("/tasks/api-task/result").json() == saved


def test_runtime_failure_is_sanitized_and_does_not_erase_prior_work(flood_result):
    def runner(task, progress):
        if task.task_id == "failed-task":
            raise RuntimeError("password: private-secret, https://example.test/?token=private-secret")
        return make_runner(flood_result)(task, progress)

    with TestClient(app_for(flood_result, runner)) as client:
        assert client.post("/tasks", json=flood_task(flood_result)).status_code == 202
        assert terminal(client)["state"] == "complete"
        saved = client.get("/tasks/api-task/result").json()
        assert client.post("/tasks", json=flood_task(flood_result, "failed-task")).status_code == 202
        status = terminal(client, "failed-task")
        assert status["state"] == "failed" and status["error"]
        response = client.get("/tasks/failed-task/result")
        assert response.status_code == 409
        assert "private-secret" not in json.dumps(status) + response.text
        assert client.get("/tasks/api-task/result").json() == saved
        assert client.get("/status").json()["status"] == "idle"


@pytest.mark.parametrize("failed", [{"dem"}, {"sentinel1", "dem", "hand"}])
def test_partial_and_structured_failed_results_remain_downloadable(flood_result, failed):
    result = deepcopy(flood_result)
    keys = {"sentinel1": "surface_water", "dem": "elevation", "hand": "hand"}
    for component in failed:
        result["evidence"].pop(component)
        result["coverage"].pop(component)
        result["summary"].pop(keys[component])
    result["sources"] = [source for source in result["sources"] if source["component"] not in failed]
    result["errors"] = [{"component": component, "code": "processing_failed", "message": "Processing failed."}
                        for component in sorted(failed)]
    result["status"] = "failed" if len(failed) == 3 else "partial"
    with TestClient(app_for(result)) as client:
        assert client.post("/tasks", json=flood_task(result)).status_code == 202
        assert terminal(client)["state"] == result["status"]
        response = client.get("/tasks/api-task/result")
        assert response.status_code == 200
        validated = FloodResult.model_validate(response.json())
        assert set(validated.evidence) == set(keys) - failed
        assert len(validated.errors) == len(failed)


@pytest.mark.parametrize("malformed", ["task_id", "bbox", "worker_id", "analysis_type", "nan", "threshold", "date"])
def test_malformed_or_mismatched_results_never_publish(flood_result, malformed):
    def runner(task, progress):
        value = make_runner(flood_result)(task, progress)
        if malformed == "task_id":
            value["task_id"] = "another-task"
        elif malformed == "bbox":
            value["bbox"]["west"] += 0.00001
        elif malformed == "worker_id":
            value["worker_id"] = "hydro-worker"
        elif malformed == "analysis_type":
            value["analysis_type"] = "hydrometeorology"
        elif malformed == "nan":
            value["evidence"]["dem"]["untrusted"] = float("nan")
        elif malformed == "threshold":
            value["summary"]["surface_water"]["threshold_db"] = -20.0
            value["evidence"]["sentinel1"]["method"]["threshold_db"] = -20.0
        else:
            value["summary"]["surface_water"]["acquired_at"] = "2020-01-01T00:00:00Z"
            value["evidence"]["sentinel1"]["scene"]["acquired_at"] = "2020-01-01T00:00:00Z"
        return value

    with TestClient(app_for(flood_result, runner)) as client:
        assert client.post("/tasks", json=flood_task(flood_result)).status_code == 202
        assert terminal(client)["state"] == "failed"
        assert client.get("/tasks/api-task/result").status_code == 409


@pytest.mark.parametrize("component", ["gpm", "smap"])
def test_well_formed_hydro_result_from_unrequested_resource_never_publishes(hydro_result, component):
    def runner(task, progress):
        result = make_runner(hydro_result)(task, progress)
        result["sources"][0 if component == "gpm" else 1]["resources_used"] = ["other.h5"]
        # Confirm this is a valid environmental envelope, but for another input.
        HydroResult.model_validate(result)
        return result
    with TestClient(app_for(hydro_result, runner)) as client:
        assert client.post("/tasks", json=hydro_task(hydro_result)).status_code == 202
        assert terminal(client)["state"] == "failed"
        assert client.get("/tasks/api-task/result").status_code == 409


def test_well_formed_result_for_different_aoi_never_publishes(flood_result):
    def runner(task, progress):
        result = make_runner(flood_result)(task, progress)
        result["bbox"]["west"] += 0.00001
        bounds = list(result["bbox"].values())
        for evidence in result["evidence"].values():
            evidence["bbox"] = bounds
        FloodResult.model_validate(result)
        return result
    with TestClient(app_for(flood_result, runner)) as client:
        assert client.post("/tasks", json=flood_task(flood_result)).status_code == 202
        assert terminal(client)["state"] == "failed"
        assert client.get("/tasks/api-task/result").status_code == 409


def test_progress_cannot_claim_terminal_state_or_move_backwards(flood_result):
    for states in (("processing", "dataset_located"), ("complete",)):
        def runner(task, progress):
            for state in states:
                progress(state)
            return make_runner_without_progress(flood_result, task.task_id)
        with TestClient(app_for(flood_result, runner)) as client:
            assert client.post("/tasks", json=flood_task(flood_result)).status_code == 202
            assert terminal(client)["state"] == "failed"


def test_wrong_worker_unknown_task_and_missing_lifespan_do_not_start_work(flood_result, hydro_result):
    with TestClient(app_for(flood_result)) as client:
        assert client.post("/tasks", json=hydro_task(hydro_result)).status_code == 422
        assert client.get("/tasks/unknown").status_code == 404
        assert client.get("/tasks/unknown/result").status_code == 404
        assert client.get("/status").json()["retained_tasks"] == 0
    with TestClient(app_for(flood_result), follow_redirects=False) as client:
        assert client.get("/openapi.json").status_code == 200
    client = TestClient(app_for(flood_result))
    try:
        assert client.post("/tasks", json=flood_task(flood_result)).status_code == 503
    finally:
        client.close()


@pytest.mark.parametrize("authorization", [None, "", "Bearer incorrect", "Basic arbitrary", "Bearer", "Bearer bad\r\nvalue", b"\xff\x00"])
def test_internal_worker_routes_ignore_legacy_authorization(flood_result, authorization):
    headers = {} if authorization is None else {"Authorization": authorization}
    with TestClient(app_for(flood_result, token="private-worker-token")) as client:
        for path, code in (("/status", 200), ("/clock", 200), ("/tasks/unknown", 404),
                           ("/tasks/unknown/result", 404), ("/docs", 200), ("/openapi.json", 200), ("/unknown", 404)):
            response = client.get(path, headers=headers)
            assert response.status_code == code
            assert "www-authenticate" not in response.headers
            assert "private-worker-token" not in response.text
        assert client.post("/tasks", json={}, headers=headers).status_code == 422
        assert client.get("/status").json()["retained_tasks"] == 0
        assert client.post("/tasks", json=flood_task(flood_result), headers=headers).status_code == 202
        assert terminal(client)["state"] == "complete"
        assert client.get("/tasks/api-task/result", headers=headers).status_code == 200


@pytest.mark.parametrize("body", [
    '{"threshold_db":NaN}', '{"threshold_db":Infinity}', '{"threshold_db":-Infinity}',
    '{"threshold_db":1e999}', '{"task_id":"one","task_id":"two"}', 'not-json',
    '[' * 2000 + ']' * 2000,
])
def test_invalid_nonfinite_duplicate_or_overdeep_json_is_rejected_before_models(flood_result, body):
    with TestClient(app_for(flood_result)) as client:
        response = client.post("/tasks", content=body, headers={"Content-Type": "application/json"})
        assert response.status_code == 422
        assert client.get("/status").json()["retained_tasks"] == 0


def test_validation_errors_never_echo_values_or_unknown_field_names(flood_result):
    with TestClient(app_for(flood_result)) as client:
        task = flood_task(flood_result)
        task.update(task_id="secret/private-input", private_secret_field="private-secret-value")
        response = client.post("/tasks", json=task)
        assert response.status_code == 422
        assert all(secret not in response.text for secret in ("secret/private-input", "private_secret_field", "private-secret-value"))
        assert all(set(error) == {"loc", "type", "msg"} for error in response.json()["detail"])


def test_body_size_is_bounded_even_without_content_length(flood_result):
    with TestClient(app_for(flood_result)) as client:
        payload = b" " * (MAX_REQUEST_BYTES + 1)
        for content in (payload, iter([payload[:20_000], payload[20_000:]])):
            response = client.post("/tasks", content=content, headers={"Content-Type": "application/json"})
            assert response.status_code == 413
        assert client.post("/tasks", content="{}", headers={"Content-Type": "text/plain"}).status_code == 415
        assert client.post("/tasks", content="{}", headers={"Content-Type": "application/json", "Content-Length": "invalid"}).status_code == 400
        assert client.get("/status").json()["retained_tasks"] == 0


@pytest.mark.parametrize("options", [{"capacity": 0}, {"capacity": True}, {"capacity": 1025}])
def test_invalid_registry_configuration_is_rejected(flood_result, options):
    with pytest.raises(ValueError):
        app_for(flood_result, **options)


@pytest.mark.parametrize("token", [None, "", " ", 7, "bad\r\nvalue", "☃", {"legacy": True}])
def test_worker_factory_accepts_unused_legacy_tokens(flood_result, token):
    with TestClient(app_for(flood_result, token=token)) as client:
        assert client.get("/status").status_code == 200
