"""The browser cannot configure execution, forge progress, or lose saved results."""

import asyncio
from contextlib import asynccontextmanager
from copy import deepcopy
import json
from uuid import uuid4

import httpx
import pytest

from backend.control.agent import INVESTIGATION
from backend.control.agent_grounding import render_explanation
from backend.control.reporting import build_review_report
from backend.control.sessions import ControlService, SessionError
from backend.control.state import DispatchRun
from backend.control.web import create_app, public_state
from test_agent import (
    ScriptedClient, control_settings, dispatch_result, explanation, plan, prepared,
)
from test_fusion import fusion_inputs, hydro_result, remove_flood_components


TOKEN = "test-control-token-" + "a" * 40
REQUEST = "Review the configured historical case and available environmental evidence."
PRIVATE = "Bearer PRIVATE_TOKEN http://100.100.3.2:8002/private?key=SECRET"
INSTANCE = "11111111-1111-1111-1111-111111111111"


def service_for(prepared, tmp_path, *, mode="review", runner=None, **kwargs):
    case, evidence, policy = prepared
    return ControlService(
        case, policy, kwargs.pop("client", ScriptedClient(plan(), explanation())), mode=mode,
        evidence=evidence if mode == "review" else None,
        control_settings=control_settings() if mode == "execute" else None,
        history_dir=tmp_path / "history", agent_runner=runner, **kwargs,
    )


@asynccontextmanager
async def api(service):
    app = create_app(service=service, token=TOKEN)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://control.test",
                                     headers={"Authorization": f"Bearer {TOKEN}"}) as client:
            yield client


async def start(client, *, request_id=None, prompt=REQUEST):
    response = await client.post("/sessions", json={"prompt": prompt, "requestId": request_id or str(uuid4())})
    assert response.status_code == 202, response.text
    return response.json()["id"]


async def finish(service):
    await asyncio.wait_for(asyncio.shield(service._job), 3)


def run_for(case, evidence, *, failed_role=None, outcome="transport_error", ambiguous=False):
    evidence = deepcopy(evidence)
    evidence["combined"]["task_id"] = case.hydro.task_id
    for role in ("hydro", "flood"):
        evidence["combined"][role]["task_id"] = case.hydro.task_id
    raw = dispatch_result(case, evidence).model_dump(mode="json")
    for role in ("hydro", "flood"):
        record = raw[role]
        identity = {"execution_host": "PRIVATE_HOST_" + role, "process_instance_id": INSTANCE}
        record["worker_status"] = {**identity, "worker_id": record["worker_id"],
                                   "analysis_type": record["analysis_type"], "status": "idle",
                                   "retained_tasks": 0, "capacity": 128}
        record["task_status"].update(identity)
        record["observations"][-1]["status"].update(identity)
    if failed_role:
        record = raw[failed_role]
        record.update(outcome=outcome, result=None, accepted=False, acceptance_unknown=ambiguous,
                      submitted_at=record["submitted_at"] if ambiguous else None,
                      task_status=None, observations=[], error={"code": outcome, "message": PRIVATE})
        raw["combined"][failed_role] = None
        raw["combined"]["errors"] = [PRIVATE]
    return DispatchRun.model_validate(raw)


def report_for(case, policy, prompt, run):
    evidence = {"requests": [task.model_dump(mode="json") for task in (case.hydro, case.flood)],
                "dispatch": run.model_dump(mode="json"),
                "requested_window": case.requested_window.model_dump(mode="json")}
    deterministic = build_review_report(evidence, policy, requested_window=evidence["requested_window"])
    return {
        "mode": "execute", "case": case.public_context(), "requests": evidence["requests"],
        "status": "complete", "validation": "PASS", "dispatch_attempted": True,
        "plan": {"tool": "investigate_case", "arguments": {"case_id": case.case_id, "investigation": INVESTIGATION}},
        "worker_evidence": evidence, "deterministic": deterministic, "error": None,
        "explanation": render_explanation(deterministic, None, status="fallback", study_area_name=case.name,
                                           original_request=prompt, execution_mode="execute"),
    }


def runner_for(evidence, *, failed_role=None, outcome="transport_error", ambiguous=False, hold=None):
    async def runner(prompt, case, policy, client, **kwargs):
        if hold is not None:
            await hold.wait()
        run = run_for(case, evidence, failed_role=failed_role, outcome=outcome, ambiguous=ambiguous)
        for role in ("hydro", "flood"):
            record = getattr(run, role)
            kwargs["on_progress"]({"worker": role, "stage": "finished",
                "status": None if record.task_status is None else record.task_status.model_dump(mode="json"),
                "record": record.model_dump(mode="json")})
        report = report_for(case, policy, prompt, run)
        kwargs["persist"](report)
        return report
    return runner


@pytest.mark.parametrize("path,method", [
    ("/config", "GET"), ("/sessions", "GET"), ("/sessions", "POST"),
    ("/sessions/not-a-uuid", "GET"), ("/sessions/not-a-uuid/retry", "POST"),
    ("/sessions/not-a-uuid/briefing", "GET"), ("/openapi.json", "GET"),
])
def test_internal_routes_ignore_authorization_and_keep_body_bounds(prepared, tmp_path, path, method):
    async def check():
        service = service_for(prepared, tmp_path)
        async with api(service) as client:
            response = await client.request(method, path, headers={"Authorization": "Bearer wrong"}, content=b"x" * 70000)
            expected = 413 if method == "POST" else 200 if path in {"/config", "/sessions"} else 404
            assert response.status_code == expected
            assert "www-authenticate" not in response.headers
            assert service.sessions == {}
    asyncio.run(check())


@pytest.mark.parametrize("change", [
    {"prompt": ""}, {"prompt": "é" * 2049}, {"prompt": 1}, {"requestId": "not-a-uuid"},
    {"mode": "execute"}, {"worker_url": "http://attacker.invalid"},
    {"resources": ["private.h5"]}, {"prompt": "bad\x00request"},
])
def test_browser_request_schema_cannot_select_mode_resources_or_destinations(prepared, tmp_path, change):
    async def check():
        service = service_for(prepared, tmp_path)
        async with api(service) as client:
            response = await client.post("/sessions", json={"prompt": REQUEST, "requestId": str(uuid4()), **change})
            assert response.status_code == 422
            assert service.sessions == {}
            assert "attacker" not in response.text
    asyncio.run(check())


def test_json_limits_duplicate_keys_and_content_type(prepared, tmp_path):
    async def check():
        service = service_for(prepared, tmp_path)
        async with api(service) as client:
            for content, headers, status in [
                (b"x" * 65537, {"Content-Type": "application/json"}, 413),
                (b'{"prompt":"a","prompt":"b"}', {"Content-Type": "application/json"}, 422),
                (b"{}", {"Content-Type": "text/plain"}, 415),
            ]:
                assert (await client.post("/sessions", content=content, headers=headers)).status_code == status
            assert service.sessions == {}
    asyncio.run(check())


def test_review_download_and_history_are_real_authoritative_and_redacted(prepared, tmp_path):
    async def check():
        case, evidence, policy = prepared
        evidence["combined"]["errors"].append(PRIVATE)
        service = service_for(prepared, tmp_path)
        async with api(service) as client:
            config = (await client.get("/config")).json()
            assert config["mode"] == "review" and config["canStart"]
            identifier = await start(client)
            await finish(service)
            view = (await client.get(f"/sessions/{identifier}")).json()
            assert view["isDemo"] is False and view["executionMode"] == "review"
            assert "does not dispatch" in view["executionNotice"]
            assert view["briefing"] is not None and view["retryableWorkers"] == []
            assert all(worker["status"] == "complete" for worker in view["workers"].values())
            assert all("retained" in worker["summary"] for worker in view["workers"].values())
            download = await client.get(f"/sessions/{identifier}/briefing")
            assert download.status_code == 200 and "attachment" in download.headers["content-disposition"]
            assert "default-src 'none'" in download.headers["content-security-policy"]
            assert "text/html" in download.headers["content-type"]
            assert PRIVATE not in download.text + json.dumps(view)
            assert "SECRET" not in download.text + json.dumps(view)
            history = (await client.get("/sessions")).json()["sessions"]
            assert history[0]["id"] == identifier and "prompt" not in history[0]
            assert download.headers["cache-control"] == "no-store"
        replacement = service_for(prepared, tmp_path)
        async with api(replacement) as client:
            restored = (await client.get(f"/sessions/{identifier}")).json()
            assert restored["briefing"] == view["briefing"]
            assert not replacement.busy
    asyncio.run(check())


def test_idempotency_concurrency_unknown_initial_workers_and_capacity(prepared, tmp_path):
    async def check():
        hold = asyncio.Event()
        service = service_for(prepared, tmp_path, mode="execute", max_sessions=1,
                              runner=runner_for(prepared[1], hold=hold))
        request_id = str(uuid4())
        async with api(service) as client:
            identifier = await start(client, request_id=request_id)
            assert await start(client, request_id=request_id) == identifier
            view = (await client.get(f"/sessions/{identifier}")).json()
            assert view["phase"] == "reviewing" and view["status"] == "running"
            assert all(worker["status"] == "unknown" and not worker["returned"] for worker in view["workers"].values())
            assert (await client.post("/sessions", json={"prompt": "different", "requestId": request_id})).status_code == 409
            assert (await client.post("/sessions", json={"prompt": REQUEST, "requestId": str(uuid4())})).status_code == 409
            assert (await client.get("/config")).json()["canStart"] is False
            hold.set()
            await finish(service)
            assert len(service.sessions) == 1
            assert (await client.post("/sessions", json={"prompt": REQUEST, "requestId": str(uuid4())})).status_code == 429
    asyncio.run(check())


@pytest.mark.parametrize("planner", [None, "rejected", "wrong_case"])
def test_unapproved_request_never_exposes_retained_briefing(prepared, tmp_path, planner):
    async def check():
        service = service_for(prepared, tmp_path)
        async with api(service) as client:
            identifier = await start(client)
            await finish(service)
            session = service.get(identifier)
            report = session["agent_report"]
            if planner is None:
                report.update(plan=None, status="degraded", error={"stage": "interpretation", "code": "timeout"})
            elif planner == "rejected":
                report.update(status="rejected", plan={"tool": "decline_request", "arguments": {"reason": "unsupported_location"}})
            else:
                report["plan"]["arguments"]["case_id"] = "another-case"
            assert report["deterministic"] is not None
            view = (await client.get(f"/sessions/{identifier}")).json()
            assert view["briefing"] is None
            assert (await client.get(f"/sessions/{identifier}/briefing")).status_code == 409
    asyncio.run(check())


@pytest.mark.parametrize("mutation", ["case", "requests", "mode", "prompt"])
def test_briefing_cannot_be_bound_to_another_session_context(prepared, tmp_path, mutation):
    async def check():
        service = service_for(prepared, tmp_path)
        async with api(service) as client:
            identifier = await start(client)
            await finish(service)
            session = service.get(identifier)
            if mutation == "prompt":
                session["prompt"] = "A different request"
            elif mutation == "case":
                session["agent_report"]["case"]["name"] = "Different place"
            elif mutation == "requests":
                session["agent_report"]["requests"][0]["task_id"] = "another-task"
            else:
                session["agent_report"]["mode"] = "execute"
            assert (await client.get(f"/sessions/{identifier}")).json()["briefing"] is None
    asyncio.run(check())


def test_interruption_preserves_finished_branch_and_restart_does_not_resume(prepared, tmp_path):
    async def check():
        completed = asyncio.Event()
        calls = []
        async def interrupted(prompt, case, policy, client, **kwargs):
            calls.append(case.hydro.task_id)
            run = run_for(case, prepared[1])
            kwargs["on_progress"]({"worker": "hydro", "stage": "finished",
                "status": run.hydro.task_status.model_dump(mode="json"), "record": run.hydro.model_dump(mode="json")})
            completed.set()
            await asyncio.Event().wait()
        service = service_for(prepared, tmp_path, mode="execute", runner=interrupted)
        async with api(service) as client:
            identifier = await start(client)
            await completed.wait()
            view = (await client.get(f"/sessions/{identifier}")).json()
            assert view["workers"]["hydro"]["status"] == "complete"
            assert view["workers"]["flood"]["status"] == "unknown"
            assert view["status"] == "running"
        replacement = service_for(prepared, tmp_path, mode="execute", runner=interrupted)
        async with api(replacement) as client:
            view = (await client.get(f"/sessions/{identifier}")).json()
            assert view["status"] == "partial" and view["retryableWorkers"] == []
            assert view["workers"]["hydro"]["returned"]
            assert "interrupted" in view["validationFailures"][0]["title"].lower()
            assert len(calls) == 1 and not replacement.busy
    asyncio.run(check())


def test_failed_flood_envelope_does_not_show_successful_processing(prepared, tmp_path):
    async def check():
        case, evidence, policy = prepared
        evidence = deepcopy(evidence)
        remove_flood_components(evidence["combined"]["flood"], {"sentinel1", "dem", "hand"})
        altered = (case, evidence, policy)
        service = service_for(altered, tmp_path)
        async with api(service) as client:
            identifier = await start(client)
            await finish(service)
            worker = (await client.get(f"/sessions/{identifier}")).json()["workers"]["flood"]
            assert worker["status"] == "failed" and not worker["returned"] and worker["validated"]
            assert any(step["state"] == "failed" for step in worker["steps"])
            assert not all(step["state"] == "complete" for step in worker["steps"])
    asyncio.run(check())


def test_one_retry_preserves_other_result_same_task_id_and_process_fence(prepared, tmp_path):
    async def check():
        attempts = []
        service = None
        class Worker:
            def __init__(self, endpoint, **kwargs):
                assert endpoint.expected_worker_id == "flood-worker"
            async def run(self, task, **kwargs):
                session = next(iter(service.sessions.values()))
                durable = json.loads((service.history_dir / f"{session['id']}.json").read_text())
                assert durable["retry_requests"] and durable["retrying"]
                assert task.task_id == session["requests"][0]["task_id"]
                assert kwargs["expected_process_instance_id"] == INSTANCE
                assert kwargs["expected_execution_host"] == "PRIVATE_HOST_flood"
                attempts.append(task.task_id)
                run = run_for(service._case_for(session), prepared[1])
                kwargs["on_progress"]({"worker": "flood", "stage": "finished",
                    "status": run.flood.task_status.model_dump(mode="json"), "record": run.flood.model_dump(mode="json")})
                return run.flood
        service = service_for(prepared, tmp_path, mode="execute", worker_factory=Worker,
                              runner=runner_for(prepared[1], failed_role="flood", ambiguous=True))
        async with api(service) as client:
            identifier = await start(client)
            await finish(service)
            before = deepcopy(service.get(identifier)["agent_report"]["worker_evidence"]["dispatch"]["hydro"])
            view = (await client.get(f"/sessions/{identifier}")).json()
            assert view["retryableWorkers"] == ["flood"]
            assert PRIVATE not in json.dumps(view) and "PRIVATE_HOST" not in json.dumps(view)
            retry_id = str(uuid4())
            body = {"worker": "flood", "requestId": retry_id}
            assert (await client.post(f"/sessions/{identifier.upper()}/retry", json=body)).status_code == 202
            await finish(service)
            assert (await client.post(f"/sessions/{identifier}/retry", json=body)).status_code == 202
            assert len(attempts) == 1
            assert list(service.sessions) == [identifier]
            after = service.get(identifier)["agent_report"]["worker_evidence"]["dispatch"]
            assert after["hydro"] == before and after["flood"]["outcome"] == "complete"
            view = (await client.get(f"/sessions/{identifier}")).json()
            assert view["briefing"] and view["retryableWorkers"] == [] and not view["retrying"]
            assert "does not establish new parallel overlap" in view["executionNotice"]
            assert (await client.post(f"/sessions/{identifier}/retry", json={**body, "requestId": str(uuid4())})).status_code == 409
    asyncio.run(check())


def test_failed_retry_persistence_does_not_consume_attempt_or_leave_running(prepared, tmp_path, monkeypatch):
    async def check():
        service = service_for(prepared, tmp_path, mode="execute",
                              runner=runner_for(prepared[1], failed_role="flood"))
        async with api(service) as client:
            identifier = await start(client)
            await finish(service)
            before = deepcopy(service.get(identifier))
            original = service._save
            def broken(session):
                raise OSError(PRIVATE)
            monkeypatch.setattr(service, "_save", broken)
            response = await client.post(f"/sessions/{identifier}/retry", json={"worker": "flood", "requestId": str(uuid4())})
            assert response.status_code == 503 and PRIVATE not in response.text
            assert service.get(identifier) == before and not service.busy
            monkeypatch.setattr(service, "_save", original)
            assert service.retryable(service.get(identifier)) == ["flood"]
    asyncio.run(check())


@pytest.mark.parametrize("outcome", ["protocol_error", "complete"])
def test_invalid_or_completed_worker_cannot_be_retried(prepared, tmp_path, outcome):
    async def check():
        service = service_for(prepared, tmp_path, mode="execute", runner=runner_for(
            prepared[1], failed_role="flood" if outcome != "complete" else None, outcome=outcome))
        async with api(service) as client:
            identifier = await start(client)
            await finish(service)
            assert (await client.get(f"/sessions/{identifier}")).json()["retryableWorkers"] == []
            assert (await client.post(f"/sessions/{identifier}/retry", json={"worker": "flood", "requestId": str(uuid4())})).status_code == 409
    asyncio.run(check())


def test_background_error_is_sanitized_and_null_report_error_is_safe(prepared, tmp_path):
    async def check():
        async def broken(prompt, case, policy, client, **kwargs):
            kwargs["persist"]({"error": None, "deterministic": None, "plan": None})
            raise RuntimeError(PRIVATE)
        service = service_for(prepared, tmp_path, mode="execute", runner=broken)
        async with api(service) as client:
            identifier = await start(client)
            await finish(service)
            response = await client.get(f"/sessions/{identifier}")
            assert response.status_code == 200 and response.json()["status"] == "failed"
            assert PRIVATE not in response.text
            assert (await client.get("/sessions")).status_code == 200
    asyncio.run(check())


@pytest.mark.parametrize("field", ["explanation", "context"])
def test_corrupted_saved_explanation_cannot_break_history_or_publish_briefing(prepared, tmp_path, field):
    async def check():
        service = service_for(prepared, tmp_path)
        async with api(service) as client:
            identifier = await start(client)
            await finish(service)
            report = service.get(identifier)["agent_report"]
            if field == "explanation":
                report["explanation"] = [PRIVATE]
            else:
                report["explanation"]["context"] = [PRIVATE]
            response = await client.get(f"/sessions/{identifier}")
            assert response.status_code == 200 and response.json()["briefing"] is None
            assert PRIVATE not in response.text
            assert (await client.get("/sessions")).status_code == 200
    asyncio.run(check())


def test_failed_initial_persistence_cannot_launch_model_or_worker(prepared, tmp_path, monkeypatch):
    async def check():
        calls = []
        async def forbidden(*args, **kwargs):
            calls.append(True)
            raise AssertionError("No work may start before the request is durable")
        service = service_for(prepared, tmp_path, mode="execute", runner=forbidden)
        async with api(service) as client:
            def broken(session):
                raise OSError(PRIVATE)
            monkeypatch.setattr(service, "_save", broken)
            response = await client.post("/sessions", json={"prompt": REQUEST, "requestId": str(uuid4())})
            assert response.status_code == 503 and PRIVATE not in response.text
            assert service.sessions == {} and not service.busy and calls == []
    asyncio.run(check())


def test_terminal_worker_failure_and_unknown_ambiguous_identity_cannot_retry(prepared, tmp_path):
    async def check():
        service = service_for(prepared, tmp_path, mode="execute", runner=runner_for(prepared[1]))
        async with api(service) as client:
            identifier = await start(client)
            await finish(service)
            session = service.get(identifier)
            failed = deepcopy(session["progress"]["flood"]["record"])
            failed.update(outcome="worker_failed", result=None, error={"code": "worker_failed", "message": PRIVATE})
            failed["task_status"].update(state="failed", error=PRIVATE)
            failed["observations"][-1]["status"] = failed["task_status"]
            session["progress"]["flood"]["record"] = failed
            assert service.retryable(session) == []
            failed.update(outcome="timed_out", result=None, accepted=False, acceptance_unknown=True,
                          worker_status=None, task_status=None, observations=[],
                          error={"code": "timed_out", "message": PRIVATE})
            assert service.retryable(session) == []
            assert (await client.post(f"/sessions/{identifier}/retry", json={"worker": "flood", "requestId": str(uuid4())})).status_code == 409
    asyncio.run(check())


@pytest.mark.parametrize("token", [None, "", "short-token", "a" * 31, "a" * 32 + "\n"])
def test_control_accepts_missing_or_unused_legacy_tokens(prepared, tmp_path, token):
    assert create_app(service=service_for(prepared, tmp_path), token=token) is not None


@pytest.mark.parametrize("authorization", [None, "", "Bearer incorrect", "Basic arbitrary", "Bearer", "Bearer bad\r\nvalue", b"\xff\x00"])
def test_control_session_lifecycle_needs_no_internal_credentials(prepared, tmp_path, authorization):
    async def check():
        service = service_for(prepared, tmp_path)
        app = create_app(service=service, token={"obsolete": True}, viewer_tokens=["unused"])
        headers = {} if authorization is None else {"Authorization": authorization}
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://control.test", headers=headers) as client:
                assert (await client.get("/config")).status_code == 200
                assert (await client.post("/sessions", json={"prompt": REQUEST, "requestId": "invalid"})).status_code == 422
                identifier = await start(client)
                await finish(service)
                assert (await client.get("/sessions")).json()["sessions"][0]["id"] == identifier
                assert (await client.get(f"/sessions/{identifier}")).status_code == 200
                assert (await client.get(f"/sessions/{identifier}/briefing")).status_code == 200
                assert (await client.post(f"/sessions/{identifier}/retry", json={"worker": "flood", "requestId": str(uuid4())})).status_code == 409
                assert (await client.get("/viewer/hydro")).status_code == 200
                assert (await client.get("/viewer/flood")).status_code == 200
    asyncio.run(check())
