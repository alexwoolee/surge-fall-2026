"""Control communicates by HTTP and retains independently validated evidence."""

import asyncio
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
import time

import httpx
from pydantic import ValidationError
import pytest

from backend.control.coordinator import WorkerClient, run_analysis
from backend.control.state import DispatchRecord, DispatchRun
from backend.shared.contracts import AnalysisTask, FloodResult, HydroResult
from backend.shared.settings import ControlSettings, WorkerEndpoint
from test_contracts import flood_resources, flood_result, hydro_result
from test_worker_api import flood_task, hydro_task


BASE = datetime(2026, 1, 1, tzinfo=timezone.utc)
INSTANCE = "11111111-1111-1111-1111-111111111111"


def task_for(result):
    raw = hydro_task(result) if result["worker_id"] == "hydro-worker" else flood_task(result)
    raw["task_id"] = result["task_id"]
    return AnalysisTask.model_validate(raw)


def worker_status(result, **updates):
    return {
        "worker_id": result["worker_id"], "analysis_type": result["analysis_type"],
        "status": "idle", "active_task_id": None, "retained_tasks": 0, "capacity": 128,
        "execution_host": result["worker_id"] + "-host", "process_instance_id": INSTANCE, **updates,
    }


def status(result, state="task_received", **updates):
    return {
        "task_id": result["task_id"], "worker_id": result["worker_id"],
        "analysis_type": result["analysis_type"], "state": state,
        "received_at": BASE.isoformat(),
        "started_at": None if state == "task_received" else (BASE + timedelta(seconds=1)).isoformat(),
        "completed_at": (BASE + timedelta(seconds=2)).isoformat() if state in {"complete", "partial", "failed"} else None,
        "error": None, "execution_host": result["worker_id"] + "-host", "process_instance_id": INSTANCE,
        **updates,
    }


class ScriptedWorker:
    """HTTP transport fixture: deliberately has no local processor fallback."""

    def __init__(self, result, *, statuses=None, override=None, calls=None):
        self.result = deepcopy(result)
        self.statuses = statuses or [status(result), status(result, "processing"), status(result, result["status"])]
        self.index = 0
        self.override = override
        self.calls = calls if calls is not None else []

    async def handle(self, request):
        self.calls.append((request.method, request.url.path, request))
        if self.override is not None:
            response = self.override(request)
            if asyncio.iscoroutine(response):
                response = await response
            if response is not None:
                return response
        if request.url.path == "/status":
            return httpx.Response(200, json=worker_status(self.result))
        if request.method == "POST":
            return httpx.Response(202, json=self.next_status())
        if request.url.path.endswith("/result"):
            return httpx.Response(200, json=self.result)
        return httpx.Response(200, json=self.next_status())

    def next_status(self):
        value = self.statuses[min(self.index, len(self.statuses) - 1)]
        self.index += 1
        return value

    def client(self, **kwargs):
        return WorkerClient(
            WorkerEndpoint("http://worker.invalid:8002", self.result["worker_id"], token="configured-token"),
            poll_interval=0.01, transport=httpx.MockTransport(self.handle), **kwargs,
        )


@pytest.mark.parametrize("kind", ["hydro", "flood"])
def test_http_lifecycle_preserves_typed_evidence_and_separate_control_times(kind, hydro_result, flood_result):
    result = hydro_result if kind == "hydro" else flood_result
    worker = ScriptedWorker(result)
    record = asyncio.run(worker.client().run(task_for(result)))
    assert record.outcome == "complete" and record.accepted and not record.acceptance_unknown
    assert record.error is None and record.result.task_id == result["task_id"]
    assert [observation.status.state.value for observation in record.observations] == ["task_received", "processing", "complete"]
    assert record.task_status.received_at == BASE
    assert record.control_started_at <= record.submitted_at <= record.control_completed_at
    assert all(observation.observed_at >= record.control_started_at for observation in record.observations)
    assert DispatchRecord.model_validate_json(record.model_dump_json()) == record
    for method, path, request in worker.calls:
        assert request.headers["authorization"] == "Bearer configured-token"
        if method == "POST":
            assert json.loads(request.content)["task_id"] == result["task_id"]
    assert "configured-token" not in record.model_dump_json()


def test_legacy_missing_machine_identity_is_preserved_without_claiming_proof(hydro_result):
    statuses = [status(hydro_result, "complete", execution_host=None, process_instance_id=None)]

    def override(request):
        if request.url.path == "/status":
            return httpx.Response(200, json=worker_status(hydro_result, execution_host=None, process_instance_id=None))

    worker = ScriptedWorker(hydro_result, statuses=statuses, override=override)
    record = asyncio.run(worker.client().run(task_for(hydro_result)))
    assert record.outcome == "complete"
    assert record.task_status.execution_host is None


@pytest.mark.parametrize("fault", ["worker", "task_id", "regression", "received_time", "start_time", "start_removed", "host", "instance", "identity_removed"])
def test_inconsistent_status_or_restarted_worker_is_rejected(hydro_result, fault):
    values = [status(hydro_result), status(hydro_result, "processing"), status(hydro_result, "complete")]
    if fault == "worker":
        values[0].update(worker_id="flood-worker", analysis_type="surface_water_and_terrain")
    elif fault == "task_id":
        values[0]["task_id"] = "another-task"
    elif fault == "regression":
        values[2] = status(hydro_result, "dataset_located")
    elif fault == "received_time":
        values[2]["received_at"] = (BASE + timedelta(microseconds=1)).isoformat()
    elif fault == "start_time":
        values[2]["started_at"] = (BASE + timedelta(seconds=1.5)).isoformat()
    elif fault == "start_removed":
        values[2] = status(hydro_result, "failed", started_at=None)
    elif fault == "host":
        values[2]["execution_host"] = "another-host"
    elif fault == "instance":
        values[2]["process_instance_id"] = "22222222-2222-2222-2222-222222222222"
    else:
        values[2]["process_instance_id"] = None
    record = asyncio.run(ScriptedWorker(hydro_result, statuses=values).client().run(task_for(hydro_result)))
    assert record.outcome == "protocol_error" and record.result is None


def test_wrong_worker_preflight_prevents_task_submission(hydro_result):
    def override(request):
        return httpx.Response(200, json=worker_status(hydro_result, worker_id="flood-worker", analysis_type="surface_water_and_terrain"))
    worker = ScriptedWorker(hydro_result, override=override)
    record = asyncio.run(worker.client().run(task_for(hydro_result)))
    assert record.outcome == "protocol_error"
    assert record.submitted_at is None and not record.accepted and not record.acceptance_unknown
    assert [method for method, _, _ in worker.calls] == ["GET"]


@pytest.mark.parametrize("code", [401, 409, 422, 429, 503])
def test_explicit_submission_rejection_is_bounded_and_does_not_echo_remote_body(hydro_result, code):
    def override(request):
        if request.method == "POST":
            return httpx.Response(code, text="private-server-token")
    worker = ScriptedWorker(hydro_result, override=override)
    record = asyncio.run(worker.client().run(task_for(hydro_result)))
    assert record.outcome == "rejected" and not record.accepted
    assert record.acceptance_unknown == (code >= 500)
    assert "private-server-token" not in record.model_dump_json()
    assert sum(method == "POST" for method, _, _ in worker.calls) == 1


@pytest.mark.parametrize("stage", ["preflight", "submission", "polling"])
def test_network_failure_tracks_ambiguous_acceptance_without_resubmission(hydro_result, stage):
    def override(request):
        failing = ((stage == "preflight" and request.url.path == "/status")
                   or (stage == "submission" and request.method == "POST")
                   or (stage == "polling" and request.url.path.startswith("/tasks/") and request.method == "GET"))
        if failing:
            raise httpx.ConnectError("private-password", request=request)
    worker = ScriptedWorker(hydro_result, override=override)
    record = asyncio.run(worker.client().run(task_for(hydro_result)))
    assert record.outcome == "transport_error"
    assert record.accepted == (stage == "polling")
    assert record.acceptance_unknown == (stage == "submission")
    assert sum(method == "POST" for method, _, _ in worker.calls) <= 1
    assert "private-password" not in record.model_dump_json()


def test_redirect_is_never_followed_or_given_worker_credentials(hydro_result):
    def override(request):
        return httpx.Response(307, headers={"Location": "https://untrusted.invalid/steal"})
    worker = ScriptedWorker(hydro_result, override=override)
    record = asyncio.run(worker.client().run(task_for(hydro_result)))
    assert record.outcome == "protocol_error" and len(worker.calls) == 1


def test_proxy_environment_is_not_used_for_worker_requests(hydro_result, monkeypatch):
    import backend.control.coordinator as module
    real_client = httpx.AsyncClient
    options = []

    def client(**kwargs):
        options.append(kwargs)
        return real_client(**kwargs)

    monkeypatch.setattr(module.httpx, "AsyncClient", client)
    record = asyncio.run(ScriptedWorker(hydro_result).client().run(task_for(hydro_result)))
    assert record.outcome == "complete"
    assert options[0]["trust_env"] is False and options[0]["follow_redirects"] is False


@pytest.mark.parametrize("component", ["gpm", "smap"])
def test_valid_hydro_envelope_for_different_resource_is_rejected(hydro_result, component):
    value = deepcopy(hydro_result)
    value["sources"][0 if component == "gpm" else 1]["resources_used"] = ["another.h5"]
    HydroResult.model_validate(value)
    record = asyncio.run(ScriptedWorker(value).client().run(task_for(hydro_result)))
    assert record.outcome == "protocol_error" and record.result is None


@pytest.mark.parametrize("fault", ["task_id", "aoi", "threshold", "date", "terminal_disagrees"])
def test_result_must_match_the_accepted_task_and_terminal_state(flood_result, fault):
    value = deepcopy(flood_result)
    if fault == "task_id":
        value["task_id"] = "another-task"
    elif fault == "aoi":
        value["bbox"]["west"] += 0.00001
        for evidence in value["evidence"].values():
            evidence["bbox"] = list(value["bbox"].values())
    elif fault == "threshold":
        value["summary"]["surface_water"]["threshold_db"] = -18
        value["evidence"]["sentinel1"]["method"]["threshold_db"] = -18
    elif fault == "date":
        value["summary"]["surface_water"]["acquired_at"] = "2020-01-01T00:00:00Z"
        value["evidence"]["sentinel1"]["scene"]["acquired_at"] = "2020-01-01T00:00:00Z"
    FloodResult.model_validate(value)
    statuses = [status(flood_result, "failed" if fault == "terminal_disagrees" else "complete")]
    worker = ScriptedWorker(value, statuses=statuses)
    record = asyncio.run(worker.client().run(task_for(flood_result)))
    assert record.outcome == "protocol_error" and record.result is None


def test_restart_between_terminal_status_and_result_fetch_is_rejected(hydro_result):
    values = [status(hydro_result, "complete"), status(
        hydro_result, "complete", process_instance_id="22222222-2222-2222-2222-222222222222",
    )]
    worker = ScriptedWorker(hydro_result, statuses=values)
    record = asyncio.run(worker.client().run(task_for(hydro_result)))
    assert any(path.endswith("/result") for _, path, _ in worker.calls)
    assert record.outcome == "protocol_error" and record.result is None


@pytest.mark.parametrize("failed", [{"dem"}, {"sentinel1", "dem", "hand"}])
def test_partial_and_structured_failed_results_are_retained(flood_result, failed):
    value = deepcopy(flood_result)
    names = {"sentinel1": "surface_water", "dem": "elevation", "hand": "hand"}
    for component in failed:
        value["evidence"].pop(component)
        value["coverage"].pop(component)
        value["summary"].pop(names[component])
    value["sources"] = [source for source in value["sources"] if source["component"] not in failed]
    value["errors"] = [{"component": component, "code": "processing_failed", "message": "Processing failed."} for component in sorted(failed)]
    value["status"] = "failed" if len(failed) == 3 else "partial"
    record = asyncio.run(ScriptedWorker(value).client().run(task_for(value)))
    assert record.outcome == ("worker_failed" if len(failed) == 3 else "partial")
    assert set(record.result.evidence) == set(names) - failed
    assert len(record.result.errors) == len(failed)


def test_worker_failure_without_result_sanitizes_task_error_and_keeps_status(hydro_result):
    def override(request):
        if request.url.path.endswith("/result"):
            return httpx.Response(409, json={"detail": "private-exception"})
    worker = ScriptedWorker(hydro_result, statuses=[status(hydro_result, "failed", error="private-exception")], override=override)
    record = asyncio.run(worker.client().run(task_for(hydro_result)))
    assert record.outcome == "worker_failed" and record.result is None
    assert record.task_status.state.value == "failed"
    assert "private-exception" not in record.model_dump_json()


class Chunks(httpx.AsyncByteStream):
    def __init__(self, chunks, delay=0):
        self.chunks, self.delay = chunks, delay
        self.closed = False

    async def __aiter__(self):
        for chunk in self.chunks:
            if self.delay:
                await asyncio.sleep(self.delay)
            yield chunk

    async def aclose(self):
        self.closed = True


@pytest.mark.parametrize("body", [b'{"x":NaN}', b'{"x":1e999}', b'{"x":1,"x":2}', b'not-json', b'[' * 2000 + b']' * 2000])
def test_invalid_json_never_becomes_a_valid_status(hydro_result, body):
    def override(request):
        return httpx.Response(200, content=body, headers={"Content-Type": "application/json"})
    record = asyncio.run(ScriptedWorker(hydro_result, override=override).client().run(task_for(hydro_result)))
    assert record.outcome == "protocol_error"


@pytest.mark.parametrize("declared", [None, "1000000", "-1", "invalid"])
def test_response_limits_check_declared_and_actual_streamed_size(hydro_result, declared):
    stream = Chunks([b" " * 700, b" " * 700])

    def override(request):
        headers = {"Content-Type": "application/json"}
        if declared is not None:
            headers["Content-Length"] = declared
        return httpx.Response(200, stream=stream, headers=headers)

    record = asyncio.run(ScriptedWorker(hydro_result, override=override).client(max_response_bytes=1024).run(task_for(hydro_result)))
    assert record.outcome == "protocol_error" and stream.closed


@pytest.mark.parametrize("timeout_kind", ["total", "request"])
def test_slow_trickle_cannot_extend_deadline_indefinitely(hydro_result, timeout_kind):
    stream = Chunks([b" "] * 100, delay=0.01)

    def override(request):
        if request.method == "POST":
            return httpx.Response(202, stream=stream, headers={"Content-Type": "application/json"})

    worker = ScriptedWorker(hydro_result, override=override)
    started = time.monotonic()
    options = {"task_timeout": 0.1, "request_timeout": 1} if timeout_kind == "total" else {"task_timeout": 2, "request_timeout": 0.1}
    record = asyncio.run(worker.client(**options).run(task_for(hydro_result)))
    assert time.monotonic() - started < 0.7
    assert record.outcome == "timed_out" and record.acceptance_unknown and not record.accepted
    assert stream.closed
    assert sum(method == "POST" for method, _, _ in worker.calls) == 1


def test_task_timeout_retains_last_real_state_and_never_sends_cancellation(hydro_result):
    worker = ScriptedWorker(hydro_result, statuses=[status(hydro_result, "processing")])
    record = asyncio.run(worker.client(task_timeout=0.1).run(task_for(hydro_result)))
    assert record.outcome == "timed_out" and record.accepted and not record.acceptance_unknown
    assert record.task_status.state.value == "processing" and record.task_status.completed_at is None
    assert len(record.observations) == 1
    assert all(method in {"GET", "POST"} and "cancel" not in path for method, path, _ in worker.calls)


@pytest.mark.parametrize("failed_role", ["hydro-worker", "flood-worker"])
def test_sequential_branches_retain_valid_completed_work_when_other_endpoint_fails(hydro_result, flood_result, failed_role):
    # Only the successful branch returns measurements. Both tasks share its real
    # fixture AOI; the other endpoint fails before accepting any computation.
    successful = flood_result if failed_role == "hydro-worker" else hydro_result
    bounds = successful["bbox"]
    hydro = AnalysisTask.model_validate({**task_for(hydro_result).model_dump(mode="json"), "bbox": bounds})
    flood = AnalysisTask.model_validate({**task_for(flood_result).model_dump(mode="json"), "bbox": bounds})
    settings = ControlSettings(WorkerEndpoint("http://hydro.invalid", "hydro-worker"),
                               WorkerEndpoint("http://flood.invalid", "flood-worker"), poll_interval=0.01)
    calls = []
    worker = ScriptedWorker(successful)

    async def handle_hydro(request):
        calls.append(("hydro-worker", request.url.path))
        if failed_role == "hydro-worker":
            raise httpx.ConnectError("unavailable", request=request)
        return await worker.handle(request)

    async def handle_flood(request):
        calls.append(("flood-worker", request.url.path))
        if failed_role == "flood-worker":
            raise httpx.ConnectError("unavailable", request=request)
        return await worker.handle(request)

    run = asyncio.run(run_analysis(hydro, flood, settings, transport_factory=lambda endpoint: httpx.MockTransport(
        handle_hydro if endpoint.expected_worker_id == "hydro-worker" else handle_flood,
    )))
    assert run.execution_mode == "sequential"
    assert run.hydro.control_completed_at <= run.flood.control_started_at
    assert calls[0][0] == "hydro-worker" and calls[-1][0] == "flood-worker"
    assert run.combined.errors
    if failed_role != "hydro-worker":
        assert run.hydro.outcome == "complete" and run.combined.hydro == run.hydro.result
    else:
        assert run.hydro.outcome == "transport_error" and run.combined.hydro is None
        assert run.flood.outcome == "complete" and run.combined.flood == run.flood.result
    assert DispatchRun.model_validate_json(run.model_dump_json()) == run


def test_both_unavailable_workers_return_collection_with_two_explicit_failures(hydro_result):
    hydro = task_for(hydro_result)
    flood = AnalysisTask.model_validate({
        "task_id": hydro.task_id, "analysis_type": "surface_water_and_terrain", "bbox": hydro.bbox.model_dump(),
        "start_time": "2021-11-13T00:00:00Z", "end_time": "2021-11-18T23:59:59Z",
    })
    settings = ControlSettings(WorkerEndpoint("http://hydro.invalid", "hydro-worker"), WorkerEndpoint("http://flood.invalid", "flood-worker"))

    async def unavailable(request):
        raise httpx.ConnectError("unavailable", request=request)

    run = asyncio.run(run_analysis(hydro, flood, settings, transport_factory=lambda endpoint: httpx.MockTransport(unavailable)))
    assert run.hydro.outcome == run.flood.outcome == "transport_error"
    assert run.combined.hydro is run.combined.flood is None
    assert len(run.combined.errors) == 2


def matching_tasks(hydro_result, flood_result, bounds):
    """Only successful fixture evidence uses its original bounds."""
    return tuple(AnalysisTask.model_validate({**task_for(result).model_dump(mode="json"), "bbox": bounds})
                 for result in (hydro_result, flood_result))


def test_parallel_calls_reach_a_shared_barrier_before_either_returns(hydro_result, flood_result):
    tasks = matching_tasks(hydro_result, flood_result, hydro_result["bbox"])
    settings = ControlSettings(WorkerEndpoint("http://hydro.invalid", "hydro-worker"),
                               WorkerEndpoint("http://flood.invalid", "flood-worker"), task_timeout=5)

    async def verify():
        arrived = set()
        both_started = asyncio.Event()

        async def unavailable(request):
            arrived.add(request.url.host)
            if len(arrived) == 2:
                both_started.set()
            await both_started.wait()
            raise httpx.ConnectError("Unavailable", request=request)

        run = await asyncio.wait_for(run_analysis(
            *tasks, settings, execution_mode="parallel",
            transport_factory=lambda endpoint: httpx.MockTransport(unavailable),
        ), timeout=2)
        assert arrived == {"hydro.invalid", "flood.invalid"}
        assert run.execution_mode == "parallel"
        assert run.hydro.outcome == run.flood.outcome == "transport_error"
        assert run.flood.control_started_at < run.hydro.control_completed_at
        assert DispatchRun.model_validate_json(run.model_dump_json()) == run
        return run

    run = asyncio.run(verify())
    sequential = run.model_dump(mode="json")
    sequential["execution_mode"] = "sequential"
    with pytest.raises(ValidationError, match="Sequential branch intervals"):
        DispatchRun.model_validate(sequential)


@pytest.mark.parametrize("successful_role", ["hydro-worker", "flood-worker"])
@pytest.mark.parametrize("fault", ["worker_failed", "transport_error", "protocol_error", "timed_out"])
@pytest.mark.parametrize("success_first", [True, False])
def test_parallel_preserves_complete_branch_in_either_completion_order(
    hydro_result, flood_result, monkeypatch, successful_role, fault, success_first,
):
    successful = hydro_result if successful_role == "hydro-worker" else flood_result
    failed = flood_result if successful_role == "hydro-worker" else hydro_result
    tasks = matching_tasks(hydro_result, flood_result, successful["bbox"])
    settings = ControlSettings(WorkerEndpoint("http://hydro.invalid", "hydro-worker"),
                               WorkerEndpoint("http://flood.invalid", "flood-worker"),
                               request_timeout=0.1, task_timeout=2, poll_interval=0.01)
    original_run = WorkerClient.run

    async def verify():
        arrived, completed = set(), {}
        both_started, first_completed, never_completed = asyncio.Event(), asyncio.Event(), asyncio.Event()
        first_role = successful_role if success_first else failed["worker_id"]

        async def observe_completion(client, task):
            record = await original_run(client, task)
            completed[client.settings.expected_worker_id] = record
            if client.settings.expected_worker_id == first_role:
                assert len(completed) == 1
                first_completed.set()
            return record

        monkeypatch.setattr(WorkerClient, "run", observe_completion)

        async def override(request, role):
            if request.url.path == "/status":
                arrived.add(role)
                if len(arrived) == 2:
                    both_started.set()
                await both_started.wait()
                if role != first_role:
                    await first_completed.wait()
                    assert completed[first_role].outcome == ("complete" if success_first else fault)
                if role != successful_role:
                    if fault == "transport_error":
                        raise httpx.ConnectError("Unavailable", request=request)
                    if fault == "protocol_error":
                        return httpx.Response(200, json={"invalid": "status"})
                    if fault == "timed_out":
                        if success_first:
                            # Exercise the real request deadline after retaining
                            # the other branch's complete record.
                            await never_completed.wait()
                        # A transport read timeout can arrive before the other
                        # request's own deadline; it must not cancel that work.
                        raise httpx.ReadTimeout("Worker read timed out", request=request)
            if role != successful_role and request.url.path.endswith("/result"):
                return httpx.Response(409, json={"detail": "Task failed"})

        async def successful_override(request):
            return await override(request, successful_role)

        async def failed_override(request):
            return await override(request, failed["worker_id"])

        workers = {
            successful_role: ScriptedWorker(successful, statuses=[status(successful, "complete")],
                                              override=successful_override),
            failed["worker_id"]: ScriptedWorker(failed, statuses=[status(failed, "failed")],
                                                 override=failed_override),
        }
        run = await asyncio.wait_for(run_analysis(
            *tasks, settings, execution_mode="parallel",
            transport_factory=lambda endpoint: httpx.MockTransport(workers[endpoint.expected_worker_id].handle),
        ), timeout=3)
        assert list(completed)[0] == first_role
        success = run.hydro if successful_role == "hydro-worker" else run.flood
        failure = run.flood if successful_role == "hydro-worker" else run.hydro
        assert success is completed[successful_role]
        assert success.outcome == "complete" and success.result.model_dump(mode="json") == successful
        assert failure.outcome == fault and failure.error.code == fault
        assert failure.result is None
        assert run.combined.hydro is run.hydro.result and run.combined.flood is run.flood.result
        assert len(run.combined.errors) == 1
        for worker in workers.values():
            assert sum(method == "POST" for method, _, _ in worker.calls) <= 1
            assert all(method in {"GET", "POST"} and "cancel" not in path for method, path, _ in worker.calls)
        assert DispatchRun.model_validate_json(run.model_dump_json()) == run

    asyncio.run(verify())


@pytest.mark.parametrize("mode", [None, True, 1, [], "concurrent", "Parallel"])
def test_invalid_execution_mode_is_rejected_before_transport_creation(hydro_result, flood_result, mode):
    tasks = matching_tasks(hydro_result, flood_result, hydro_result["bbox"])
    settings = ControlSettings(WorkerEndpoint("http://hydro.invalid", "hydro-worker"),
                               WorkerEndpoint("http://flood.invalid", "flood-worker"))

    def unexpected_transport(endpoint):
        pytest.fail("Invalid execution mode must be rejected before opening transports.")

    with pytest.raises(ValueError, match="Execution mode"):
        asyncio.run(run_analysis(*tasks, settings, execution_mode=mode, transport_factory=unexpected_transport))


@pytest.mark.parametrize("mode", ["sequential", "parallel"])
@pytest.mark.parametrize("role", ["hydro", "flood"])
@pytest.mark.parametrize("edge", ["start", "end"])
def test_dispatch_branch_intervals_must_fit_inside_run(hydro_result, flood_result, mode, role, edge):
    tasks = matching_tasks(hydro_result, flood_result, hydro_result["bbox"])
    settings = ControlSettings(WorkerEndpoint("http://hydro.invalid", "hydro-worker"),
                               WorkerEndpoint("http://flood.invalid", "flood-worker"))

    async def unavailable(request):
        raise httpx.ConnectError("Unavailable", request=request)

    run = asyncio.run(run_analysis(*tasks, settings, execution_mode=mode,
                                   transport_factory=lambda endpoint: httpx.MockTransport(unavailable)))
    value = run.model_dump(mode="json")
    if edge == "start":
        value[role]["control_started_at"] = (run.control_started_at - timedelta(seconds=1)).isoformat()
    else:
        value[role]["control_completed_at"] = (run.control_completed_at + timedelta(seconds=1)).isoformat()
    with pytest.raises(ValidationError, match="Each branch interval"):
        DispatchRun.model_validate(value)


def test_wrong_task_role_and_investigation_identity_are_rejected_before_http(hydro_result, flood_result):
    client = ScriptedWorker(hydro_result).client()
    with pytest.raises(ValueError, match="analysis type"):
        asyncio.run(client.run(task_for(flood_result)))
    settings = ControlSettings(WorkerEndpoint("http://hydro.invalid", "hydro-worker"), WorkerEndpoint("http://flood.invalid", "flood-worker"))
    with pytest.raises(ValueError, match="investigation ID and AOI"):
        asyncio.run(run_analysis(task_for(hydro_result), task_for(flood_result), settings))


@pytest.mark.parametrize("options", [
    {"request_timeout": float("inf")}, {"task_timeout": 3601}, {"poll_interval": 0},
    {"max_response_bytes": True}, {"max_response_bytes": 32 * 1024 * 1024 + 1},
])
def test_client_limits_remain_bounded_for_direct_callers(options):
    with pytest.raises(ValueError):
        WorkerClient(WorkerEndpoint("http://worker.invalid", "hydro-worker"), **options)


@pytest.mark.parametrize("fault", ["missing_result", "unacknowledged", "missing_submission", "wrong_observation", "wrong_worker"])
def test_persisted_dispatch_cannot_contradict_its_validated_evidence(hydro_result, fault):
    record = asyncio.run(ScriptedWorker(hydro_result).client().run(task_for(hydro_result)))
    value = record.model_dump(mode="json")
    if fault == "missing_result":
        value["result"] = None
    elif fault == "unacknowledged":
        value["accepted"] = False
    elif fault == "missing_submission":
        value["submitted_at"] = None
    elif fault == "wrong_observation":
        value["observations"][-1]["status"]["task_id"] = "another-task"
    else:
        value["worker_status"]["worker_id"] = "flood-worker"
        value["worker_status"]["analysis_type"] = "surface_water_and_terrain"
    with pytest.raises(ValidationError):
        DispatchRecord.model_validate(value)


@pytest.mark.parametrize('source', [None, '192.0.2.10'])
def test_default_transport_receives_explicit_source_and_disables_environment(hydro_result, monkeypatch, source):
    observed = []
    worker = ScriptedWorker(hydro_result)

    def transport(**options):
        observed.append(options)
        return httpx.MockTransport(worker.handle)

    monkeypatch.setattr(httpx, 'AsyncHTTPTransport', transport)
    client = WorkerClient(WorkerEndpoint('http://worker.invalid', 'hydro-worker'),
                          local_address=source, poll_interval=0.01)
    record = asyncio.run(client.run(task_for(hydro_result)))
    assert record.outcome == 'complete'
    assert observed == [{'local_address': source, 'trust_env': False}]


def test_explicit_source_preserves_injected_transport(hydro_result, monkeypatch):
    def unexpected_transport(**options):
        pytest.fail('An injected transport must not be replaced.')

    monkeypatch.setattr(httpx, 'AsyncHTTPTransport', unexpected_transport)
    record = asyncio.run(ScriptedWorker(hydro_result).client(local_address='192.0.2.10').run(task_for(hydro_result)))
    assert record.outcome == 'complete'
    with pytest.raises(ValueError, match='MESHMIND_CONTROL_SOURCE_IP'):
        ScriptedWorker(hydro_result).client(local_address='host.invalid')


def test_dispatch_forwards_control_source_to_both_workers(hydro_result, monkeypatch):
    import backend.control.coordinator as module
    hydro = task_for(hydro_result)
    flood = AnalysisTask.model_validate({
        'task_id': hydro.task_id, 'analysis_type': 'surface_water_and_terrain', 'bbox': hydro.bbox.model_dump(),
        'start_time': '2021-11-13T00:00:00Z', 'end_time': '2021-11-18T23:59:59Z',
    })
    settings = ControlSettings(WorkerEndpoint('http://hydro.invalid', 'hydro-worker'),
                               WorkerEndpoint('http://flood.invalid', 'flood-worker'), local_address='192.0.2.10')
    observed = []

    def client(endpoint, **options):
        observed.append((endpoint.expected_worker_id, options['local_address']))
        return WorkerClient(endpoint, **options)

    async def unavailable(request):
        raise httpx.ConnectError('Unavailable', request=request)

    monkeypatch.setattr(module, 'WorkerClient', client)
    run = asyncio.run(run_analysis(hydro, flood, settings,
                                   transport_factory=lambda endpoint: httpx.MockTransport(unavailable)))
    assert run.hydro.outcome == run.flood.outcome == 'transport_error'
    assert observed == [('hydro-worker', '192.0.2.10'), ('flood-worker', '192.0.2.10')]


def test_http_transport_actually_binds_configured_source_socket(hydro_result, monkeypatch):
    import socket
    bindings, peers = [], []
    original_bind = socket.socket.bind

    def observed_bind(sock, address):
        bindings.append(address)
        return original_bind(sock, address)

    async def verify():
        async def reject(reader, writer):
            await reader.readuntil(b'\r\n\r\n')
            peers.append(writer.get_extra_info('peername')[0])
            writer.write(b'HTTP/1.1 401 Unauthorized\r\nContent-Length: 0\r\nConnection: close\r\n\r\n')
            await writer.drain()
            writer.close()
            await writer.wait_closed()

        server = await asyncio.start_server(reject, '127.0.0.1', 0)
        port = server.sockets[0].getsockname()[1]
        monkeypatch.setattr(socket.socket, 'bind', observed_bind)
        async with server:
            client = WorkerClient(WorkerEndpoint(f'http://127.0.0.1:{port}', 'hydro-worker'),
                                  local_address='127.0.0.1', request_timeout=2, task_timeout=3)
            record = await client.run(task_for(hydro_result))
        assert record.outcome == 'rejected' and not record.accepted

    asyncio.run(verify())
    assert ('127.0.0.1', 0) in bindings
    assert peers == ['127.0.0.1']
