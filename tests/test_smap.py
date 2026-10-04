"""
Tests for MeshMind SMAP L4 soil-moisture processing.

These tests create small synthetic SMAP-style HDF5 files,
so they do not require NASA access or cached real data.
"""

from pathlib import Path

import h5py
import numpy as np
import pytest

from backend.workers.hydro.smap import (
    SMAPProcessingError,
    analyze_smap_granule,
)


TEST_BBOX = (
    -122.45,
    48.95,
    -121.95,
    49.30,
)


def create_smap_file(
    file_path: Path,
    surface: np.ndarray,
    rootzone: np.ndarray,
) -> Path:
    """
    Create a small synthetic SMAP-style HDF5 file containing
    the datasets used by MeshMind.
    """

    cell_lat = np.array(
        [
            [49.25, 49.25, 49.25],
            [49.10, 49.10, 49.10],
            [48.95, 48.95, 48.95],
        ],
        dtype=np.float32,
    )

    cell_lon = np.array(
        [
            [-122.40, -122.20, -122.00],
            [-122.40, -122.20, -122.00],
            [-122.40, -122.20, -122.00],
        ],
        dtype=np.float32,
    )

    with h5py.File(
        file_path,
        "w",
    ) as hdf:

        geophysical = hdf.create_group(
            "Geophysical_Data"
        )

        surface_dataset = geophysical.create_dataset(
            "sm_surface",
            data=surface,
            dtype=np.float32,
            fillvalue=-9999.0,
        )

        rootzone_dataset = geophysical.create_dataset(
            "sm_rootzone",
            data=rootzone,
            dtype=np.float32,
            fillvalue=-9999.0,
        )

        for dataset, long_name in (
            (
                surface_dataset,
                "Top layer soil moisture (0-5 cm)",
            ),
            (
                rootzone_dataset,
                "Root zone soil moisture (0-100 cm)",
            ),
        ):
            dataset.attrs["units"] = "m3 m-3"
            dataset.attrs["_FillValue"] = -9999.0
            dataset.attrs["valid_min"] = 0.0
            dataset.attrs["valid_max"] = 0.9
            dataset.attrs["long_name"] = long_name

        hdf.create_dataset(
            "cell_lat",
            data=cell_lat,
        )

        hdf.create_dataset(
            "cell_lon",
            data=cell_lon,
        )

    return file_path


def test_smap_statistics(
    tmp_path: Path,
) -> None:

    surface = np.array(
        [
            [0.30, 0.40, 0.50],
            [0.35, 0.45, 0.55],
            [0.25, 0.35, 0.45],
        ],
        dtype=np.float32,
    )

    rootzone = np.array(
        [
            [0.40, 0.42, 0.44],
            [0.38, 0.40, 0.42],
            [0.36, 0.38, 0.40],
        ],
        dtype=np.float32,
    )

    file_path = create_smap_file(
        tmp_path
        / "SMAP_L4_SM_gph_20211114T223000_test.h5",
        surface,
        rootzone,
    )

    result = analyze_smap_granule(
        file_path,
        TEST_BBOX,
    )

    assert result["selected_grid"][
        "aoi_pixels"
    ] == 9

    assert result["surface_soil_moisture"][
        "valid_pixels"
    ] == 9

    assert result["rootzone_soil_moisture"][
        "valid_pixels"
    ] == 9

    assert result["surface_soil_moisture"][
        "mean"
    ] == pytest.approx(
        float(surface.mean())
    )

    assert result["rootzone_soil_moisture"][
        "mean"
    ] == pytest.approx(
        float(rootzone.mean())
    )


def test_fill_value_is_excluded(
    tmp_path: Path,
) -> None:

    surface = np.full(
        (3, 3),
        0.4,
        dtype=np.float32,
    )

    rootzone = np.full(
        (3, 3),
        0.5,
        dtype=np.float32,
    )

    surface[0, 0] = -9999.0
    rootzone[1, 1] = -9999.0

    file_path = create_smap_file(
        tmp_path
        / "SMAP_L4_SM_gph_20211114T223000_fill.h5",
        surface,
        rootzone,
    )

    result = analyze_smap_granule(
        file_path,
        TEST_BBOX,
    )

    assert result["surface_soil_moisture"][
        "valid_pixels"
    ] == 8

    assert result["rootzone_soil_moisture"][
        "valid_pixels"
    ] == 8


def test_values_outside_valid_range_are_excluded(
    tmp_path: Path,
) -> None:

    surface = np.full(
        (3, 3),
        0.4,
        dtype=np.float32,
    )

    rootzone = np.full(
        (3, 3),
        0.5,
        dtype=np.float32,
    )

    surface[0, 0] = 1.2
    rootzone[0, 1] = -0.2

    file_path = create_smap_file(
        tmp_path
        / "SMAP_L4_SM_gph_20211114T223000_range.h5",
        surface,
        rootzone,
    )

    result = analyze_smap_granule(
        file_path,
        TEST_BBOX,
    )

    assert result["surface_soil_moisture"][
        "valid_pixels"
    ] == 8

    assert result["rootzone_soil_moisture"][
        "valid_pixels"
    ] == 8


def test_invalid_bbox_raises(
    tmp_path: Path,
) -> None:

    surface = np.full(
        (3, 3),
        0.4,
        dtype=np.float32,
    )

    rootzone = np.full(
        (3, 3),
        0.5,
        dtype=np.float32,
    )

    file_path = create_smap_file(
        tmp_path
        / "SMAP_L4_SM_gph_20211114T223000_bbox.h5",
        surface,
        rootzone,
    )

    with pytest.raises(
        SMAPProcessingError
    ):
        analyze_smap_granule(
            file_path,
            (
                -121.0,
                49.0,
                -122.0,
                50.0,
            ),
        )


def test_non_intersecting_bbox_raises(
    tmp_path: Path,
) -> None:

    surface = np.full(
        (3, 3),
        0.4,
        dtype=np.float32,
    )

    rootzone = np.full(
        (3, 3),
        0.5,
        dtype=np.float32,
    )

    file_path = create_smap_file(
        tmp_path
        / "SMAP_L4_SM_gph_20211114T223000_outside.h5",
        surface,
        rootzone,
    )

    with pytest.raises(
        SMAPProcessingError
    ):
        analyze_smap_granule(
            file_path,
            (
                -100.0,
                30.0,
                -99.0,
                31.0,
            ),
        )


def test_timestamp_extracted_from_filename(
    tmp_path: Path,
) -> None:

    surface = np.full(
        (3, 3),
        0.4,
        dtype=np.float32,
    )

    rootzone = np.full(
        (3, 3),
        0.5,
        dtype=np.float32,
    )

    file_path = create_smap_file(
        tmp_path
        / "SMAP_L4_SM_gph_20211114T223000_Vv8010_001.h5",
        surface,
        rootzone,
    )

    result = analyze_smap_granule(
        file_path,
        TEST_BBOX,
    )

    assert result["timestamp_utc"] == (
        "2021-11-14T22:30:00Z"
    )