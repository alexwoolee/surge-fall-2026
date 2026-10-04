"""Bounded HTTP dispatch from Control to independently running workers.

Control can dispatch Hydro and Flood sequentially or concurrently. No local
environmental processor is called. Concurrent HTTP calls alone do not prove
overlapping computation or execution on physically different computers.
"""

import asyncio
from collections.abc import Callable
from copy import deepcopy
from datetime import datetime, timezone
import json
import math
import time
from typing import Literal

import httpx
from pydantic import TypeAdapter, ValidationError

from backend.control.state import DispatchError, DispatchRecord, DispatchRun, StatusObservation
from backend.shared.contracts import (
    AnalysisTask, CombinedAnalysis, ExecutionHost, FloodResult, HydroResult, ProcessInstance, TaskStatus, WorkerStatus,
)
from backend.shared.settings import ControlSettings, WorkerEndpoint, validate_local_address
from backend.shared.status import TERMINAL_STATES, TaskState


_ANALYSIS = {"hydro-worker": "hydrometeorology", "flood-worker": "surface_water_and_terrain"}
_ORDER = {"task_received": 0, "acquiring_data": 1, "dataset_located": 2, "processing": 3, "preparing_result": 4,
          "complete": 5, "partial": 5, "failed": 5}
_ERRORS = {
    "worker_failed": "The worker reported processing failure; any validated component evidence is retained.",
    "transport_error": "Control could not complete communication with the worker.",
    "protocol_error": "The worker response did not satisfy the task, result or lifecycle contract.",
    "rejected": "The worker endpoint rejected the request.",
    "timed_out": "Control stopped waiting at its deadline; remote processing may still be running.",
}


def _now():
    return datetime.now(timezone.utc)


class _ProtocolError(Exception):
    pass


class _ResponseCode(Exception):
    def __init__(self, status_code):
        self.status_code = status_code


def _constant(value):
    raise ValueError("Nonfinite JSON value")


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key")
        result[key] = value
    return result


def _finite(value):
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("Nonfinite JSON value")
    if isinstance(value, dict):
        for child in value.values():
            _finite(child)
    elif isinstance(value, list):
        for child in value:
            _finite(child)


def _check_result(result, task, worker_id):
    if (result.task_id != task.task_id or result.worker_id != worker_id
            or result.analysis_type != task.analysis_type or result.bbox != task.bbox):
        raise _ProtocolError
    if isinstance(result, HydroResult):
        if (sorted(result.sources[0]["resources_used"]) != sorted(task.gpm_resources)
                or result.sources[1]["resources_used"] != [task.smap_resource]):
            raise _ProtocolError
    else:
        water = result.summary.surface_water
        if water is not None and (
            water.threshold_db != task.threshold_db
            or not task.start_time <= water.acquired_at <= task.end_time
        ):
            raise _ProtocolError


class WorkerClient:
    """One bounded dispatch with no implicit task resubmission or cancellation.

    A lost POST response leaves acceptance unknown. Retrying explicitly with the
    same task ID remains possible through the worker's idempotency contract;
    silently creating another task could duplicate expensive remote work.
    """

    def __init__(
        self, settings: WorkerEndpoint, *, request_timeout: float = 15.0,
        task_timeout: float = 600.0, poll_interval: float = 0.5,
        max_response_bytes: int = 8 * 1024 * 1024,
        local_address: str | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        if not isinstance(settings, WorkerEndpoint):
            raise ValueError("An explicit worker endpoint is required.")
        for value, minimum, maximum in ((request_timeout, 0.1, 120), (task_timeout, 0.1, 3600), (poll_interval, 0.01, 30)):
            if (isinstance(value, bool) or not isinstance(value, (float, int))
                    or not minimum <= value <= maximum or not math.isfinite(value)):
                raise ValueError("Dispatch time limits and poll interval must stay within the configured bounds.")
        if isinstance(max_response_bytes, bool) or not isinstance(max_response_bytes, int) or not 1024 <= max_response_bytes <= 32 * 1024 * 1024:
            raise ValueError("Response byte limit must be an integer between 1 KiB and 32 MiB.")
        self.settings = settings
        self.request_timeout = request_timeout
        self.task_timeout = task_timeout
        self.poll_interval = poll_interval
        self.max_response_bytes = max_response_bytes
        self.local_address = validate_local_address(local_address)
        self.transport = transport

    async def _json(self, client, method, path, deadline, *, body=None, expected=200):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError
        request_deadline = min(deadline, time.monotonic() + self.request_timeout)
        async with asyncio.timeout(min(self.request_timeout, remaining)):
            async with client.stream(method, path, json=body) as response:
                if response.status_code != expected:
                    raise _ResponseCode(response.status_code)
                content_type = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
                if content_type != "application/json" and not (
                    content_type.startswith("application/") and content_type.endswith("+json")
                ):
                    raise _ProtocolError
                declared = response.headers.get("content-length")
                if declared is not None:
                    try:
                        length = int(declared)
                    except ValueError:
                        raise _ProtocolError from None
                    if not 0 <= length <= self.max_response_bytes:
                        raise _ProtocolError
                raw = bytearray()
                async for chunk in response.aiter_bytes(chunk_size=64 * 1024):
                    if time.monotonic() >= request_deadline:
                        raise TimeoutError
                    if len(raw) + len(chunk) > self.max_response_bytes:
                        raise _ProtocolError
                    raw.extend(chunk)
                try:
                    value = json.loads(raw, parse_constant=_constant, object_pairs_hook=_object)
                    _finite(value)
                except (ValueError, UnicodeError, RecursionError):
                    raise _ProtocolError from None
                if time.monotonic() >= request_deadline:
                    raise TimeoutError
                return value

    async def run(self, task: AnalysisTask, *, on_progress: Callable[[dict], None] | None = None,
                  expected_process_instance_id: str | None = None,
                  expected_execution_host: str | None = None) -> DispatchRecord:
        if on_progress is not None and not callable(on_progress):
            raise ValueError("Progress persistence must be a callable.")
        for value, model in ((expected_process_instance_id, ProcessInstance), (expected_execution_host, ExecutionHost)):
            if value is not None:
                try:
                    TypeAdapter(model).validate_python(value)
                except ValidationError:
                    raise ValueError("Expected worker identity must satisfy its contract.") from None
        task = AnalysisTask.model_validate(task.model_dump(mode="json"))
        worker_id = self.settings.expected_worker_id
        if task.analysis_type != _ANALYSIS[worker_id]:
            raise ValueError("Task analysis type does not match the configured worker.")
        record = {
            "task_id": task.task_id, "worker_id": worker_id, "analysis_type": task.analysis_type,
            "control_started_at": _now(), "submitted_at": None,
            "accepted": False, "acceptance_unknown": False,
            "worker_status": None, "task_status": None, "observations": [], "result": None,
        }
        identity = {"execution_host": expected_execution_host,
                    "process_instance_id": expected_process_instance_id}

        def emit(stage, *, status=None, finished=None):
            if on_progress is not None:
                snapshot = {"worker": "hydro" if worker_id == "hydro-worker" else "flood",
                            "stage": stage,
                            "status": None if status is None else status.model_dump(mode="json"),
                            "record": None if finished is None else finished.model_dump(mode="json")}
                try:
                    on_progress(deepcopy(snapshot))
                except Exception:
                    # A failed persistence callback must stop dispatch, not be
                    # misclassified as a worker/protocol failure and continued.
                    raise RuntimeError("Control could not persist worker progress.") from None

        def check_identity(status):
            if status.worker_id != worker_id or status.analysis_type != task.analysis_type:
                raise _ProtocolError
            for key, known in identity.items():
                current = getattr(status, key, None)
                if known is not None and current != known:
                    raise _ProtocolError
                if current is not None:
                    identity[key] = current

        def observe(raw):
            status = TaskStatus.model_validate(raw)
            check_identity(status)
            if status.task_id != task.task_id:
                raise _ProtocolError
            previous = record["task_status"]
            if previous is not None:
                if (status.received_at != previous.received_at
                        or _ORDER[status.state.value] < _ORDER[previous.state.value]
                        or (previous.started_at is not None and status.started_at != previous.started_at)
                        or (previous.completed_at is not None and status.completed_at != previous.completed_at)
                        or (previous.state in TERMINAL_STATES and status.state != previous.state)):
                    raise _ProtocolError
            # Worker exception text is not a safe diagnostic channel. Preserve
            # the reported failure state, but retain only a fixed error message.
            if status.error is not None:
                status = status.model_copy(update={"error": "The worker reported processing failure."})
            if previous != status:
                record["observations"].append(StatusObservation(observed_at=_now(), status=status))
                emit("polling", status=status)
            record["task_status"] = status
            return status

        deadline = time.monotonic() + self.task_timeout
        stage = "preflight"
        outcome = "protocol_error"
        headers = {"Accept": "application/json"}
        emit("preflight")
        try:
            async with asyncio.timeout(self.task_timeout):
                transport = self.transport
                if transport is None:
                    transport = httpx.AsyncHTTPTransport(local_address=self.local_address, trust_env=False)
                async with httpx.AsyncClient(
                    base_url=self.settings.url, headers=headers, transport=transport,
                    timeout=httpx.Timeout(self.request_timeout), follow_redirects=False, trust_env=False,
                ) as client:
                    worker = WorkerStatus.model_validate(await self._json(client, "GET", "/status", deadline))
                    check_identity(worker)
                    record["worker_status"] = worker
                    stage = "submission"
                    record["submitted_at"] = _now()
                    record["acceptance_unknown"] = True
                    emit("submission")
                    status = observe(await self._json(
                        client, "POST", "/tasks", deadline, body=task.model_dump(mode="json"), expected=202,
                    ))
                    record["accepted"], record["acceptance_unknown"] = True, False
                    stage = "polling"
                    while status.state not in TERMINAL_STATES:
                        await asyncio.sleep(min(self.poll_interval, max(0, deadline - time.monotonic())))
                        status = observe(await self._json(client, "GET", f"/tasks/{task.task_id}", deadline))
                    stage = "result"
                    emit("result", status=status)
                    try:
                        raw_result = await self._json(client, "GET", f"/tasks/{task.task_id}/result", deadline)
                    except _ResponseCode as exc:
                        if exc.status_code == 409 and status.state == TaskState.FAILED:
                            outcome = "worker_failed"
                        else:
                            raise
                    else:
                        model = HydroResult if worker_id == "hydro-worker" else FloodResult
                        result = model.model_validate(raw_result)
                        _check_result(result, task, worker_id)
                        if result.status != status.state.value:
                            raise _ProtocolError
                        # Recheck the terminal task after reading the result. A
                        # restart between those requests must not attach new
                        # evidence to the previous process's execution times.
                        observe(await self._json(client, "GET", f"/tasks/{task.task_id}", deadline))
                        if time.monotonic() >= deadline:
                            raise TimeoutError
                        record["result"] = result
                        outcome = "worker_failed" if result.status == "failed" else result.status
        except (TimeoutError, httpx.TimeoutException):
            outcome = "timed_out"
        except httpx.RequestError:
            outcome = "transport_error"
        except _ResponseCode as exc:
            if stage in {"preflight", "submission"} and exc.status_code >= 400:
                outcome = "rejected"
                if stage == "submission" and exc.status_code < 500:
                    record["acceptance_unknown"] = False
            else:
                outcome = "protocol_error"
        except (ValidationError, _ProtocolError, TypeError, ValueError, KeyError, OverflowError):
            outcome = "protocol_error"
        record["control_completed_at"] = _now()
        record["outcome"] = outcome
        record["error"] = None if outcome in {"complete", "partial"} else DispatchError(code=outcome, message=_ERRORS[outcome])
        finished = DispatchRecord.model_validate(record)
        emit("finished", status=finished.task_status, finished=finished)
        return finished


async def run_analysis(
    hydro_task: AnalysisTask, flood_task: AnalysisTask, settings: ControlSettings,
    *, execution_mode: Literal["sequential", "parallel"] = "sequential",
    transport_factory: Callable[[WorkerEndpoint], httpx.AsyncBaseTransport] | None = None,
    on_progress: Callable[[dict], None] | None = None,
) -> DispatchRun:
    """Collect both workers in the requested mode, retaining independent results.

    Each client converts expected failures and timeouts into its own record, so
    one unsuccessful branch does not cancel or erase the other branch's work.
    Sequential remains the default for callers reproducing Phase 5 evidence.
    """
    if not isinstance(execution_mode, str) or execution_mode not in ("sequential", "parallel"):
        raise ValueError("Execution mode must be 'sequential' or 'parallel'.")
    if on_progress is not None and not callable(on_progress):
        raise ValueError("Progress persistence must be a callable.")
    hydro_task = AnalysisTask.model_validate(hydro_task.model_dump(mode="json"))
    flood_task = AnalysisTask.model_validate(flood_task.model_dump(mode="json"))
    if (hydro_task.analysis_type != "hydrometeorology" or flood_task.analysis_type != "surface_water_and_terrain"
            or hydro_task.task_id != flood_task.task_id or hydro_task.bbox != flood_task.bbox):
        raise ValueError("Hydro and Flood tasks must share an investigation ID and AOI with their correct analysis types.")
    started = _now()

    async def dispatch(task, endpoint):
        client = WorkerClient(
            endpoint, request_timeout=settings.request_timeout, task_timeout=settings.task_timeout,
            poll_interval=settings.poll_interval, max_response_bytes=settings.max_response_bytes,
            local_address=settings.local_address,
            transport=transport_factory(endpoint) if transport_factory is not None else None,
        )
        return await client.run(task, **({"on_progress": on_progress} if on_progress is not None else {}))

    if execution_mode == "parallel":
        pending = [asyncio.create_task(dispatch(hydro_task, settings.hydro)),
                   asyncio.create_task(dispatch(flood_task, settings.flood))]
        try:
            hydro, flood = await asyncio.gather(*pending)
        except BaseException:
            # Persistence/caller cancellation stops local collection. Remote
            # tasks are not cancelled or silently resubmitted; retain their IDs.
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
            raise
    else:
        hydro = await dispatch(hydro_task, settings.hydro)
        flood = await dispatch(flood_task, settings.flood)
    records = (hydro, flood)
    errors = [f"{record.worker_id}: {record.error.message}" for record in records if record.error is not None]
    errors.extend(f"{record.worker_id}: Partial evidence was returned." for record in records if record.outcome == "partial")
    combined = CombinedAnalysis(task_id=hydro_task.task_id, hydro=hydro.result, flood=flood.result, errors=errors)
    return DispatchRun(
        task_id=hydro_task.task_id, execution_mode=execution_mode,
        control_started_at=started, control_completed_at=_now(),
        hydro=hydro, flood=flood, combined=combined,
    )
