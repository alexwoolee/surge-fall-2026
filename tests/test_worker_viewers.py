"""Worker displays receive only their role's durable, observed execution state."""

import asyncio
from contextlib import asynccontextmanager
from copy import deepcopy
import hashlib
import json
from uuid import uuid4

import httpx
import pytest

from backend.control.sessions import MAX_OBSERVED_EVENTS
from backend.control.web import create_app
from test_control_web import (
    TOKEN, PRIVATE, REQUEST, finish, fusion_inputs, hydro_result, prepared,
    report_for, run_for, runner_for, service_for, start,
)


VIEWERS = {"hydro": "private-hydro-viewer-" + "h" * 32,
           "flood": "private-flood-viewer-" + "f" * 32}


@asynccontextmanager
async def api(service, viewers=VIEWERS):
    app = create_app(service=service, token=TOKEN, viewer_tokens=viewers)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://control.test",
                                     headers={"Authorization": f"Bearer {TOKEN}"}) as client:
            yield client


async def view(client, role):
    return await client.get("/viewer/" + role, headers={"Authorization": "Bearer " + VIEWERS[role]})


def event_for(record, stage, state=None):
    status = None
    if state is not None:
        status = record.task_status.model_dump(mode="json")
        status["state"] = state
        if state not in {"complete", "partial", "failed"}:
            status["completed_at"] = None
    return {"worker": record.worker_id.removesuffix("-worker"), "stage": stage,
            "status": status, "record": record.model_dump(mode="json") if stage == "finished" else None}


@pytest.mark.parametrize("role", ["hydro", "flood"])
@pytest.mark.parametrize("path,method", [
    ("/config", "GET"), ("/sessions", "GET"), ("/sessions", "POST"),
    ("/sessions/unknown", "GET"), ("/sessions/unknown/briefing", "GET"),
    ("/sessions/unknown/retry", "POST"), ("/viewer/other", "GET"),
    ("/viewer/self", "POST"), ("/viewer/self", "HEAD"), ("/viewer/self", "OPTIONS"),
])
def test_legacy_viewer_credentials_do_not_restrict_routes(prepared, tmp_path, role, path, method):
    async def check():
        service = service_for(prepared, tmp_path)
        async with api(service) as client:
            actual = path.replace("other", "flood" if role == "hydro" else "hydro").replace("self", role)
            response = await client.request(method, actual, headers={"Authorization": "Bearer " + VIEWERS[role]},
                                            content=b"x" * 70000)
            expected = (413 if method == "POST" else 405 if method in {"HEAD", "OPTIONS"}
                        else 404 if "/unknown" in actual else 200)
            assert response.status_code == expected
            assert "www-authenticate" not in response.headers
            assert not service.sessions
    asyncio.run(check())


def test_empty_and_review_only_history_never_masquerade_as_worker_execution(prepared, tmp_path):
    async def check():
        service = service_for(prepared, tmp_path)
        empty = {"session": None, "worker": None, "observedAt": None, "events": []}
        async with api(service) as client:
            assert (await view(client, "hydro")).json() == empty
            identifier = await start(client)
            await finish(service)
            assert service.get(identifier)["mode"] == "review"
            assert (await view(client, "hydro")).json() == empty
            assert (await view(client, "flood")).json() == empty
            assert (await client.get("/config")).status_code == 200
            assert (await client.get("/sessions")).json()["sessions"][0]["id"] == identifier
    asyncio.run(check())


def test_role_projection_is_redacted_and_completed_history_survives_fast_processing(prepared, tmp_path):
    async def check():
        async def runner(prompt, case, policy, client, **kwargs):
            run = run_for(case, prepared[1])
            for role in ("hydro", "flood"):
                record = getattr(run, role)
                for stage, state in (("preflight", None), ("submission", None), ("polling", "task_received"),
                                     ("polling", "processing"), ("result", "complete"), ("finished", "complete")):
                    event = event_for(record, stage, state)
                    kwargs["on_progress"](event)
                    kwargs["on_progress"](deepcopy(event))  # Duplicate observation is not another transition.
            return report_for(case, policy, prompt, run)
        service = service_for(prepared, tmp_path, mode="execute", runner=runner)
        async with api(service) as client:
            identifier = await start(client, prompt=REQUEST + " PRIVATE_PROMPT")
            await finish(service)  # First viewer poll deliberately occurs after Hydro has finished.
            hydro = (await view(client, "hydro")).json()
            flood = (await view(client, "flood")).json()
            assert set(hydro) == {"session", "worker", "observedAt", "events"}
            assert set(hydro["session"]) == {"id", "title", "createdAt", "executionNotice", "status"}
            assert hydro["session"]["id"] == identifier
            assert hydro["worker"]["id"] == "hydro" and hydro["worker"]["status"] == "complete"
            assert hydro["worker"]["returned"] and hydro["worker"]["validated"]
            assert len(hydro["events"]) == 6
            assert hydro["events"][-1]["label"] == "Validated evidence returned."
            assert hydro["observedAt"] == hydro["events"][-1]["observedAt"]
            assert all(event["observedAt"].endswith("+00:00") for event in hydro["events"])
            assert {event["id"] for event in hydro["events"]}.isdisjoint(event["id"] for event in flood["events"])
            assert (await view(client, "hydro")).json() == hydro  # Polling adds no fake heartbeat or events.
            serialized = json.dumps(hydro)
            assert all(value not in serialized for value in ("PRIVATE_PROMPT", "PRIVATE_HOST", "100.100.", PRIVATE,
                                                             "flood-worker", VIEWERS["hydro"], VIEWERS["flood"], TOKEN))
            assert "Sentinel-1" not in serialized and "NASA GPM" in serialized
            path = service.history_dir / f"{identifier}.json"
            prior_hash = hashlib.sha256(path.read_bytes()).hexdigest()
        replacement = service_for(prepared, tmp_path, mode="execute", runner=runner)
        async with api(replacement) as client:
            assert (await view(client, "hydro")).json() == hydro
            assert hashlib.sha256(path.read_bytes()).hexdigest() == prior_hash
            assert not replacement.busy
    asyncio.run(check())


def test_newest_execute_session_selected_while_newer_reviews_are_ignored(prepared, tmp_path):
    async def check():
        service = service_for(prepared, tmp_path, mode="execute", runner=runner_for(prepared[1]))
        async with api(service) as client:
            first = await start(client)
            await finish(service)
            second = await start(client)
            await finish(service)
            assert (await view(client, "hydro")).json()["session"]["id"] == second
            review = deepcopy(service.get(first))
            review.update(id=str(uuid4()), mode="review", created_at="2099-01-01T00:00:00+00:00")
            service.sessions[review["id"]] = review
            assert (await view(client, "hydro")).json()["session"]["id"] == second
    asyncio.run(check())


def test_progress_is_durable_before_visible_and_failed_save_does_not_publish(prepared, tmp_path, monkeypatch):
    async def check():
        hold = asyncio.Event()
        service = service_for(prepared, tmp_path, mode="execute", runner=runner_for(prepared[1], hold=hold))
        async with api(service) as client:
            identifier = await start(client)
            session = service.get(identifier)
            record = run_for(service._case_for(session), prepared[1]).hydro
            event = event_for(record, "polling", "processing")
            original_save = service._save
            def verify_before_publish(updated):
                assert "observed_events" not in session
                original_save(updated)
                saved = json.loads((service.history_dir / f"{identifier}.json").read_text())
                assert saved["observed_events"]["hydro"][0]["task_state"] == "processing"
            monkeypatch.setattr(service, "_save", verify_before_publish)
            service._progress(session, event)
            published = (await view(client, "hydro")).json()
            assert published["worker"]["status"] == "active" and len(published["events"]) == 1
            def fail(updated):
                raise OSError(PRIVATE)
            monkeypatch.setattr(service, "_save", fail)
            with pytest.raises(OSError):
                service._progress(session, event_for(record, "finished", "complete"))
            assert (await view(client, "hydro")).json() == published
            monkeypatch.setattr(service, "_save", original_save)
            hold.set()
            await finish(service)
    asyncio.run(check())


def test_timeline_is_bounded_and_preserves_completed_observations(prepared, tmp_path):
    async def check():
        service = service_for(prepared, tmp_path, mode="execute", runner=runner_for(prepared[1]))
        async with api(service) as client:
            identifier = await start(client)
            await finish(service)
            session = service.get(identifier)
            record = service.branch_records(session)["hydro"]
            completed_id = session["observed_events"]["hydro"][0]["id"]
            for index in range(MAX_OBSERVED_EVENTS + 10):
                service._progress(session, event_for(record, "preflight" if index % 2 else "submission"))
            entries = session["observed_events"]["hydro"]
            assert len(entries) == MAX_OBSERVED_EVENTS
            assert completed_id in {entry["id"] for entry in entries}
    asyncio.run(check())


def test_terminal_session_does_not_claim_stale_processing_is_current(prepared, tmp_path):
    async def check():
        async def runner(prompt, case, policy, client, **kwargs):
            record = run_for(case, prepared[1]).hydro
            kwargs["on_progress"](event_for(record, "polling", "processing"))
            raise RuntimeError(PRIVATE)
        service = service_for(prepared, tmp_path, mode="execute", runner=runner)
        async with api(service) as client:
            await start(client)
            await finish(service)
            payload = (await view(client, "hydro")).json()
            assert payload["worker"]["status"] == "unknown"
            assert not any(step["state"] == "active" for step in payload["worker"]["steps"])
            assert payload["observedAt"] and len(payload["events"]) == 1
            assert "observed" in payload["events"][0]["label"]
            assert PRIVATE not in json.dumps(payload)
    asyncio.run(check())


def test_old_completed_history_without_events_is_readable_without_rewrite(prepared, tmp_path):
    async def check():
        service = service_for(prepared, tmp_path, mode="execute", runner=runner_for(prepared[1]))
        async with api(service) as client:
            identifier = await start(client)
            await finish(service)
            path = service.history_dir / f"{identifier}.json"
        old = json.loads(path.read_text())
        old.pop("observed_events")
        path.write_text(json.dumps(old))
        original = path.read_bytes()
        replacement = service_for(prepared, tmp_path, mode="execute", runner=runner_for(prepared[1]))
        async with api(replacement) as client:
            payload = (await view(client, "hydro")).json()
            assert payload["worker"]["status"] == "complete"
            assert payload["events"] == [] and payload["observedAt"] is None
            assert path.read_bytes() == original
    asyncio.run(check())


@pytest.mark.parametrize("mutation", ["role", "too_many", "timestamp", "naive_time", "extra_field", "state", "outcome", "duplicate_id"])
def test_malformed_new_history_fields_fail_closed_without_rewriting(prepared, tmp_path, mutation):
    async def check():
        service = service_for(prepared, tmp_path, mode="execute", runner=runner_for(prepared[1]))
        async with api(service) as client:
            identifier = await start(client)
            await finish(service)
            path = service.history_dir / f"{identifier}.json"
        raw = json.loads(path.read_text())
        event = raw["observed_events"]["hydro"][0]
        if mutation == "role":
            raw["observed_events"]["attacker"] = []
        elif mutation == "too_many":
            raw["observed_events"]["hydro"] *= MAX_OBSERVED_EVENTS + 1
        elif mutation == "timestamp":
            event["observed_at"] = PRIVATE
        elif mutation == "naive_time":
            event["observed_at"] = "2026-01-01T00:00:00"
        elif mutation == "extra_field":
            event["label"] = PRIVATE
        elif mutation == "state":
            event["task_state"] = PRIVATE
        elif mutation == "outcome":
            event["outcome"] = None
        else:
            raw["observed_events"]["flood"][0]["id"] = event["id"]
        path.write_text(json.dumps(raw))
        before = path.read_bytes()
        replacement = service_for(prepared, tmp_path, mode="execute", runner=runner_for(prepared[1]))
        with pytest.raises(ValueError) as error:
            await replacement.start()
        assert PRIVATE not in str(error.value)
        assert path.read_bytes() == before and not replacement.busy
    asyncio.run(check())


@pytest.mark.parametrize("tokens", [
    {"hydro": TOKEN}, {"hydro": VIEWERS["hydro"], "flood": VIEWERS["hydro"]},
    {"hydro": "short"}, {"hydro": None}, {"unknown": VIEWERS["hydro"]},
    {"hydro": "a" * 32 + "\n"}, {"hydro": "a" * 257}, {"hydro": "a" * 32 + "+"},
    {"hydro": "a" * 32 + "/"}, [VIEWERS["hydro"]],
])
def test_legacy_viewer_token_configuration_is_ignored(prepared, tmp_path, tokens):
    assert create_app(service=service_for(prepared, tmp_path), token=TOKEN, viewer_tokens=tokens) is not None


def test_absent_and_unknown_viewer_credentials_do_not_block_access(prepared, tmp_path):
    async def check():
        service = service_for(prepared, tmp_path)
        async with api(service, viewers=None) as client:
            assert (await view(client, "hydro")).status_code == 200
            assert (await client.get("/viewer/hydro")).status_code == 200  # Operator inspection remains available.
            assert (await client.get("/config", headers={"Authorization": "Bearer unknown"})).status_code == 200
    asyncio.run(check())
