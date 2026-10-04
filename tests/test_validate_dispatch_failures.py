"""Actual loopback sockets exercise failures that mock HTTP transports miss."""

import json

import pytest

from backend.control.state import DispatchRecord, DispatchRun
from scripts.validate import validate_dispatch_failures as checkpoint


@pytest.mark.parametrize("execution_mode", ["sequential", "parallel"])
def test_terminal_negative_checkpoint_uses_real_tcp_and_preserves_evidence(tmp_path, capsys, execution_mode):
    output = tmp_path / "result.json"
    assert checkpoint.main(["--output", str(output), "--execution-mode", execution_mode]) == 0
    report = json.loads(output.read_text())
    assert report["validation"] == "PASS"
    assert report["execution_mode"] == execution_mode
    assert report["phase"] == ("6" if execution_mode == "parallel" else "5")
    assert report["phase_gate"] == (
        "PENDING_REMOTE_PARALLEL_EXECUTION" if execution_mode == "parallel" else "PENDING_REMOTE_LAPTOPS"
    )
    assert "synthetic" in report["execution_scope"]
    assert "not validate remote" in report["execution_scope"]
    cases = report["cases"]
    assert len(cases) == 3 and all(case["validation"] == "PASS" for case in cases.values())

    delayed = cases["accepted_post_response_timeout"]
    record = DispatchRecord.model_validate(delayed["dispatch"])
    assert record.outcome == "timed_out" and record.acceptance_unknown and not record.accepted
    assert delayed["fixture_accepted_once"]
    assert delayed["fixture_running_when_control_stopped"]
    assert delayed["fixture_completed_after_control_timeout"]
    assert delayed["no_automatic_retry_or_cancellation"]
    assert delayed["requests_received"] == [["GET", "/status"], ["POST", "/tasks"]]
    assert delayed["fixture_terminal_status"]["state"] == "complete"

    preserved = cases["hydro_preserved_when_flood_connection_drops"]
    run = DispatchRun.model_validate(preserved["dispatch"])
    assert run.execution_mode == execution_mode
    assert run.hydro.outcome == "complete" and run.flood.outcome == "transport_error"
    assert run.combined.hydro == run.hydro.result and run.combined.flood is None
    assert run.combined.hydro.summary.rainfall.area_mean_total_accumulation_mm == 5
    if execution_mode == "parallel":
        assert len(preserved["parallel_checks"]) == 4 and all(preserved["parallel_checks"].values())
        assert preserved["hydro_status_before_flood_drop"]["state"] == "complete"
        assert preserved["hydro_completion_observed_at"] <= preserved["flood_connection_dropped_at"]
        assert "overlapping numerical processing on two workers" in report["execution_scope"]
    else:
        assert preserved["parallel_checks"] == {}
    failed = DispatchRecord.model_validate(cases["worker_reported_missing_resource_failure"]["dispatch"])
    assert failed.outcome == "worker_failed" and failed.task_status.state.value == "failed"
    assert failed.result is None
    assert "local fixtures only" in capsys.readouterr().out


def test_fixture_setup_error_leaves_safe_failed_report_without_remote_pass(tmp_path, monkeypatch, capsys):
    def broken(*args, **kwargs):
        raise RuntimeError("Bearer secret-token https://user:password@example.test/?sig=private")

    monkeypatch.setattr(checkpoint, "run_checks", broken)
    output = tmp_path / "result.json"
    assert checkpoint.main(["--output", str(output)]) == 1
    report = json.loads(output.read_text())
    assert report["validation"] == "FAIL"
    assert report["phase_gate"] == "PENDING_REMOTE_LAPTOPS"
    assert report["cases"] == {}
    text = output.read_text() + capsys.readouterr().out
    assert all(secret not in text for secret in ("secret-token", "password", "sig=private"))


def test_failed_case_cannot_be_reported_as_pass(tmp_path, monkeypatch):
    monkeypatch.setattr(checkpoint, "run_checks", lambda *args, **kwargs: {
        "timeout": {"validation": "PASS"}, "retention": {"validation": "FAIL"},
        "worker_failure": {"validation": "PASS"},
    })
    output = tmp_path / "result.json"
    assert checkpoint.main(["--output", str(output)]) == 1
    assert json.loads(output.read_text())["validation"] == "FAIL"


def test_parallel_completion_probe_failure_cannot_claim_retention_order(tmp_path, monkeypatch, capsys):
    def unavailable(*args):
        raise RuntimeError("Bearer probe-secret https://user:password@example.test/?sig=private")

    monkeypatch.setattr(checkpoint, "_observe_hydro_completion", unavailable)
    output = tmp_path / "failed-parallel.json"
    assert checkpoint.main(["--output", str(output), "--execution-mode", "parallel"]) == 1
    report = json.loads(output.read_text())
    assert report["validation"] == "FAIL"
    assert report["phase_gate"] == "PENDING_REMOTE_PARALLEL_EXECUTION"
    preserved = report["cases"]["hydro_preserved_when_flood_connection_drops"]
    assert preserved["validation"] == "FAIL"
    assert preserved["parallel_checks"]["hydro_completed_before_flood_drop"] is False
    assert preserved["hydro_status_before_flood_drop"] is None
    text = output.read_text() + capsys.readouterr().out
    assert all(secret not in text for secret in ("probe-secret", "password", "sig=private"))
