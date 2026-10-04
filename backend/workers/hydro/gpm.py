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

from pathlib import Path
from typing import Any

import h5py
import numpy as np


PRECIPITATION_PATH = "Grid/precipitation"
LATITUDE_PATH = "Grid/lat"
LONGITUDE_PATH = "Grid/lon"

DEFAULT_GRANULE_DURATION_HOURS = 0.5


class GPMProcessingError(Exception):
    """Raised when a GPM granule cannot be processed safely."""


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
) -> dict[str, Any]:
    """
    Analyze one GPM IMERG half-hourly granule.

    Parameters
    ----------
    file_path:
        Local path to a GPM IMERG HDF5 granule.

    bbox:
        Geographic bounding box:

        (west, south, east, north)

    duration_hours:
        Duration represented by the precipitation rate.

        IMERG half-hourly granules use 0.5 hours.

    Returns
    -------
    dict
        Deterministic rainfall statistics for the AOI.
    """

    _validate_bbox(bbox)

    if duration_hours <= 0:
        raise GPMProcessingError(
            "duration_hours must be greater than zero."
        )

    file_path = Path(file_path)

    if not file_path.exists():
        raise GPMProcessingError(
            f"GPM file does not exist: {file_path}"
        )

    west, south, east, north = bbox

    with h5py.File(
        file_path,
        "r",
    ) as hdf:

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
                "GPM longitude dimension does not "
                "match precipitation array."
            )

        if (
            precipitation_dataset.shape[2]
            != latitudes.size
        ):
            raise GPMProcessingError(
                "GPM latitude dimension does not "
                "match precipitation array."
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

        long_name = _decode_attribute(
            precipitation_dataset.attrs.get(
                "LongName",
                precipitation_dataset.attrs.get(
                    "long_name",
                    None,
                ),
            )
        )

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

    # Negative precipitation rates are not physically
    # meaningful and are commonly used for missing values.
    valid_mask &= precipitation >= 0

    valid_rates = precipitation[
        valid_mask
    ]

    if valid_rates.size == 0:
        raise GPMProcessingError(
            "No valid precipitation pixels "
            "remain inside the AOI."
        )

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

    valid_accumulation = accumulation[
        np.isfinite(accumulation)
    ]

    # -----------------------------------------------------
    # Deterministic summary
    # -----------------------------------------------------

    result = {
        "source": "NASA GPM IMERG",
        "product": "GPM_3IMERGHH",
        "version": "07",
        "file": file_path.name,
        "bbox": {
            "west": west,
            "south": south,
            "east": east,
            "north": north,
        },
        "selected_grid": {
            "longitude_cells": int(
                selected_lons.size
            ),
            "latitude_cells": int(
                selected_lats.size
            ),
            "total_pixels": int(
                precipitation.size
            ),
            "valid_pixels": int(
                valid_rates.size
            ),
            "longitude_min": float(
                selected_lons.min()
            ),
            "longitude_max": float(
                selected_lons.max()
            ),
            "latitude_min": float(
                selected_lats.min()
            ),
            "latitude_max": float(
                selected_lats.max()
            ),
        },
        "dataset": {
            "path": PRECIPITATION_PATH,
            "units": units,
            "long_name": long_name,
            "fill_value": fill_value,
        },
        "granule_duration_hours": (
            float(duration_hours)
        ),
        "rainfall": {
            "mean_rate_mm_hr": float(
                valid_rates.mean()
            ),
            "max_rate_mm_hr": float(
                valid_rates.max()
            ),
            "min_rate_mm_hr": float(
                valid_rates.min()
            ),
            "area_mean_accumulation_mm": float(
                valid_accumulation.mean()
            ),
            "max_cell_accumulation_mm": float(
                valid_accumulation.max()
            ),
            "min_cell_accumulation_mm": float(
                valid_accumulation.min()
            ),
        },
    }

    return result


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

    if duration_hours <= 0:
        raise GPMProcessingError(
            "duration_hours must be greater than zero."
        )

    file_path = Path(file_path)

    if not file_path.exists():
        raise GPMProcessingError(
            f"GPM file does not exist: {file_path}"
        )

    west, south, east, north = bbox

    with h5py.File(
        file_path,
        "r",
    ) as hdf:

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

    return {
        "file": file_path,
        "rates": precipitation,
        "accumulation": accumulation,
        "valid_mask": valid_mask,
        "longitudes": selected_lons,
        "latitudes": selected_lats,
        "fill_value": fill_value,
        "units": units,
    }


def analyze_gpm_granules(
    file_paths: list[str | Path],
    bbox: tuple[float, float, float, float],
    duration_hours_per_granule: float = (
        DEFAULT_GRANULE_DURATION_HOURS
    ),
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
    """

    _validate_bbox(bbox)

    if not file_paths:
        raise GPMProcessingError(
            "At least one GPM granule is required."
        )

    if duration_hours_per_granule <= 0:
        raise GPMProcessingError(
            "duration_hours_per_granule must be "
            "greater than zero."
        )

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

    # Standard IMERG filenames sort chronologically.
    paths = sorted(
        paths,
        key=lambda path: path.name,
    )

    reference_lons = None
    reference_lats = None

    cumulative = None
    valid_observation_count = None

    granule_summaries = []

    # -----------------------------------------------------
    # Process every granule
    # -----------------------------------------------------

    for path in paths:

        granule = _read_gpm_aoi(
            path,
            bbox,
            duration_hours_per_granule,
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

    granule_count = len(paths)

    complete_mask = (
        valid_observation_count
        == granule_count
    )

    complete_values = cumulative[
        complete_mask
    ]

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
        "total_duration_hours": float(
            granule_count
            * duration_hours_per_granule
        ),
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