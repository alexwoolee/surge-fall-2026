"""Durable, single-process Control sessions with bounded explicit recovery.

Raw worker and model evidence is private. The web projection is constructed in
web.py and never returns these records directly. Restart never resumes a job.
"""

import asyncio
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timezone
import json
from pathlib import Path
from uuid import UUID, uuid4

from backend.control.agent import ConfiguredCase, _validate_case, run_agent
from backend.control.agent_grounding import render_explanation
from backend.control.alerts import ReviewPolicy
from backend.control.coordinator import WorkerClient
from backend.control.fusion import TimeWindow
from backend.control.reporting import build_review_report, read_evidence, write_review_report
from backend.control.state import DispatchRecord, DispatchRun
from backend.shared.contracts import AnalysisTask, CombinedAnalysis, TaskStatus
from backend.shared.settings import ControlSettings, ROOT


_ROLES = ("hydro", "flood")
_RETRYABLE = {"transport_error", "timed_out", "rejected"}
_STAGES = {"preflight", "submission", "polling", "result", "finished"}


def _now():
    return datetime.now(timezone.utc).isoformat()


def canonical_id(value):
    if not isinstance(value, str) or len(value) != 36:
        raise ValueError("A UUID request identifier is required.")
    return str(UUID(value))


class SessionError(Exception):
    def __init__(self, status, message):
        self.status, self.message = status, message
        super().__init__(message)


class ControlService:
    """One active investigation and a bounded durable history, without a queue."""

    def __init__(self, case, policy, client, *, mode="review", evidence=None,
                 control_settings=None, history_dir=ROOT / "outputs/debug/control-web/history",
                 max_sessions=100, agent_runner=None, worker_factory=None):
        self.case = _validate_case(case)
        self.policy = ReviewPolicy.model_validate(policy.model_dump(mode="json"))
        if mode not in {"execute", "review"} or (mode == "review") != (evidence is not None):
            raise ValueError("Select explicit execution or retained-evidence review.")
        if mode == "execute" and not isinstance(control_settings, ControlSettings):
            raise ValueError("Execution requires explicit Control settings.")
        if client is None or not callable(getattr(client, "create", None)):
            raise ValueError("An explicitly configured model client is required.")
        if isinstance(max_sessions, bool) or not isinstance(max_sessions, int) or not 1 <= max_sessions <= 1000:
            raise ValueError("Session capacity must be from 1 to 1000.")
        self.mode, self.client = mode, client
        self.evidence, self.control_settings = deepcopy(evidence), control_settings
        # Fail startup before serving if the retained input is not the configured case.
        if mode == "review":
            checked = build_review_report(evidence, self.policy,
                                          requested_window=self.case.requested_window.model_dump(mode="json"))
            if checked["fusion"]["requests"] != [task.model_dump(mode="json") for task in (case.hydro, case.flood)]:
                raise ValueError("Retained evidence does not match the configured case.")
        self.history_dir = Path(history_dir).expanduser().resolve()
        self.max_sessions = max_sessions
        self.agent_runner = agent_runner or run_agent
        self.worker_factory = worker_factory or WorkerClient
        self.sessions = {}
        self._job = None
        self._lock = asyncio.Lock()
        self._started = False

    @property
    def busy(self):
        return self._job is not None and not self._job.done()

    def _save(self, session):
        session["updated_at"] = _now()
        path = self.history_dir / f"{session['id']}.json"
        # write_review_report uses a new 0600 temporary file and atomic replace.
        # No fallible operation follows the commit of a new idempotency record.
        write_review_report(path, session)

    async def start(self):
        if self._started:
            raise RuntimeError("A Control service may have only one active app lifespan.")
        self.history_dir.mkdir(parents=True, exist_ok=True)
        self.history_dir.chmod(0o700)
        loaded = {}
        for path in sorted(self.history_dir.glob("*.json")):
            # No path from a browser is ever used here, and aliases are not followed.
            if path.is_symlink():
                raise ValueError("Session history cannot contain symbolic links.")
            value, _ = read_evidence(path)
            try:
                identifier = canonical_id(value["id"])
                if path.name != identifier + ".json" or value["schema_version"] != 1:
                    raise ValueError
                canonical_id(value["request_id"])
                if value["state"] not in {"queued", "running", "finished", "interrupted"}:
                    raise ValueError
                if value["mode"] not in {"review", "execute"}:
                    raise ValueError
                self._case_for(value)
                ReviewPolicy.model_validate(value["policy"])
                if not isinstance(value["prompt"], str) or not 0 < len(value["prompt"].encode("utf-8")) <= 4096:
                    raise ValueError
                if not isinstance(value["progress"], dict) or not isinstance(value["retry_requests"], list):
                    raise ValueError
                if len(value["retry_requests"]) > 1:
                    raise ValueError
                for request in value["retry_requests"]:
                    canonical_id(request["request_id"])
                    if request["worker"] not in _ROLES:
                        raise ValueError
                if value["state"] in {"queued", "running"}:
                    value.update(state="interrupted", retrying=False, interruption=True)
                    self._save(value)
                loaded[identifier] = value
                if len(loaded) > self.max_sessions:
                    raise ValueError
            except (KeyError, TypeError, ValueError):
                raise ValueError("Session history is invalid or exceeds configured capacity.") from None
        if len({value["request_id"] for value in loaded.values()}) != len(loaded):
            raise ValueError("Session history contains duplicate request identifiers.")
        self.sessions = loaded
        self._started = True

    async def close(self):
        if self.busy:
            self._job.cancel()
            await asyncio.gather(self._job, return_exceptions=True)
        self._started = False

    def get(self, identifier):
        try:
            return self.sessions[canonical_id(identifier)]
        except (KeyError, ValueError):
            raise SessionError(404, "Session not found.") from None

    def _case_for(self, session):
        context = session["case"]
        case = _validate_case(ConfiguredCase(
            context["case_id"], context["name"],
            AnalysisTask.model_validate(session["requests"][0]),
            AnalysisTask.model_validate(session["requests"][1]),
            TimeWindow.model_validate(context["requested_window"]),
        ))
        if case.public_context() != context:
            raise ValueError("Saved session context does not match its requests.")
        return case

    def _launch(self, coroutine, name):
        self._job = asyncio.create_task(coroutine, name=name)
        # Retrieve any terminal persistence exception; do not emit private paths
        # or exception text through asyncio's unhandled-task logging.
        self._job.add_done_callback(lambda task: None if task.cancelled() else task.exception())

    def _progress(self, session, event):
        if not isinstance(event, dict) or event.get("worker") not in _ROLES or event.get("stage") not in _STAGES:
            raise RuntimeError("Invalid Control progress event.")
        role = event["worker"]
        status = None if event.get("status") is None else TaskStatus.model_validate(event["status"])
        record = None if event.get("record") is None else DispatchRecord.model_validate(event["record"])
        expected_task = session["requests"][0]["task_id"]
        for item in (status, record):
            if item is not None and (item.worker_id != role + "-worker" or item.task_id != expected_task):
                raise RuntimeError("Progress does not match the configured investigation.")
        session["progress"][role] = {
            "stage": event["stage"], "status": None if status is None else status.model_dump(mode="json"),
            "record": None if record is None else record.model_dump(mode="json"),
        }
        self._save(session)  # In particular, a submission event is durable before POST.

    async def submit(self, prompt, request_id):
        request_id = canonical_id(request_id)
        if (not isinstance(prompt, str) or not prompt.strip() or len(prompt.encode("utf-8")) > 4096
                or any(ord(char) < 32 and char not in "\n\t" for char in prompt)):
            raise SessionError(422, "Use a nonblank request of at most 4096 UTF-8 bytes.")
        async with self._lock:
            for session in self.sessions.values():
                if session["request_id"] == request_id:
                    if session["prompt"] != prompt:
                        raise SessionError(409, "This request identifier already belongs to a different request.")
                    return session["id"]
            if not self._started:
                raise SessionError(503, "Control is not ready.")
            if self.busy:
                raise SessionError(409, "An investigation is already running.")
            if len(self.sessions) >= self.max_sessions:
                raise SessionError(429, "Session history is at capacity; ask the operator to archive it.")
            identifier = str(uuid4())
            case = self.case if self.mode == "review" else replace(
                self.case, hydro=self.case.hydro.model_copy(update={"task_id": identifier}),
                flood=self.case.flood.model_copy(update={"task_id": identifier}),
            )
            session = {
                "schema_version": 1, "id": identifier, "request_id": request_id,
                "prompt": prompt, "created_at": _now(), "state": "queued", "mode": self.mode,
                "case": case.public_context(), "requests": [task.model_dump(mode="json") for task in (case.hydro, case.flood)],
                "policy": self.policy.model_dump(mode="json"), "agent_report": None, "progress": {},
                "retry_requests": [], "retrying": False, "interruption": False, "service_error": None,
            }
            self._save(session)
            self.sessions[identifier] = session
            self._launch(self._run(session, case), "control-session")
            return identifier

    async def _run(self, session, case):
        try:
            session["state"] = "running"
            self._save(session)

            def persist(report):
                session["agent_report"] = deepcopy(report)
                self._save(session)

            report = await self.agent_runner(
                session["prompt"], case, self.policy, self.client,
                execute=self.mode == "execute", evidence=deepcopy(self.evidence),
                control_settings=self.control_settings, include_request=True, persist=persist,
                on_progress=lambda event: self._progress(session, event),
            )
            session.update(agent_report=deepcopy(report), state="finished")
            self._save(session)
        except asyncio.CancelledError:
            session.update(state="interrupted", interruption=True, retrying=False)
            self._save(session)
            raise
        except Exception:
            # Raw exceptions can contain URLs, credentials or remote response bodies.
            session.update(state="finished", service_error="Investigation could not finish; saved evidence is retained.")
            self._save(session)

    def branch_records(self, session):
        values = {}
        report = session.get("agent_report") or {}
        evidence = report.get("worker_evidence") or {}
        dispatch = evidence.get("dispatch") or {}
        for role in _ROLES:
            raw = session.get("progress", {}).get(role, {}).get("record") or dispatch.get(role)
            if raw is not None:
                try:
                    values[role] = DispatchRecord.model_validate(raw)
                except (TypeError, ValueError):
                    continue
        return values

    def retryable(self, session):
        if (session["mode"] != "execute" or self.mode != "execute" or session["state"] != "finished"
                or session["interruption"] or session["retry_requests"] or self.busy):
            return []
        eligible = []
        for role, record in self.branch_records(session).items():
            if record.result is None and record.outcome in _RETRYABLE:
                # Once a POST was attempted, retry must be fenced to its known
                # process. Restart clears the worker's idempotency registry.
                if record.submitted_at is not None and (
                    record.worker_status is None or not record.worker_status.process_instance_id
                    or not record.worker_status.execution_host
                ):
                    continue
                eligible.append(role)
        return eligible

    async def retry(self, identifier, worker, request_id):
        request_id = canonical_id(request_id)
        async with self._lock:
            session = self.get(identifier)
            for request in session["retry_requests"]:
                if request["request_id"] == request_id:
                    if request["worker"] != worker:
                        raise SessionError(409, "This retry identifier already belongs to a different worker.")
                    return session["id"]
            if worker not in self.retryable(session):
                raise SessionError(409, "This worker cannot be retried from this session.")
            updated = deepcopy(session)
            updated["retry_requests"].append({
                "request_id": request_id, "worker": worker,
                "original_record": self.branch_records(session)[worker].model_dump(mode="json"),
            })
            updated.update(state="running", retrying=True, service_error=None)
            self._save(updated)
            self.sessions[session["id"]] = updated
            self._launch(self._run_retry(updated, worker), "control-retry")
            return session["id"]

    async def _run_retry(self, session, role):
        try:
            records = self.branch_records(session)
            previous = records[role]
            case = self._case_for(session)
            settings = self.control_settings
            endpoint = getattr(settings, role)
            client = self.worker_factory(
                endpoint, request_timeout=settings.request_timeout, task_timeout=settings.task_timeout,
                poll_interval=settings.poll_interval, max_response_bytes=settings.max_response_bytes,
                local_address=settings.local_address,
            )
            kwargs = {"on_progress": lambda event: self._progress(session, event)}
            if previous.submitted_at is not None:
                kwargs.update(expected_process_instance_id=previous.worker_status.process_instance_id,
                              expected_execution_host=previous.worker_status.execution_host)
            records[role] = await client.run(getattr(case, role), **kwargs)
            other = "flood" if role == "hydro" else "hydro"
            if other not in records:
                raise ValueError("The other worker's dispatch record must be retained.")
            combined = CombinedAnalysis(
                task_id=case.hydro.task_id, hydro=records["hydro"].result, flood=records["flood"].result,
                errors=[f"{item.worker_id}: Worker evidence is incomplete." for item in records.values()
                        if item.outcome != "complete"],
            )
            run = DispatchRun(
                task_id=case.hydro.task_id, execution_mode="parallel",
                control_started_at=min(item.control_started_at for item in records.values()),
                control_completed_at=max(item.control_completed_at for item in records.values()),
                hydro=records["hydro"], flood=records["flood"], combined=combined,
            )
            evidence = {"requests": session["requests"], "dispatch": run.model_dump(mode="json"),
                        "requested_window": case.requested_window.model_dump(mode="json")}
            report = deepcopy(session["agent_report"] or {})
            report["prior_worker_evidence"] = deepcopy(report.get("worker_evidence"))
            report.update(worker_evidence=evidence, requests=session["requests"], case=case.public_context(),
                          mode="execute", dispatch_attempted=True, execution_repeated=True,
                          deterministic=None, explanation=None, retry_performed=True)
            session["agent_report"] = report
            self._save(session)  # Preserve returned evidence before deterministic review.
            deterministic = build_review_report(evidence, ReviewPolicy.model_validate(session["policy"]),
                                                 requested_window=evidence["requested_window"])
            report.update(deterministic=deterministic, explanation=render_explanation(
                deterministic, None, status="fallback", study_area_name=case.name,
                original_request=session["prompt"], execution_mode="execute"),
                status="complete", validation="PASS", error=None)
            session.update(agent_report=report, state="finished", retrying=False)
            self._save(session)
        except asyncio.CancelledError:
            session.update(state="interrupted", interruption=True, retrying=False)
            self._save(session)
            raise
        except Exception:
            session.update(state="finished", retrying=False,
                           service_error="Retry could not finish; previously returned evidence is retained.")
            self._save(session)
