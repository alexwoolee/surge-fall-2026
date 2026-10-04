"""Exercise the manual-check CLI against small, local HDF5 fixtures."""

import json
from pathlib import Path
import subprocess
import sys

import h5py
import numpy as np
import pytest

import scripts.validate.validate_gpm as validation_cli
from scripts.validate.validate_gpm import main


def _granule(directory: Path, start: str, end: str, rate: float = 4.0) -> Path:
    minute_of_day = int(start[:2]) * 60 + int(start[2:4])
    path = directory / f"3B-HHR.MS.MRG.3IMERG.20211115-S{start}-E{end}.{minute_of_day:04d}.V07B.HDF5"
    with h5py.File(path, "w") as hdf:
        grid = hdf.create_group("Grid")
        grid.create_dataset("lon", data=np.array([0.25, 0.75]))
        grid.create_dataset("lat", data=np.array([0.25, 0.75]))
        precipitation = grid.create_dataset(
            "precipitation", data=np.full((1, 2, 2), rate), fillvalue=-9999.9,
        )
        precipitation.attrs["units"] = "mm/hr"
        precipitation.attrs["_FillValue"] = -9999.9
    return path


@pytest.fixture
def inputs(tmp_path: Path) -> tuple[Path, Path, Path]:
    config = tmp_path / "config.json"
    config.write_text(json.dumps({
        "id": "test", "name": "CLI test", "bbox": [0, 0, 1, 1],
        "gpm_smoke_start": "2021-11-15T00:00:00Z",
        "gpm_smoke_end": "2021-11-15T01:00:00Z",
    }))
    granules = tmp_path / "granules"
    granules.mkdir()
    return config, granules, tmp_path / "report.json"


def _args(config: Path, granules: Path, output: Path) -> list[str]:
    return ["--config", str(config), "--gpm-dir", str(granules), "--output", str(output)]


def test_module_cli_writes_deterministic_manual_review_report(inputs) -> None:
    config, granules, output = inputs
    _granule(granules, "000000", "002959", rate=4)
    _granule(granules, "003000", "005959", rate=6)
    command = [sys.executable, "-m", "scripts.validate.validate_gpm", *_args(*inputs)]
    completed = subprocess.run(command, capture_output=True, text=True, check=False)
    assert completed.returncode == 0, completed.stderr
    assert "Manual review required" in completed.stdout
    assert "PASS" not in completed.stdout
    first_report = output.read_text()
    report = json.loads(first_report)
    assert report["validation"]["status"] == "manual_review_required"
    assert report["result"]["granule_count"] == 2
    assert report["result"]["total_duration_hours"] == 1.0
    assert report["result"]["rainfall"]["area_mean_total_accumulation_mm"] == pytest.approx(5.0)
    assert main(_args(*inputs)) == 0
    assert output.read_text() == first_report


def test_explicit_files_and_time_overrides(inputs) -> None:
    config, granules, output = inputs
    first = _granule(granules, "000000", "002959", rate=4)
    second = _granule(granules, "003000", "005959", rate=6)
    assert main([
        "--config", str(config), "--gpm-files", str(second), str(first),
        "--start", "2021-11-15T00:30:00Z", "--end", "2021-11-15T01:00:00Z",
        "--output", str(output),
    ]) == 0
    report = json.loads(output.read_text())
    assert report["result"]["granule_count"] == 1
    assert report["result"]["rainfall"]["area_mean_total_accumulation_mm"] == pytest.approx(3.0)


def test_report_exposes_missing_requested_interval(inputs, capsys) -> None:
    config, granules, output = inputs
    _granule(granules, "000000", "002959")
    assert main(_args(*inputs)) == 0
    report = json.loads(output.read_text())
    coverage = report["result"]["temporal_coverage"]
    assert coverage["complete"] is False
    assert coverage["coverage_fraction"] == pytest.approx(0.5)
    assert coverage["observation_end_utc"] == "2021-11-15T00:30:00Z"
    assert coverage["gaps"] == [{
        "start_utc": "2021-11-15T00:30:00Z", "end_utc": "2021-11-15T01:00:00Z",
    }]
    assert "2021-11-15T00:30:00Z" in capsys.readouterr().out
    assert report["validation"]["status"] == "manual_review_required"


def test_missing_granules_preserve_existing_report(inputs, capsys) -> None:
    config, granules, output = inputs
    output.write_text("previous manual result\n")
    assert main(_args(*inputs)) == 1
    assert "No local GPM HDF5 granules" in capsys.readouterr().err
    assert output.read_text() == "previous manual result\n"


def test_corrupt_granule_does_not_create_report(inputs, capsys) -> None:
    config, granules, output = inputs
    path = _granule(granules, "000000", "002959")
    path.write_text("not HDF5")
    assert main(_args(*inputs)) == 1
    assert "Phase 2 validation failed" in capsys.readouterr().err
    assert not output.exists()


@pytest.mark.parametrize("bbox", [None, [0, 0, 1], [0, 0, float("nan"), 1], [False, 0, 1, 1]])
def test_bad_config_has_actionable_error(inputs, capsys, bbox) -> None:
    config, granules, output = inputs
    config.write_text(json.dumps({"bbox": bbox}))
    assert main(_args(*inputs)) == 1
    assert "Config bbox" in capsys.readouterr().err
    assert not output.exists()


def test_output_cannot_overwrite_an_input(inputs, capsys) -> None:
    config, granules, output = inputs
    path = _granule(granules, "000000", "002959")
    original = path.read_bytes()
    assert main(_args(config, granules, path)) == 1
    assert "Output path must differ" in capsys.readouterr().err
    assert path.read_bytes() == original


def test_nonfinite_result_cannot_replace_report(inputs, monkeypatch, capsys) -> None:
    config, granules, output = inputs
    _granule(granules, "000000", "002959")
    output.write_text("previous manual result\n")
    monkeypatch.setattr(
        validation_cli, "analyze_gpm_granules",
        lambda *args, **kwargs: {"rainfall": float("nan")},
    )
    assert main(_args(*inputs)) == 1
    assert "Phase 2 validation failed" in capsys.readouterr().err
    assert output.read_text() == "previous manual result\n"
    assert not list(output.parent.glob(".report.json.*.tmp"))
