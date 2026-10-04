"""Resolve bounded worker tasks to the existing deterministic services."""

from pathlib import Path
import re
from typing import Callable

from backend.shared.contracts import AnalysisTask
from backend.shared.context_contracts import ContextTask
from backend.shared.settings import WorkerSettings
from backend.shared.status import TaskState
from backend.workers.hydro.service import run_hydro_analysis
from backend.workers.flood.service import run_flood_analysis
from backend.workers.flood.terrain import discover_dem_tiles
from backend.workers.flood.hand import discover_hand_tiles
from backend.workers.flood.sentinel1 import discover_sentinel1_scene

_RESOURCE = re.compile(r'[A-Za-z0-9][A-Za-z0-9._-]{0,199}')


class WorkerResourceError(Exception):
    """Requested input is unavailable in the worker's configured resource store."""


def _resource(folder: Path, name: str) -> Path:
    # Check at the filesystem boundary as well as in the HTTP request contract.
    if not isinstance(name, str) or not _RESOURCE.fullmatch(name) or '..' in name:
        raise WorkerResourceError('Invalid worker resource identifier.')
    root = folder.resolve()
    resolved = (root / name).resolve()
    if resolved.parent != root or not resolved.is_file():
        raise WorkerResourceError('Requested resource is unavailable in the configured worker data folder.')
    return resolved


def _validated(task: AnalysisTask, analysis_type: str) -> AnalysisTask:
    # Revalidate even if a caller supplies a mutated model or bypasses HTTP.
    task = AnalysisTask.model_validate(task.model_dump(mode='json'))
    if task.analysis_type != analysis_type:
        raise WorkerResourceError('Task analysis type does not match this worker.')
    return task


def run_hydro_task(task: AnalysisTask | ContextTask, progress: Callable, *, settings: WorkerSettings) -> dict:
    if isinstance(task, ContextTask):
        from backend.workers.hydro.context import run_hydro_context
        return run_hydro_context(task, progress, settings=settings)
    task = _validated(task, 'hydrometeorology')
    gpm = [_resource(settings.gpm_dir, name) for name in task.gpm_resources]
    smap = _resource(settings.smap_dir, task.smap_resource)
    progress(TaskState.DATASET_LOCATED)
    progress(TaskState.PROCESSING)
    result = run_hydro_analysis(gpm, smap, task.bbox.as_tuple(), task_id=task.task_id)
    progress(TaskState.PREPARING_RESULT)
    return result


def run_flood_task(task: AnalysisTask | ContextTask, progress: Callable, *, settings: WorkerSettings) -> dict:
    if isinstance(task, ContextTask):
        from backend.workers.flood.context import run_flood_context
        return run_flood_context(task, progress)
    task = _validated(task, 'surface_water_and_terrain')
    bbox = task.bbox.as_tuple()
    scene = discover_sentinel1_scene(bbox, task.start_time, task.end_time, reference_time=task.reference_time)
    dem, hand = discover_dem_tiles(bbox), discover_hand_tiles(bbox)
    progress(TaskState.DATASET_LOCATED)
    progress(TaskState.PROCESSING)
    result = run_flood_analysis(scene, dem, hand, bbox, task_id=task.task_id,
                                threshold_db=task.threshold_db)
    progress(TaskState.PREPARING_RESULT)
    return result
