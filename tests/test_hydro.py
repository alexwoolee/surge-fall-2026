"""
Tests for MeshMind hydrometeorology processing.

These tests use small synthetic GPM-style HDF5 files so
they do not depend on NASA network access or local cache files.
"""

from pathlib import Path
import json
import shutil

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


def timed_gpm_file(tmp_path, start="000000", end="002959", rate=4.0, date="20211115"):
    return create_gpm_file(
        tmp_path / f"3B-HHR.MS.MRG.3IMERG.{date}-S{start}-E{end}.0000.V07B.HDF5",
        np.full((4, 3), rate, dtype=np.float32),
    )


def test_temporal_filtering_and_half_open_boundaries(tmp_path):
    before = timed_gpm_file(tmp_path, rate=100)
    selected = timed_gpm_file(tmp_path, "003000", "005959", rate=4)
    after = timed_gpm_file(tmp_path, "010000", "012959", rate=100)
    result = analyze_gpm_granules(
        [after, selected, before], TEST_BBOX,
        start_time="2021-11-15T00:30:00Z", end_time="2021-11-15T01:00:00Z",
    )
    assert result["granule_count"] == 1
    assert result["granules"][0]["file"] == selected.name
    assert result["rainfall"]["area_mean_total_accumulation_mm"] == 2
    assert result["temporal_coverage"]["complete"] is True
    assert result["temporal_coverage"]["coverage_fraction"] == 1


def test_partial_window_prorates_mean_rate_and_normalizes_timezone(tmp_path):
    first = timed_gpm_file(tmp_path, rate=4)
    second = timed_gpm_file(tmp_path, "003000", "005959", rate=8)
    result = analyze_gpm_granules(
        [second, first], TEST_BBOX,
        start_time="2021-11-14T16:15:00-08:00", end_time="2021-11-15T00:45:00Z",
    )
    assert result["total_duration_hours"] == 0.5
    assert result["rainfall"]["area_mean_total_accumulation_mm"] == 3
    assert result["temporal_coverage"]["requested_start_utc"] == "2021-11-15T00:15:00Z"
    assert [g["included_duration_hours"] for g in result["granules"]] == [0.25, 0.25]


def test_single_granule_window_and_metadata_only_timestamp(tmp_path):
    path = create_gpm_file(tmp_path / "renamed.HDF5", np.full((4, 3), 8))
    with h5py.File(path, "a") as hdf:
        hdf.attrs["FileHeader"] = np.array([
            b"StartGranuleDateTime=2021-11-15T00:00:00.000Z;StopGranuleDateTime=2021-11-15T00:29:59.999Z;"
        ])
    result = analyze_gpm_granule(
        path, TEST_BBOX,
        start_time="2021-11-15T00:15:00Z", end_time="2021-11-15T00:30:00Z",
    )
    assert result["rainfall"]["area_mean_accumulation_mm"] == 2
    assert result["temporal_coverage"]["timing_verified"] is True


def test_missing_intervals_are_reported_without_zero_filling(tmp_path):
    first = timed_gpm_file(tmp_path, "003000", "005959", rate=4)
    last = timed_gpm_file(tmp_path, "013000", "015959", rate=8)
    result = analyze_gpm_granules(
        [last, first], TEST_BBOX,
        start_time="2021-11-15T00:00:00Z", end_time="2021-11-15T02:30:00Z",
    )
    coverage = result["temporal_coverage"]
    assert coverage["observed_duration_hours"] == 1
    assert coverage["expected_duration_hours"] == 2.5
    assert coverage["coverage_fraction"] == 0.4
    assert coverage["complete"] is False
    assert coverage["gaps"] == [
        {"start_utc": "2021-11-15T00:00:00Z", "end_utc": "2021-11-15T00:30:00Z"},
        {"start_utc": "2021-11-15T01:00:00Z", "end_utc": "2021-11-15T01:30:00Z"},
        {"start_utc": "2021-11-15T02:00:00Z", "end_utc": "2021-11-15T02:30:00Z"},
    ]
    assert result["rainfall"]["area_mean_total_accumulation_mm"] == 6


def test_copied_observation_is_rejected(tmp_path):
    first = timed_gpm_file(tmp_path)
    destination = tmp_path / "copy"
    destination.mkdir()
    second = destination / first.name
    shutil.copyfile(first, second)
    with pytest.raises(GPMProcessingError, match="overlapping"):
        analyze_gpm_granules([first, second], TEST_BBOX)


@pytest.mark.parametrize("times", [
    {"start_time": "2021-11-15T00:00:00Z"},
    {"start_time": "2021-11-15T00:30:00Z", "end_time": "2021-11-15T00:00:00Z"},
    {"start_time": "2021-11-15T00:00:00", "end_time": "2021-11-15T00:30:00Z"},
    {"start_time": "invalid", "end_time": "2021-11-15T00:30:00Z"},
])
def test_invalid_time_window_rejected(tmp_path, times):
    with pytest.raises(GPMProcessingError):
        analyze_gpm_granules([timed_gpm_file(tmp_path)], TEST_BBOX, **times)


def test_no_matching_observations_rejected(tmp_path):
    with pytest.raises(GPMProcessingError, match="No GPM observations"):
        analyze_gpm_granules(
            [timed_gpm_file(tmp_path)], TEST_BBOX,
            start_time="2021-11-16T00:00:00Z", end_time="2021-11-16T01:00:00Z",
        )


def test_time_filter_requires_known_observation_time(tmp_path):
    path = create_gpm_file(tmp_path / "untimed.HDF5", np.ones((4, 3)))
    result = analyze_gpm_granules([path], TEST_BBOX)
    assert result["temporal_coverage"]["timing_verified"] is False
    assert result["temporal_coverage"]["complete"] is None
    with pytest.raises(GPMProcessingError, match="time is unavailable"):
        analyze_gpm_granules(
            [path], TEST_BBOX,
            start_time="2021-11-15T00:00:00Z", end_time="2021-11-15T01:00:00Z",
        )


def test_invalid_native_observation_duration_rejected(tmp_path):
    path = timed_gpm_file(tmp_path, "000000", "005959")
    with pytest.raises(GPMProcessingError, match="half-hour"):
        analyze_gpm_granules([path], TEST_BBOX)


def test_filename_metadata_disagreement_rejected(tmp_path):
    path = timed_gpm_file(tmp_path)
    with h5py.File(path, "a") as hdf:
        hdf.attrs["FileHeader"] = (
            "StartGranuleDateTime=2021-11-15T01:00:00Z;"
            "StopGranuleDateTime=2021-11-15T01:29:59.999Z;"
        )
    with pytest.raises(GPMProcessingError, match="disagree"):
        analyze_gpm_granule(path, TEST_BBOX)


@pytest.mark.parametrize("duration", [float("nan"), float("inf"), 0, -0.5])
def test_invalid_duration_rejected_by_both_apis(tmp_path, duration):
    path = timed_gpm_file(tmp_path)
    with pytest.raises(GPMProcessingError, match="finite"):
        analyze_gpm_granule(path, TEST_BBOX, duration_hours=duration)
    with pytest.raises(GPMProcessingError, match="finite"):
        analyze_gpm_granules([path], TEST_BBOX, duration_hours_per_granule=duration)


def test_implicit_hdf5_zero_fill_preserves_dry_pixels(tmp_path):
    rates = np.full((4, 3), 4.0)
    rates[0, :] = 0
    path = create_gpm_file(tmp_path / "dry.HDF5", rates)
    with h5py.File(path, "a") as hdf:
        del hdf["Grid/precipitation"]
        dataset = hdf.create_dataset("Grid/precipitation", data=rates[np.newaxis])
        dataset.attrs["units"] = np.array([b"mm/hr"])
    result = analyze_gpm_granule(path, TEST_BBOX)
    assert result["selected_grid"]["valid_pixels"] == 12
    assert result["rainfall"]["mean_rate_mm_hr"] == 3
    assert result["rainfall"]["min_rate_mm_hr"] == 0
    assert result["dataset"]["fill_value"] is None


def test_aoi_subsetting_excludes_outside_pixels(tmp_path):
    rates = np.full((4, 3), 100.0)
    rates[1:3, 1] = 2
    path = create_gpm_file(tmp_path / "subset.HDF5", rates)
    result = analyze_gpm_granule(path, (-122.4, 49.0, -122.2, 49.1))
    assert result["selected_grid"]["total_pixels"] == 2
    assert result["rainfall"]["mean_rate_mm_hr"] == 2
    with pytest.raises(GPMProcessingError, match="does not intersect"):
        analyze_gpm_granule(path, (10, 10, 11, 11))


@pytest.mark.parametrize("invalid", [-9999.9, -1, float("nan"), float("inf")])
def test_all_invalid_pixels_rejected(tmp_path, invalid):
    path = create_gpm_file(tmp_path / "invalid.HDF5", np.full((4, 3), invalid))
    with pytest.raises(GPMProcessingError, match="No valid precipitation"):
        analyze_gpm_granule(path, TEST_BBOX)
    with pytest.raises(GPMProcessingError, match="No valid precipitation"):
        analyze_gpm_granules([path], TEST_BBOX)


def test_incomplete_pixel_coverage_excludes_missing_observations(tmp_path):
    first = np.full((4, 3), 4.0)
    second = np.full((4, 3), 6.0)
    first[0, 0] = np.nan
    second[1, 0] = -9999.9
    paths = [create_gpm_file(tmp_path / "a.HDF5", first), create_gpm_file(tmp_path / "b.HDF5", second)]
    result = analyze_gpm_granules(paths, TEST_BBOX)
    assert result["selected_grid"]["complete_coverage_pixels"] == 10
    assert result["selected_grid"]["complete_coverage_fraction"] == pytest.approx(10 / 12)
    assert result["rainfall"]["area_mean_total_accumulation_mm"] == 5


def test_no_pixels_with_complete_coverage_rejected(tmp_path):
    first = np.full((4, 3), np.nan)
    second = np.full((4, 3), np.nan)
    first[:2] = 4
    second[2:] = 6
    paths = [create_gpm_file(tmp_path / "a.HDF5", first), create_gpm_file(tmp_path / "b.HDF5", second)]
    with pytest.raises(GPMProcessingError, match="complete coverage"):
        analyze_gpm_granules(paths, TEST_BBOX)


@pytest.mark.parametrize("units", ["kg/m2/s", "mm", None])
def test_unsupported_or_missing_units_rejected(tmp_path, units):
    path = timed_gpm_file(tmp_path)
    with h5py.File(path, "a") as hdf:
        del hdf["Grid/precipitation"].attrs["units"]
        if units:
            hdf["Grid/precipitation"].attrs["units"] = units
    with pytest.raises(GPMProcessingError, match="units"):
        analyze_gpm_granule(path, TEST_BBOX)


def test_repeated_and_reordered_runs_have_identical_strict_json(tmp_path):
    first = timed_gpm_file(tmp_path, rate=4)
    second = timed_gpm_file(tmp_path, "003000", "005959", rate=6)
    results = [analyze_gpm_granules(paths, TEST_BBOX) for paths in ([first, second], [second, first], [first, second])]
    assert json.dumps(results[0], allow_nan=False, sort_keys=True) == json.dumps(results[1], allow_nan=False, sort_keys=True)
    assert results[0] == results[2]


def test_unreadable_hdf5_raises_domain_error(tmp_path):
    path = tmp_path / "corrupt.HDF5"
    path.write_text("not HDF5")
    with pytest.raises(GPMProcessingError, match="Cannot read GPM file"):
        analyze_gpm_granule(path, TEST_BBOX)
    with pytest.raises(GPMProcessingError, match="Cannot read GPM file"):
        analyze_gpm_granules([path], TEST_BBOX)
