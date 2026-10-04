"""Live-discovered rainfall/soil evidence for the requested location and dates."""

from datetime import datetime, timedelta, timezone
import re

from backend.shared.context_contracts import (
    ContextComponent, ContextTask, RainMetrics, SoilMetrics, context_result, unavailable,
)
from backend.shared.contracts import BoundingBox
from backend.shared.settings import WorkerSettings
from backend.shared.status import TaskState
from backend.workers.hydro.gpm import analyze_gpm_granules
from backend.workers.hydro.smap import analyze_smap_granule


# V07 includes the reprocessed TRMM-era record from January 1998.
# https://gpm.nasa.gov/data/directory
GPM_START = datetime(1998, 1, 1, tzinfo=timezone.utc)
SMAP_START = datetime(2015, 3, 31, tzinfo=timezone.utc)
_GPM = re.compile(r"^3B-HHR\.MS\.MRG\.3IMERG\.(\d{8})-S(\d{6})-E(\d{6})\.\d{4}\.V07[A-Z]?\.HDF5$")
_SMAP = re.compile(r"^SMAP_L4_SM_gph_(\d{8}T\d{6})_Vv8\d{3}_\d{3}\.h5$")


def gpm_interval(name: str):
    match = _GPM.fullmatch(name)
    if match is None:
        return None
    try:
        day, begin, finish = match.groups()
        start = datetime.strptime(day + begin, "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)
        end = datetime.strptime(day + finish, "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc) + timedelta(seconds=1)
        if end <= start:
            end += timedelta(days=1)
        if start.second or start.minute not in {0, 30} or end - start != timedelta(minutes=30):
            return None
        return start, end
    except ValueError:
        return None


def smap_interval(name: str):
    match = _SMAP.fullmatch(name)
    if match is None:
        return None
    try:
        midpoint = datetime.strptime(match.group(1), "%Y%m%dT%H%M%S").replace(tzinfo=timezone.utc)
        return midpoint - timedelta(hours=1.5), midpoint + timedelta(hours=1.5), midpoint
    except ValueError:
        return None


def _gpm(task, settings, provider):
    if task.end_time <= GPM_START:
        return unavailable("gpm", "before_product_coverage")
    from backend.workers.hydro.context_sources import live_paths
    paths, reason = live_paths(provider, "gpm", task, settings.gpm_dir)
    if reason:
        return unavailable("gpm", reason)
    try:
        selected = {}
        for path in paths:
            interval = gpm_interval(path.name)
            if interval and task.start_time <= interval[0] < interval[1] <= task.end_time:
                if interval[0] in selected:
                    return unavailable("gpm", "invalid_result")
                selected[interval[0]] = (interval, path)
    except OSError:
        return unavailable("gpm", "source_unavailable")
    if not selected:
        return unavailable("gpm", "missing_local_data")
    ordered = [selected[key] for key in sorted(selected)]
    if len(ordered) > 336:
        return unavailable("gpm", "resource_limit")
    try:
        raw = analyze_gpm_granules([path for _, path in ordered], task.bbox.as_tuple())
    except Exception:
        return unavailable("gpm", "processing_failed")
    try:
        if (BoundingBox.model_validate(raw["bbox"]) != task.bbox
                or (raw["source"], raw["product"], raw["version"]) != ("NASA GPM IMERG", "GPM_3IMERGHH", "07")
                or raw["granule_count"] != len(ordered)
                or raw["duration_hours_per_granule"] != 0.5
                or raw["total_duration_hours"] != len(ordered) * 0.5
                or [row["file"] for row in raw["granules"]] != [path.name for _, path in ordered]):
            raise ValueError
        grid = raw["selected_grid"]
        if not 0 < grid["complete_coverage_pixels"] <= grid["total_pixels"]:
            raise ValueError
        valid_fraction = grid["complete_coverage_pixels"] / grid["total_pixels"]
        if abs(valid_fraction - grid["complete_coverage_fraction"]) > 1e-12:
            raise ValueError
        requested = (task.end_time - task.start_time).total_seconds() / 3600
        covered = len(ordered) * 0.5
        metrics = RainMetrics(**{key: raw["rainfall"][key] for key in ("area_mean_total_accumulation_mm", "max_cell_total_accumulation_mm")},
                              covered_hours=covered, requested_hours=requested,
                              granule_count=len(ordered), temporal_coverage_fraction=covered / requested,
                              valid_fraction=valid_fraction)
        return ContextComponent(component="gpm", availability="available",
                                reason="measured" if covered == requested else "partial_temporal_coverage",
                                temporal_kind="observation", observed_start=ordered[0][0][0],
                                observed_end=ordered[-1][0][1], metrics=metrics)
    except Exception:
        return unavailable("gpm", "invalid_result")


def _smap(task, settings, provider):
    if task.end_time <= SMAP_START:
        return unavailable("smap", "before_product_coverage")
    from backend.workers.hydro.context_sources import live_paths
    paths, reason = live_paths(provider, "smap", task, settings.smap_dir)
    if reason:
        return unavailable("smap", reason)
    try:
        selected = []
        for path in paths:
            interval = smap_interval(path.name)
            if interval and task.start_time <= interval[0] < interval[1] <= task.end_time:
                selected.append((interval, path))
    except OSError:
        return unavailable("smap", "source_unavailable")
    if not selected:
        return unavailable("smap", "missing_local_data")
    interval, path = max(selected, key=lambda item: (item[0][2], item[1].name))
    if sum(item[0][2] == interval[2] for item in selected) != 1:
        return unavailable("smap", "invalid_result")
    try:
        raw = analyze_smap_granule(path, task.bbox.as_tuple())
    except Exception:
        return unavailable("smap", "processing_failed")
    try:
        if (BoundingBox.model_validate(raw["bbox"]) != task.bbox
                or (raw["source"], raw["product"], raw["version"]) != ("NASA SMAP L4", "SPL4SMGP", "008")
                or datetime.fromisoformat(raw["timestamp_utc"].replace("Z", "+00:00")) != interval[2]):
            raise ValueError
        count = raw["selected_grid"]["aoi_pixels"]
        if type(count) is not int or count < 1:
            raise ValueError
        values = {"timestamp_utc": interval[2]}
        for layer in ("surface", "rootzone"):
            row = raw[f"{layer}_soil_moisture"]
            valid = row["valid_pixels"]
            if type(valid) is not int or not 0 < valid <= count:
                raise ValueError
            values[f"{layer}_mean_m3_m3"] = row["mean"]
            values[f"{layer}_max_m3_m3"] = row["maximum"]
            values[f"{layer}_valid_fraction"] = valid / count
        return ContextComponent(component="smap", availability="available", reason="measured",
                                temporal_kind="observation", observed_start=interval[0], observed_end=interval[1],
                                metrics=SoilMetrics(**values))
    except Exception:
        return unavailable("smap", "invalid_result")


def run_hydro_context(task: ContextTask, progress, *, settings: WorkerSettings) -> dict:
    task = ContextTask.model_validate(task.model_dump(mode="json"))
    if task.analysis_type != "hydrometeorology":
        raise ValueError("Environmental context task does not match the Hydro role.")
    progress(TaskState.PROCESSING)
    from backend.workers.hydro.context_sources import NASAContextProvider
    provider = NASAContextProvider()
    try:
        components = [_gpm(task, settings, provider), _smap(task, settings, provider)]
    finally:
        provider.close()
    progress(TaskState.PREPARING_RESULT)
    return context_result(task, components)
