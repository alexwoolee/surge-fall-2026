"""Exercise Control failure handling over real loopback TCP with small fixtures.

This is a negative HTTP checkpoint, not physical remote execution or a real
environmental-data gate. It needs neither public datasets nor Earthdata login.
"""

import argparse
import asyncio
from contextlib import contextmanager
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import secrets
import socket
import tempfile
from threading import Event, Lock, Thread
from uuid import uuid4

from backend.control.coordinator import WorkerClient, run_analysis
from backend.control.main import save_json
from backend.shared.contracts import AnalysisTask, TaskStatus, WorkerStatus
from backend.shared.settings import ControlSettings, ROOT, WorkerEndpoint
from backend.shared.status import TaskState
from scripts.validate.validate_worker_apis import _server, _synthetic_hydro


_BBOX = (-122.4, 49.0, -122.3, 49.1)
_SCOPE = (
    "Local loopback TCP using synthetic HDF5 and controlled fault endpoints. "
    "This does not validate remote laptops, live environmental data or parallel execution."
)


def _now():
    return datetime.now(timezone.utc)


class _FaultState:
    def __init__(self):
        self.lock = Lock()
        self.release = Event()
        self.completed = Event()
        self.requests = []
        self.accepted_count = 0
        self.task_status = None


@contextmanager
def _fault_endpoint(mode, token):
    """Bind an ephemeral loopback port for a delayed POST or dropped TCP reply.

    The delayed fixture marks acceptance before waiting for the test to release
    it. This deterministically proves that a client timeout does not stop the
    accepted operation. No environmental measurements are fabricated here.
    """
    if mode not in {"delayed_post", "disconnect"}:
        raise ValueError("Unsupported fault fixture.")
    state = _FaultState()
    worker_id = "hydro-worker" if mode == "delayed_post" else "flood-worker"
    analysis_type = "hydrometeorology" if mode == "delayed_post" else "surface_water_and_terrain"
    identity = {"execution_host": "loopback-fault-fixture", "process_instance_id": str(uuid4())}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            # HTTP headers and authentication values never enter the checkpoint.
            pass

        def _begin(self):
            with state.lock:
                state.requests.append((self.command, self.path))
            if self.headers.get("Authorization") != f"Bearer {token}":
                self._reply(401, {"detail": "Authentication required."})
                return False
            return True

        def _reply(self, code, value):
            body = json.dumps(value, allow_nan=False).encode("utf-8")
            try:
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            except OSError:
                # The delayed client's connection may already have timed out.
                pass

        def do_GET(self):
            if not self._begin():
                return
            if mode == "disconnect":
                # A real accepted TCP connection ends without an HTTP response.
                self.close_connection = True
                try:
                    self.connection.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
                return
            if self.path != "/status":
                return self._reply(404, {"detail": "Fixture endpoint not found."})
            self._reply(200, WorkerStatus(
                worker_id=worker_id, analysis_type=analysis_type,
                status="idle", retained_tasks=0, capacity=1, **identity,
            ).model_dump(mode="json"))

        def do_POST(self):
            if not self._begin():
                return
            if mode != "delayed_post" or self.path != "/tasks":
                return self._reply(404, {"detail": "Fixture endpoint not found."})
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 64 * 1024:
                    raise ValueError
                task = AnalysisTask.model_validate_json(self.rfile.read(length))
            except ValueError:
                return self._reply(422, {"detail": "Invalid fixture task."})
            started = _now()
            with state.lock:
                state.accepted_count += 1
                state.task_status = TaskStatus(
                    task_id=task.task_id, worker_id=worker_id, analysis_type=analysis_type,
                    state="processing", received_at=started, started_at=started, **identity,
                )
            # The caller releases this only after recording the Control timeout.
            if not state.release.wait(timeout=10):
                return
            with state.lock:
                state.task_status = state.task_status.model_copy(update={
                    "state": TaskState.COMPLETE, "completed_at": _now(),
                })
                reply = state.task_status.model_dump(mode="json")
            state.completed.set()
            self._reply(202, reply)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    thread = Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
    thread.start()
    endpoint = WorkerEndpoint(f"http://127.0.0.1:{server.server_port}", worker_id, token)
    try:
        yield endpoint, state
    finally:
        state.release.set()
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def _tasks(gpm_resources, smap_resource):
    task_id = "negative-http-" + str(uuid4())
    bbox = dict(zip(("west", "south", "east", "north"), _BBOX))
    return (
        AnalysisTask(task_id=task_id, analysis_type="hydrometeorology", bbox=bbox,
                     gpm_resources=gpm_resources, smap_resource=smap_resource),
        AnalysisTask(task_id=task_id, analysis_type="surface_water_and_terrain", bbox=bbox,
                     start_time="2021-11-13T00:00:00Z", end_time="2021-11-18T23:59:59Z"),
    )


def run_checks(folder, token):
    """Run all three failure scenarios without catalogs, credentials or HTML."""
    settings, gpm, smap = _synthetic_hydro(folder, _BBOX)
    cases = {}

    task, _ = _tasks(gpm, smap)
    with _fault_endpoint("delayed_post", token) as (endpoint, state):
        record = asyncio.run(WorkerClient(
            endpoint, request_timeout=1, task_timeout=5, poll_interval=0.01,
        ).run(task))
        with state.lock:
            accepted_before_timeout = state.accepted_count == 1
            still_running = state.task_status is not None and state.task_status.state.value == "processing"
        no_completion_at_timeout = not state.completed.is_set()
        state.release.set()
        continued = state.completed.wait(timeout=2)
        with state.lock:
            request_log = list(state.requests)
            terminal = state.task_status.model_dump(mode="json") if state.task_status else None
        no_retry_or_cancel = request_log == [("GET", "/status"), ("POST", "/tasks")]
        passed = (
            record.outcome == "timed_out" and record.acceptance_unknown and not record.accepted
            and record.result is None and accepted_before_timeout and still_running
            and no_completion_at_timeout and continued and no_retry_or_cancel
        )
        cases["accepted_post_response_timeout"] = {
            "validation": "PASS" if passed else "FAIL", "dispatch": record.model_dump(mode="json"),
            "fixture_accepted_once": accepted_before_timeout,
            "fixture_running_when_control_stopped": still_running and no_completion_at_timeout,
            "fixture_completed_after_control_timeout": continued,
            "no_automatic_retry_or_cancellation": no_retry_or_cancel,
            "requests_received": request_log, "fixture_terminal_status": terminal,
        }

    with _server("hydro", settings, token, folder) as client:
        hydro_endpoint = WorkerEndpoint(str(client.base_url), "hydro-worker", token)
        with _fault_endpoint("disconnect", token) as (flood_endpoint, state):
            tasks = _tasks(gpm, smap)
            control = ControlSettings(hydro_endpoint, flood_endpoint, request_timeout=2,
                                      task_timeout=10, poll_interval=0.01)
            run = asyncio.run(run_analysis(*tasks, control))
            with state.lock:
                request_log = list(state.requests)
            hydro = run.hydro.result
            passed = (
                run.hydro.outcome == "complete" and hydro is not None
                and hydro.summary.rainfall.area_mean_total_accumulation_mm == 5
                and run.flood.outcome == "transport_error" and run.flood.result is None
                and run.combined.hydro == hydro and run.combined.flood is None
                and bool(run.combined.errors) and request_log == [("GET", "/status")]
            )
            cases["hydro_preserved_when_flood_connection_drops"] = {
                "validation": "PASS" if passed else "FAIL", "dispatch": run.model_dump(mode="json"),
                "data_source": "synthetic_HDF5_with_known_5_mm_rainfall",
                "fault_endpoint_requests": request_log,
            }

        missing, _ = _tasks(["missing-fixture-resource.HDF5"], smap)
        failed = asyncio.run(WorkerClient(
            hydro_endpoint, request_timeout=2, task_timeout=10, poll_interval=0.01,
        ).run(missing))
        status = failed.task_status
        passed = (
            failed.outcome == "worker_failed" and failed.accepted and not failed.acceptance_unknown
            and failed.result is None and status is not None and status.state.value == "failed"
            and status.started_at is not None and status.completed_at is not None
        )
        cases["worker_reported_missing_resource_failure"] = {
            "validation": "PASS" if passed else "FAIL", "dispatch": failed.model_dump(mode="json"),
            "trigger": "A valid basename is deliberately absent from the temporary Hydro resource folder.",
        }
    return cases


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "outputs/debug/dispatch-failures/result.json")
    args = parser.parse_args(argv)
    report = {"phase": "5", "validation": "RUNNING", "phase_gate": "PENDING_REMOTE_LAPTOPS",
              "execution_scope": _SCOPE, "cases": {}}
    save_json(args.output, report)
    try:
        with tempfile.TemporaryDirectory(prefix="meshmind-negative-http-") as temporary:
            report["cases"] = run_checks(Path(temporary), secrets.token_urlsafe(32))
        report["validation"] = "PASS" if all(
            case["validation"] == "PASS" for case in report["cases"].values()
        ) and len(report["cases"]) == 3 else "FAIL"
    except Exception:
        # Upstream exceptions can contain URLs, local paths or request headers.
        report.update(validation="FAIL", error="Local HTTP failure checks could not complete; inspect dependencies and loopback access.")
    report["completed_at"] = _now().isoformat()
    save_json(args.output, report)
    for name, case in report["cases"].items():
        print(f"{name}: {case['validation']}", flush=True)
    print(f"Phase 5 negative HTTP checks: {report['validation']} (local fixtures only).", flush=True)
    print("Remote laptop and real-data phase gates are unchanged.", flush=True)
    print(f"Terminal evidence: {args.output}", flush=True)
    return 0 if report["validation"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
