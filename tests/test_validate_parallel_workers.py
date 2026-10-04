"""Phase 6 orchestration must retain evidence without overstating its gate."""

import asyncio
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from types import SimpleNamespace

import httpx
import pytest

from backend.control.timing import ClockCheckError
from backend.control.state import DispatchRun
from backend.shared.settings import ControlSettings, WorkerEndpoint
from scripts.validate import validate_parallel_workers as checkpoint
from test_contracts import flood_resources, flood_result, hydro_result
from test_control_timing import scenario
from test_coordinator import task_for


BASE = datetime(2026, 1, 1, tzinfo=timezone.utc)
TOKEN = "private-parallel-test-token"
SECRET_ERROR = "Bearer leaked-token https://user:password@example.test/?sig=private"
ROLES = ("hydro-worker", "flood-worker")


@pytest.fixture
def harness(monkeypatch, tmp_path, hydro_result, flood_result):
    run, before, after = scenario(hydro_result, flood_result)
    settings = ControlSettings(
        WorkerEndpoint("http://hydro.invalid:8002", ROLES[0], TOKEN),
        WorkerEndpoint("http://flood.invalid:8003", ROLES[1], TOKEN),
        local_address="100.100.3.5",
    )
    state = SimpleNamespace(
        run=run, tasks=tuple(task_for(record.result.model_dump(mode="json"))
                             for record in (run.hydro, run.flood)),
        settings=settings, before=before, after=after, calls=[], snapshots=[],
        auth={role: True for role in ROLES}, duplicate={role: True for role in ROLES},
        errors={}, proof={"passed": True, "guaranteed_overlap_seconds": 5.98},
        topology={"non_loopback_worker_urls": True, "three_distinct_reported_hosts": True,
                  "distinct_worker_processes": True, "operator_confirmed_three_physical_laptops": True},
        output=tmp_path / "parallel-result.json",
    )
    save_json = checkpoint.save_json

    def save(path, value):
        state.snapshots.append(deepcopy(value))
        return save_json(path, value)

    def fail_if_requested(stage):
        if stage in state.errors:
            raise state.errors[stage]

    async def authentication(endpoint, timeout, local_address):
        state.calls.append(("authentication", endpoint.expected_worker_id))
        assert timeout == state.settings.request_timeout
        assert local_address == state.settings.local_address
        fail_if_requested("authentication")
        return state.auth[endpoint.expected_worker_id]

    async def clocks(actual_settings):
        assert actual_settings is state.settings
        stage = "clock_after" if any(call[0] == "dispatch" for call in state.calls) else "clock_before"
        state.calls.append((stage,))
        fail_if_requested(stage)
        return deepcopy(state.after if stage == "clock_after" else state.before)

    async def dispatch(hydro_task, flood_task, actual_settings, **kwargs):
        state.calls.append(("dispatch", kwargs))
        assert (hydro_task, flood_task) == state.tasks
        assert actual_settings is state.settings
        fail_if_requested("dispatch")
        return state.run

    def assess(actual_run, actual_before, actual_after):
        state.calls.append(("assess_overlap",))
        assert actual_run is state.run
        assert actual_before == state.before and actual_after == state.after
        fail_if_requested("assess_overlap")
        return deepcopy(state.proof)

    def topology(actual_run, actual_settings, control_host, confirmed):
        assert actual_run is state.run and actual_settings is state.settings
        state.calls.append(("topology", confirmed))
        return {**state.topology, "operator_confirmed_three_physical_laptops": confirmed}

    async def duplicate(endpoint, task, record, timeout, local_address):
        state.calls.append(("duplicate", endpoint.expected_worker_id))
        index = ROLES.index(endpoint.expected_worker_id)
        assert task == state.tasks[index]
        assert record == (state.run.hydro, state.run.flood)[index]
        assert timeout == state.settings.request_timeout
        assert local_address == state.settings.local_address
        fail_if_requested("duplicate")
        return state.duplicate[endpoint.expected_worker_id]

    class StableUTC:
        @staticmethod
        def now(tz):
            return BASE

    monkeypatch.setattr(checkpoint, "datetime", StableUTC)
    # Replace this module's clock handle, not time.monotonic globally: asyncio
    # must retain its real event-loop clock while the continuity gate is tested.
    monkeypatch.setattr(checkpoint, "time", SimpleNamespace(monotonic=lambda: 0.0))
    monkeypatch.setattr(checkpoint, "save_json", save)
    monkeypatch.setattr(checkpoint, "_authentication_check", authentication)
    monkeypatch.setattr(checkpoint, "sample_clocks", clocks)
    monkeypatch.setattr(checkpoint, "run_analysis", dispatch)
    monkeypatch.setattr(checkpoint, "assess_overlap", assess)
    monkeypatch.setattr(checkpoint, "topology_checks", topology)
    monkeypatch.setattr(checkpoint, "_duplicate_check", duplicate)
    return state


def validate(harness, *, local_check=False, confirmed=True):
    code = asyncio.run(checkpoint.validate(
        harness.settings, harness.tasks, local_check=local_check,
        confirmed=confirmed, output=harness.output,
    ))
    return code, json.loads(harness.output.read_text())


def assert_results_preserved(report, harness):
    for role in ("hydro", "flood"):
        expected = getattr(harness.run, role).result.model_dump(mode="json")
        assert report["dispatch"][role]["result"] == expected
        assert report["dispatch"]["combined"][role] == expected


def test_remote_success_runs_all_checks_and_explicitly_dispatches_parallel(harness, capsys):
    code, report = validate(harness)
    assert code == 0 and report["validation"] == "PASS"
    assert report["phase_gate"] == "PENDING_USER"
    assert report["scope"] == "configured_remote_workers"
    assert report["execution_mode"] == report["dispatch"]["execution_mode"] == "parallel"
    assert report["dispatch_attempted"] and report["completed_results_preserved"]
    assert harness.calls == [
        ("authentication", ROLES[0]), ("authentication", ROLES[1]),
        ("clock_before",), ("dispatch", {"execution_mode": "parallel"}),
        ("clock_after",), ("assess_overlap",), ("topology", True),
        ("duplicate", ROLES[0]), ("duplicate", ROLES[1]),
    ]
    assert report["clock_before"] == harness.before
    assert report["clock_after"] == harness.after
    assert all(report["authentication"].values())
    assert all(report["duplicate_submission"].values())
    assert all(report["topology_checks"].values())
    assert report["control_clock_continuity"]["passed"]
    assert_results_preserved(report, harness)
    assert TOKEN not in harness.output.read_text() + capsys.readouterr().out


def test_preflight_clock_error_replaces_stale_pass_without_submitting(harness, capsys):
    harness.output.write_text(json.dumps({"validation": "PASS", "old_dispatch": {"result": "stale"}}))
    harness.errors["clock_before"] = ClockCheckError(SECRET_ERROR)
    code, report = validate(harness)
    assert code == 1 and report["validation"] == "FAIL"
    assert report["phase_gate"] == "NOT_READY" and report["failed_stage"] == "clock_preflight"
    assert not report["dispatch_attempted"] and "dispatch" not in report and "old_dispatch" not in report
    assert harness.snapshots[0]["validation"] == "RUNNING"
    assert not harness.snapshots[0]["dispatch_attempted"]
    assert not any(call[0] in {"dispatch", "duplicate"} for call in harness.calls)
    text = harness.output.read_text() + capsys.readouterr().out
    assert all(value not in text for value in (TOKEN, "leaked-token", "password", "sig=private"))


@pytest.mark.parametrize("role", ROLES)
def test_failed_access_policy_check_stops_before_clock_or_task_requests(harness, role):
    harness.auth[role] = False
    code, report = validate(harness)
    assert code == 1 and report["validation"] == "FAIL"
    assert report["failed_stage"] == "preflight" and not report["dispatch_attempted"]
    assert report["authentication"][role] is False
    assert all(call[0] == "authentication" for call in harness.calls)


@pytest.mark.parametrize("role", ROLES)
@pytest.mark.parametrize("token", [None, "", "invalid\nheader", "unrelated token"])
def test_any_configured_token_can_submit_tasks(harness, role, token):
    endpoints = [harness.settings.hydro, harness.settings.flood]
    index = ROLES.index(role)
    endpoints[index] = WorkerEndpoint(endpoints[index].url, role, token=token)
    harness.settings = ControlSettings(*endpoints, local_address="100.100.3.5")
    code, report = validate(harness)
    assert code == 0 and report["validation"] == "PASS" and report["dispatch_attempted"]
    assert "clock_before" in report and "dispatch" in report
    assert report["authentication_policy"] == "credentials_ignored"
    assert_results_preserved(report, harness)


def test_missing_physical_confirmation_never_contacts_workers(harness):
    code, report = validate(harness, confirmed=False)
    assert code == 1 and report["validation"] == "FAIL" and not report["dispatch_attempted"]
    assert report["scope"] == "configured_remote_workers"
    assert harness.calls == []


def test_postflight_clock_error_retains_both_returned_results(harness):
    harness.errors["clock_after"] = ClockCheckError(SECRET_ERROR)
    code, report = validate(harness)
    assert code == 1 and report["validation"] == "FAIL"
    assert report["failed_stage"] == "clock_postflight" and report["dispatch_attempted"]
    assert_results_preserved(report, harness)
    assert "overlap" not in report and "duplicate_submission" not in report
    # Evidence was persisted before the postflight clock request failed.
    assert any(snapshot.get("dispatch") == report["dispatch"] and snapshot["validation"] == "RUNNING"
               for snapshot in harness.snapshots)


def test_local_success_cannot_pass_the_physical_gate(harness):
    code, report = validate(harness, local_check=True, confirmed=False)
    assert code == 0 and report["validation"] == "PASS_LOCAL_ONLY"
    assert report["phase_gate"] == "PENDING_REMOTE_LAPTOPS"
    assert report["scope"] == "local_loopback"
    assert not report["topology_checks"]["operator_confirmed_three_physical_laptops"]


@pytest.mark.parametrize("failure", ["no_overlap", "clock_jump", "too_uncertain", "worker_restarted"])
def test_failed_overlap_proof_cannot_be_promoted_to_pass(harness, failure):
    harness.proof = {"passed": False, "guaranteed_overlap_seconds": 0.0,
                     "checks": {failure: False}}
    code, report = validate(harness)
    assert code == 1 and report["validation"] == "FAIL" and report["phase_gate"] == "NOT_READY"
    assert report["overlap"] == harness.proof
    assert_results_preserved(report, harness)
    assert set(report["duplicate_submission"]) == set(ROLES)


def test_control_wall_clock_jump_blocks_pass_despite_positive_worker_overlap(harness, monkeypatch):
    timestamps = iter((BASE, BASE + timedelta(seconds=1), BASE + timedelta(seconds=1)))

    class JumpedUTC:
        @staticmethod
        def now(tz):
            return next(timestamps)

    monkeypatch.setattr(checkpoint, "datetime", JumpedUTC)
    code, report = validate(harness)
    assert code == 1 and report["validation"] == "FAIL"
    assert report["overlap"]["passed"]
    assert not report["control_clock_continuity"]["passed"]
    assert_results_preserved(report, harness)


@pytest.mark.parametrize("check", ["non_loopback_worker_urls", "three_distinct_reported_hosts", "distinct_worker_processes"])
def test_failed_deployment_check_cannot_pass_remote_gate(harness, check):
    harness.topology[check] = False
    code, report = validate(harness)
    assert code == 1 and report["validation"] == "FAIL"
    assert report["phase_gate"] == "PENDING_PHYSICAL_DEPLOYMENT_CHECK"
    assert not report["topology_checks"][check]
    assert_results_preserved(report, harness)


@pytest.mark.parametrize("role", ROLES)
def test_each_duplicate_check_is_required(harness, role):
    harness.duplicate[role] = False
    code, report = validate(harness)
    assert code == 1 and report["validation"] == "FAIL" and report["phase_gate"] == "NOT_READY"
    assert set(report["duplicate_submission"]) == set(ROLES)
    assert not report["duplicate_submission"][role]
    assert_results_preserved(report, harness)


@pytest.mark.parametrize("role", ["hydro", "flood"])
def test_incomplete_branch_cannot_pass_even_if_boundary_checks_pass(harness, role):
    raw = harness.run.model_dump(mode="json")
    raw[role].update(
        outcome="timed_out", accepted=False, acceptance_unknown=True,
        task_status=None, observations=[], result=None,
        error={"code": "timed_out", "message": "Control stopped waiting."},
    )
    raw["combined"][role] = None
    raw["combined"]["errors"] = [f"{role}-worker: Control stopped waiting."]
    harness.run = DispatchRun.model_validate(raw)
    code, report = validate(harness)
    assert code == 1 and report["validation"] == "FAIL"
    assert report["dispatch"][role]["result"] is None
    other = "flood" if role == "hydro" else "hydro"
    assert report["dispatch"]["combined"][other] == getattr(harness.run, other).result.model_dump(mode="json")
    assert report["completed_results_preserved"]


@pytest.mark.parametrize("stage,error", [
    ("authentication", httpx.ConnectError(SECRET_ERROR)),
    ("clock_before", ClockCheckError(SECRET_ERROR)),
    ("dispatch", ValueError(SECRET_ERROR)),
    ("clock_after", ClockCheckError(SECRET_ERROR)),
    ("assess_overlap", ValueError(SECRET_ERROR)),
    ("duplicate", TimeoutError(SECRET_ERROR)),
])
def test_boundary_errors_fail_without_echoing_remote_or_credential_text(harness, capsys, stage, error):
    harness.errors[stage] = error
    code, report = validate(harness)
    assert code == 1 and report["validation"] == "FAIL" and report["phase_gate"] == "NOT_READY"
    assert report["error"] == (
        "Parallel checkpoint failed; inspect clock readiness, connectivity and worker configuration."
    )
    text = harness.output.read_text() + capsys.readouterr().out
    assert all(value not in text for value in (TOKEN, "leaked-token", "password", "sig=private"))
    if stage in {"clock_after", "assess_overlap", "duplicate"}:
        assert_results_preserved(report, harness)


@pytest.mark.parametrize("failure", [
    "missing_confirmation", "conflicting_modes", "missing_config", "invalid_config",
    "invalid_settings", "worker_startup",
])
def test_cli_setup_failure_invalidates_existing_pass_before_any_dispatch(tmp_path, monkeypatch, capsys, failure):
    output = tmp_path / "checkpoint.json"
    output.write_text(json.dumps({"validation": "PASS", "old_dispatch": "stale evidence"}))
    config = tmp_path / "config.json"
    config.write_text(json.dumps({
        "bbox": [-122.45, 48.95, -121.95, 49.3],
        "sentinel1_smoke_start": "2021-11-13T00:00:00Z",
        "sentinel1_smoke_end": "2021-11-18T23:59:59Z",
        "event_end": "2021-11-16T23:59:59Z",
    }))
    args = ["--config", str(config), "--output", str(output)]

    async def unexpected_dispatch(*args, **kwargs):
        raise AssertionError("Setup failure must not reach the validator or submit tasks")

    def broken_settings():
        raise ValueError(SECRET_ERROR)

    def broken_server(*args, **kwargs):
        raise RuntimeError(SECRET_ERROR)

    monkeypatch.setattr(checkpoint, "validate", unexpected_dispatch)
    if failure == "conflicting_modes":
        args += ["--local-check", "--confirm-separate-laptops"]
    elif failure == "worker_startup":
        args += ["--local-check"]
        monkeypatch.setattr(checkpoint.WorkerSettings, "from_env", staticmethod(lambda: object()))
        monkeypatch.setattr(checkpoint, "_server", broken_server)
    elif failure != "missing_confirmation":
        args += ["--confirm-separate-laptops"]
    if failure == "missing_config":
        config.unlink()
    elif failure == "invalid_config":
        config.write_text(SECRET_ERROR)
    elif failure == "invalid_settings":
        monkeypatch.setattr(checkpoint.ControlSettings, "from_env", staticmethod(broken_settings))

    if failure in {"missing_confirmation", "conflicting_modes"}:
        with pytest.raises(SystemExit) as exit_info:
            checkpoint.main(args)
        assert exit_info.value.code == 2
    else:
        assert checkpoint.main(args) == 2
    report = json.loads(output.read_text())
    assert report["validation"] == "FAIL" and report["phase_gate"] == "NOT_READY"
    assert report["failed_stage"] == "setup" and report["dispatch_attempted"] is False
    assert "old_dispatch" not in report and "dispatch" not in report
    captured = capsys.readouterr()
    text = output.read_text() + captured.out + captured.err
    assert all(value not in text for value in (TOKEN, "leaked-token", "password", "sig=private"))
