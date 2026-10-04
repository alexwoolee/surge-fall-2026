"""Scene context bounded by observation dates for a requested location."""

from datetime import datetime, timedelta, timezone

from backend.shared.context_contracts import (
    ContextComponent, ContextTask, WaterMetrics, context_result, unavailable,
)
from backend.shared.status import TaskState
from backend.workers.flood.sentinel1 import (
    Sentinel1NoSceneError, analyze_sentinel1_scene, discover_sentinel1_scene,
    _timestamp, _validate_scene,
)
from backend.workers.flood.service import _checked_result


# Launch is a conservative lower bound; later empty provider coverage remains unavailable.
SENTINEL1_START = datetime(2014, 4, 3, tzinfo=timezone.utc)


def _water(task, located):
    if task.end_time <= SENTINEL1_START:
        return unavailable("sentinel1", "before_product_coverage")
    try:
        scene = discover_sentinel1_scene(task.bbox.as_tuple(), task.start_time,
                                         task.end_time - timedelta(microseconds=1),
                                         reference_time=task.end_time - timedelta(microseconds=1))
    except Sentinel1NoSceneError:
        return unavailable("sentinel1", "no_matching_observations")
    except Exception:
        return unavailable("sentinel1", "source_unavailable")
    try:
        _validate_scene(scene)
        acquired = _timestamp(scene.acquired_at)
        if not task.start_time <= acquired < task.end_time:
            raise ValueError
    except Exception:
        return unavailable("sentinel1", "invalid_result")
    # The selected scene has passed the source and cutoff checks. Announce it
    # before raster work, so the milestone remains true even if processing fails.
    located()
    try:
        raw = analyze_sentinel1_scene(scene, task.bbox.as_tuple(), threshold_db=-17.0, max_pixels=20_000_000)
    except Exception:
        return unavailable("sentinel1", "processing_failed")
    try:
        _, summary, _ = _checked_result("sentinel1", raw, task.bbox.as_tuple(), scene, -17.0, 20_000_000)
        metrics = WaterMetrics(**{key: summary[key] for key in ("candidate_fraction_valid", "candidate_area_km2", "valid_fraction", "threshold_db")})
        return ContextComponent(component="sentinel1", availability="available", reason="measured",
                                temporal_kind="observation", observed_start=acquired, observed_end=acquired, metrics=metrics)
    except Exception:
        return unavailable("sentinel1", "invalid_result")


def _terrain(task, component):
    # RasterTile does not carry a verified observation period. A modern
    # product's publication/version date cannot establish when its underlying
    # terrain was observed. Exclude it before discovery or any raster read.
    return unavailable(component, "observation_date_unverified")


def run_flood_context(task: ContextTask, progress) -> dict:
    task = ContextTask.model_validate(task.model_dump(mode="json"))
    if task.analysis_type != "surface_water_and_terrain":
        raise ValueError("Environmental context task does not match the Flood role.")
    processing_started = False
    def located():
        nonlocal processing_started
        progress(TaskState.DATASET_LOCATED)
        progress(TaskState.PROCESSING)
        processing_started = True
    # Scene coverage is independent of terrain exclusion. Legacy fixed-case
    # terrain processing is unchanged; this dated investigation requires proof
    # that every observed input predates its cutoff.
    water = _water(task, located)
    if not processing_started:
        # No input was located; processing here assembles the coverage result.
        progress(TaskState.PROCESSING)
    components = [water, _terrain(task, "dem"), _terrain(task, "hand")]
    progress(TaskState.PREPARING_RESULT)
    return context_result(task, components)
