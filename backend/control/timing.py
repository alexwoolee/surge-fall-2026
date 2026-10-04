"""Conservative execution overlap on a common Control clock.

If theta = worker UTC - Control UTC, a clock sample received between Control
times a and b bounds theta by [worker_sample - b, worker_sample - a]. We
intersect pre/post samples under an explicit stable-clock assumption; worker
execution [s, e] then certainly includes [s - lower, e - upper] in Control time.
No wall-clock synchronization or worker processing delay is performed here.
"""

import asyncio
from datetime import datetime, timedelta, timezone
import json
import math
import time

import httpx

from backend.control.state import DispatchRun
from backend.shared.contracts import WorkerClock
from backend.shared.settings import ControlSettings


MAX_CLOCK_RESPONSE_BYTES = 64 * 1024
MAX_CLOCK_UNCERTAINTY_SECONDS = 0.1
CONTROL_CLOCK_JUMP_TOLERANCE_SECONDS = 0.020
_ROLES = {"hydro-worker": "hydrometeorology", "flood-worker": "surface_water_and_terrain"}
_SAMPLE_KEYS = {
    "worker_clock", "control_before", "control_after", "elapsed_monotonic_seconds",
    "offset_lower_seconds", "offset_upper_seconds",
}
_LIMITATIONS = [
    "Bounds assume each worker clock and the Control clock remain stable throughout the run; transient jumps that reverse between samples are not observable.",
    "The maximum accepted offset uncertainty is 0.1 seconds; Control UTC versus monotonic request duration may differ by at most 0.020 seconds.",
    "Worker execution timestamps and process identities are trusted observations, not independent attestation of physical machines.",
]


class ClockCheckError(Exception):
    """Sanitized calibration failure; never contains endpoint credentials."""


def _now():
    return datetime.now(timezone.utc)


def _reject_constant(value):
    raise ValueError("Nonfinite clock value")


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate clock field")
        result[key] = value
    return result


def _timestamp(value):
    if not isinstance(value, str):
        raise ValueError("Clock time requires an ISO UTC string")
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None or result.utcoffset() != timedelta(0):
        raise ValueError("Clock time requires UTC")
    return result.astimezone(timezone.utc)


def _number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError("Clock bound must be finite")
    return float(value)


def _sample_parts(sample, role):
    """Recompute bounds instead of trusting saved derived values."""
    if not isinstance(sample, dict) or set(sample) != _SAMPLE_KEYS:
        raise ValueError("Invalid clock sample fields")
    clock = WorkerClock.model_validate(sample["worker_clock"])
    if clock.worker_id != role or clock.analysis_type != _ROLES[role]:
        raise ValueError("Clock worker does not match endpoint")
    before, after = _timestamp(sample["control_before"]), _timestamp(sample["control_after"])
    elapsed = _number(sample["elapsed_monotonic_seconds"])
    wall_elapsed = (after - before).total_seconds()
    if not 0 <= elapsed <= 120 or wall_elapsed < 0:
        raise ValueError("Clock request times are invalid")
    if abs(wall_elapsed - elapsed) > CONTROL_CLOCK_JUMP_TOLERANCE_SECONDS:
        raise ValueError("Control clock changed during sampling")
    lower = (clock.sampled_at - after).total_seconds()
    upper = (clock.sampled_at - before).total_seconds()
    if not (math.isclose(_number(sample["offset_lower_seconds"]), lower, rel_tol=0, abs_tol=1e-9)
            and math.isclose(_number(sample["offset_upper_seconds"]), upper, rel_tol=0, abs_tol=1e-9)):
        raise ValueError("Saved clock bounds do not match observations")
    return clock, before, after, lower, upper


async def _read_clock(client):
    async with client.stream("GET", "/clock") as response:
        if response.status_code != 200:
            raise ValueError("Clock endpoint rejected the request")
        content_type = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        if content_type != "application/json" and not (
            content_type.startswith("application/") and content_type.endswith("+json")
        ):
            raise ValueError("Clock endpoint did not return JSON")
        declared = response.headers.get("content-length")
        if declared is not None and not 0 <= int(declared) <= MAX_CLOCK_RESPONSE_BYTES:
            raise ValueError("Clock response exceeds its size limit")
        raw = bytearray()
        async for chunk in response.aiter_bytes(chunk_size=4096):
            if len(raw) + len(chunk) > MAX_CLOCK_RESPONSE_BYTES:
                raise ValueError("Clock response exceeds its size limit")
            raw.extend(chunk)
        if declared is not None and len(raw) != int(declared) and not response.headers.get("content-encoding"):
            raise ValueError("Clock response is truncated")
        return WorkerClock.model_validate(json.loads(
            raw, parse_constant=_reject_constant, object_pairs_hook=_unique_object,
        ))


async def sample_clocks(settings: ControlSettings, *, samples=3, transport_factory=None) -> dict:
    """Collect bounded authenticated observations without submitting any tasks.

    The default collects three observations per worker. The optional transport
    factory receives a WorkerEndpoint and exists for deterministic HTTP tests.
    Every reported error is fixed text, independent of remote exception bodies.
    """
    if not isinstance(settings, ControlSettings) or isinstance(samples, bool) or not isinstance(samples, int) or not 1 <= samples <= 10:
        raise ClockCheckError("Clock sampling requires valid Control settings and 1 to 10 samples.")

    async def sample_worker(endpoint):
        try:
            headers = {"Accept": "application/json", "Cache-Control": "no-cache"}
            transport = (transport_factory(endpoint) if transport_factory is not None else
                         httpx.AsyncHTTPTransport(local_address=settings.local_address, trust_env=False))
            async with httpx.AsyncClient(
                base_url=endpoint.url, headers=headers, transport=transport,
                timeout=httpx.Timeout(settings.request_timeout), follow_redirects=False, trust_env=False,
            ) as client:
                observations, identity = [], None
                for _ in range(samples):
                    before = _now()
                    monotonic_before = time.monotonic()
                    async with asyncio.timeout(settings.request_timeout):
                        clock = await _read_clock(client)
                    elapsed = time.monotonic() - monotonic_before
                    after = _now()
                    if elapsed >= settings.request_timeout:
                        raise TimeoutError
                    sample = {
                        "worker_clock": clock.model_dump(mode="json"),
                        "control_before": before.isoformat(), "control_after": after.isoformat(),
                        "elapsed_monotonic_seconds": elapsed,
                        "offset_lower_seconds": (clock.sampled_at - after).total_seconds(),
                        "offset_upper_seconds": (clock.sampled_at - before).total_seconds(),
                    }
                    _sample_parts(sample, endpoint.expected_worker_id)
                    current = clock.execution_host, clock.process_instance_id
                    if identity is not None and current != identity:
                        raise ValueError("Worker process changed during clock sampling")
                    identity = current
                    observations.append(sample)
                lower = max(item["offset_lower_seconds"] for item in observations)
                upper = min(item["offset_upper_seconds"] for item in observations)
                if lower > upper or upper - lower > MAX_CLOCK_UNCERTAINTY_SECONDS + 1e-9:
                    raise ValueError("Clock batch has inconsistent or uncertain offset bounds")
                return observations
        except Exception:
            raise ClockCheckError("Worker clock sampling failed; check reachability, clock stability and the worker version.") from None

    tasks = [asyncio.create_task(sample_worker(endpoint)) for endpoint in (settings.hydro, settings.flood)]
    try:
        values = await asyncio.gather(*tasks)
    except BaseException:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        raise
    return dict(zip(_ROLES, values))


def assess_overlap(run: DispatchRun, before: dict, after: dict) -> dict:
    """Prove a positive conservative intersection or return a sanitized failure."""
    report = {
        "passed": False, "checks": {}, "offset_bounds": {}, "raw_intervals": {},
        "conservative_intervals": {}, "guaranteed_overlap_seconds": 0.0,
        "max_clock_uncertainty_seconds": MAX_CLOCK_UNCERTAINTY_SECONDS,
        "limitations": list(_LIMITATIONS), "errors": [],
    }

    def require(condition, name, message):
        report["checks"][name] = bool(condition)
        if not condition:
            raise ClockCheckError(message)

    try:
        require(isinstance(run, DispatchRun), "valid_dispatch", "A validated dispatch run is required.")
        run = DispatchRun.model_validate(run.model_dump(mode="json"))
        require(run.execution_mode == "parallel", "parallel_dispatch", "The run must explicitly use parallel dispatch.")
        require(isinstance(before, dict) and isinstance(after, dict)
                and set(before) == set(after) == set(_ROLES),
                "clock_sample_roles", "Clock samples for both worker roles are required before and after the run.")
        intervals = []
        for record in (run.hydro, run.flood):
            role = record.worker_id
            status = record.task_status
            require(record.accepted and not record.acceptance_unknown and record.outcome == "complete"
                    and record.result is not None and record.result.status == "complete"
                    and status is not None and status.state.value == "complete"
                    and record.submitted_at is not None and record.worker_status is not None,
                    f"{role}_complete", "Both workers must retain acknowledged complete results.")
            groups = []
            for phase, data in (("before", before), ("after", after)):
                require(isinstance(data[role], list) and 1 <= len(data[role]) <= 10,
                        f"{role}_{phase}_samples", "Each worker requires bounded pre/post clock sample lists.")
                parsed = [_sample_parts(sample, role) for sample in data[role]]
                require(all(a[2] <= b[1] for a, b in zip(parsed, parsed[1:])),
                        f"{role}_{phase}_ordered", "Clock requests within a worker batch must be ordered.")
                batch_lower, batch_upper = max(item[3] for item in parsed), min(item[4] for item in parsed)
                require(batch_lower <= batch_upper,
                        f"{role}_{phase}_clock_bounds", "Clock bounds within a calibration batch disagree.")
                require(batch_upper - batch_lower <= MAX_CLOCK_UNCERTAINTY_SECONDS + 1e-9,
                        f"{role}_{phase}_bounded_uncertainty", "Calibration uncertainty exceeds the 0.1 second policy limit.")
                groups.append(parsed)
            first, last = groups
            all_samples = first + last
            expected_identity = status.execution_host, status.process_instance_id
            observed_statuses = [record.worker_status, status] + [item.status for item in record.observations]
            require(all(expected_identity) and all(
                (item.execution_host, item.process_instance_id) == expected_identity for item in observed_statuses
            ) and all((item[0].execution_host, item[0].process_instance_id) == expected_identity for item in all_samples),
                f"{role}_stable_identity", "Clock samples and task observations must identify the same worker process.")
            require(all(item[2] <= record.submitted_at for item in first)
                    and all(item[1] >= record.control_completed_at for item in last),
                    f"{role}_samples_bracket_run", "Clock samples must precede submission and follow Control completion.")
            lower, upper = max(item[3] for item in all_samples), min(item[4] for item in all_samples)
            require(lower <= upper, f"{role}_stable_clock_bounds", "Pre/post clock bounds disagree; clock stability is unproven.")
            width = upper - lower
            report["offset_bounds"][role] = {
                "lower_seconds": lower, "upper_seconds": upper, "uncertainty_seconds": width,
                "meaning": "worker UTC minus Control UTC",
            }
            require(width <= MAX_CLOCK_UNCERTAINTY_SECONDS + 1e-9,
                    f"{role}_bounded_uncertainty", "Clock uncertainty exceeds the 0.1 second policy limit.")
            require(status.started_at is not None and status.completed_at is not None
                    and status.completed_at > status.started_at,
                    f"{role}_positive_execution", "Worker execution intervals must have positive duration.")
            report["raw_intervals"][role] = {
                "started_at": status.started_at.isoformat(), "completed_at": status.completed_at.isoformat(),
                "duration_seconds": (status.completed_at - status.started_at).total_seconds(),
            }
            # One common offset must place the entire execution inside the
            # observed submission/completion window. Checking each endpoint
            # separately could accept a task longer than that entire window.
            feasible_lower = max(lower, (status.completed_at - record.control_completed_at).total_seconds())
            feasible_upper = min(upper, (status.started_at - record.submitted_at).total_seconds())
            require(feasible_lower <= feasible_upper,
                    f"{role}_execution_inside_control_window",
                    "Worker execution times cannot fit the observed Control submission/completion window.")
            start = max(record.submitted_at, status.started_at - timedelta(seconds=lower))
            end = min(record.control_completed_at, status.completed_at - timedelta(seconds=upper))
            report["conservative_intervals"][role] = {
                "started_at": start.isoformat(), "completed_at": end.isoformat(),
                "duration_seconds": (end - start).total_seconds(),
            }
            intervals.append((start, end))
        overlap = (min(item[1] for item in intervals) - max(item[0] for item in intervals)).total_seconds()
        report["guaranteed_overlap_seconds"] = max(0.0, overlap)
        require(overlap > 0, "positive_guaranteed_overlap", "The calibrated worker intervals do not prove positive execution overlap.")
        report["passed"] = True
    except ClockCheckError as exc:
        report["errors"].append(str(exc))
    except Exception:
        report["checks"]["valid_observations"] = False
        report["errors"].append("The dispatch or clock observations are invalid; overlap is unproven.")
    return report
