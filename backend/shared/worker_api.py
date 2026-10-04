"""Bounded, in-memory HTTP lifecycle for the deterministic worker processes.

One accepted task executes at a time in a dedicated thread. The event loop can
serve status requests while raster/HDF5 processing runs. Completed tasks remain
available until process restart; capacity exhaustion rejects new work rather
than silently discarding evidence. Run each app with one Uvicorn process.
"""

import asyncio
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from copy import deepcopy
from datetime import datetime, timezone
import json
import math
import re
import socket
from threading import Lock
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from backend.shared.contracts import (
    AnalysisTask, FloodResult, HydroResult, TaskStatus, WorkerClock, WorkerStatus,
)
from backend.shared.dam_contracts import DamTask, DamResult
from backend.shared.context_contracts import ContextTask, ContextResult
from backend.shared.status import TaskState
from backend.shared.worker_dashboard import (
    DASHBOARD_ASSETS, MAX_DASHBOARD_EVENTS, PUBLIC_GET_PATHS, dashboard_asset,
    dashboard_event, dashboard_headers, dashboard_snapshot,
)


MAX_REQUEST_BYTES = 64 * 1024
_FAILURE_MESSAGE = "Worker processing failed; no validated result is available."
_PROGRESS_ORDER = {"task_received": 0, "acquiring_data": 1, "dataset_located": 2, "processing": 3, "preparing_result": 4}
_PAIRS = {"hydro-worker": "hydrometeorology", "flood-worker": "surface_water_and_terrain", "dam-worker": "dam_risk"}
_SAFE_LOCATIONS = {
    "body", "query", "path", "task_id", "analysis_type", "bbox", "west", "south", "east", "north",
    "gpm_resources", "smap_resource", "start_time", "end_time", "reference_time", "threshold_db",
    "site_id", "window", "as_of", "investigation", "location_id",
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _reject_constant(value):
    raise ValueError("JSON numbers must be finite")


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("JSON object keys must be unique")
        result[key] = value
    return result


def _finite_json(value):
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("JSON numbers must be finite")
    if isinstance(value, dict):
        for item in value.values():
            _finite_json(item)
    elif isinstance(value, list):
        for item in value:
            _finite_json(item)


class _RequestGuard:
    """Bound JSON requests without interpreting legacy internal credentials."""

    def __init__(self, app, *, token=None, public_get_paths=()):
        # Keep these keyword arguments compatible with existing app factories.
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        headers = {key.lower(): value for key, value in scope["headers"]}
        if scope["method"] != "POST":
            return await self.app(scope, receive, send)
        try:
            declared = int(headers.get(b"content-length", b"0"))
            if declared < 0:
                raise ValueError
        except ValueError:
            response = JSONResponse({"detail": "Invalid content length."}, status_code=400)
            return await response(scope, receive, send)
        if declared > MAX_REQUEST_BYTES:
            response = JSONResponse({"detail": "Request body is too large."}, status_code=413)
            return await response(scope, receive, send)
        content_type = headers.get(b"content-type", b"").split(b";", 1)[0].strip().lower()
        if content_type != b"application/json" and not (
            content_type.startswith(b"application/") and content_type.endswith(b"+json")
        ):
            response = JSONResponse({"detail": "A JSON request body is required."}, status_code=415)
            return await response(scope, receive, send)
        body = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            body.extend(message.get("body", b""))
            if len(body) > MAX_REQUEST_BYTES:
                response = JSONResponse({"detail": "Request body is too large."}, status_code=413)
                return await response(scope, receive, send)
            if not message.get("more_body", False):
                break
        try:
            value = json.loads(body, parse_constant=_reject_constant, object_pairs_hook=_unique_object)
            _finite_json(value)
        except (ValueError, UnicodeError, RecursionError):
            response = JSONResponse({"detail": "Request body must contain valid, finite JSON."}, status_code=422)
            return await response(scope, receive, send)

        consumed = False

        async def replay():
            nonlocal consumed
            if not consumed:
                consumed = True
                return {"type": "http.request", "body": bytes(body), "more_body": False}
            return await receive()

        return await self.app(scope, replay, send)


@dataclass
class _Record:
    fingerprint: str
    task: AnalysisTask | DamTask | ContextTask
    status: TaskStatus
    result: HydroResult | FloodResult | DamResult | ContextResult | None = None
    events: list[dict] = field(default_factory=list)


def create_worker_app(
    worker_id: str,
    analysis_type: str,
    runner: Callable[[AnalysisTask | DamTask | ContextTask, Callable[[str], None]], dict[str, Any]],
    *,
    token: str | None = None,
    capacity: int = 128,
) -> FastAPI:
    """Create an app for one approved worker; the runner owns data discovery.

    HTTP tasks cannot supply arbitrary paths or URLs. Their resource identifiers
    are validated by AnalysisTask and resolved against configured roots by the
    production runners. This registry is process-local, non-durable, and has no
    cancellation endpoint. Shutdown waits for accepted work to finish.
    """
    if _PAIRS.get(worker_id) != analysis_type or not callable(runner):
        raise ValueError("A supported worker, analysis type and callable runner are required.")
    if isinstance(capacity, bool) or not isinstance(capacity, int) or not 1 <= capacity <= 1024:
        raise ValueError("Task capacity must be an integer from 1 to 1024.")
    traditional_result_type = HydroResult if worker_id == "hydro-worker" else FloodResult
    task_type = DamTask if worker_id == "dam-worker" else AnalysisTask | ContextTask
    response_result_type = DamResult if worker_id == "dam-worker" else traditional_result_type | ContextResult
    lock = Lock()
    records: dict[str, _Record] = {}
    executor: ThreadPoolExecutor | None = None
    active_task_id: str | None = None
    accepting = False
    execution_host: str | None = None
    process_instance_id: str | None = None

    def record_event(record, state, observed_at):
        # Called only while holding the lifecycle lock. Legal progress is
        # monotonic, so each genuine lifecycle state is recorded at most once.
        if not record.events or record.events[-1]["state"] != state:
            record.events.append(dashboard_event(state, observed_at))
            del record.events[:-MAX_DASHBOARD_EVENTS]

    def run_task(record: _Record):
        nonlocal active_task_id
        with lock:
            record.status = record.status.model_copy(update={"started_at": _now()})

        def progress(state):
            state = TaskState(state).value
            if state not in _PROGRESS_ORDER or state == "task_received":
                raise ValueError("Unsupported processing progress state.")
            with lock:
                current = record.status.state.value
                if current not in _PROGRESS_ORDER or _PROGRESS_ORDER[state] < _PROGRESS_ORDER[current]:
                    raise ValueError("Processing progress cannot move backwards.")
                record.status = record.status.model_copy(update={"state": TaskState(state)})
                record_event(record, state, _now())

        try:
            raw = runner(record.task.model_copy(deep=True), progress)
            progress("preparing_result")
            # A strict JSON round trip detaches all producer-owned containers and
            # rejects NaN/infinity or objects that could not cross the boundary.
            raw = json.loads(json.dumps(raw, allow_nan=False))
            result_type = (DamResult if isinstance(record.task, DamTask) else ContextResult
                           if isinstance(record.task, ContextTask) else traditional_result_type)
            result = result_type.model_validate(raw)
            if (result.task_id != record.task.task_id or result.worker_id != worker_id
                    or result.analysis_type != analysis_type):
                raise ValueError("Worker result does not match its accepted task.")
            if isinstance(result, DamResult):
                if (result.window != record.task.window or result.as_of != record.task.as_of
                        or result.site.id != record.task.site_id):
                    raise ValueError("Result does not match its accepted date and site.")
            elif result.bbox != record.task.bbox:
                raise ValueError("Result does not match its accepted area.")
            if isinstance(result, ContextResult):
                if any(getattr(result, key) != getattr(record.task, key) for key in ContextTask.model_fields):
                    raise ValueError("Context result does not match its accepted task.")
            if isinstance(result, FloodResult) and result.summary.surface_water is not None:
                water = result.summary.surface_water
                if (water.threshold_db != record.task.threshold_db
                        or not record.task.start_time <= water.acquired_at <= record.task.end_time):
                    raise ValueError("Surface-water result does not match the requested scene window or threshold.")
            if isinstance(result, HydroResult):
                if (sorted(result.sources[0]["resources_used"]) != sorted(record.task.gpm_resources)
                        or result.sources[1]["resources_used"] != [record.task.smap_resource]):
                    raise ValueError("Hydro result does not match the requested resource identifiers.")
            json.dumps(result.model_dump(mode="json"), allow_nan=False)
            with lock:
                record.result = result
                completed_at = _now()
                record.status = record.status.model_copy(update={
                    "state": TaskState(result.status), "completed_at": completed_at,
                })
                record_event(record, result.status, completed_at)
                active_task_id = None
        except Exception:
            with lock:
                completed_at = _now()
                record.status = record.status.model_copy(update={
                    "state": TaskState("failed"), "completed_at": completed_at, "error": _FAILURE_MESSAGE,
                })
                record_event(record, "failed", completed_at)
                active_task_id = None

    @asynccontextmanager
    async def lifespan(app):
        nonlocal executor, accepting, execution_host, process_instance_id
        with lock:
            # Identity is observed at startup, never supplied by an HTTP request
            # or an environment override. Hostnames alone are not proof of
            # separate physical machines.
            execution_host = re.sub(r"[^A-Za-z0-9_.-]", "_", socket.gethostname())[:253] or None
            process_instance_id = str(uuid4())
            executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix=worker_id)
            accepting = True
        try:
            yield
        finally:
            with lock:
                accepting = False
                pool = executor
            # Waiting on the event loop would prevent in-flight status requests.
            await asyncio.to_thread(pool.shutdown, wait=True, cancel_futures=False)
            with lock:
                executor = None

    app = FastAPI(title=f"Amalga {worker_id}", version="1.0", lifespan=lifespan)
    app.add_middleware(_RequestGuard, token=token, public_get_paths=PUBLIC_GET_PATHS)

    def require_dashboard_query(request):
        if request.url.query:
            raise HTTPException(status_code=400, detail="Dashboard query selectors are not supported.",
                                headers=dashboard_headers())

    async def dashboard_static(request: Request):
        require_dashboard_query(request)
        return dashboard_asset(request.url.path)

    for path in DASHBOARD_ASSETS:
        app.add_api_route(path, dashboard_static, methods=["GET"], include_in_schema=False)

    @app.get("/dashboard/state", include_in_schema=False)
    async def dashboard_state(request: Request):
        require_dashboard_query(request)
        with lock:
            latest = records[next(reversed(records))] if records else None
            status = latest.status.model_copy(deep=True) if latest else None
            events = deepcopy(latest.events) if latest else []
            result = latest.result.model_copy(deep=True) if latest and isinstance(latest.result, DamResult) else None
        return JSONResponse(dashboard_snapshot(worker_id, status, events, result=result), headers=dashboard_headers())

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request: Request, error: RequestValidationError):
        details = [{
            "loc": [entry if isinstance(entry, int) or entry in _SAFE_LOCATIONS else "field"
                    for entry in item["loc"]],
            "type": item["type"], "msg": "Invalid value.",
        } for item in error.errors()]
        return JSONResponse({"detail": details}, status_code=422)

    @app.post("/tasks", status_code=202, response_model=TaskStatus)
    async def submit_task(task: task_type):
        nonlocal active_task_id
        if task.analysis_type != analysis_type:
            raise HTTPException(status_code=422, detail="This worker does not support the requested analysis type.")
        fingerprint = json.dumps(task.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
        with lock:
            if task.task_id in records:
                record = records[task.task_id]
                if record.fingerprint != fingerprint:
                    raise HTTPException(status_code=409, detail="Task ID is already assigned to a different request.")
                return record.status.model_copy(deep=True)
            if not accepting or executor is None:
                raise HTTPException(status_code=503, detail="Worker is not accepting tasks.")
            if active_task_id is not None:
                raise HTTPException(status_code=429, detail="Worker is busy; retry after the active task finishes.")
            if len(records) >= capacity:
                raise HTTPException(status_code=503, detail="Worker task retention capacity is full.")
            status = TaskStatus(
                task_id=task.task_id, worker_id=worker_id, analysis_type=analysis_type,
                state=TaskState("task_received"), received_at=_now(),
                execution_host=execution_host, process_instance_id=process_instance_id,
            )
            record = _Record(fingerprint, task.model_copy(deep=True), status)
            record_event(record, "task_received", status.received_at)
            records[task.task_id] = record
            active_task_id = task.task_id
            try:
                executor.submit(run_task, record)
            except RuntimeError:
                del records[task.task_id]
                active_task_id = None
                raise HTTPException(status_code=503, detail="Worker is not accepting tasks.") from None
            return status

    @app.get("/status", response_model=WorkerStatus)
    async def worker_status():
        with lock:
            return WorkerStatus(
                worker_id=worker_id, analysis_type=analysis_type,
                status="busy" if active_task_id is not None else "idle",
                active_task_id=active_task_id, retained_tasks=len(records), capacity=capacity,
                execution_host=execution_host, process_instance_id=process_instance_id,
            )

    @app.get("/clock", response_model=WorkerClock)
    async def worker_clock():
        with lock:
            if execution_host is None or process_instance_id is None:
                raise HTTPException(status_code=503, detail="Worker clock is not ready.")
            return WorkerClock(
                execution_host=execution_host, process_instance_id=process_instance_id,
                worker_id=worker_id, analysis_type=analysis_type, sampled_at=_now(),
            )

    @app.get("/tasks/{task_id}", response_model=TaskStatus)
    async def task_status(task_id: str):
        with lock:
            if task_id not in records:
                raise HTTPException(status_code=404, detail="Task was not found.")
            return records[task_id].status.model_copy(deep=True)

    @app.get("/tasks/{task_id}/result", response_model=response_result_type)
    async def task_result(task_id: str):
        with lock:
            if task_id not in records:
                raise HTTPException(status_code=404, detail="Task was not found.")
            record = records[task_id]
            if record.result is None:
                detail = "Task failed; no validated result is available." if record.status.state.value == "failed" else "Result is not ready."
                raise HTTPException(status_code=409, detail=detail)
            return record.result.model_copy(deep=True)

    return app
