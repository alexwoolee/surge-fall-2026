"""Dam worker entry point. Only this process opens its configured local records."""

from backend.shared.settings import WorkerSettings
from backend.shared.worker_api import create_worker_app
from backend.workers.dam.service import run_dam_task


def create_app(settings: WorkerSettings | None = None):
    settings = settings if settings is not None else WorkerSettings.from_env()
    return create_worker_app('dam-worker', 'dam_risk',
                             lambda task, progress: run_dam_task(task, progress, settings=settings),
                             token=settings.worker_token, capacity=settings.max_tasks)
