"""Independent context components retain date, location, and privacy boundaries."""

from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path

import numpy as np
import pytest
from pydantic import ValidationError
import rasterio
from rasterio.transform import from_origin
from rasterio.warp import transform_bounds

from backend.shared.context_contracts import ContextTask, ContextResult, unavailable, context_result
from backend.shared.settings import WorkerSettings
from backend.shared.status import TaskState
from backend.shared.worker_runners import run_hydro_task, run_flood_task
from backend.workers.hydro import context as hydro
from backend.workers.hydro import context_sources
from backend.workers.flood import context as flood
from backend.workers.flood._raster import RasterTile
from backend.workers.flood.sentinel1 import Sentinel1Scene
from scripts.validate.validate_worker_apis import _synthetic_hydro


BOUNDS = [-2.10, 53.25, -1.85, 53.40]


@pytest.fixture(autouse=True)
def mock_live_nasa_discovery(tmp_path, monkeypatch):
    """These offline tests emulate a live catalog; they never use Earthdata auth."""
    original = context_sources.NASAContextProvider
    class Catalog(original):
        def search(self, component, requested):
            parser = hydro.gpm_interval if component == "gpm" else hydro.smap_interval
            found = []
            root = (tmp_path / component).resolve()
            paths = [path for path in root.glob("*") if path.is_file() and not path.is_symlink() and path.resolve().parent == root]
            for path in paths:
                interval = parser(path.name)
                if interval and requested.start_time <= interval[0] < interval[1] <= requested.end_time:
                    found.append((None, path.name, interval))
            found.sort(key=lambda row: row[2][0])
            return found[-1:] if component == "smap" else found
    monkeypatch.setattr(context_sources, "NASAContextProvider", Catalog)


def task(kind="hydrometeorology", **changes):
    values = dict(task_id="context-check", analysis_type=kind, location_id="any-bounded-location",
                  bbox=dict(zip(("west", "south", "east", "north"), BOUNDS)),
                  as_of="2019-07-25", start_time="2019-07-25T00:00:00Z", end_time="2019-07-26T00:00:00Z")
    values.update(changes)
    return ContextTask(**values)


def prepare_hydro(tmp_path):
    settings, gpm_names, smap_name = _synthetic_hydro(tmp_path, BOUNDS)
    for name, stamp in zip(gpm_names, ["230000-E232959.1380", "233000-E235959.1410"]):
        (settings.gpm_dir / name).rename(settings.gpm_dir / f"3B-HHR.MS.MRG.3IMERG.20190725-S{stamp}.V07B.HDF5")
    (settings.smap_dir / smap_name).rename(settings.smap_dir / "SMAP_L4_SM_gph_20190725T223000_Vv8010_001.h5")
    return settings


def components(result):
    return {row.component: row for row in ContextResult.model_validate(result).components}


def test_local_hydro_uses_matching_dates_and_actual_processors_without_extrapolation(tmp_path):
    settings = prepare_hydro(tmp_path)
    seen = []
    result = run_hydro_task(task(), seen.append, settings=settings)
    assert seen == [TaskState.DATASET_LOCATED, TaskState.PROCESSING, TaskState.PREPARING_RESULT]
    measured = components(result)
    assert result["status"] == "partial"
    rain = measured["gpm"]
    assert rain.metrics.area_mean_total_accumulation_mm == 5
    assert rain.metrics.covered_hours == 1
    assert rain.metrics.requested_hours == 24
    assert rain.metrics.temporal_coverage_fraction == pytest.approx(1 / 24)
    assert rain.reason == "partial_temporal_coverage"
    assert measured["smap"].metrics.surface_mean_m3_m3 == pytest.approx(.4)
    assert measured["smap"].observed_end.isoformat() == "2019-07-26T00:00:00+00:00"
    assert all(secret not in json.dumps(result) for secret in (str(tmp_path), "synthetic", ".h5", "HDF5"))


def test_old_abbotsford_files_are_unavailable_not_relabelled(tmp_path):
    settings, _, _ = _synthetic_hydro(tmp_path, BOUNDS)
    result = components(run_hydro_task(task(), lambda _: None, settings=settings))
    assert all(row.reason == "no_matching_observations" and row.metrics is None for row in result.values())


def test_2007_smap_unavailable_before_coverage_and_gpm_independent(tmp_path, monkeypatch):
    monkeypatch.setattr(hydro, "analyze_smap_granule", lambda *a: pytest.fail("SMAP must not process pre-coverage data"))
    value = task(as_of="2007-12-09", start_time="2007-12-09T00:00:00Z", end_time="2007-12-10T00:00:00Z")
    result = components(run_hydro_task(value, lambda _: None, settings=WorkerSettings(gpm_dir=tmp_path, smap_dir=tmp_path)))
    assert result["smap"].reason == "before_product_coverage"
    assert result["gpm"].reason == "no_matching_observations"


def test_reprocessed_v07_rainfall_before_june2000_is_not_excluded(tmp_path):
    settings = prepare_hydro(tmp_path)
    for path in settings.gpm_dir.iterdir():
        path.rename(path.with_name(path.name.replace("20190725", "19990725")))
    value = task(as_of="1999-07-25", start_time="1999-07-25T00:00:00Z", end_time="1999-07-26T00:00:00Z")
    rows = components(run_hydro_task(value, lambda _: None, settings=settings))
    assert rows["gpm"].metrics.area_mean_total_accumulation_mm == 5
    assert rows["smap"].reason == "before_product_coverage"


def test_smap_entire_three_hour_interval_must_be_before_end(tmp_path):
    settings = prepare_hydro(tmp_path)
    value = task(end_time="2019-07-25T23:00:00Z")
    result = components(run_hydro_task(value, lambda _: None, settings=settings))
    assert result["smap"].reason == "no_matching_observations"  # centre is 22:30, but averaging ends at midnight
    assert result["gpm"].reason == "no_matching_observations"


@pytest.mark.parametrize("change", [
    {"bbox": {"west": -2., "south": 53., "east": 1., "north": 54.}},
    {"end_time": "2019-07-27T00:00:00Z"},
    {"start_time": "2019-07-01T00:00:00Z"},
    {"start_time": "2019-07-26T00:00:00Z"},
    {"as_of": "9999-12-31"}, {"as_of": 1564099200},
    {"location_id": "../records"}, {"data_dir": "/somewhere"},
])
def test_tasks_reject_unbound_dates_locations_and_paths(change):
    with pytest.raises(ValidationError):
        task(**change)


def test_processor_failures_are_safe_and_do_not_suppress_other_components(tmp_path, monkeypatch):
    settings = prepare_hydro(tmp_path)
    def fail(*args, **kwargs):
        raise RuntimeError("https://provider.example/?api_key=SECRET /owner/private/records")
    monkeypatch.setattr(hydro, "analyze_gpm_granules", fail)
    result = run_hydro_task(task(), lambda _: None, settings=settings)
    rows = components(result)
    assert rows["gpm"].reason == "processing_failed"
    assert rows["smap"].availability == "available"
    assert "SECRET" not in json.dumps(result)
    assert "/owner" not in json.dumps(result)


@pytest.mark.parametrize("corrupt", ["nan", "wrong_bbox", "wrong_count", "wrong_timestamp"])
def test_invalid_processor_outputs_fail_closed(tmp_path, monkeypatch, corrupt):
    settings = prepare_hydro(tmp_path)
    original = hydro.analyze_smap_granule
    def altered(*args, **kwargs):
        raw = original(*args, **kwargs)
        if corrupt == "nan": raw["surface_soil_moisture"]["mean"] = float("nan")
        elif corrupt == "wrong_bbox": raw["bbox"]["west"] += .01
        elif corrupt == "wrong_count": raw["surface_soil_moisture"]["valid_pixels"] = 10000
        else: raw["timestamp_utc"] = "2021-11-14T22:30:00Z"
        return raw
    monkeypatch.setattr(hydro, "analyze_smap_granule", altered)
    rows = components(run_hydro_task(task(), lambda _: None, settings=settings))
    assert rows["smap"].reason == "invalid_result"
    assert rows["gpm"].availability == "available"


def test_cache_limit_is_explicit(tmp_path, monkeypatch):
    settings = prepare_hydro(tmp_path)
    original = context_sources.NASAContextProvider.search
    def search(self, component, requested):
        if component == "gpm":
            raise context_sources.SourceUnavailable("resource_limit")
        return original(self, component, requested)
    monkeypatch.setattr(context_sources.NASAContextProvider, "search", search)
    rows = components(run_hydro_task(task(), lambda _: None, settings=settings))
    assert rows["gpm"].reason == "resource_limit"
    assert rows["smap"].availability == "available"


def _raster(tmp_path, name, values, collection):
    grid = from_origin(500000, 40, 10, 10)
    values = np.asarray(values, dtype="float32")
    path = tmp_path / f"{name}.tif"
    with rasterio.open(path, "w", driver="GTiff", width=values.shape[1], height=values.shape[0],
                       count=1, dtype="float32", crs="EPSG:32631", transform=grid) as dst:
        dst.write(values, 1)
    bounds = transform_bounds("EPSG:32631", "EPSG:4326", 500000, 20, 500020, 40)
    return RasterTile(name, str(path), collection), bounds


@pytest.fixture
def forbid_undated_terrain(monkeypatch):
    from backend.workers.flood import hand, terrain
    def forbidden(*args, **kwargs):
        pytest.fail("Unverified terrain dates must be rejected before discovery or reading.")
    for module, names in ((terrain, ("discover_dem_tiles", "analyze_dem_tiles")),
                          (hand, ("discover_hand_tiles", "analyze_hand_tiles"))):
        for name in names:
            monkeypatch.setattr(module, name, forbidden)


@pytest.mark.parametrize("day,end", [("2007-12-09", "2007-12-10"),
                                      ("2019-08-01", "2019-08-02"),
                                      ("2026-08-01", "2026-08-02")])
def test_undated_terrain_excluded_before_any_catalog_or_asset_read(day, end, monkeypatch, forbid_undated_terrain):
    def discover(*args, **kwargs):
        assert day != "2007-12-09", "Pre-launch satellite discovery is not allowed."
        raise RuntimeError("No matching satellite scene.")
    monkeypatch.setattr(flood, "discover_sentinel1_scene", discover)
    monkeypatch.setattr(rasterio, "open", lambda *a, **k: pytest.fail("Excluded assets must not be read."))
    value = task("surface_water_and_terrain", as_of=day,
                 start_time=f"{day}T00:00:00Z", end_time=f"{end}T00:00:00Z")
    seen = []
    result = components(run_flood_task(value, seen.append, settings=WorkerSettings()))
    assert seen == [TaskState.PROCESSING, TaskState.PREPARING_RESULT]
    assert result["sentinel1"].reason == ("before_product_coverage" if day.startswith("2007") else "source_unavailable")
    for name in ("dem", "hand"):
        assert result[name].reason == "observation_date_unverified"
        assert result[name].availability == "unavailable"
        assert result[name].metrics is result[name].observed_start is result[name].observed_end is None


def test_future_scene_rejected_without_reading_assets(monkeypatch, forbid_undated_terrain):
    calls = []
    def discover(*args, **kwargs):
        calls.append((args, kwargs))
        return Sentinel1Scene(scene_id="future", href="https://provider.example/tile.tif",
                              acquired_at="2019-07-26T00:00:00Z", bbox=BOUNDS)
    monkeypatch.setattr(flood, "discover_sentinel1_scene", discover)
    monkeypatch.setattr(flood, "analyze_sentinel1_scene", lambda *a, **k: pytest.fail("Future scene must not be read"))
    rows = components(run_flood_task(task("surface_water_and_terrain"), lambda _: None, settings=WorkerSettings()))
    assert rows["sentinel1"].reason == "invalid_result"
    assert rows["dem"].reason == rows["hand"].reason == "observation_date_unverified"
    assert calls[0][0][2] < task().end_time


def test_verified_satellite_observation_still_processed_when_terrain_excluded(tmp_path, monkeypatch, forbid_undated_terrain):
    tile, bbox = _raster(tmp_path, "scene", [[.01, .01], [.5, .5]], "sentinel-1-rtc")
    scene = Sentinel1Scene(scene_id="observed-before-cutoff", href=tile.href,
                           acquired_at="2019-07-25T12:00:00Z", bbox=bbox)
    monkeypatch.setattr(flood, "discover_sentinel1_scene", lambda *a, **k: scene)
    value = task("surface_water_and_terrain", bbox=dict(zip(("west", "south", "east", "north"), bbox)))
    result = run_flood_task(value, lambda _: None, settings=WorkerSettings())
    rows = components(result)
    assert result["status"] == "partial"
    assert rows["sentinel1"].availability == "available"
    assert rows["sentinel1"].metrics.candidate_fraction_valid == .5
    assert rows["dem"].reason == rows["hand"].reason == "observation_date_unverified"


def test_result_cannot_change_identity_or_invent_measurements():
    result = context_result(task(), [unavailable("gpm", "missing_local_data"), unavailable("smap", "missing_local_data")])
    for key, value in [("worker_id", "flood-worker"), ("status", "complete")]:
        altered = deepcopy(result); altered[key] = value
        with pytest.raises(ValidationError): ContextResult.model_validate(altered)
    altered = deepcopy(result); altered["components"][0]["metrics"] = {"risk": 0}
    with pytest.raises(ValidationError): ContextResult.model_validate(altered)


@pytest.mark.parametrize("name", ["dem", "hand"])
def test_stale_worker_cannot_return_undated_terrain_measurements(name):
    value = task("surface_water_and_terrain")
    result = context_result(value, [unavailable("sentinel1", "source_unavailable"),
                                   unavailable("dem", "observation_date_unverified"),
                                   unavailable("hand", "observation_date_unverified")])
    stale = next(row for row in result["components"] if row["component"] == name)
    stale.update(availability="available", reason="static_noncontemporaneous",
                 metrics={"mean_m": 1., "min_m": 0., "max_m": 2., "median_m": 1.,
                          "valid_fraction": 1., "valid_pixels": 4, "tile_count": 1})
    with pytest.raises(ValidationError, match="verified observation period"):
        ContextResult.model_validate(result)


def test_file_symlinks_are_never_opened(tmp_path, monkeypatch):
    settings = prepare_hydro(tmp_path)
    original = Path.resolve
    outside = tmp_path / "outside"
    def redirected(path, *args, **kwargs):
        if path.suffix == ".HDF5":
            return outside / path.name
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, "resolve", redirected)
    rows = components(run_hydro_task(task(), lambda _: None, settings=settings))
    assert rows["gpm"].reason == "no_matching_observations"


def test_hydro_http_accepts_context_and_preserves_exact_task_binding(tmp_path):
    from fastapi.testclient import TestClient
    from backend.workers.hydro.main import create_app
    from test_worker_api import terminal
    settings = prepare_hydro(tmp_path)
    submitted = task()
    with TestClient(create_app(settings)) as client:
        response = client.post("/tasks", json=submitted.model_dump(mode="json"))
        assert response.status_code == 202
        assert terminal(client, submitted.task_id)["state"] == "partial"
        result = ContextResult.model_validate(client.get(f"/tasks/{submitted.task_id}/result").json())
        assert all(getattr(result, key) == getattr(submitted, key) for key in ContextTask.model_fields)
        assert result.components[0].metrics.covered_hours == 1


def test_flood_http_rejects_hydro_context_before_processing(monkeypatch):
    from fastapi.testclient import TestClient
    from backend.workers.flood.main import create_app
    monkeypatch.setattr(flood, "run_flood_context", lambda *a, **k: pytest.fail("Mismatched task must not dispatch"))
    with TestClient(create_app(WorkerSettings())) as client:
        response = client.post("/tasks", json=task().model_dump(mode="json"))
        assert response.status_code == 422
