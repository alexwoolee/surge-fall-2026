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
from dataclasses import dataclass
from datetime import datetime, timezone
import hmac
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
    AnalysisTask, FloodResult, HydroResult, TaskStatus, WorkerStatus,
)
from backend.shared.status import TaskState
from backend.shared.settings import validate_token


MAX_REQUEST_BYTES = 64 * 1024
_FAILURE_MESSAGE = "Worker processing failed; no validated result is available."
_PROGRESS_ORDER = {"task_received": 0, "dataset_located": 1, "processing": 2, "preparing_result": 3}
_PAIRS = {"hydro-worker": "hydrometeorology", "flood-worker": "surface_water_and_terrain"}
_SAFE_LOCATIONS = {
    "body", "query", "path", "task_id", "analysis_type", "bbox", "west", "south", "east", "north",
    "gpm_resources", "smap_resource", "start_time", "end_time", "reference_time", "threshold_db",
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
    """Authenticate before reading bounded JSON; never echo untrusted inputs."""

    def __init__(self, app, *, token: str | None):
        self.app = app
        self.token = token.encode("utf-8") if token is not None else None

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        headers = {key.lower(): value for key, value in scope["headers"]}
        if self.token is not None:
            auth = headers.get(b"authorization", b"").split(b" ", 1)
            if (len(auth) != 2 or auth[0].lower() != b"bearer"
                    or not hmac.compare_digest(auth[1], self.token)):
                response = JSONResponse(
                    {"detail": "Authentication required."}, status_code=401,
                    headers={"WWW-Authenticate": "Bearer"},
                )
                return await response(scope, receive, send)
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
    task: AnalysisTask
    status: TaskStatus
    result: HydroResult | FloodResult | None = None


def create_worker_app(
    worker_id: str,
    analysis_type: str,
    runner: Callable[[AnalysisTask, Callable[[str], None]], dict[str, Any]],
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
    validate_token(token)
    result_type = HydroResult if worker_id == "hydro-worker" else FloodResult
    lock = Lock()
    records: dict[str, _Record] = {}
    executor: ThreadPoolExecutor | None = None
    active_task_id: str | None = None
    accepting = False
    execution_host: str | None = None
    process_instance_id: str | None = None

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

        try:
            raw = runner(record.task.model_copy(deep=True), progress)
            progress("preparing_result")
            # A strict JSON round trip detaches all producer-owned containers and
            # rejects NaN/infinity or objects that could not cross the boundary.
            raw = json.loads(json.dumps(raw, allow_nan=False))
            result = result_type.model_validate(raw)
            if (result.task_id != record.task.task_id or result.worker_id != worker_id
                    or result.analysis_type != analysis_type
                    or result.bbox.as_tuple() != record.task.bbox.as_tuple()):
                raise ValueError("Worker result does not match its accepted task.")
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
                record.status = record.status.model_copy(update={
                    "state": TaskState(result.status), "completed_at": _now(),
                })
                active_task_id = None
        except Exception:
            with lock:
                record.status = record.status.model_copy(update={
                    "state": TaskState("failed"), "completed_at": _now(), "error": _FAILURE_MESSAGE,
                })
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

    app = FastAPI(title=f"MeshMind {worker_id}", version="1.0", lifespan=lifespan)
    app.add_middleware(_RequestGuard, token=token)

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request: Request, error: RequestValidationError):
        details = [{
            "loc": [entry if isinstance(entry, int) or entry in _SAFE_LOCATIONS else "field"
                    for entry in item["loc"]],
            "type": item["type"], "msg": "Invalid value.",
        } for item in error.errors()]
        return JSONResponse({"detail": details}, status_code=422)

    @app.post("/tasks", status_code=202, response_model=TaskStatus)
    async def submit_task(task: AnalysisTask):
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

    @app.get("/tasks/{task_id}", response_model=TaskStatus)
    async def task_status(task_id: str):
        with lock:
            if task_id not in records:
                raise HTTPException(status_code=404, detail="Task was not found.")
            return records[task_id].status.model_copy(deep=True)

    @app.get("/tasks/{task_id}/result", response_model=result_type)
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
