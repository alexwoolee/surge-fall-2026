"""Bounded HTTP tasks and validated envelopes around deterministic evidence.

Evidence remains a lossless JSON object. Typed summaries and coverage validate
what callers consume, including agreement with the underlying measurements.
Contracts do not calculate new environmental conclusions or alter processors.
"""

from datetime import datetime, timedelta, timezone
import math
import re
from typing import Annotated, Literal, Self
from urllib.parse import urlsplit
from uuid import uuid4

from pydantic import (
    AwareDatetime, BaseModel, BeforeValidator, ConfigDict, Field, JsonValue,
    Strict, field_validator, model_serializer, model_validator,
)

from backend.shared.status import TaskState, TERMINAL_STATES


AnalysisType = Literal["hydrometeorology", "surface_water_and_terrain"]
WorkerID = Literal["hydro-worker", "flood-worker"]
TaskID = Annotated[str, Field(strict=True, pattern=r"^[A-Za-z0-9_-]{1,128}$")]
Finite = Annotated[float, Strict(), Field(allow_inf_nan=False)]
Nonnegative = Annotated[Finite, Field(ge=0)]
Fraction = Annotated[Finite, Field(ge=0, le=1)]
PositiveInt = Annotated[int, Field(strict=True, gt=0)]
Count = Annotated[int, Field(strict=True, ge=0)]
Threshold = Annotated[Finite, Field(ge=-40, le=0)]
Nonempty = Annotated[str, Field(strict=True, min_length=1)]
ExecutionHost = Annotated[str, Field(strict=True, pattern=r"^[A-Za-z0-9_.-]{1,253}$")]
ProcessInstance = Annotated[str, Field(strict=True, pattern=r"^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$")]
ResourceID = Annotated[str, Field(strict=True, min_length=1, max_length=200, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")]


def _datetime_input(value):
    if not isinstance(value, (str, datetime)):
        raise ValueError("Use an ISO datetime with an explicit timezone.")
    return value


Timestamp = Annotated[AwareDatetime, BeforeValidator(_datetime_input)]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, validate_default=True)


class BoundingBox(Contract):
    west: Annotated[Finite, Field(ge=-180, le=180)]
    south: Annotated[Finite, Field(ge=-90, le=90)]
    east: Annotated[Finite, Field(ge=-180, le=180)]
    north: Annotated[Finite, Field(ge=-90, le=90)]

    @model_validator(mode="after")
    def ordered(self) -> Self:
        if self.west >= self.east or self.south >= self.north:
            raise ValueError("Require west < east and south < north; antimeridian AOIs are unsupported.")
        return self

    def as_tuple(self) -> tuple[float, float, float, float]:
        return self.west, self.south, self.east, self.north


class AnalysisTask(Contract):
    task_id: TaskID = Field(default_factory=lambda: str(uuid4()))
    analysis_type: AnalysisType
    bbox: BoundingBox
    gpm_resources: Annotated[list[ResourceID], Field(max_length=48)] = Field(default_factory=list)
    smap_resource: ResourceID | None = None
    start_time: Timestamp | None = None
    end_time: Timestamp | None = None
    reference_time: Timestamp | None = None
    threshold_db: Threshold = -17.0

    @field_validator("gpm_resources", "smap_resource")
    @classmethod
    def safe_resources(cls, value):
        resources = value if isinstance(value, list) else [] if value is None else [value]
        if any(".." in item for item in resources) or len(resources) != len(set(resources)):
            raise ValueError("Resource IDs must be unique basenames without parent-directory segments.")
        return value

    @model_validator(mode="after")
    def bounded_task(self) -> Self:
        if self.bbox.east - self.bbox.west > 2 or self.bbox.north - self.bbox.south > 2:
            raise ValueError("Worker tasks are limited to a 2 degree longitude and latitude span.")
        if self.analysis_type == "hydrometeorology":
            if not self.gpm_resources or self.smap_resource is None:
                raise ValueError("Hydro tasks require GPM resource IDs and one SMAP resource ID.")
            if any(value is not None for value in (self.start_time, self.end_time, self.reference_time)) or self.threshold_db != -17:
                raise ValueError("Hydro tasks cannot configure Sentinel-1 dates or threshold.")
        else:
            if self.gpm_resources or self.smap_resource is not None:
                raise ValueError("Surface-water tasks cannot specify Hydro resources.")
            if self.start_time is None or self.end_time is None:
                raise ValueError("Surface-water tasks require start_time and end_time.")
            if not timedelta(0) < self.end_time - self.start_time <= timedelta(days=7):
                raise ValueError("Scene discovery must have a positive window of at most 7 days.")
            if self.reference_time is not None and not self.start_time <= self.reference_time <= self.end_time:
                raise ValueError("reference_time must be inside the scene discovery window.")
        return self


def _safe_json(value, key=None):
    """Reject nonfinite evidence and credential-bearing URLs without echoing them."""
    if key == "href" and not isinstance(value, str):
        raise ValueError("Evidence hrefs must be strings.")
    if key == "resources_used" and (not isinstance(value, list) or not value or any(not isinstance(item, str) or not item for item in value)):
        raise ValueError("Evidence provenance requires nonempty resource identifiers.")
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("Evidence must contain only finite JSON numbers.")
    if isinstance(value, dict):
        for child_key, child in value.items():
            _safe_json(child, child_key)
    elif isinstance(value, (list, tuple)):
        for child in value:
            _safe_json(child)
    elif isinstance(value, str) and re.match(r"^[A-Za-z][A-Za-z0-9+.-]*://", value):
        try:
            parsed = urlsplit(value)
            if parsed.username or parsed.password or parsed.query or parsed.fragment or any(c.isspace() for c in value):
                raise ValueError
        except ValueError:
            raise ValueError("Evidence resource URLs must omit credentials, query parameters and fragments.") from None
    return value


SafeJSON = Annotated[dict[str, JsonValue], BeforeValidator(lambda value: _safe_json(value))]


def _same(actual, expected):
    if isinstance(actual, bool) or not isinstance(actual, (int, float)) or not math.isfinite(actual):
        raise ValueError("Measurement must be a finite number.")
    if not math.isclose(actual, expected, rel_tol=1e-12, abs_tol=1e-12):
        raise ValueError("Summary and evidence measurements must agree.")


def _bbox_matches(data, bbox):
    raw = data["bbox"]
    if isinstance(raw, (list, tuple)) and len(raw) == 4:
        raw = dict(zip(("west", "south", "east", "north"), raw))
    if BoundingBox.model_validate(raw) != bbox:
        raise ValueError("Evidence AOI must match the result AOI.")


def _identity(worker_id, analysis_type):
    expected = "hydrometeorology" if worker_id == "hydro-worker" else "surface_water_and_terrain"
    if analysis_type != expected:
        raise ValueError("Worker identity and analysis_type must agree.")


class Coverage(Contract):
    aoi_pixels: PositiveInt
    covered_pixels: PositiveInt
    valid_pixels: PositiveInt
    coverage_fraction: Fraction
    valid_fraction: Fraction
    status: Literal["complete", "partial"]

    @model_validator(mode="after")
    def consistent(self) -> Self:
        if not self.valid_pixels <= self.covered_pixels <= self.aoi_pixels:
            raise ValueError("Require valid <= covered <= AOI pixels.")
        _same(self.coverage_fraction, self.covered_pixels / self.aoi_pixels)
        _same(self.valid_fraction, self.valid_pixels / self.aoi_pixels)
        if self.status != ("complete" if self.valid_pixels == self.aoi_pixels else "partial"):
            raise ValueError("Coverage status must describe valid pixels.")
        return self


class RainfallSummary(Contract):
    area_mean_total_accumulation_mm: Nonnegative
    max_cell_total_accumulation_mm: Nonnegative
    duration_hours: Annotated[Finite, Field(gt=0)]
    granule_count: PositiveInt

    @model_validator(mode="after")
    def ordered(self) -> Self:
        if self.area_mean_total_accumulation_mm > self.max_cell_total_accumulation_mm:
            raise ValueError("Mean rainfall cannot exceed its maximum.")
        return self


class SoilSummary(Contract):
    surface_mean_m3_m3: Fraction
    surface_max_m3_m3: Fraction
    rootzone_mean_m3_m3: Fraction
    rootzone_max_m3_m3: Fraction
    smap_timestamp_utc: Timestamp | None

    @model_validator(mode="after")
    def ordered(self) -> Self:
        if self.surface_mean_m3_m3 > self.surface_max_m3_m3 or self.rootzone_mean_m3_m3 > self.rootzone_max_m3_m3:
            raise ValueError("Mean soil moisture cannot exceed its maximum.")
        return self


class HydroSummary(Contract):
    rainfall: RainfallSummary
    soil_moisture: SoilSummary


class HydroResult(Contract):
    task_id: TaskID
    worker_id: Literal["hydro-worker"]
    analysis_type: Literal["hydrometeorology"]
    status: Literal["complete"]
    bbox: BoundingBox
    sources: Annotated[list[SafeJSON], Field(min_length=2, max_length=2)]
    summary: HydroSummary
    evidence: dict[Literal["gpm", "smap"], SafeJSON]
    limitations: Annotated[list[Nonempty], Field(min_length=1)]

    @model_validator(mode="after")
    def consistent(self) -> Self:
        try:
            if set(self.evidence) != {"gpm", "smap"}:
                raise ValueError
            gpm, smap = self.evidence["gpm"], self.evidence["smap"]
            for evidence in (gpm, smap):
                _bbox_matches(evidence, self.bbox)
            rainfall, soil = self.summary.rainfall, self.summary.soil_moisture
            for key in ("area_mean_total_accumulation_mm", "max_cell_total_accumulation_mm"):
                _same(gpm["rainfall"][key], getattr(rainfall, key))
            _same(gpm["total_duration_hours"], rainfall.duration_hours)
            _same(gpm["granule_count"], rainfall.granule_count)
            for layer in ("surface", "rootzone"):
                for field, key in (("mean", "mean"), ("max", "maximum")):
                    _same(smap[f"{layer}_soil_moisture"][key], getattr(soil, f"{layer}_{field}_m3_m3"))
            timestamp = smap["timestamp_utc"]
            parsed = None if timestamp is None else datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
            if parsed != soil.smap_timestamp_utc:
                raise ValueError
            for source, data, name in zip(self.sources, (gpm, smap), ("NASA GPM IMERG", "NASA SMAP L4")):
                if source["name"] != name or data["source"] != name or any(source[key] != data[key] for key in ("product", "version")):
                    raise ValueError
                if not source["resources_used"]:
                    raise ValueError
            if (gpm["product"], gpm["version"], smap["product"], smap["version"]) != ("GPM_3IMERGHH", "07", "SPL4SMGP", "008"):
                raise ValueError
            if len(self.sources[0]["resources_used"]) != rainfall.granule_count or len(self.sources[1]["resources_used"]) != 1:
                raise ValueError
        except (KeyError, TypeError, AttributeError, ValueError):
            raise ValueError("Hydro summary, AOI, provenance and required evidence must agree.") from None
        return self


class SurfaceWaterSummary(Contract):
    candidate_area_km2: Nonnegative
    candidate_fraction_valid: Fraction
    valid_fraction: Fraction
    scene_id: Nonempty
    acquired_at: Timestamp
    threshold_db: Threshold


class TerrainSummary(Contract):
    mean_m: Finite
    min_m: Finite
    max_m: Finite
    median_m: Finite
    valid_pixels: PositiveInt
    valid_fraction: Fraction
    tile_count: PositiveInt

    @model_validator(mode="after")
    def ordered(self) -> Self:
        if self.min_m > self.max_m or not all(self.min_m <= value <= self.max_m for value in (self.mean_m, self.median_m)):
            raise ValueError("Mean and median terrain heights must lie within the range.")
        return self


class FloodSummary(Contract):
    surface_water: SurfaceWaterSummary | None = None
    elevation: TerrainSummary | None = None
    hand: TerrainSummary | None = None

    @model_serializer(mode="wrap")
    def omit_absent_components(self, serializer):
        return {key: value for key, value in serializer(self).items() if value is not None}


class ComponentError(Contract):
    component: Literal["sentinel1", "dem", "hand"]
    code: Literal["processing_failed", "invalid_result"]
    message: Nonempty


class FloodResult(Contract):
    task_id: TaskID
    worker_id: Literal["flood-worker"]
    analysis_type: Literal["surface_water_and_terrain"]
    status: Literal["complete", "partial", "failed"]
    bbox: BoundingBox
    summary: FloodSummary
    evidence: dict[Literal["sentinel1", "dem", "hand"], SafeJSON]
    sources: list[SafeJSON]
    coverage: dict[Literal["sentinel1", "dem", "hand"], Coverage]
    errors: list[ComponentError]
    limitations: Annotated[list[Nonempty], Field(min_length=1)]

    @model_validator(mode="after")
    def consistent(self) -> Self:
        keys = {"sentinel1": "surface_water", "dem": "elevation", "hand": "hand"}
        successful = set(self.evidence)
        try:
            expected_status = "complete" if len(successful) == 3 else "partial" if successful else "failed"
            failed = [error.component for error in self.errors]
            if self.status != expected_status or set(self.coverage) != successful or len(failed) != len(set(failed)) or set(failed) != set(keys) - successful:
                raise ValueError
            summaries = {name for name in keys.values() if getattr(self.summary, name) is not None}
            if summaries != {keys[name] for name in successful}:
                raise ValueError
            sources = {source["component"]: source for source in self.sources}
            if len(sources) != len(self.sources) or set(sources) != successful:
                raise ValueError
            approved = {"sentinel1": ("Sentinel-1 RTC", "sentinel-1-rtc"),
                        "dem": ("Copernicus DEM GLO-30", "cop-dem-glo-30"),
                        "hand": ("ASF GLO-30 HAND", "glo-30-hand")}
            for component, data in self.evidence.items():
                if (data["source"], data["collection"]) != approved[component]:
                    raise ValueError
                _bbox_matches(data, self.bbox)
                coverage = self.coverage[component]
                if Coverage.model_validate(data["coverage"]) != coverage:
                    raise ValueError
                summary = getattr(self.summary, keys[component])
                _same(summary.valid_fraction, coverage.valid_fraction)
                source = sources[component]
                if source["name"] != data["source"] or source["collection"] != data["collection"] or not source["resources_used"]:
                    raise ValueError
                if component == "sentinel1":
                    _same(data["candidate_water"]["area_km2"], summary.candidate_area_km2)
                    _same(data["candidate_water"]["fraction_valid"], summary.candidate_fraction_valid)
                    _same(data["method"]["threshold_db"], summary.threshold_db)
                    count = data["candidate_water"]["count"]
                    if isinstance(count, bool) or not isinstance(count, int) or not 0 <= count <= coverage.valid_pixels:
                        raise ValueError
                    _same(summary.candidate_fraction_valid, count / coverage.valid_pixels)
                    _same(summary.candidate_area_km2, count * data["raster"]["pixel_area_m2"] / 1_000_000)
                    if data["scene"]["scene_id"] != summary.scene_id or datetime.fromisoformat(data["scene"]["acquired_at"].replace("Z", "+00:00")) != summary.acquired_at:
                        raise ValueError
                    if source["resources_used"] != [data["scene"]["href"]]:
                        raise ValueError
                else:
                    for key in ("mean", "min", "max", "median"):
                        _same(data["statistics"][key], getattr(summary, f"{key}_m"))
                    if summary.valid_pixels != coverage.valid_pixels or data["statistics"]["count"] != summary.valid_pixels or summary.tile_count != len(data["source_tiles"]):
                        raise ValueError
                    if component == "hand" and summary.min_m < 0:
                        raise ValueError
                    if source["resources_used"] != [tile["href"] for tile in data["source_tiles"]]:
                        raise ValueError
        except (KeyError, TypeError, AttributeError, ValueError, OverflowError):
            raise ValueError("Flood status, summary, coverage, provenance and required evidence must agree.") from None
        return self


class TaskStatus(Contract):
    execution_host: ExecutionHost | None = None
    process_instance_id: ProcessInstance | None = None
    task_id: TaskID
    worker_id: WorkerID
    analysis_type: AnalysisType
    state: TaskState
    received_at: Timestamp
    started_at: Timestamp | None = None
    completed_at: Timestamp | None = None
    error: Nonempty | None = None

    @field_validator("received_at", "started_at", "completed_at")
    @classmethod
    def utc_timestamps(cls, value):
        return value.astimezone(timezone.utc) if value is not None else None

    @model_validator(mode="after")
    def consistent(self) -> Self:
        _identity(self.worker_id, self.analysis_type)
        if self.started_at is not None and self.started_at < self.received_at:
            raise ValueError("started_at precedes received_at.")
        if self.state in TERMINAL_STATES:
            if self.completed_at is None or self.completed_at < (self.started_at or self.received_at):
                raise ValueError("Terminal status requires a completion time after receipt/start.")
        elif self.completed_at is not None:
            raise ValueError("Active status cannot have a completion time.")
        if self.state in {TaskState.PROCESSING, TaskState.PREPARING_RESULT, TaskState.COMPLETE, TaskState.PARTIAL} and self.started_at is None:
            raise ValueError("Processing status requires a start time.")
        if self.error is not None and self.state != TaskState.FAILED:
            raise ValueError("Task-level errors require failed status.")
        return self


class WorkerStatus(Contract):
    execution_host: ExecutionHost | None = None
    process_instance_id: ProcessInstance | None = None
    worker_id: WorkerID
    analysis_type: AnalysisType
    status: Literal["idle", "busy"]
    active_task_id: TaskID | None = None
    retained_tasks: Count
    capacity: PositiveInt

    @model_validator(mode="after")
    def consistent(self) -> Self:
        _identity(self.worker_id, self.analysis_type)
        if (self.status == "busy") != (self.active_task_id is not None):
            raise ValueError("Busy workers must identify their active task.")
        if self.retained_tasks > self.capacity:
            raise ValueError("Retained task count exceeds capacity.")
        return self


class CombinedAnalysis(Contract):
    """Collection envelope only; fusion and review rules belong to later phases."""

    task_id: TaskID
    hydro: HydroResult | None = None
    flood: FloodResult | None = None
    errors: list[Nonempty] = Field(default_factory=list)

    @model_validator(mode="after")
    def same_task(self) -> Self:
        results = [result for result in (self.hydro, self.flood) if result is not None]
        if any(result.task_id != self.task_id for result in results):
            raise ValueError("Combined results must belong to the requested task.")
        if len(results) == 2 and results[0].bbox != results[1].bbox:
            raise ValueError("Combined results must describe the same AOI.")
        if not results and not self.errors:
            raise ValueError("A combined analysis requires a result or an explicit error.")
        return self
