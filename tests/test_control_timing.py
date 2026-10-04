"""Clock bounds prove actual intervals, not merely concurrent HTTP calls."""

import asyncio
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json

import httpx
import pytest

from backend.control import timing
from backend.control.state import DispatchRun
from backend.control.timing import ClockCheckError, assess_overlap, sample_clocks
from backend.shared.settings import ControlSettings, WorkerEndpoint
from test_contracts import flood_resources, flood_result, hydro_result


BASE = datetime(2026, 1, 1, tzinfo=timezone.utc)
TOKEN = "private-clock-test-token"
ROLES = {"hydro-worker": "hydrometeorology", "flood-worker": "surface_water_and_terrain"}
INSTANCES = {
    "hydro-worker": "11111111-1111-1111-1111-111111111111",
    "flood-worker": "22222222-2222-2222-2222-222222222222",
}


def utc(seconds):
    return (BASE + timedelta(seconds=seconds)).isoformat()


def clock(role, timestamp):
    return {
        "worker_id": role, "analysis_type": ROLES[role],
        "execution_host": role + "-host", "process_instance_id": INSTANCES[role],
        "sampled_at": timestamp,
    }


def sample(role, when, offset=0, rtt=0.02):
    value = {
        "worker_clock": clock(role, utc(when + rtt / 2 + offset)),
        "control_before": utc(when), "control_after": utc(when + rtt),
        "elapsed_monotonic_seconds": rtt,
    }
    # Derive from the serialized microsecond timestamps exactly as the sampler.
    remote = datetime.fromisoformat(value["worker_clock"]["sampled_at"])
    value["offset_lower_seconds"] = (remote - datetime.fromisoformat(value["control_after"])).total_seconds()
    value["offset_upper_seconds"] = (remote - datetime.fromisoformat(value["control_before"])).total_seconds()
    return value


def scenario(hydro_result, flood_result, *, offsets=(0, 0), intervals=((12, 20), (14, 24)), rtt=0.02):
    hydro, flood = deepcopy(hydro_result), deepcopy(flood_result)
    # The timing fixture aligns the two independent tiny processor fixture AOIs.
    hydro["bbox"] = flood["bbox"]
    for evidence in hydro["evidence"].values():
        evidence["bbox"] = flood["bbox"]
    records, before, after = {}, {}, {}
    for result, offset, (start, end) in zip((hydro, flood), offsets, intervals):
        role = result["worker_id"]
        identity = {key: value for key, value in clock(role, utc(0)).items() if key != "sampled_at"}
        status = {
            **identity, "task_id": result["task_id"], "state": "complete",
            "received_at": utc(start + offset - 0.01), "started_at": utc(start + offset),
            "completed_at": utc(end + offset),
        }
        records[role] = {
            "worker_id": role, "analysis_type": ROLES[role], "task_id": result["task_id"],
            "outcome": "complete", "control_started_at": utc(9), "control_completed_at": utc(30),
            "submitted_at": utc(10), "accepted": True, "acceptance_unknown": False,
            "worker_status": {**identity, "status": "idle", "retained_tasks": 0, "capacity": 128},
            "task_status": status, "observations": [{"observed_at": utc(30), "status": status}],
            "result": result,
        }
        before[role] = [sample(role, t, offset, rtt) for t in (0, 1, 2)]
        after[role] = [sample(role, t, offset, rtt) for t in (40, 41, 42)]
    run = DispatchRun.model_validate({
        "task_id": hydro["task_id"], "execution_mode": "parallel", "control_started_at": utc(9),
        "control_completed_at": utc(31), "hydro": records["hydro-worker"], "flood": records["flood-worker"],
        "combined": {"task_id": hydro["task_id"], "hydro": hydro, "flood": flood},
    })
    return run, before, after


def settings(**updates):
    return ControlSettings(
        WorkerEndpoint("http://hydro.invalid:8002", "hydro-worker", TOKEN),
        WorkerEndpoint("http://flood.invalid:8003", "flood-worker", TOKEN), **updates,
    )


def factory(handler):
    return lambda endpoint: httpx.MockTransport(lambda request: handler(endpoint, request))


def success(endpoint, request):
    return httpx.Response(200, json=clock(endpoint.expected_worker_id, datetime.now(timezone.utc).isoformat()))


@pytest.mark.parametrize("offsets", [(0, 0), (2, -3), (3600, -3600)])
def test_overlap_uses_correct_offset_sign_and_allows_known_stable_skew(hydro_result, flood_result, offsets):
    run, before, after = scenario(hydro_result, flood_result, offsets=offsets)
    report = assess_overlap(run, before, after)
    assert report["passed"], report
    assert all(report["checks"].values())
    assert report["guaranteed_overlap_seconds"] == pytest.approx(5.98)
    for role, offset in zip(ROLES, offsets):
        assert report["offset_bounds"][role]["lower_seconds"] == pytest.approx(offset - 0.01)
        assert report["offset_bounds"][role]["upper_seconds"] == pytest.approx(offset + 0.01)
    assert report["conservative_intervals"]["hydro-worker"]["started_at"] == utc(12.01)
    assert report["conservative_intervals"]["hydro-worker"]["completed_at"] == utc(19.99)
    json.dumps(report, allow_nan=False)


def test_apparent_raw_overlap_is_rejected_after_skew_correction(hydro_result, flood_result):
    run, before, after = scenario(hydro_result, flood_result, offsets=(0, -4), intervals=((12, 14), (16, 18)))
    assert run.hydro.task_status.started_at == run.flood.task_status.started_at
    report = assess_overlap(run, before, after)
    assert not report["passed"]
    assert report["guaranteed_overlap_seconds"] == 0
    assert not report["checks"]["positive_guaranteed_overlap"]


@pytest.mark.parametrize("rtt, passes", [(0.1, True), (0.100002, False), (0.2, False)])
def test_clock_uncertainty_policy(hydro_result, flood_result, rtt, passes):
    run, before, after = scenario(hydro_result, flood_result, rtt=rtt)
    report = assess_overlap(run, before, after)
    assert report["passed"] is passes
    assert report["max_clock_uncertainty_seconds"] == 0.1


@pytest.mark.parametrize("intervals, rtt", [(((12, 14), (16, 18)), 0.02), (((12, 14), (14, 18)), 0)])
def test_no_execution_overlap_or_zero_boundary_cannot_pass(hydro_result, flood_result, intervals, rtt):
    report = assess_overlap(*scenario(hydro_result, flood_result, intervals=intervals, rtt=rtt))
    assert not report["passed"]
    assert report["guaranteed_overlap_seconds"] == 0


def test_sequential_dispatch_does_not_qualify(hydro_result, flood_result):
    run, before, after = scenario(hydro_result, flood_result)
    # The proof revalidates even a model modified without Pydantic validation.
    run = run.model_copy(update={"execution_mode": "sequential"})
    assert not assess_overlap(run, before, after)["passed"]


@pytest.mark.parametrize("intervals", [
    ((3, 6), (4, 7)),  # Old completed work, despite matching current task IDs.
    ((32, 36), (33, 37)),  # Future completion outside Control's observation.
    ((9.995, 30.01), (14, 24)),  # Each endpoint fits individually; no single offset fits both.
])
def test_impossible_execution_outside_control_window_cannot_prove_overlap(hydro_result, flood_result, intervals):
    report = assess_overlap(*scenario(hydro_result, flood_result, intervals=intervals))
    assert not report["passed"]
    assert not report["checks"]["hydro-worker_execution_inside_control_window"]


@pytest.mark.parametrize("intervals", [
    ((9.995, 20), (14, 24)),  # A possible clock offset puts the start after submission.
    ((12, 30.005), (14, 24)),  # A possible offset puts completion before Control's final read.
    ((10, 30), (14, 24)),  # Exact observation boundaries are valid with one common offset.
])
def test_valid_boundary_clock_uncertainty_remains_accepted(hydro_result, flood_result, intervals):
    run, before, after = scenario(hydro_result, flood_result, intervals=intervals)
    report = assess_overlap(run, before, after)
    assert report["passed"], report
    for role, value in report["conservative_intervals"].items():
        record = run.hydro if role == "hydro-worker" else run.flood
        assert datetime.fromisoformat(value["started_at"]) >= record.submitted_at
        assert datetime.fromisoformat(value["completed_at"]) <= record.control_completed_at


@pytest.mark.parametrize("field,value", [
    ("execution_host", "different-host"),
    ("process_instance_id", "33333333-3333-3333-3333-333333333333"),
])
def test_clock_restart_or_host_change_cannot_pass(hydro_result, flood_result, field, value):
    run, before, after = scenario(hydro_result, flood_result)
    after["hydro-worker"][1]["worker_clock"][field] = value
    report = assess_overlap(run, before, after)
    assert not report["passed"]
    assert not report["checks"]["hydro-worker_stable_identity"]


def test_pre_post_disjoint_bounds_reject_clock_change(hydro_result, flood_result):
    run, before, after = scenario(hydro_result, flood_result)
    after["hydro-worker"] = [sample("hydro-worker", t, offset=1) for t in (40, 41, 42)]
    report = assess_overlap(run, before, after)
    assert not report["passed"]
    assert not report["checks"]["hydro-worker_stable_clock_bounds"]


@pytest.mark.parametrize("phase,times", [("before", (10, 11, 12)), ("after", (25, 26, 27))])
def test_calibration_must_bracket_dispatch(hydro_result, flood_result, phase, times):
    run, before, after = scenario(hydro_result, flood_result)
    (before if phase == "before" else after)["hydro-worker"] = [sample("hydro-worker", t) for t in times]
    report = assess_overlap(run, before, after)
    assert not report["passed"]
    assert not report["checks"]["hydro-worker_samples_bracket_run"]


@pytest.mark.parametrize("key,value", [
    ("offset_lower_seconds", -100), ("offset_upper_seconds", 100),
    ("elapsed_monotonic_seconds", 0.2), ("elapsed_monotonic_seconds", float("nan")),
    ("control_before", "private-clock-test-token"), ("control_after", "2026-01-01T00:00:00"),
    ("worker_clock", {"token": TOKEN}), ("unexpected", TOKEN),
])
def test_invalid_saved_samples_fail_without_leaking_values(hydro_result, flood_result, key, value):
    run, before, after = scenario(hydro_result, flood_result)
    before["hydro-worker"][0][key] = value
    report = assess_overlap(run, before, after)
    assert not report["passed"]
    assert TOKEN not in json.dumps(report)


@pytest.mark.parametrize("mutation", ["missing_status", "missing_result", "unaccepted", "zero_duration", "missing_samples"])
def test_incomplete_execution_evidence_cannot_pass(hydro_result, flood_result, mutation):
    run, before, after = scenario(hydro_result, flood_result)
    if mutation == "missing_samples":
        before["hydro-worker"] = []
    elif mutation == "zero_duration":
        status = run.hydro.task_status.model_copy(update={"completed_at": run.hydro.task_status.started_at})
        record = run.hydro.model_copy(update={
            "task_status": status,
            "observations": [run.hydro.observations[-1].model_copy(update={"status": status})],
        })
        run = run.model_copy(update={"hydro": record})
    else:
        field, value = {"missing_status": ("task_status", None), "missing_result": ("result", None), "unaccepted": ("accepted", False)}[mutation]
        run = run.model_copy(update={"hydro": run.hydro.model_copy(update={field: value})})
    assert not assess_overlap(run, before, after)["passed"]


@pytest.mark.parametrize("token", [None, "", TOKEN, "bad\r\nvalue", "☃", 123, {"legacy": True}])
def test_sampler_ignores_legacy_tokens_and_does_not_submit_tasks(token):
    calls = []

    def handler(endpoint, request):
        calls.append((endpoint.expected_worker_id, request.method, request.url.path))
        assert "Authorization" not in request.headers
        assert request.headers["Cache-Control"] == "no-cache"
        return success(endpoint, request)

    configured = settings()
    configured = ControlSettings(
        hydro=WorkerEndpoint(configured.hydro.url, "hydro-worker", token),
        flood=WorkerEndpoint(configured.flood.url, "flood-worker", token),
    )
    observations = asyncio.run(sample_clocks(configured, transport_factory=factory(handler)))
    assert set(observations) == set(ROLES)
    assert len(calls) == 6 and all(method == "GET" and path == "/clock" for _, method, path in calls)
    assert TOKEN not in json.dumps(observations)
    for role, values in observations.items():
        assert len(values) == 3
        for value in values:
            timing._sample_parts(value, role)
            assert value["offset_lower_seconds"] <= 0 <= value["offset_upper_seconds"]


@pytest.mark.parametrize("fault", ["401", "redirect", "html", "truncated", "too_large", "bad_json", "wrong_role", "transport", "restart"])
def test_sampler_sanitizes_protocol_transport_and_identity_failures(fault):
    calls = {}

    def handler(endpoint, request):
        calls[endpoint.expected_worker_id] = calls.get(endpoint.expected_worker_id, 0) + 1
        if fault == "401":
            return httpx.Response(401, text=TOKEN)
        if fault == "redirect":
            return httpx.Response(307, headers={"location": "http://private.invalid/" + TOKEN})
        if fault == "html":
            return httpx.Response(200, text=TOKEN)
        if fault == "truncated":
            return httpx.Response(200, json=clock(endpoint.expected_worker_id, utc(0)), headers={"content-length": "64000"})
        if fault == "too_large":
            return httpx.Response(200, content=b"x" * 65537, headers={"content-type": "application/json"})
        if fault == "bad_json":
            return httpx.Response(200, content=TOKEN.encode(), headers={"content-type": "application/json"})
        if fault == "transport":
            raise httpx.ConnectError(TOKEN, request=request)
        role = endpoint.expected_worker_id
        value = clock("flood-worker" if fault == "wrong_role" else role, utc(0))
        if fault == "restart" and calls[role] > 1:
            value["process_instance_id"] = "33333333-3333-3333-3333-333333333333"
        return httpx.Response(200, json=value)

    with pytest.raises(ClockCheckError) as error:
        asyncio.run(sample_clocks(settings(), transport_factory=factory(handler)))
    assert TOKEN not in str(error.value)
    assert "private.invalid" not in str(error.value)


def test_sampler_enforces_timeout_even_with_custom_transport():
    async def handler(request):
        await asyncio.Event().wait()

    with pytest.raises(ClockCheckError):
        asyncio.run(sample_clocks(settings(request_timeout=0.1), transport_factory=lambda _: httpx.MockTransport(handler)))


def test_sampler_rejects_control_wall_clock_jump(monkeypatch):
    ticks = iter([BASE, BASE + timedelta(seconds=1), BASE, BASE + timedelta(seconds=1)])
    monkeypatch.setattr(timing, "_now", lambda: next(ticks))
    with pytest.raises(ClockCheckError):
        asyncio.run(sample_clocks(settings(), samples=1, transport_factory=factory(success)))


def test_sampler_rejects_disjoint_bounds_within_batch():
    counts = {}

    def handler(endpoint, request):
        role = endpoint.expected_worker_id
        counts[role] = counts.get(role, 0) + 1
        timestamp = datetime.now(timezone.utc) + timedelta(seconds=counts[role])
        return httpx.Response(200, json=clock(role, timestamp.isoformat()))

    with pytest.raises(ClockCheckError):
        asyncio.run(sample_clocks(settings(), transport_factory=factory(handler)))


def test_sampler_rejects_uncertain_calibration_before_dispatch():
    async def handler(request):
        role = "hydro-worker" if request.url.host == "hydro.invalid" else "flood-worker"
        timestamp = datetime.now(timezone.utc).isoformat()
        # Emulate slow HTTP calibration only; no worker computation is delayed.
        await asyncio.sleep(0.11)
        return httpx.Response(200, json=clock(role, timestamp))

    with pytest.raises(ClockCheckError):
        asyncio.run(sample_clocks(settings(), samples=1, transport_factory=lambda _: httpx.MockTransport(handler)))


def test_sampler_limits_streamed_response_without_content_length():
    class OversizedStream(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b"x" * 40000
            yield b"x" * 40000

    def handler(endpoint, request):
        return httpx.Response(200, headers={"content-type": "application/json"}, stream=OversizedStream())

    with pytest.raises(ClockCheckError):
        asyncio.run(sample_clocks(settings(), samples=1, transport_factory=factory(handler)))


def test_sampler_binds_configured_source_and_disables_proxy_and_redirects(monkeypatch):
    transports, clients = [], []
    real_client = httpx.AsyncClient

    def make_transport(**kwargs):
        transports.append(kwargs)
        return httpx.MockTransport(lambda request: success(
            WorkerEndpoint(str(request.url.copy_with(path="")), "hydro-worker" if request.url.host == "hydro.invalid" else "flood-worker"), request,
        ))

    def make_client(**kwargs):
        clients.append(kwargs)
        return real_client(**kwargs)

    monkeypatch.setattr(timing.httpx, "AsyncHTTPTransport", make_transport)
    monkeypatch.setattr(timing.httpx, "AsyncClient", make_client)
    asyncio.run(sample_clocks(settings(local_address="100.100.3.5"), samples=1))
    assert transports == [{"local_address": "100.100.3.5", "trust_env": False}] * 2
    assert all(value["trust_env"] is False and value["follow_redirects"] is False for value in clients)


@pytest.mark.parametrize("count", [True, 0, 11, 1.5, "3"])
def test_sampler_requires_bounded_sample_count(count):
    with pytest.raises(ClockCheckError):
        asyncio.run(sample_clocks(settings(), samples=count))
