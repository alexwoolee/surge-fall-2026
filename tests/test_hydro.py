"""
Tests for MeshMind hydrometeorology processing.

These tests use small synthetic GPM-style HDF5 files so
they do not depend on NASA network access or local cache files.
"""

from pathlib import Path

import h5py
import numpy as np
import pytest

from backend.workers.hydro.gpm import (
    GPMProcessingError,
    analyze_gpm_granule,
    analyze_gpm_granules,
)


TEST_BBOX = (
    -122.45,
    48.95,
    -122.15,
    49.15,
)


def create_gpm_file(
    file_path: Path,
    precipitation: np.ndarray,
) -> Path:
    """
    Create a small synthetic HDF5 file matching the parts
    of the GPM IMERG structure that MeshMind uses.
    """

    longitudes = np.array(
        [
            -122.45,
            -122.35,
            -122.25,
            -122.15,
        ],
        dtype=np.float32,
    )

    latitudes = np.array(
        [
            48.95,
            49.05,
            49.15,
        ],
        dtype=np.float32,
    )

    with h5py.File(
        file_path,
        "w",
    ) as hdf:

        grid = hdf.create_group("Grid")

        grid.create_dataset(
            "lon",
            data=longitudes,
        )

        grid.create_dataset(
            "lat",
            data=latitudes,
        )

        dataset = grid.create_dataset(
            "precipitation",
            data=precipitation[
                np.newaxis,
                :,
                :,
            ],
            dtype=np.float32,
            fillvalue=-9999.9,
        )

        dataset.attrs["units"] = "mm/hr"
        dataset.attrs["_FillValue"] = -9999.9

    return file_path


def test_single_granule_accumulation(
    tmp_path: Path,
) -> None:

    rates = np.array(
        [
            [2.0, 4.0, 6.0],
            [4.0, 6.0, 8.0],
            [6.0, 8.0, 10.0],
            [8.0, 10.0, 12.0],
        ],
        dtype=np.float32,
    )

    file_path = create_gpm_file(
        tmp_path / "gpm_001.HDF5",
        rates,
    )

    result = analyze_gpm_granule(
        file_path,
        TEST_BBOX,
    )

    expected_mean_rate = float(
        rates.mean()
    )

    assert result["selected_grid"][
        "total_pixels"
    ] == 12

    assert result["selected_grid"][
        "valid_pixels"
    ] == 12

    assert result["rainfall"][
        "mean_rate_mm_hr"
    ] == pytest.approx(
        expected_mean_rate
    )

    assert result["rainfall"][
        "area_mean_accumulation_mm"
    ] == pytest.approx(
        expected_mean_rate * 0.5
    )

    assert result["rainfall"][
        "max_cell_accumulation_mm"
    ] == pytest.approx(
        12.0 * 0.5
    )


def test_two_granule_accumulation(
    tmp_path: Path,
) -> None:

    first = np.full(
        (4, 3),
        4.0,
        dtype=np.float32,
    )

    second = np.full(
        (4, 3),
        6.0,
        dtype=np.float32,
    )

    file_one = create_gpm_file(
        tmp_path / "gpm_001.HDF5",
        first,
    )

    file_two = create_gpm_file(
        tmp_path / "gpm_002.HDF5",
        second,
    )

    result = analyze_gpm_granules(
        [
            file_one,
            file_two,
        ],
        TEST_BBOX,
    )

    # 4 mm/hr * 0.5 h = 2 mm
    # 6 mm/hr * 0.5 h = 3 mm
    # Total = 5 mm at every grid cell.

    assert result[
        "granule_count"
    ] == 2

    assert result[
        "total_duration_hours"
    ] == pytest.approx(
        1.0
    )

    assert result["selected_grid"][
        "complete_coverage_fraction"
    ] == pytest.approx(
        1.0
    )

    assert result["rainfall"][
        "area_mean_total_accumulation_mm"
    ] == pytest.approx(
        5.0
    )

    assert result["rainfall"][
        "max_cell_total_accumulation_mm"
    ] == pytest.approx(
        5.0
    )

    assert result["rainfall"][
        "min_cell_total_accumulation_mm"
    ] == pytest.approx(
        5.0
    )


def test_fill_value_is_excluded(
    tmp_path: Path,
) -> None:

    rates = np.full(
        (4, 3),
        4.0,
        dtype=np.float32,
    )

    rates[0, 0] = -9999.9

    file_path = create_gpm_file(
        tmp_path / "gpm_fill.HDF5",
        rates,
    )

    result = analyze_gpm_granule(
        file_path,
        TEST_BBOX,
    )

    assert result["selected_grid"][
        "total_pixels"
    ] == 12

    assert result["selected_grid"][
        "valid_pixels"
    ] == 11


def test_invalid_bbox_raises(
    tmp_path: Path,
) -> None:

    rates = np.full(
        (4, 3),
        4.0,
        dtype=np.float32,
    )

    file_path = create_gpm_file(
        tmp_path / "gpm_bbox.HDF5",
        rates,
    )

    with pytest.raises(
        GPMProcessingError
    ):
        analyze_gpm_granule(
            file_path,
            (
                -121.0,
                49.0,
                -122.0,
                50.0,
            ),
        )


def test_duplicate_granule_rejected(
    tmp_path: Path,
) -> None:

    rates = np.full(
        (4, 3),
        4.0,
        dtype=np.float32,
    )

    file_path = create_gpm_file(
        tmp_path / "gpm_duplicate.HDF5",
        rates,
    )

    with pytest.raises(
        GPMProcessingError
    ):
        analyze_gpm_granules(
            [
                file_path,
                file_path,
            ],
            TEST_BBOX,
        )