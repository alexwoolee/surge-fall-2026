"""
MeshMind SMAP L4 processing utilities.

This module contains deterministic soil-moisture processing.

Responsibilities:
- open a real SMAP L4 HDF5 granule
- validate required datasets
- use 2D cell latitude/longitude arrays
- spatially subset the SMAP EASE-Grid to an AOI
- remove fill and invalid values
- calculate deterministic surface soil-moisture statistics
- calculate deterministic root-zone soil-moisture statistics

The LLM must not calculate these values.
"""

from pathlib import Path
from typing import Any
import re

import h5py
import numpy as np


SURFACE_SM_PATH = "Geophysical_Data/sm_surface"
ROOTZONE_SM_PATH = "Geophysical_Data/sm_rootzone"

CELL_LAT_PATH = "cell_lat"
CELL_LON_PATH = "cell_lon"


class SMAPProcessingError(Exception):
    """Raised when SMAP data cannot be processed safely."""


def _validate_bbox(
    bbox: tuple[float, float, float, float],
) -> None:
    """
    Validate bbox order:

    west, south, east, north
    """

    west, south, east, north = bbox

    if west >= east:
        raise SMAPProcessingError(
            "Invalid bbox: west must be less than east."
        )

    if south >= north:
        raise SMAPProcessingError(
            "Invalid bbox: south must be less than north."
        )

    if not (-180 <= west <= 180):
        raise SMAPProcessingError(
            "Invalid bbox west longitude."
        )

    if not (-180 <= east <= 180):
        raise SMAPProcessingError(
            "Invalid bbox east longitude."
        )

    if not (-90 <= south <= 90):
        raise SMAPProcessingError(
            "Invalid bbox south latitude."
        )

    if not (-90 <= north <= 90):
        raise SMAPProcessingError(
            "Invalid bbox north latitude."
        )


def _decode_attribute(
    value: Any,
) -> Any:
    """
    Convert common HDF5 byte attributes
    into normal Python strings.
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


def _attribute_as_float(
    dataset: h5py.Dataset,
    name: str,
) -> float | None:
    """
    Read a numeric HDF5 attribute as a float.
    """

    if name not in dataset.attrs:
        return None

    value = dataset.attrs[name]

    if isinstance(value, np.ndarray):
        value = value.item()

    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _get_fill_value(
    dataset: h5py.Dataset,
) -> float | None:
    """
    Find the dataset fill value.
    """

    fill_value = _attribute_as_float(
        dataset,
        "_FillValue",
    )

    if fill_value is not None:
        return fill_value

    fill_value = dataset.fillvalue

    if fill_value is None:
        return None

    try:
        return float(fill_value)
    except (TypeError, ValueError):
        return None


def _extract_timestamp_from_filename(
    file_path: Path,
) -> str | None:
    """
    Extract a SMAP timestamp from filenames such as:

    SMAP_L4_SM_gph_20211114T223000_Vv8010_001.h5
    """

    match = re.search(
        r"_(\d{8}T\d{6})_",
        file_path.name,
    )

    if match is None:
        return None

    timestamp = match.group(1)

    return (
        f"{timestamp[0:4]}-"
        f"{timestamp[4:6]}-"
        f"{timestamp[6:8]}T"
        f"{timestamp[9:11]}:"
        f"{timestamp[11:13]}:"
        f"{timestamp[13:15]}Z"
    )


def _build_valid_mask(
    values: np.ndarray,
    aoi_mask: np.ndarray,
    fill_value: float | None,
    valid_min: float | None,
    valid_max: float | None,
) -> np.ndarray:
    """
    Build a validity mask for one SMAP variable.
    """

    valid_mask = (
        aoi_mask
        & np.isfinite(values)
    )

    if fill_value is not None:
        valid_mask &= ~np.isclose(
            values,
            fill_value,
        )

    if valid_min is not None:
        valid_mask &= (
            values >= valid_min
        )

    if valid_max is not None:
        valid_mask &= (
            values <= valid_max
        )

    return valid_mask


def _summarize_variable(
    dataset_path: str,
    dataset: h5py.Dataset,
    values: np.ndarray,
    aoi_mask: np.ndarray,
) -> dict[str, Any]:
    """
    Calculate deterministic statistics for
    one SMAP soil-moisture variable.
    """

    fill_value = _get_fill_value(
        dataset
    )

    valid_min = _attribute_as_float(
        dataset,
        "valid_min",
    )

    valid_max = _attribute_as_float(
        dataset,
        "valid_max",
    )

    valid_mask = _build_valid_mask(
        values=values,
        aoi_mask=aoi_mask,
        fill_value=fill_value,
        valid_min=valid_min,
        valid_max=valid_max,
    )

    valid_values = values[
        valid_mask
    ]

    if valid_values.size == 0:
        raise SMAPProcessingError(
            f"No valid values remain for {dataset_path} "
            "inside the requested AOI."
        )

    units = _decode_attribute(
        dataset.attrs.get(
            "units",
            None,
        )
    )

    long_name = _decode_attribute(
        dataset.attrs.get(
            "long_name",
            None,
        )
    )

    if isinstance(long_name, str):
        long_name = long_name.strip()

    return {
        "dataset": dataset_path,
        "units": units,
        "long_name": long_name,
        "fill_value": fill_value,
        "valid_min": valid_min,
        "valid_max": valid_max,
        "valid_pixels": int(
            valid_values.size
        ),
        "mean": float(
            valid_values.mean()
        ),
        "minimum": float(
            valid_values.min()
        ),
        "maximum": float(
            valid_values.max()
        ),
        "standard_deviation": float(
            valid_values.std()
        ),
    }


def analyze_smap_granule(
    file_path: str | Path,
    bbox: tuple[float, float, float, float],
) -> dict[str, Any]:
    """
    Analyze one SMAP L4 soil-moisture granule.

    Parameters
    ----------
    file_path:
        Local path to an SPL4SMGP HDF5 file.

    bbox:
        Geographic bounding box:

        (west, south, east, north)

    Returns
    -------
    dict
        Deterministic surface and root-zone
        soil-moisture statistics.
    """

    _validate_bbox(bbox)

    file_path = Path(
        file_path
    )

    if not file_path.exists():
        raise SMAPProcessingError(
            f"SMAP file does not exist: {file_path}"
        )

    west, south, east, north = bbox

    with h5py.File(
        file_path,
        "r",
    ) as hdf:

        required_paths = (
            SURFACE_SM_PATH,
            ROOTZONE_SM_PATH,
            CELL_LAT_PATH,
            CELL_LON_PATH,
        )

        for path in required_paths:

            if path not in hdf:
                raise SMAPProcessingError(
                    f"Required SMAP dataset missing: {path}"
                )

        surface_dataset = hdf[
            SURFACE_SM_PATH
        ]

        rootzone_dataset = hdf[
            ROOTZONE_SM_PATH
        ]

        cell_lat_dataset = hdf[
            CELL_LAT_PATH
        ]

        cell_lon_dataset = hdf[
            CELL_LON_PATH
        ]

        expected_shape = (
            surface_dataset.shape
        )

        if (
            rootzone_dataset.shape
            != expected_shape
        ):
            raise SMAPProcessingError(
                "Surface and root-zone datasets "
                "have different grid shapes."
            )

        if (
            cell_lat_dataset.shape
            != expected_shape
        ):
            raise SMAPProcessingError(
                "cell_lat does not match "
                "soil-moisture grid shape."
            )

        if (
            cell_lon_dataset.shape
            != expected_shape
        ):
            raise SMAPProcessingError(
                "cell_lon does not match "
                "soil-moisture grid shape."
            )

        # -------------------------------------------------
        # Read geolocation arrays
        # -------------------------------------------------
        #
        # SMAP's cell_lat and cell_lon are two-dimensional,
        # unlike the one-dimensional GPM coordinate arrays.

        cell_lat = np.asarray(
            cell_lat_dataset[:],
            dtype=np.float64,
        )

        cell_lon = np.asarray(
            cell_lon_dataset[:],
            dtype=np.float64,
        )

        coordinate_mask = (
            np.isfinite(cell_lat)
            & np.isfinite(cell_lon)
            & (cell_lon >= west)
            & (cell_lon <= east)
            & (cell_lat >= south)
            & (cell_lat <= north)
        )

        matching_rows, matching_cols = (
            np.where(coordinate_mask)
        )

        if matching_rows.size == 0:
            raise SMAPProcessingError(
                "Requested AOI does not intersect "
                "the SMAP grid."
            )

        # -------------------------------------------------
        # Find smallest raster window around the AOI
        # -------------------------------------------------

        row_start = int(
            matching_rows.min()
        )

        row_stop = int(
            matching_rows.max()
        ) + 1

        col_start = int(
            matching_cols.min()
        )

        col_stop = int(
            matching_cols.max()
        ) + 1

        row_slice = slice(
            row_start,
            row_stop,
        )

        col_slice = slice(
            col_start,
            col_stop,
        )

        # -------------------------------------------------
        # Read only the selected soil-moisture window
        # -------------------------------------------------

        surface = np.asarray(
            surface_dataset[
                row_slice,
                col_slice,
            ],
            dtype=np.float64,
        )

        rootzone = np.asarray(
            rootzone_dataset[
                row_slice,
                col_slice,
            ],
            dtype=np.float64,
        )

        selected_lat = cell_lat[
            row_slice,
            col_slice,
        ]

        selected_lon = cell_lon[
            row_slice,
            col_slice,
        ]

        # -------------------------------------------------
        # Exact AOI mask inside rectangular window
        # -------------------------------------------------

        aoi_mask = (
            np.isfinite(selected_lat)
            & np.isfinite(selected_lon)
            & (selected_lon >= west)
            & (selected_lon <= east)
            & (selected_lat >= south)
            & (selected_lat <= north)
        )

        aoi_pixels = int(
            np.count_nonzero(
                aoi_mask
            )
        )

        if aoi_pixels == 0:
            raise SMAPProcessingError(
                "SMAP AOI window contains "
                "no matching cells."
            )

        # -------------------------------------------------
        # Summarize variables while HDF5 attributes
        # are still available.
        # -------------------------------------------------

        surface_summary = (
            _summarize_variable(
                SURFACE_SM_PATH,
                surface_dataset,
                surface,
                aoi_mask,
            )
        )

        rootzone_summary = (
            _summarize_variable(
                ROOTZONE_SM_PATH,
                rootzone_dataset,
                rootzone,
                aoi_mask,
            )
        )

    # -----------------------------------------------------
    # Coordinate statistics
    # -----------------------------------------------------

    aoi_latitudes = selected_lat[
        aoi_mask
    ]

    aoi_longitudes = selected_lon[
        aoi_mask
    ]

    # -----------------------------------------------------
    # Final deterministic result
    # -----------------------------------------------------

    result = {
        "source": "NASA SMAP L4",
        "product": "SPL4SMGP",
        "version": "008",
        "file": file_path.name,
        "timestamp_utc": (
            _extract_timestamp_from_filename(
                file_path
            )
        ),
        "bbox": {
            "west": west,
            "south": south,
            "east": east,
            "north": north,
        },
        "selected_grid": {
            "row_start": row_start,
            "row_stop": row_stop,
            "column_start": col_start,
            "column_stop": col_stop,
            "window_rows": int(
                row_stop - row_start
            ),
            "window_columns": int(
                col_stop - col_start
            ),
            "window_pixels": int(
                surface.size
            ),
            "aoi_pixels": aoi_pixels,
            "longitude_min": float(
                aoi_longitudes.min()
            ),
            "longitude_max": float(
                aoi_longitudes.max()
            ),
            "latitude_min": float(
                aoi_latitudes.min()
            ),
            "latitude_max": float(
                aoi_latitudes.max()
            ),
        },
        "surface_soil_moisture": (
            surface_summary
        ),
        "rootzone_soil_moisture": (
            rootzone_summary
        ),
    }

    return result