"""Grounded evidence assembly; no spatial overlay or environmental inference.

Fusion retains the original contracts and exposes a small, explicit metric
registry for deterministic review rules. Missing evidence is never a zero.
"""

from datetime import datetime, timezone
import json
import math
from typing import Annotated, Literal, Self

from pydantic import BaseModel, Field, field_validator, model_validator

from backend.control.state import DispatchRun
from backend.shared.contracts import (
    AnalysisTask, BoundingBox, CombinedAnalysis, Contract, Finite, Fraction,
    Nonempty, SafeJSON, TaskID, Timestamp,
)


DISCLAIMER = (
    "MeshMind is an environmental analysis and analyst-support system. "
    "It is not an operational emergency-response or evacuation system."
)
ComponentID = Literal["gpm", "smap", "sentinel1", "dem", "hand"]
Availability = Literal["available", "unavailable"]
PositiveFinite = Annotated[Finite, Field(gt=0)]
_COMPONENTS = ("gpm", "smap", "sentinel1", "dem", "hand")
_METRICS = {
    "gpm.mean_accumulation_mm": ("gpm", "Mean accumulation over supplied granules", "mm"),
    "gpm.max_cell_accumulation_mm": ("gpm", "Maximum cell accumulation over supplied granules", "mm"),
    "smap.surface_mean_m3_m3": ("smap", "Mean surface soil moisture", "m3/m3"),
    "smap.rootzone_mean_m3_m3": ("smap", "Mean root-zone soil moisture", "m3/m3"),
    "sentinel1.candidate_area_km2": ("sentinel1", "Observed candidate surface-water area", "km2"),
    "sentinel1.valid_fraction": ("sentinel1", "Valid SAR AOI pixel fraction", "fraction"),
    "dem.mean_m": ("dem", "Mean AOI elevation", "m"),
    "hand.mean_m": ("hand", "Mean AOI height above drainage", "m"),
}
METRIC_UNITS = {key: spec[2] for key, spec in _METRICS.items()}
_LIMITATIONS = [
    "Evidence is combined at the requested AOI level. Native grids, valid coverage and observation dates differ; no spatial water/terrain overlay is performed.",
    "Processing completion does not imply complete spatial or temporal coverage. Missing observations are not extrapolated or replaced with zero.",
    "GPM duration is the sum represented by supplied granules; validated interval boundaries and temporal continuity are not reported by the current worker.",
    "One SMAP state and one Sentinel-1 acquisition do not establish change, event evolution, causation, future conditions or confirmed flooding.",
    "DEM and HAND describe terrain across their available AOI cells, not specifically candidate-water pixels. Water depth, water-on-low-HAND fraction and severity are not calculated.",
    "Worker execution times describe processing, not environmental observation times. Dispatch mode alone is not proof of physical parallel execution.",
]


class FusionValidationError(ValueError):
    """Input cannot be safely combined; errors never interpolate input values."""


class TimeWindow(Contract):
    start: Timestamp
    end: Timestamp

    @field_validator("start", "end")
    @classmethod
    def normalize_utc(cls, value):
        return value.astimezone(timezone.utc)

    @model_validator(mode="after")
    def ordered(self) -> Self:
        if self.start >= self.end:
            raise ValueError("Requested time window must have start before end.")
        return self


class MetricEvidence(Contract):
    metric_id: Nonempty
    component: ComponentID
    label: Nonempty
    unit: Nonempty
    status: Availability
    value: Finite | None
    unavailable_reason: Nonempty | None = None
    valid_fraction: Fraction | None = None
    duration_hours: PositiveFinite | None = None

    @model_validator(mode="after")
    def consistent(self) -> Self:
        if _METRICS.get(self.metric_id) != (self.component, self.label, self.unit):
            raise ValueError("Metric identity, label and units must match the supported registry.")
        if self.status == "available":
            if self.value is None or self.unavailable_reason is not None:
                raise ValueError("Available metrics require a value and no unavailable reason.")
        elif (self.value is not None or self.unavailable_reason is None
              or self.valid_fraction is not None or self.duration_hours is not None):
            raise ValueError("Unavailable metrics require a reason and no measurement or eligibility values.")
        return self


class ComponentEvidence(Contract):
    component: ComponentID
    status: Availability
    summary: SafeJSON | None
    evidence: SafeJSON | None
    provenance: list[SafeJSON]
    coverage: SafeJSON | None
    time_basis: SafeJSON
    errors: list[SafeJSON]
    limitations: list[Nonempty]
    unavailable_reason: Nonempty | None = None


def _json_default(value):
    if isinstance(value, BaseModel):
        return value.model_dump(mode="python")
    if isinstance(value, datetime):
        return value.isoformat()
    raise TypeError("Evidence must be JSON serializable.")


def _detached(model, value):
    """Serialize first so nested/model_copy-created objects are revalidated too."""
    try:
        raw = json.loads(json.dumps(value, default=_json_default, allow_nan=False))
        return model.model_validate(raw)
    except (TypeError, ValueError, OverflowError, RecursionError):
        raise FusionValidationError("Input does not satisfy its evidence contract.") from None


def _number(value, *, positive=False, fraction=False):
    if (isinstance(value, bool) or not isinstance(value, (int, float))
            or not math.isfinite(value) or (positive and value <= 0)
            or (fraction and not 0 <= value <= 1)):
        raise FusionValidationError("Hydro support metadata contains an invalid number.")
    return float(value)


def _count(value, *, positive=False):
    if isinstance(value, bool) or not isinstance(value, int) or value < (1 if positive else 0):
        raise FusionValidationError("Hydro support metadata contains an invalid pixel count.")
    return value


def _mapping(value):
    if not isinstance(value, dict):
        raise FusionValidationError("Hydro support metadata must be an object.")
    return value


def _gpm_coverage(evidence, notes):
    grid = evidence.get("selected_grid")
    if grid is None:
        notes.append("GPM complete-observation pixel coverage is unreported; coverage-dependent rules are not assessable.")
        return None
    grid = _mapping(grid)
    for key in ("total_pixels", "complete_coverage_pixels", "longitude_cells", "latitude_cells"):
        if key in grid:
            _count(grid[key], positive=True)
    if "complete_coverage_fraction" in grid:
        _number(grid["complete_coverage_fraction"], fraction=True)
    if not {"total_pixels", "complete_coverage_pixels", "complete_coverage_fraction"} <= grid.keys():
        notes.append("GPM coverage metadata is incomplete; coverage-dependent rules are not assessable.")
        return None
    total, valid = grid["total_pixels"], grid["complete_coverage_pixels"]
    if valid > total or not math.isclose(grid["complete_coverage_fraction"], valid / total, rel_tol=1e-12, abs_tol=1e-12):
        raise FusionValidationError("GPM coverage counts and fraction disagree.")
    if {"longitude_cells", "latitude_cells"} <= grid.keys() and grid["longitude_cells"] * grid["latitude_cells"] != total:
        raise FusionValidationError("GPM grid dimensions and pixel count disagree.")
    granules = evidence.get("granules")
    if granules is None:
        notes.append("GPM per-granule support is unreported; coverage-dependent rules are not assessable.")
        return None
    for granule in granules:
        if "valid_pixels" in granule:
            granule_valid = _count(granule["valid_pixels"], positive=True)
            if not valid <= granule_valid <= total:
                raise FusionValidationError("GPM complete coverage is inconsistent with per-granule pixel counts.")
    return float(grid["complete_coverage_fraction"])


def _smap_coverage(evidence, layer, notes):
    data = _mapping(evidence[f"{layer}_soil_moisture"])
    grid = evidence.get("selected_grid")
    if grid is not None:
        grid = _mapping(grid)
        for key in ("aoi_pixels", "window_pixels", "window_rows", "window_columns"):
            if key in grid:
                _count(grid[key], positive=True)
        if {"aoi_pixels", "window_pixels"} <= grid.keys() and grid["aoi_pixels"] > grid["window_pixels"]:
            raise FusionValidationError("SMAP AOI pixels exceed the selected window.")
        if {"window_rows", "window_columns", "window_pixels"} <= grid.keys() and grid["window_rows"] * grid["window_columns"] != grid["window_pixels"]:
            raise FusionValidationError("SMAP selected window dimensions and pixel count disagree.")
    if "valid_pixels" in data:
        _count(data["valid_pixels"], positive=True)
    units = data.get("units")
    if units is not None and (not isinstance(units, str) or units not in {"m3 m-3", "m3/m3", "m^3/m^3", "m³/m³", "m3 m^-3", "m^3 m^-3"}):
        raise FusionValidationError("SMAP declared units do not support volume-fraction measurements.")
    if (grid is None or "aoi_pixels" not in grid or "valid_pixels" not in data or units is None):
        notes.append(f"SMAP {layer} coverage or declared units are unreported; coverage-dependent rules are not assessable.")
        return None
    if data["valid_pixels"] > grid["aoi_pixels"]:
        raise FusionValidationError("SMAP valid pixels exceed AOI pixels.")
    return data["valid_pixels"] / grid["aoi_pixels"]


def _validate_context(hydro, flood, combined, dispatch):
    if hydro.analysis_type != "hydrometeorology" or flood.analysis_type != "surface_water_and_terrain":
        raise FusionValidationError("Fusion requires Hydro then Flood requests with the correct roles.")
    if hydro.task_id != flood.task_id or hydro.task_id != combined.task_id or hydro.bbox != flood.bbox:
        raise FusionValidationError("Requests and results must share one task ID and AOI.")
    for result in (combined.hydro, combined.flood):
        if result is not None and (result.task_id != hydro.task_id or result.bbox != hydro.bbox):
            raise FusionValidationError("Returned evidence must match the requested task ID and AOI.")
    if combined.hydro is not None:
        result = combined.hydro
        gpm_resources, smap_resources = (source["resources_used"] for source in result.sources)
        if (not isinstance(gpm_resources, list) or not all(isinstance(name, str) for name in gpm_resources)
                or sorted(gpm_resources) != sorted(hydro.gpm_resources)
                or smap_resources != [hydro.smap_resource]):
            raise FusionValidationError("Hydro provenance does not match the requested resources.")
        granules = result.evidence["gpm"].get("granules")
        if granules is not None:
            if (not isinstance(granules, list) or any(not isinstance(item, dict) or not isinstance(item.get("file"), str) for item in granules)
                    or sorted(item["file"] for item in granules) != sorted(hydro.gpm_resources)):
                raise FusionValidationError("GPM granule evidence does not match requested resources.")
        filename = result.evidence["smap"].get("file")
        if filename is not None and filename != hydro.smap_resource:
            raise FusionValidationError("SMAP state evidence does not match the requested resource.")
        duration = result.evidence["gpm"].get("duration_hours_per_granule")
        if duration is not None and not math.isclose(
            _number(duration, positive=True) * result.summary.rainfall.granule_count,
            result.summary.rainfall.duration_hours, rel_tol=1e-12, abs_tol=1e-12,
        ):
            raise FusionValidationError("GPM granule durations disagree with the accumulated duration.")
    if combined.flood is not None and combined.flood.summary.surface_water is not None:
        water = combined.flood.summary.surface_water
        if water.threshold_db != flood.threshold_db or not flood.start_time <= water.acquired_at <= flood.end_time:
            raise FusionValidationError("Sentinel-1 evidence does not match the requested search window and threshold.")
    if dispatch is not None and (dispatch.task_id != hydro.task_id or dispatch.combined != combined):
        raise FusionValidationError("Dispatch evidence must exactly match the supplied result collection.")


def _assemble(hydro_task, flood_task, combined, requested_window):
    components = {}
    values = {}
    fractions = {}
    duration = None
    notes = list(_LIMITATIONS)
    if requested_window is not None:
        notes.append("The requested time window is user context; it does not establish that each source covers that window.")
    for component in _COMPONENTS:
        worker = combined.hydro if component in {"gpm", "smap"} else combined.flood
        if worker is None or component not in worker.evidence:
            reason = ("Hydro worker result is unavailable." if component in {"gpm", "smap"}
                      else "Flood worker result is unavailable." if worker is None
                      else f"The {component} component returned no validated evidence.")
            errors = ([error.model_dump(mode="json") for error in worker.errors if error.component == component]
                      if worker is not None else [{"code": "unavailable_worker_result", "message": error} for error in combined.errors])
            components[component] = ComponentEvidence(
                component=component, status="unavailable", summary=None, evidence=None, provenance=[],
                coverage=None, time_basis={"basis": "unavailable", "observed_at": None}, errors=errors,
                limitations=[reason], unavailable_reason=reason,
            )
            continue
        evidence = worker.evidence[component]
        component_notes = list(worker.limitations)
        if component in {"gpm", "smap"}:
            provenance = [worker.sources[0 if component == "gpm" else 1]]
            if component == "gpm":
                summary = worker.summary.rainfall.model_dump(mode="json")
                fraction = _gpm_coverage(evidence, component_notes)
                duration = worker.summary.rainfall.duration_hours
                coverage = {"basis": "AOI grid cells valid in every supplied granule", "selected_grid": evidence.get("selected_grid"), "valid_fraction": fraction}
                time_basis = {"basis": "sum_of_supplied_granule_durations", "duration_hours": duration,
                              "interval_start": None, "interval_end": None, "continuity": "unknown"}
                values.update({"gpm.mean_accumulation_mm": summary["area_mean_total_accumulation_mm"],
                               "gpm.max_cell_accumulation_mm": summary["max_cell_total_accumulation_mm"]})
                fractions.update({key: fraction for key in values if key.startswith("gpm.")})
                component_notes.append(_LIMITATIONS[2])
            else:
                summary = worker.summary.soil_moisture.model_dump(mode="json")
                surface = _smap_coverage(evidence, "surface", component_notes)
                rootzone = _smap_coverage(evidence, "rootzone", component_notes)
                coverage = {"basis": "valid layer pixels divided by AOI grid pixels, not geographic area",
                            "selected_grid": evidence.get("selected_grid"), "surface_valid_fraction": surface,
                            "rootzone_valid_fraction": rootzone}
                time_basis = {"basis": "single_state_timestamp_from_resource_filename", "observed_at": summary["smap_timestamp_utc"]}
                values.update({"smap.surface_mean_m3_m3": summary["surface_mean_m3_m3"],
                               "smap.rootzone_mean_m3_m3": summary["rootzone_mean_m3_m3"]})
                fractions.update({"smap.surface_mean_m3_m3": surface, "smap.rootzone_mean_m3_m3": rootzone})
                component_notes.append("One selected soil-moisture state is retained; no change across time or antecedent-state selection is established.")
                if summary["smap_timestamp_utc"] is None:
                    component_notes.append("SMAP observation timestamp is unknown; execution time must not substitute for it.")
        else:
            key = {"sentinel1": "surface_water", "dem": "elevation", "hand": "hand"}[component]
            summary = getattr(worker.summary, key).model_dump(mode="json")
            coverage = worker.coverage[component].model_dump(mode="json")
            provenance = [source for source in worker.sources if source["component"] == component]
            fraction = worker.coverage[component].valid_fraction
            if component == "sentinel1":
                time_basis = {"basis": "single_scene_acquisition", "observed_at": summary["acquired_at"],
                              "search_window": {"start": flood_task.start_time.astimezone(timezone.utc).isoformat(),
                                                "end": flood_task.end_time.astimezone(timezone.utc).isoformat()}}
                values.update({"sentinel1.candidate_area_km2": summary["candidate_area_km2"], "sentinel1.valid_fraction": fraction})
                fractions.update({"sentinel1.candidate_area_km2": fraction, "sentinel1.valid_fraction": fraction})
            else:
                time_basis = {"basis": "static_terrain_product", "observed_at": None, "product_date": None}
                values[f"{component}.mean_m"] = summary["mean_m"]
                fractions[f"{component}.mean_m"] = fraction
                component_notes.append("No observation or product timestamp is supplied for this static terrain evidence.")
            detail_notes = evidence.get("limitations", [])
            if not isinstance(detail_notes, list) or not all(isinstance(note, str) and note.strip() for note in detail_notes):
                raise FusionValidationError("Component limitations must be a list of nonempty text.")
            component_notes.extend(detail_notes)
        components[component] = ComponentEvidence(
            component=component, status="available", summary=summary, evidence=evidence,
            provenance=provenance, coverage=coverage, time_basis=time_basis, errors=[],
            limitations=list(dict.fromkeys(component_notes)),
        )
    metrics = {}
    for metric_id, (component, label, unit) in _METRICS.items():
        available = metric_id in values
        metrics[metric_id] = MetricEvidence(
            metric_id=metric_id, component=component, label=label, unit=unit,
            status="available" if available else "unavailable", value=values.get(metric_id),
            unavailable_reason=None if available else components[component].unavailable_reason,
            valid_fraction=fractions.get(metric_id),
            duration_hours=duration if available and component == "gpm" else None,
        )
    available_count = sum(component.status == "available" for component in components.values())
    status = "complete" if available_count == len(_COMPONENTS) else "partial" if available_count else "unavailable"
    return components, metrics, status, notes


class FusionResult(Contract):
    schema_version: Literal["1.0"] = "1.0"
    task_id: TaskID
    bbox: BoundingBox
    status: Literal["complete", "partial", "unavailable"]
    requests: Annotated[list[AnalysisTask], Field(min_length=2, max_length=2)]
    requested_window: TimeWindow | None = None
    source_results: CombinedAnalysis
    dispatch: DispatchRun | None = None
    components: dict[ComponentID, ComponentEvidence]
    metrics: dict[str, MetricEvidence]
    limitations: list[Nonempty]
    disclaimer: Literal[DISCLAIMER] = DISCLAIMER

    @model_validator(mode="after")
    def grounded(self) -> Self:
        hydro, flood = (_detached(AnalysisTask, request) for request in self.requests)
        combined = _detached(CombinedAnalysis, self.source_results)
        dispatch = None if self.dispatch is None else _detached(DispatchRun, self.dispatch)
        window = None if self.requested_window is None else _detached(TimeWindow, self.requested_window)
        _validate_context(hydro, flood, combined, dispatch)
        if self.task_id != hydro.task_id or self.bbox != hydro.bbox:
            raise ValueError("Fusion identity must match its source requests.")
        expected = _assemble(hydro, flood, combined, window)
        if (self.components, self.metrics, self.status, self.limitations) != expected:
            raise ValueError("Fusion fields must remain grounded in the preserved source evidence.")
        return self


def fuse_analysis(
    hydro_task: AnalysisTask | dict,
    flood_task: AnalysisTask | dict,
    combined: CombinedAnalysis | dict,
    *, requested_window: TimeWindow | dict | None = None,
    dispatch: DispatchRun | dict | None = None,
) -> FusionResult:
    """Revalidate and combine supplied evidence without dispatching any work."""
    hydro = _detached(AnalysisTask, hydro_task)
    flood = _detached(AnalysisTask, flood_task)
    results = _detached(CombinedAnalysis, combined)
    window = None if requested_window is None else _detached(TimeWindow, requested_window)
    execution = None if dispatch is None else _detached(DispatchRun, dispatch)
    _validate_context(hydro, flood, results, execution)
    components, metrics, status, notes = _assemble(hydro, flood, results, window)
    return FusionResult(task_id=hydro.task_id, bbox=hydro.bbox, status=status,
                        requests=[hydro, flood], requested_window=window, source_results=results,
                        dispatch=execution, components=components, metrics=metrics, limitations=notes)
