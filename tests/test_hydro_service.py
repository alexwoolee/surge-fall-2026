"""
Tests for the MeshMind hydrometeorology worker service.

The GPM and SMAP processors already have dedicated numerical
tests. These tests focus on worker orchestration, structured
output, and failure handling.
"""

from pathlib import Path

import pytest

import backend.workers.hydro.service as hydro_service

from backend.workers.hydro.gpm import (
    GPMProcessingError,
)

from backend.workers.hydro.service import (
    HydroWorkerError,
    run_hydro_analysis,
)

from backend.workers.hydro.smap import (
    SMAPProcessingError,
)


TEST_BBOX = (
    -122.45,
    48.95,
    -121.95,
    49.30,
)


def _fake_gpm_result() -> dict:
    return {
        "source": "NASA GPM IMERG",
        "product": "GPM_3IMERGHH",
        "version": "07",
        "granule_count": 2,
        "total_duration_hours": 1.0,
        "rainfall": {
            "area_mean_total_accumulation_mm": 6.5,
            "max_cell_total_accumulation_mm": 15.0,
            "min_cell_total_accumulation_mm": 2.0,
        },
    }


def _fake_smap_result() -> dict:
    return {
        "source": "NASA SMAP L4",
        "product": "SPL4SMGP",
        "version": "008",
        "timestamp_utc": "2021-11-14T22:30:00Z",
        "surface_soil_moisture": {
            "mean": 0.40,
            "maximum": 0.44,
        },
        "rootzone_soil_moisture": {
            "mean": 0.39,
            "maximum": 0.43,
        },
    }


def test_hydro_service_combines_results(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:

    gpm_one = (
        tmp_path / "gpm_001.HDF5"
    )

    gpm_two = (
        tmp_path / "gpm_002.HDF5"
    )

    smap = (
        tmp_path / "smap_001.h5"
    )

    gpm_one.touch()
    gpm_two.touch()
    smap.touch()

    monkeypatch.setattr(
        hydro_service,
        "analyze_gpm_granules",
        lambda files, bbox: _fake_gpm_result(),
    )

    monkeypatch.setattr(
        hydro_service,
        "analyze_smap_granule",
        lambda file_path, bbox: _fake_smap_result(),
    )

    result = run_hydro_analysis(
        gpm_files=[
            gpm_one,
            gpm_two,
        ],
        smap_file=smap,
        bbox=TEST_BBOX,
        task_id="test-task-001",
    )

    assert result[
        "task_id"
    ] == "test-task-001"

    assert result[
        "worker_id"
    ] == "hydro-worker"

    assert result[
        "analysis_type"
    ] == "hydrometeorology"

    assert result[
        "status"
    ] == "complete"

    assert result["summary"][
        "rainfall"
    ][
        "area_mean_total_accumulation_mm"
    ] == pytest.approx(
        6.5
    )

    assert result["summary"][
        "rainfall"
    ][
        "granule_count"
    ] == 2

    assert result["summary"][
        "soil_moisture"
    ][
        "surface_mean_m3_m3"
    ] == pytest.approx(
        0.40
    )

    assert result["summary"][
        "soil_moisture"
    ][
        "rootzone_mean_m3_m3"
    ] == pytest.approx(
        0.39
    )

    assert len(
        result["sources"]
    ) == 2

    assert result["evidence"][
        "gpm"
    ][
        "product"
    ] == "GPM_3IMERGHH"

    assert result["evidence"][
        "smap"
    ][
        "product"
    ] == "SPL4SMGP"


def test_missing_gpm_file_rejected(
    tmp_path: Path,
) -> None:

    missing_gpm = (
        tmp_path / "missing.HDF5"
    )

    smap = (
        tmp_path / "smap.h5"
    )

    smap.touch()

    with pytest.raises(
        HydroWorkerError,
        match="GPM resources do not exist",
    ):
        run_hydro_analysis(
            gpm_files=[
                missing_gpm
            ],
            smap_file=smap,
            bbox=TEST_BBOX,
        )


def test_missing_smap_file_rejected(
    tmp_path: Path,
) -> None:

    gpm = (
        tmp_path / "gpm.HDF5"
    )

    missing_smap = (
        tmp_path / "missing.h5"
    )

    gpm.touch()

    with pytest.raises(
        HydroWorkerError,
        match="SMAP resource does not exist",
    ):
        run_hydro_analysis(
            gpm_files=[
                gpm
            ],
            smap_file=missing_smap,
            bbox=TEST_BBOX,
        )


def test_gpm_processing_failure_wrapped(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:

    gpm = (
        tmp_path / "gpm.HDF5"
    )

    smap = (
        tmp_path / "smap.h5"
    )

    gpm.touch()
    smap.touch()

    def fail_gpm(
        files,
        bbox,
    ):
        raise GPMProcessingError(
            "synthetic GPM failure"
        )

    monkeypatch.setattr(
        hydro_service,
        "analyze_gpm_granules",
        fail_gpm,
    )

    with pytest.raises(
        HydroWorkerError,
        match="GPM rainfall analysis failed",
    ):
        run_hydro_analysis(
            gpm_files=[
                gpm
            ],
            smap_file=smap,
            bbox=TEST_BBOX,
        )


def test_smap_processing_failure_wrapped(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:

    gpm = (
        tmp_path / "gpm.HDF5"
    )

    smap = (
        tmp_path / "smap.h5"
    )

    gpm.touch()
    smap.touch()

    monkeypatch.setattr(
        hydro_service,
        "analyze_gpm_granules",
        lambda files, bbox: _fake_gpm_result(),
    )

    def fail_smap(
        file_path,
        bbox,
    ):
        raise SMAPProcessingError(
            "synthetic SMAP failure"
        )

    monkeypatch.setattr(
        hydro_service,
        "analyze_smap_granule",
        fail_smap,
    )

    with pytest.raises(
        HydroWorkerError,
        match="SMAP soil-moisture analysis failed",
    ):
        run_hydro_analysis(
            gpm_files=[
                gpm
            ],
            smap_file=smap,
            bbox=TEST_BBOX,
        )


def test_generated_task_id_when_omitted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:

    gpm = (
        tmp_path / "gpm.HDF5"
    )

    smap = (
        tmp_path / "smap.h5"
    )

    gpm.touch()
    smap.touch()

    monkeypatch.setattr(
        hydro_service,
        "analyze_gpm_granules",
        lambda files, bbox: _fake_gpm_result(),
    )

    monkeypatch.setattr(
        hydro_service,
        "analyze_smap_granule",
        lambda file_path, bbox: _fake_smap_result(),
    )

    result = run_hydro_analysis(
        gpm_files=[
            gpm
        ],
        smap_file=smap,
        bbox=TEST_BBOX,
    )

    assert isinstance(
        result["task_id"],
        str,
    )

    assert result[
        "task_id"
    ]