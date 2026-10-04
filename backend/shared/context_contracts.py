"""Bounded, location-independent environmental evidence for optional investigations.

These envelopes contain only derived measurements. They do not accept local
paths or provider URLs, and do not transport worker-local records.
"""

from datetime import date, datetime, time, timedelta, timezone
from typing import Annotated, Literal, Self
from uuid import uuid4

from pydantic import Field, field_validator, model_validator

from backend.shared.contracts import (
    AnalysisType, BoundingBox, Contract, Finite, Fraction, Nonnegative,
    PositiveInt, TaskID, Timestamp,
)


class ContextTask(Contract):
    task_id: TaskID = Field(default_factory=lambda: str(uuid4()))
    analysis_type: AnalysisType
    investigation: Literal["environmental_context"] = "environmental_context"
    location_id: Annotated[str, Field(strict=True, pattern=r"^[a-z0-9][a-z0-9_-]{0,79}$")]
    bbox: BoundingBox
    as_of: date
    start_time: Timestamp
    end_time: Timestamp

    @field_validator("as_of", mode="before")
    @classmethod
    def date_only(cls, value):
        if isinstance(value, datetime) or not isinstance(value, (str, date)):
            raise ValueError("as_of must be an ISO calendar date.")
        if isinstance(value, str) and len(value) != 10:
            raise ValueError("as_of must be an ISO calendar date.")
        return value

    @model_validator(mode="after")
    def bounded(self) -> Self:
        if not 1900 <= self.as_of.year <= 2100:
            raise ValueError("Environmental context dates must be between 1900 and 2100.")
        if self.bbox.east - self.bbox.west > 2 or self.bbox.north - self.bbox.south > 2:
            raise ValueError("Environmental context is limited to a 2 degree AOI.")
        if not timedelta(0) < self.end_time - self.start_time <= timedelta(days=7):
            raise ValueError("Environmental context requires a positive interval of at most 7 days.")
        cutoff = datetime.combine(self.as_of, time.max, tzinfo=timezone.utc) + timedelta(microseconds=1)
        if self.end_time > cutoff or self.end_time <= cutoff - timedelta(days=1):
            raise ValueError("The interval must end on as_of, or exactly at the following midnight UTC.")
        return self


class RainMetrics(Contract):
    area_mean_total_accumulation_mm: Nonnegative
    max_cell_total_accumulation_mm: Nonnegative
    covered_hours: Annotated[Finite, Field(gt=0, le=168)]
    requested_hours: Annotated[Finite, Field(gt=0, le=168)]
    granule_count: Annotated[PositiveInt, Field(le=336)]
    temporal_coverage_fraction: Fraction
    valid_fraction: Fraction

    @model_validator(mode="after")
    def consistent(self) -> Self:
        if self.area_mean_total_accumulation_mm > self.max_cell_total_accumulation_mm:
            raise ValueError("Mean rainfall cannot exceed maximum rainfall.")
        if self.covered_hours != self.granule_count * 0.5 or self.covered_hours > self.requested_hours:
            raise ValueError("Rainfall duration must match the selected half-hour granules.")
        if abs(self.temporal_coverage_fraction - self.covered_hours / self.requested_hours) > 1e-12:
            raise ValueError("Temporal coverage must reflect covered and requested hours.")
        return self


class SoilMetrics(Contract):
    timestamp_utc: Timestamp
    surface_mean_m3_m3: Fraction
    surface_max_m3_m3: Fraction
    rootzone_mean_m3_m3: Fraction
    rootzone_max_m3_m3: Fraction
    surface_valid_fraction: Fraction
    rootzone_valid_fraction: Fraction

    @model_validator(mode="after")
    def ordered(self) -> Self:
        if self.surface_mean_m3_m3 > self.surface_max_m3_m3 or self.rootzone_mean_m3_m3 > self.rootzone_max_m3_m3:
            raise ValueError("Soil means must not exceed maxima.")
        return self


class WaterMetrics(Contract):
    candidate_fraction_valid: Fraction
    candidate_area_km2: Nonnegative
    valid_fraction: Fraction
    threshold_db: Annotated[Finite, Field(ge=-40, le=0)]


class HeightMetrics(Contract):
    mean_m: Finite
    min_m: Finite
    max_m: Finite
    median_m: Finite
    valid_fraction: Fraction
    valid_pixels: PositiveInt
    tile_count: PositiveInt

    @model_validator(mode="after")
    def ordered(self) -> Self:
        if not self.min_m <= self.mean_m <= self.max_m or not self.min_m <= self.median_m <= self.max_m:
            raise ValueError("Height summaries must lie within their measured range.")
        return self


ContextReason = Literal[
    "measured", "partial_temporal_coverage", "static_noncontemporaneous",
    "missing_local_data", "before_product_coverage", "source_unavailable",
    "processing_failed", "invalid_result", "resource_limit",
    "authentication_unavailable", "provider_timeout", "download_limit",
    "observation_date_unverified",
    "no_matching_observations",
]


class ContextComponent(Contract):
    component: Literal["gpm", "smap", "sentinel1", "dem", "hand"]
    availability: Literal["available", "unavailable"]
    reason: ContextReason
    temporal_kind: Literal["observation", "static_context"]
    observed_start: Timestamp | None = None
    observed_end: Timestamp | None = None
    metrics: RainMetrics | SoilMetrics | WaterMetrics | HeightMetrics | None = None

    @model_validator(mode="after")
    def consistent(self) -> Self:
        static = self.component in {"dem", "hand"}
        if self.temporal_kind != ("static_context" if static else "observation"):
            raise ValueError("Component temporal kind must match its dataset.")
        if self.availability == "unavailable":
            if self.metrics is not None or self.observed_start is not None or self.observed_end is not None:
                raise ValueError("Unavailable components cannot contain measurements.")
            if self.reason in {"measured", "partial_temporal_coverage", "static_noncontemporaneous"}:
                raise ValueError("Unavailable components require an unavailability reason.")
            return self
        expected = {"gpm": RainMetrics, "smap": SoilMetrics, "sentinel1": WaterMetrics,
                    "dem": HeightMetrics, "hand": HeightMetrics}[self.component]
        if not isinstance(self.metrics, expected):
            raise ValueError("Measurement fields must match the component.")
        if static:
            if self.reason != "static_noncontemporaneous" or self.observed_start is not None or self.observed_end is not None:
                raise ValueError("Terrain must be labelled noncontemporaneous static context.")
            if self.component == "hand" and self.metrics.min_m < 0:
                raise ValueError("HAND must not be negative.")
        else:
            if self.observed_start is None or self.observed_end is None or self.observed_start > self.observed_end:
                raise ValueError("Observed datasets require ordered acquisition coverage.")
            expected_reason = "partial_temporal_coverage" if self.component == "gpm" and self.metrics.temporal_coverage_fraction < 1 else "measured"
            if self.reason != expected_reason:
                raise ValueError("Component reason must describe its measurements.")
        return self


class ContextResult(ContextTask):
    worker_id: Literal["hydro-worker", "flood-worker"]
    status: Literal["complete", "partial"]
    components: Annotated[list[ContextComponent], Field(min_length=2, max_length=3)]

    @model_validator(mode="after")
    def result_consistent(self) -> Self:
        hydro = self.analysis_type == "hydrometeorology"
        if self.worker_id != ("hydro-worker" if hydro else "flood-worker"):
            raise ValueError("Context worker role must match the task.")
        expected = {"gpm", "smap"} if hydro else {"sentinel1", "dem", "hand"}
        if len(self.components) != len(expected) or {item.component for item in self.components} != expected:
            raise ValueError("Every expected component must occur exactly once.")
        complete = True
        for item in self.components:
            if item.availability == "unavailable":
                complete = False
                continue
            if item.component in {"dem", "hand"}:
                raise ValueError("Dated investigations cannot accept terrain without a verified observation period.")
            if item.temporal_kind == "observation":
                if not self.start_time <= item.observed_start <= item.observed_end <= self.end_time:
                    raise ValueError("Observations must remain inside the requested interval.")
                if item.component == "sentinel1" and item.observed_start != item.observed_end:
                    raise ValueError("Snapshot datasets have one acquisition timestamp.")
                if item.component == "sentinel1" and item.observed_end == self.end_time:
                    raise ValueError("Snapshot timestamps must precede the exclusive interval end.")
                if item.component == "smap" and (
                    item.observed_start != item.metrics.timestamp_utc - timedelta(hours=1.5)
                    or item.observed_end != item.metrics.timestamp_utc + timedelta(hours=1.5)
                ):
                    raise ValueError("SMAP geophysical fields cover the three-hour interval around their timestamp.")
            if item.component == "gpm":
                hours = (self.end_time - self.start_time).total_seconds() / 3600
                if item.metrics.requested_hours != hours:
                    raise ValueError("Rainfall denominator must match the requested interval.")
                if item.metrics.temporal_coverage_fraction < 1:
                    complete = False
            fractions = [getattr(item.metrics, name) for name in ("valid_fraction", "surface_valid_fraction", "rootzone_valid_fraction") if hasattr(item.metrics, name)]
            if any(fraction < 1 for fraction in fractions):
                complete = False
        if self.status != ("complete" if complete else "partial"):
            raise ValueError("Context status must reflect missing temporal or spatial coverage.")
        return self


def unavailable(component: str, reason: str) -> ContextComponent:
    return ContextComponent(component=component, availability="unavailable", reason=reason,
                            temporal_kind="static_context" if component in {"dem", "hand"} else "observation")


def context_result(task: ContextTask, components: list[ContextComponent]) -> dict:
    """Construct a strict result; compute completeness without filling any gaps."""
    complete = all(item.availability == "available" for item in components)
    for item in components:
        if item.metrics is not None:
            for name in ("valid_fraction", "surface_valid_fraction", "rootzone_valid_fraction", "temporal_coverage_fraction"):
                if hasattr(item.metrics, name) and getattr(item.metrics, name) < 1:
                    complete = False
    return ContextResult(**task.model_dump(),
                         worker_id="hydro-worker" if task.analysis_type == "hydrometeorology" else "flood-worker",
                         status="complete" if complete else "partial", components=components).model_dump(mode="json")
