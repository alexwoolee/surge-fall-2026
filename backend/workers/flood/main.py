"""Laptop 3 HTTP entry point: ``uvicorn backend.workers.flood.main:create_app --factory``."""

from backend.shared.settings import WorkerSettings
from backend.shared.worker_api import create_worker_app
from backend.shared.worker_runners import run_flood_task


def create_app(settings: WorkerSettings | None = None):
    settings = settings if settings is not None else WorkerSettings.from_env()
    return create_worker_app(
        "flood-worker", "surface_water_and_terrain",
        lambda task, progress: run_flood_task(task, progress, settings=settings),
        token=settings.worker_token, capacity=settings.max_tasks,
    )
