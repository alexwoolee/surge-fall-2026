"""Bounded Control API and a deliberately narrow public state projection."""

from contextlib import asynccontextmanager
from copy import deepcopy
from typing import Literal

from fastapi import FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, field_validator

from backend.control.briefing import build_briefing, render_briefing_html
from backend.control.agent import INVESTIGATION
from backend.control.sessions import ControlService, SessionError, canonical_id
from backend.shared.contracts import FloodResult, HydroResult, TaskStatus
from backend.shared.worker_api import _RequestGuard


_ROLES = ("hydro", "flood")
_NAMES = {"hydro": "Hydrometeorology Agent", "flood": "Surface Water and Terrain Agent"}
_RESOURCES = {"hydro": ["NASA GPM IMERG", "NASA SMAP L4"],
              "flood": ["Sentinel-1 radar", "Copernicus DEM", "HAND terrain"]}
_NOTICES = {
    "execute": "New execution uses the operator-configured historical case and workers. Measurements are returned by deterministic Python processors.",
    "review": "Review of retained evidence. This session does not dispatch workers or establish fresh remote execution.",
}
_OUTCOMES = {
    "complete": "Validated evidence returned.", "partial": "Partial evidence returned; missing components remain explicit.",
    "timed_out": "Control stopped waiting; remote processing may still be running.",
    "transport_error": "Communication did not complete; saved evidence remains available.",
    "rejected": "The worker request was rejected.", "protocol_error": "Worker evidence did not pass the required checks.",
    "worker_failed": "The worker reported a processing failure.",
}
_TASK_STATES = {
    "task_received": "The worker accepted the task.", "dataset_located": "The worker located input data.",
    "processing": "The worker is processing the configured data.",
    "preparing_result": "The worker is preparing its result.",
    "complete": "The worker reports completion; Control is checking the result.",
    "partial": "The worker reports partial evidence; Control is checking the result.",
    "failed": "The worker reported a processing failure.",
}


def _briefing(session):
    report = session.get("agent_report") or {}
    if not isinstance(report, dict):
        return None
    if (report.get("deterministic") is None or report.get("status") == "rejected"
            or report.get("case") != session["case"] or report.get("requests") != session["requests"]
            or report.get("mode") != session["mode"]
            or report.get("plan") != {"tool": "investigate_case", "arguments": {
                "case_id": session["case"]["case_id"], "investigation": INVESTIGATION}}):
        return None
    explanation = report.get("explanation") or {}
    if not isinstance(explanation, dict):
        return None
    context = explanation.get("context")
    if context is not None and not isinstance(context, dict):
        return None
    if context is not None and context.get("request_retained") and context.get("original_request") != session["prompt"]:
        return None
    try:
        return build_briefing(report)
    except (ValueError, TypeError, KeyError, OverflowError):
        return None


def _worker_state(service, session, role, briefing):
    record = service.branch_records(session).get(role)
    progress = session.get("progress", {}).get(role, {})
    raw_status = progress.get("status")
    try:
        observed = TaskStatus.model_validate(raw_status) if raw_status is not None else None
    except (ValueError, TypeError):
        observed = None
    result = record.result if record else None
    # A saved review may have no dispatch envelope. Its validated source result
    # is evidence of past computation, never a heartbeat for a current worker.
    if result is None and briefing is not None:
        raw = (session["agent_report"].get("deterministic") or {}).get("fusion", {}).get("source_results", {}).get(role)
        if raw is not None:
            try:
                result = (HydroResult if role == "hydro" else FloodResult).model_validate(raw)
            except (TypeError, ValueError):
                pass
    failed_envelope = result is not None and result.status == "failed"
    returned = result is not None and not failed_envelope
    stage = progress.get("stage")
    if (session["retrying"] and session["retry_requests"][-1]["worker"] == role
            and stage != "finished"):
        record = None  # The previous failed attempt is retained privately, not shown as current activity.
    availability = "unknown"
    summary = "No worker activity has been observed for this session."
    if failed_envelope:
        availability = "failed"
        summary = "A checked failure record contains no available measurements."
        if session["mode"] == "review":
            summary = "The retained worker record reports failure; no measurements are available."
    elif returned:
        availability = "complete"
        summary = _OUTCOMES["complete" if result.status == "complete" else "partial"]
        if session["mode"] == "review":
            summary = "Validated retained evidence is available; no new work was dispatched."
    elif record is not None:
        availability = "down" if record.outcome in {"transport_error", "timed_out"} else "failed"
        summary = _OUTCOMES.get(record.outcome, "Worker evidence is unavailable.")
    elif session["state"] == "interrupted":
        summary = "Control stopped observing this worker. Remote work may continue."
    elif observed is not None:
        availability = "failed" if observed.state.value == "failed" else "active"
        summary = _TASK_STATES[observed.state.value]
    elif stage in {"submission", "result"}:
        availability = "active"
        summary = "Submitting the configured task." if stage == "submission" else "Retrieving and checking returned evidence."
    elif stage == "preflight":
        summary = "Control is checking worker availability."
    elif session["mode"] == "review":
        summary = "Review mode does not contact this worker."
    steps = [
        {"id": "accepted", "label": "Task accepted", "state": "pending"},
        {"id": "processing", "label": "Processing", "state": "pending"},
        {"id": "returned", "label": "Evidence returned", "state": "pending"},
        {"id": "validated", "label": "Evidence checked", "state": "pending"},
    ]
    if returned:
        for step in steps:
            step["state"] = "complete"
    elif failed_envelope:
        steps[0]["state"] = "complete"
        steps[1]["state"] = "failed"
        steps[3]["state"] = "complete"
    elif observed is not None:
        steps[0]["state"] = "complete"
        if observed.state.value in {"dataset_located", "processing"}:
            steps[1]["state"] = "active"
        elif observed.state.value in {"preparing_result", "complete", "partial"}:
            steps[1]["state"] = "complete"
            steps[2]["state"] = "active"
        elif observed.state.value == "failed":
            steps[1]["state"] = "failed"
    if record is not None and not returned:
        for step in steps:
            if step["state"] == "active":
                step["state"] = "failed"
        if all(step["state"] == "pending" for step in steps):
            steps[0]["state"] = "failed"
    if session["state"] == "interrupted":
        for step in steps:
            if step["state"] == "active":
                step["state"] = "pending"
    return {
        "id": role, "name": _NAMES[role], "location": "Retained evidence" if session["mode"] == "review" else f"Configured {role.title()} worker",
        "status": availability, "steps": steps, "summary": summary,
        "resources": list(_RESOURCES[role]), "returned": returned, "validated": result is not None,
    }


def public_state(service, session):
    """Only fixed text, validated display evidence and user-owned context escape."""
    briefing = _briefing(session)
    report = session.get("agent_report") or {}
    workers = {role: _worker_state(service, session, role, briefing) for role in _ROLES}
    running = session["state"] in {"queued", "running"}
    returned = sum(worker["returned"] for worker in workers.values())
    failures = []
    if running:
        status = "running"
        if report.get("deterministic") is not None:
            phase, detail = "reviewing", "Preparing the explanation from checked evidence."
        elif report.get("dispatch_attempted") or session["progress"]:
            phase, detail = "processing", "Observing independent worker activity."
            if len(service.branch_records(session)) == 2:
                phase, detail = "validating", "Checking returned evidence and review prerequisites."
        else:
            phase, detail = "reviewing", "Interpreting the request against the configured case."
    elif session["state"] == "interrupted":
        status, phase = ("partial" if returned else "failed"), "complete"
        detail = "Control restarted or stopped before this session finished. Saved evidence is retained; remote work may continue."
        failures.append({"title": "Session interrupted", "detail": detail})
    elif briefing is not None:
        status, phase = ("partial" if briefing["partial"] else "briefing-ready"), "complete"
        if (report.get("deterministic") or {}).get("fusion", {}).get("status") == "unavailable":
            status = "failed"
        detail = "The briefing preserves checked observations, source coverage and scientific limitations."
        if report.get("status") == "degraded" or session.get("service_error"):
            detail = "Saved evidence remains available with a deterministic explanation."
    else:
        status, phase = ("checks-failed" if (report.get("error") or {}).get("code") == "invalid_evidence" else "failed"), "complete"
        detail = "The request could not produce a checked briefing. Retained worker results remain visible."
        if report.get("status") == "rejected":
            detail = "The request is outside the configured case or supported environmental review. No new worker execution was authorized."
        failures.append({"title": "Briefing unavailable", "detail": detail})
    control = "active" if running else "complete" if briefing is not None else "failed"
    if session["state"] == "queued":
        control = "unknown"
        detail = "The request is saved and awaiting interpretation."
    window = session["case"]["requested_window"]
    return {
        "id": session["id"], "title": session["case"]["name"], "createdAt": session["created_at"],
        "status": status, "description": detail, "prompt": session["prompt"], "phase": phase,
        "studyArea": session["case"]["name"], "requestedWindow": f"{window['start']} to {window['end']}",
        "actualCoverage": briefing["actualCoverage"] if briefing else "Source coverage has not yet been assembled into a checked briefing.",
        "control": control, "workers": workers,
        "activities": [{"id": "control", "name": "Control", "location": "Investigation coordinator",
                        "status": control, "events": [detail]}] + [
            {"id": role, "name": workers[role]["name"], "location": workers[role]["location"],
             "status": workers[role]["status"], "events": [workers[role]["summary"]]} for role in _ROLES
        ],
        "reviewConditions": deepcopy(briefing["reviewConditions"]) if briefing else [],
        "validationFailures": failures, "briefing": briefing, "isDemo": False,
        "executionMode": session["mode"], "executionNotice": _NOTICES[session["mode"]] + (
            " One bounded retry reuses the original task identifier and preserves the other worker's evidence; it does not establish new parallel overlap."
            if session["retry_requests"] else ""),
        "retryableWorkers": service.retryable(session), "retrying": session["retrying"],
    }


def worker_view(service, role):
    """A read-only, role-specific display of Control-observed execution.

The latest executed-mode request is selected even during interpretation. A
viewer never falls back to a retained-evidence review or invents a heartbeat.
"""
    candidates = [item for item in service.sessions.values() if item["mode"] == "execute"]
    if not candidates:
        return {"session": None, "worker": None, "observedAt": None, "events": []}
    session = max(candidates, key=lambda item: (item["created_at"], item["id"]))
    view = public_state(service, session)
    worker = view["workers"][role]
    if session["state"] not in {"queued", "running"} and worker["status"] == "active":
        worker["status"] = "unknown"
        worker["summary"] = "Control is no longer observing this task; the last observed events are retained below."
        for step in worker["steps"]:
            if step["state"] == "active":
                step["state"] = "pending"
    events = []
    for event in session.get("observed_events", {}).get(role, []):
        if event["stage"] == "finished":
            label = _OUTCOMES[event["outcome"]]
        elif event["stage"] == "preflight":
            label = "Control began checking worker availability."
        elif event["stage"] == "submission":
            label = "Control began submitting the configured task."
        elif event["stage"] == "result":
            label = "Control began retrieving the worker result."
        else:
            label = {
                "task_received": "Control observed that the worker accepted the task.",
                "dataset_located": "Control observed that input data was located.",
                "processing": "Control observed the worker processing data.",
                "preparing_result": "Control observed the worker preparing its result.",
                "complete": "Control observed a reported completion, before checking the result.",
                "partial": "Control observed a reported partial result, before checking the evidence.",
                "failed": "Control observed a reported processing failure.",
            }.get(event["task_state"], "Control observed the worker task.")
        events.append({"id": event["id"], "observedAt": event["observed_at"], "label": label})
    return {
        "session": {key: view[key] for key in ("id", "title", "createdAt", "executionNotice", "status")},
        "worker": worker,
        "observedAt": events[-1]["observedAt"] if events else None,
        "events": events,
    }


class _ControlAccessGuard(_RequestGuard):
    """Compatibility wrapper retaining request bounds without internal auth."""

    def __init__(self, app, *, token=None, viewer_tokens=None):
        super().__init__(app)


class SessionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    prompt: str
    requestId: str

    @field_validator("requestId")
    @classmethod
    def request_uuid(cls, value):
        return canonical_id(value)

    @field_validator("prompt")
    @classmethod
    def bounded_prompt(cls, value):
        if (not value.strip() or len(value.encode("utf-8")) > 4096
                or any(ord(char) < 32 and char not in "\n\t" for char in value)):
            raise ValueError("A bounded nonblank request is required.")
        return value


class RetryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    worker: Literal["hydro", "flood"]
    requestId: str

    @field_validator("requestId")
    @classmethod
    def request_uuid(cls, value):
        return canonical_id(value)


def create_app(*, service: ControlService, token=None, viewer_tokens=None):
    if not isinstance(service, ControlService):
        raise ValueError("An explicitly configured Control service is required.")

    @asynccontextmanager
    async def lifespan(app):
        await service.start()
        try:
            yield
        finally:
            await service.close()

    app = FastAPI(title="MeshMind Control", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(_ControlAccessGuard, token=token, viewer_tokens=viewer_tokens)
    app.state.control_service = service

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request, error):
        return JSONResponse({"detail": "Invalid bounded request."}, status_code=422)

    @app.exception_handler(SessionError)
    async def session_error(request, error):
        return JSONResponse({"detail": error.message}, status_code=error.status)

    @app.middleware("http")
    async def private_responses(request, call_next):
        try:
            response = await call_next(request)
        except (OSError, ValueError, RuntimeError):
            response = JSONResponse({"detail": "Control could not complete this request safely."}, status_code=503)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    @app.get("/config")
    async def config():
        return {"mode": service.mode, "case": service.case.public_context(),
                "canStart": not service.busy and len(service.sessions) < service.max_sessions,
                "notice": _NOTICES[service.mode]}

    @app.get("/viewer/{role}")
    async def viewer(role: Literal["hydro", "flood"]):
        return worker_view(service, role)

    @app.get("/sessions")
    async def sessions():
        values = sorted(service.sessions.values(), key=lambda item: item["created_at"], reverse=True)
        return {"sessions": [{key: view[key] for key in ("id", "title", "createdAt", "status", "description")}
                             for view in (public_state(service, item) for item in values)]}

    @app.post("/sessions", status_code=202)
    async def submit(body: SessionRequest):
        return {"id": await service.submit(body.prompt, body.requestId)}

    @app.get("/sessions/{identifier}")
    async def session(identifier: str):
        return public_state(service, service.get(identifier))

    @app.post("/sessions/{identifier}/retry", status_code=202)
    async def retry(identifier: str, body: RetryRequest):
        return {"id": await service.retry(identifier, body.worker, body.requestId)}

    @app.get("/sessions/{identifier}/briefing", response_class=HTMLResponse)
    async def briefing(identifier: str):
        session = service.get(identifier)
        if session["state"] != "finished":
            raise HTTPException(409, "The briefing is not ready.")
        view = _briefing(session)
        if view is None:
            raise HTTPException(409, "A checked briefing is not available.")
        return HTMLResponse(render_briefing_html(view), headers={
            "Content-Disposition": f'attachment; filename="meshmind-{session["id"]}.html"',
            "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'",
        })

    return app
