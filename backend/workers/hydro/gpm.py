"""
MeshMind GPM IMERG processing utilities.

This module contains deterministic rainfall-processing logic.

Responsibilities:
- open a real GPM IMERG HDF5 granule
- validate the expected datasets
- spatially subset the global grid to an AOI
- remove invalid/fill values
- calculate precipitation-rate statistics
- convert half-hourly precipitation rates into accumulation
- accumulate rainfall across multiple half-hourly granules

The LLM must not calculate these values.
"""

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
import re
from typing import Any

import h5py
import numpy as np


PRECIPITATION_PATH = "Grid/precipitation"
LATITUDE_PATH = "Grid/lat"
LONGITUDE_PATH = "Grid/lon"

DEFAULT_GRANULE_DURATION_HOURS = 0.5


class GPMProcessingError(Exception):
    """Raised when a GPM granule cannot be processed safely."""


def _validate_duration(value: float) -> None:
    if not np.isfinite(value) or value <= 0:
        raise GPMProcessingError("Granule duration must be finite and greater than zero.")


@contextmanager
def _open_gpm(file_path: Path):
    try:
        with h5py.File(file_path, "r") as hdf:
            yield hdf
    except OSError as exc:
        raise GPMProcessingError(f"Cannot read GPM file: {file_path.name}") from exc


def _parse_time(value: str | datetime) -> datetime:
    try:
        parsed = value if isinstance(value, datetime) else datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError("Timezone is required")
        return parsed.astimezone(timezone.utc)
    except (AttributeError, TypeError, ValueError) as exc:
        raise GPMProcessingError("Times must be ISO 8601 timestamps with a timezone.") from exc


def _time_window(start_time, end_time):
    if start_time is None and end_time is None:
        return None
    if start_time is None or end_time is None:
        raise GPMProcessingError("Provide both start_time and end_time.")
    start, end = _parse_time(start_time), _parse_time(end_time)
    if start >= end:
        raise GPMProcessingError("start_time must be before end_time.")
    return start, end


def _iso(value: datetime | None) -> str | None:
    return value.isoformat().replace("+00:00", "Z") if value else None


def _observation_interval(file_path: Path, hdf: h5py.File):
    """Read UTC half-hours from the IMERG name or PPS FileHeader.

    NASA's V07 technical documentation specifies date/S/E fields in UTC:
    https://gpm.nasa.gov/sites/default/files/2023-07/IMERG_TechnicalDocumentation_final_230713.pdf
    Filename ends are inclusive seconds; FileHeader ends may include milliseconds.
    Internally all intervals use an exclusive end.
    """
    match = re.match(
        r"^3B-HHR(?:-[EL])?\.MS\.MRG\.3IMERG\.(\d{8})-S(\d{6})-E(\d{6})\.",
        file_path.name,
    )
    named_interval = None
    if match:
        try:
            start = datetime.strptime(match[1] + match[2], "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)
            end = datetime.strptime(match[1] + match[3], "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)
            if end < start:
                end += timedelta(days=1)
            named_interval = start, end + timedelta(seconds=1)
        except ValueError as exc:
            raise GPMProcessingError(f"Invalid IMERG timestamp: {file_path.name}") from exc

    header = _decode_attribute(hdf.attrs.get("FileHeader", ""))
    header_interval = None
    if isinstance(header, str):
        fields = dict(re.findall(r"([A-Za-z]+)\s*=\s*([^;]*);", header))
        start_text = fields.get("StartGranuleDateTime")
        stop_text = fields.get("StopGranuleDateTime")
        if start_text is not None or stop_text is not None:
            if not start_text or not stop_text:
                raise GPMProcessingError("GPM FileHeader has incomplete observation times.")
            start, stop = _parse_time(start_text.strip()), _parse_time(stop_text.strip())
            end = start + timedelta(minutes=30)
            if not end - timedelta(seconds=1) <= stop < end:
                raise GPMProcessingError("Expected a half-hour GPM observation interval.")
            header_interval = start, end

    interval = header_interval or named_interval
    if interval:
        start, end = interval
        if end - start != timedelta(minutes=30) or start.minute not in (0, 30) or start.second or start.microsecond:
            raise GPMProcessingError("Expected a half-hour GPM observation interval on a 00/30 minute boundary.")
        if named_interval and header_interval and named_interval != header_interval:
            raise GPMProcessingError("GPM filename and FileHeader timestamps disagree.")
    return interval


def _select_observations(paths, duration_hours, window):
    records = []
    for path in paths:
        with _open_gpm(path) as hdf:
            interval = _observation_interval(path, hdf)
        if interval is None and window:
            raise GPMProcessingError(f"GPM observation time is unavailable: {path.name}")
        if interval is not None:
            if duration_hours != DEFAULT_GRANULE_DURATION_HOURS:
                raise GPMProcessingError("Timed IMERG observations require the native 0.5 hour duration.")
            start, end = interval
            if window:
                start, end = max(start, window[0]), min(end, window[1])
                if start >= end:
                    continue
            records.append((path, interval, start, end, (end - start).total_seconds() / 3600))
        else:
            records.append((path, None, None, None, duration_hours))
    if not records:
        raise GPMProcessingError("No GPM observations intersect the requested time range.")
    if any(record[1] is None for record in records) and any(record[1] is not None for record in records):
        raise GPMProcessingError("Cannot combine timed and untimed GPM observations.")
    records.sort(key=lambda record: (record[2] or datetime.min.replace(tzinfo=timezone.utc), record[0].name, str(record[0].resolve())))
    for previous, current in zip(records, records[1:]):
        if current[1] and current[1][0] < previous[1][1]:
            raise GPMProcessingError("Duplicate or overlapping GPM observation intervals were supplied.")
    return records


def _temporal_coverage(records, window):
    observed_hours = sum(record[4] for record in records)
    verified = all(record[1] is not None for record in records)
    start, end = (window or (records[0][2], records[-1][3])) if verified else (None, None)
    gaps = []
    if verified:
        cursor = start
        for record in records:
            if record[2] > cursor:
                gaps.append({"start_utc": _iso(cursor), "end_utc": _iso(record[2])})
            cursor = record[3]
        if cursor < end:
            gaps.append({"start_utc": _iso(cursor), "end_utc": _iso(end)})
    expected_hours = (end - start).total_seconds() / 3600 if verified else None
    return {
        "timing_verified": verified,
        "requested_start_utc": _iso(window[0]) if window else None,
        "requested_end_utc": _iso(window[1]) if window else None,
        "observation_start_utc": _iso(records[0][2]),
        "observation_end_utc": _iso(records[-1][3]),
        "observed_duration_hours": observed_hours,
        "expected_duration_hours": expected_hours,
        "coverage_fraction": observed_hours / expected_hours if expected_hours else None,
        "complete": not gaps if verified else None,
        "gaps": gaps,
        "partial_window_method": "Prorate the half-hour mean rate by the overlapping duration.",
    }


def _validate_bbox(
    bbox: tuple[float, float, float, float],
) -> None:
    """
    Validate bbox order:

    west, south, east, north
    """

    west, south, east, north = bbox

    if west >= east:
        raise GPMProcessingError(
            "Invalid bbox: west must be less than east."
        )

    if south >= north:
        raise GPMProcessingError(
            "Invalid bbox: south must be less than north."
        )

    if not (-180 <= west <= 180):
        raise GPMProcessingError(
            "Invalid bbox west longitude."
        )

    if not (-180 <= east <= 180):
        raise GPMProcessingError(
            "Invalid bbox east longitude."
        )

    if not (-90 <= south <= 90):
        raise GPMProcessingError(
            "Invalid bbox south latitude."
        )

    if not (-90 <= north <= 90):
        raise GPMProcessingError(
            "Invalid bbox north latitude."
        )


def _decode_attribute(value: Any) -> Any:
    """
    Convert common HDF5 byte attributes into readable text.
    """

    if isinstance(value, np.ndarray) and value.size == 1:
        value = value.item()

    if isinstance(value, bytes):
        return value.decode(
            "utf-8",
            errors="replace",
        )

    if isinstance(value, np.bytes_):
        return value.tobytes().decode(
            "utf-8",
            errors="replace",
        )

    return value


def _find_coordinate_slice(
    coordinates: np.ndarray,
    minimum: float,
    maximum: float,
) -> tuple[slice, np.ndarray]:
    """
    Find the contiguous coordinate slice intersecting
    the requested range.
    """

    tolerance = 1e-6

    indices = np.flatnonzero(
        (coordinates >= minimum - tolerance)
        & (coordinates <= maximum + tolerance)
    )

    if indices.size == 0:
        raise GPMProcessingError(
            "Requested AOI does not intersect "
            "the coordinate grid."
        )

    start = int(indices[0])
    stop = int(indices[-1]) + 1

    return (
        slice(start, stop),
        coordinates[start:stop],
    )


def _get_fill_value(
    dataset: h5py.Dataset,
) -> float | None:
    """
    Find the fill value declared by the HDF5 dataset,
    if one exists.
    """

    if "_FillValue" in dataset.attrs:
        value = dataset.attrs["_FillValue"]

        if isinstance(value, np.ndarray):
            value = value.item()

        return float(value)

    # HDF5's implicit zero fill is not a missing-data declaration.
    if dataset.id.get_create_plist().fill_value_defined() != h5py.h5d.FILL_VALUE_USER_DEFINED:
        return None

    fill_value = dataset.fillvalue

    if fill_value is None:
        return None

    try:
        return float(fill_value)
    except (TypeError, ValueError):
        return None


def analyze_gpm_granule(
    file_path: str | Path,
    bbox: tuple[float, float, float, float],
    duration_hours: float = DEFAULT_GRANULE_DURATION_HOURS,
    *,
    start_time: str | datetime | None = None,
    end_time: str | datetime | None = None,
) -> dict[str, Any]:
    """Analyze one local IMERG granule, optionally within [start_time, end_time).

    Time bounds must have an explicit timezone. Partial half-hours contribute
    the mean rate times the overlapping duration. Untimed legacy files remain
    supported without a requested window, with timing marked unverified.
    """
    _validate_bbox(bbox)
    _validate_duration(duration_hours)
    window = _time_window(start_time, end_time)
    file_path = Path(file_path)
    records = _select_observations([file_path], duration_hours, window)
    _, interval, selected_start, selected_end, effective_hours = records[0]
    granule = _read_gpm_aoi(file_path, bbox, effective_hours)
    valid_rates = granule["rates"][granule["valid_mask"]]
    if valid_rates.size == 0:
        raise GPMProcessingError("No valid precipitation pixels remain inside the AOI.")
    valid_accumulation = granule["accumulation"][granule["valid_mask"]]
    lons, lats = granule["longitudes"], granule["latitudes"]
    west, south, east, north = bbox
    return {
        "source": "NASA GPM IMERG",
        "product": "GPM_3IMERGHH",
        "version": "07",
        "file": file_path.name,
        "bbox": {"west": west, "south": south, "east": east, "north": north},
        "selected_grid": {
            "longitude_cells": int(lons.size),
            "latitude_cells": int(lats.size),
            "total_pixels": int(granule["rates"].size),
            "valid_pixels": int(valid_rates.size),
            "longitude_min": float(lons.min()),
            "longitude_max": float(lons.max()),
            "latitude_min": float(lats.min()),
            "latitude_max": float(lats.max()),
        },
        "dataset": {
            "path": PRECIPITATION_PATH,
            "units": granule["units"],
            "long_name": granule["long_name"],
            "fill_value": granule["fill_value"],
        },
        "granule_duration_hours": float(effective_hours),
        "temporal_coverage": _temporal_coverage(records, window),
        "rainfall": {
            "mean_rate_mm_hr": float(valid_rates.mean()),
            "max_rate_mm_hr": float(valid_rates.max()),
            "min_rate_mm_hr": float(valid_rates.min()),
            "area_mean_accumulation_mm": float(valid_accumulation.mean()),
            "max_cell_accumulation_mm": float(valid_accumulation.max()),
            "min_cell_accumulation_mm": float(valid_accumulation.min()),
        },
    }


def _read_gpm_aoi(
    file_path: str | Path,
    bbox: tuple[float, float, float, float],
    duration_hours: float,
) -> dict[str, Any]:
    """
    Read one IMERG granule and return the AOI arrays needed
    for multi-granule accumulation.

    This is an internal helper. It deliberately returns
    NumPy arrays and is not intended as the final API result.
    """

    _validate_bbox(bbox)

    _validate_duration(duration_hours)

    file_path = Path(file_path)

    if not file_path.exists():
        raise GPMProcessingError(
            f"GPM file does not exist: {file_path}"
        )

    west, south, east, north = bbox

    with _open_gpm(file_path) as hdf:

        required_paths = (
            PRECIPITATION_PATH,
            LATITUDE_PATH,
            LONGITUDE_PATH,
        )

        for path in required_paths:

            if path not in hdf:
                raise GPMProcessingError(
                    f"Required GPM dataset missing: {path}"
                )

        precipitation_dataset = hdf[
            PRECIPITATION_PATH
        ]

        latitudes = np.asarray(
            hdf[LATITUDE_PATH][:]
        )

        longitudes = np.asarray(
            hdf[LONGITUDE_PATH][:]
        )

        for name, coordinates in (("latitude", latitudes), ("longitude", longitudes)):
            if coordinates.ndim != 1 or coordinates.size == 0 or not np.isfinite(coordinates).all():
                raise GPMProcessingError(f"Invalid GPM {name} coordinates.")
            differences = np.diff(coordinates)
            if not (np.all(differences > 0) or np.all(differences < 0)):
                raise GPMProcessingError(f"GPM {name} coordinates must be strictly monotonic.")

        if precipitation_dataset.ndim != 3:
            raise GPMProcessingError(
                "Unexpected GPM precipitation "
                f"shape: {precipitation_dataset.shape}"
            )

        if precipitation_dataset.shape[0] != 1:
            raise GPMProcessingError(
                "Expected one time step in "
                "half-hourly GPM granule."
            )

        if (
            precipitation_dataset.shape[1]
            != longitudes.size
        ):
            raise GPMProcessingError(
                "Longitude dimension does not match "
                "the precipitation dataset."
            )

        if (
            precipitation_dataset.shape[2]
            != latitudes.size
        ):
            raise GPMProcessingError(
                "Latitude dimension does not match "
                "the precipitation dataset."
            )

        lon_slice, selected_lons = (
            _find_coordinate_slice(
                longitudes,
                west,
                east,
            )
        )

        lat_slice, selected_lats = (
            _find_coordinate_slice(
                latitudes,
                south,
                north,
            )
        )

        precipitation = np.asarray(
            precipitation_dataset[
                0,
                lon_slice,
                lat_slice,
            ],
            dtype=np.float64,
        )

        fill_value = _get_fill_value(
            precipitation_dataset
        )

        units = _decode_attribute(
            precipitation_dataset.attrs.get(
                "units",
                None,
            )
        )

        if not isinstance(units, str) or units.strip().lower() not in {"mm/hr", "mm/h", "mm hr-1", "mm h-1"}:
            raise GPMProcessingError(f"Expected GPM precipitation rate units in mm/hr, received {units!r}.")
        long_name = _decode_attribute(precipitation_dataset.attrs.get(
            "LongName", precipitation_dataset.attrs.get("long_name")
        ))

    # -----------------------------------------------------
    # Build validity mask
    # -----------------------------------------------------

    valid_mask = np.isfinite(
        precipitation
    )

    if fill_value is not None:
        valid_mask &= ~np.isclose(
            precipitation,
            fill_value,
        )

    valid_mask &= precipitation >= 0

    # -----------------------------------------------------
    # Convert rate to accumulation
    # -----------------------------------------------------

    accumulation = np.full(
        precipitation.shape,
        np.nan,
        dtype=np.float64,
    )

    accumulation[valid_mask] = (
        precipitation[valid_mask]
        * duration_hours
    )

    if not np.isfinite(accumulation[valid_mask]).all():
        raise GPMProcessingError("GPM accumulation exceeds the supported numeric range.")

    return {
        "file": file_path,
        "rates": precipitation,
        "accumulation": accumulation,
        "valid_mask": valid_mask,
        "longitudes": selected_lons,
        "latitudes": selected_lats,
        "fill_value": fill_value if fill_value is None or np.isfinite(fill_value) else None,
        "units": units,
        "long_name": long_name,
    }


def analyze_gpm_granules(
    file_paths: list[str | Path],
    bbox: tuple[float, float, float, float],
    duration_hours_per_granule: float = (
        DEFAULT_GRANULE_DURATION_HOURS
    ),
    *,
    start_time: str | datetime | None = None,
    end_time: str | datetime | None = None,
) -> dict[str, Any]:
    """
    Accumulate rainfall across multiple GPM IMERG granules.

    Each granule contains precipitation rate in mm/hr.

    A half-hour granule contributes:

        precipitation_rate * 0.5 hours

    Accumulation is performed cell-by-cell.

    Only pixels with valid observations in every granule
    are used for final cumulative statistics. This prevents
    missing observations from being silently treated as
    zero rainfall.

    Optional timezone-aware bounds select the half-open interval [start, end).
    Boundary half-hours are prorated using their mean rate and overlap duration.
    Time gaps are reported explicitly; totals cover only supplied observations.
    Without bounds, legacy untimed files remain usable with unverified timing.
    """

    _validate_bbox(bbox)

    if not file_paths:
        raise GPMProcessingError(
            "At least one GPM granule is required."
        )

    _validate_duration(duration_hours_per_granule)
    window = _time_window(start_time, end_time)

    paths = [
        Path(path)
        for path in file_paths
    ]

    # -----------------------------------------------------
    # Prevent duplicate granules
    # -----------------------------------------------------

    resolved_paths = [
        path.resolve()
        for path in paths
    ]

    if (
        len(set(resolved_paths))
        != len(resolved_paths)
    ):
        raise GPMProcessingError(
            "Duplicate GPM granules were supplied."
        )

    records = _select_observations(paths, duration_hours_per_granule, window)

    reference_lons = None
    reference_lats = None

    cumulative = None
    valid_observation_count = None

    granule_summaries = []

    # -----------------------------------------------------
    # Process every granule
    # -----------------------------------------------------

    for path, interval, selected_start, selected_end, effective_hours in records:

        granule = _read_gpm_aoi(
            path,
            bbox,
            effective_hours,
        )

        lons = granule["longitudes"]
        lats = granule["latitudes"]

        if reference_lons is None:

            reference_lons = lons
            reference_lats = lats

            cumulative = np.zeros(
                granule["accumulation"].shape,
                dtype=np.float64,
            )

            valid_observation_count = np.zeros(
                granule["accumulation"].shape,
                dtype=np.int32,
            )

        else:

            if not np.array_equal(
                reference_lons,
                lons,
            ):
                raise GPMProcessingError(
                    "Longitude grids differ between "
                    "GPM granules."
                )

            if not np.array_equal(
                reference_lats,
                lats,
            ):
                raise GPMProcessingError(
                    "Latitude grids differ between "
                    "GPM granules."
                )

        valid_mask = granule[
            "valid_mask"
        ]

        accumulation = granule[
            "accumulation"
        ]

        valid_rates = granule["rates"][
            valid_mask
        ]

        valid_accumulation = accumulation[
            valid_mask
        ]

        if valid_rates.size == 0:
            raise GPMProcessingError(
                f"No valid precipitation pixels "
                f"in granule: {path.name}"
            )

        # Add each valid pixel's rainfall accumulation
        # into the cumulative raster.
        cumulative[valid_mask] += (
            accumulation[valid_mask]
        )

        valid_observation_count[
            valid_mask
        ] += 1

        granule_summaries.append(
            {
                "file": path.name,
                "observation_start_utc": _iso(interval[0]) if interval else None,
                "observation_end_utc": _iso(interval[1]) if interval else None,
                "included_start_utc": _iso(selected_start),
                "included_end_utc": _iso(selected_end),
                "included_duration_hours": effective_hours,
                "valid_pixels": int(
                    valid_rates.size
                ),
                "mean_rate_mm_hr": float(
                    valid_rates.mean()
                ),
                "max_rate_mm_hr": float(
                    valid_rates.max()
                ),
                "area_mean_accumulation_mm": float(
                    valid_accumulation.mean()
                ),
            }
        )

    # -----------------------------------------------------
    # Require complete coverage
    # -----------------------------------------------------

    granule_count = len(records)

    complete_mask = (
        valid_observation_count
        == granule_count
    )

    complete_values = cumulative[
        complete_mask
    ]

    if not np.isfinite(complete_values).all():
        raise GPMProcessingError("Cumulative GPM rainfall exceeds the supported numeric range.")

    if complete_values.size == 0:
        raise GPMProcessingError(
            "No AOI pixels have complete coverage "
            "across all GPM granules."
        )

    total_pixels = int(
        cumulative.size
    )

    complete_pixels = int(
        complete_values.size
    )

    coverage_fraction = (
        complete_pixels
        / total_pixels
    )

    west, south, east, north = bbox

    # -----------------------------------------------------
    # Final deterministic result
    # -----------------------------------------------------

    result = {
        "source": "NASA GPM IMERG",
        "product": "GPM_3IMERGHH",
        "version": "07",
        "bbox": {
            "west": west,
            "south": south,
            "east": east,
            "north": north,
        },
        "granule_count": granule_count,
        "duration_hours_per_granule": float(
            duration_hours_per_granule
        ),
        "total_duration_hours": sum(record[4] for record in records),
        "temporal_coverage": _temporal_coverage(records, window),
        "selected_grid": {
            "longitude_cells": int(
                reference_lons.size
            ),
            "latitude_cells": int(
                reference_lats.size
            ),
            "total_pixels": total_pixels,
            "complete_coverage_pixels": (
                complete_pixels
            ),
            "complete_coverage_fraction": float(
                coverage_fraction
            ),
            "longitude_min": float(
                reference_lons.min()
            ),
            "longitude_max": float(
                reference_lons.max()
            ),
            "latitude_min": float(
                reference_lats.min()
            ),
            "latitude_max": float(
                reference_lats.max()
            ),
        },
        "rainfall": {
            "area_mean_total_accumulation_mm": float(
                complete_values.mean()
            ),
            "max_cell_total_accumulation_mm": float(
                complete_values.max()
            ),
            "min_cell_total_accumulation_mm": float(
                complete_values.min()
            ),
        },
        "granules": granule_summaries,
    }

    return result
