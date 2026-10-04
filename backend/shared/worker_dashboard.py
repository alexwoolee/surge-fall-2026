"""Fixed, read-only dashboard assets and a narrow worker lifecycle projection."""

from datetime import datetime
from pathlib import Path

from fastapi.responses import Response

from backend.shared.contracts import TaskStatus


MAX_DASHBOARD_EVENTS = 16
DASHBOARD_ASSETS = {
    "/dashboard": ("index.html", "text/html"),
    "/dashboard/dashboard.css": ("dashboard.css", "text/css"),
    "/dashboard/dashboard.js": ("dashboard.js", "application/javascript"),
}
PUBLIC_GET_PATHS = frozenset({*DASHBOARD_ASSETS, "/dashboard/state"})
_ASSET_ROOT = Path(__file__).with_name("dashboard_assets")
_HEADERS = {
    "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
}
_CSP = ("default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; "
        "base-uri 'none'; form-action 'none'; frame-ancestors 'none'")
_NAMES = {"hydro-worker": "Hydrometeorology Agent", "flood-worker": "Surface Water and Terrain Agent"}
_LABELS = {
    "task_received": "Worker accepted the task.",
    "dataset_located": "Worker located the input data.",
    "processing": "Worker began processing the data.",
    "preparing_result": "Worker began preparing its result.",
    "complete": "Worker checked and completed its result.",
    "partial": "Worker checked a partial result; some evidence is unavailable.",
    "failed": "Worker processing failed; no completed result is claimed.",
}
_NOTICE = ("This page shows the latest task accepted by this worker process. Events and task history "
           "are kept in memory and reset when the worker restarts. Completion means the worker checked "
           "its own result; Control review and fusion are separate.")


def dashboard_headers(*, html=False):
    return {**_HEADERS, **({"Content-Security-Policy": _CSP} if html else {})}


def dashboard_event(state: str, observed_at: datetime):
    return {"state": state, "observedAt": observed_at.isoformat(), "label": _LABELS[state]}


def dashboard_snapshot(worker_id: str, status: TaskStatus | None, events: list[dict]):
    task, state = None, "idle"
    if status is not None:
        state = status.state.value
        if state not in {"complete", "partial", "failed"}:
            state = "active"
        elapsed = None
        if (status.started_at is not None and status.completed_at is not None
                and status.completed_at >= status.started_at):
            elapsed = (status.completed_at - status.started_at).total_seconds()
        task = {
            "id": status.task_id, "state": status.state.value,
            "receivedAt": status.received_at.isoformat(),
            "startedAt": status.started_at.isoformat() if status.started_at else None,
            "completedAt": status.completed_at.isoformat() if status.completed_at else None,
            "durationSeconds": elapsed,
        }
    return {"role": worker_id.removesuffix("-worker"), "name": _NAMES[worker_id],
            "status": state, "task": task, "events": events, "notice": _NOTICE}


def dashboard_asset(path: str):
    """The caller supplies one exact route from the fixed asset mapping."""
    filename, media_type = DASHBOARD_ASSETS[path]
    headers = dashboard_headers(html=path == "/dashboard")
    try:
        content = (_ASSET_ROOT / filename).read_bytes()
    except OSError:
        return Response("Worker dashboard is unavailable.", status_code=503, headers=headers)
    return Response(content, media_type=media_type, headers=headers)
