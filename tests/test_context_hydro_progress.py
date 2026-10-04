"""Hydro milestones reflect actual acquisition before independent processing."""

import pytest

from backend.shared.context_contracts import ContextResult
from backend.shared.status import TaskState
from backend.shared.worker_runners import run_hydro_task
from backend.workers.hydro import context as hydro, context_sources
from test_context_workers import prepare_hydro, task


@pytest.mark.parametrize("missing", [set(), {"gpm"}, {"smap"}, {"gpm", "smap"}])
def test_acquisition_finishes_before_processing_and_only_actual_inputs_are_located(tmp_path, monkeypatch, missing):
    settings = prepare_hydro(tmp_path)
    order = []
    seen = []
    def acquire(provider, component, requested, folder):
        assert not seen
        order.append(component)
        if component in missing:
            return [], "authentication_unavailable"
        return sorted(folder.iterdir()), None
    monkeypatch.setattr(context_sources, "live_paths", acquire)
    monkeypatch.setattr(context_sources.NASAContextProvider, "close", lambda self: order.append("closed"))
    analyze = hydro.analyze_gpm_granules
    def analyze_after_acquisition(*args):
        assert order == ["gpm", "smap", "closed"]
        assert seen == [TaskState.DATASET_LOCATED, TaskState.PROCESSING]
        return analyze(*args)
    monkeypatch.setattr(hydro, "analyze_gpm_granules", analyze_after_acquisition)
    result = ContextResult.model_validate(run_hydro_task(task(), seen.append, settings=settings))
    assert order == ["gpm", "smap", "closed"]
    assert seen == ([] if len(missing) == 2 else [TaskState.DATASET_LOCATED]) + [TaskState.PROCESSING, TaskState.PREPARING_RESULT]
    for row in result.components:
        if row.component in missing:
            assert row.availability == "unavailable"
            assert row.reason == "authentication_unavailable"
        else:
            assert row.availability == "available"


def test_precoverage_sources_are_not_queried_and_no_located_event_is_invented(tmp_path, monkeypatch):
    settings = prepare_hydro(tmp_path)
    monkeypatch.setattr(context_sources, "live_paths", lambda *args: pytest.fail("Product did not cover this date"))
    seen = []
    result = ContextResult.model_validate(run_hydro_task(
        task(as_of="1990-01-01", start_time="1990-01-01T00:00:00Z", end_time="1990-01-02T00:00:00Z"),
        seen.append, settings=settings))
    assert seen == [TaskState.PROCESSING, TaskState.PREPARING_RESULT]
    assert all(row.reason == "before_product_coverage" for row in result.components)


def test_located_data_can_fail_processing_without_losing_other_source(tmp_path, monkeypatch):
    settings = prepare_hydro(tmp_path)
    monkeypatch.setattr(context_sources, "live_paths", lambda provider, component, requested, folder: (sorted(folder.iterdir()), None))
    def fail(*args):
        raise ValueError("private provider information")
    monkeypatch.setattr(hydro, "analyze_gpm_granules", fail)
    seen = []
    result = ContextResult.model_validate(run_hydro_task(task(), seen.append, settings=settings))
    assert seen == [TaskState.DATASET_LOCATED, TaskState.PROCESSING, TaskState.PREPARING_RESULT]
    rows = {row.component: row for row in result.components}
    assert rows["gpm"].reason == "processing_failed"
    assert rows["smap"].availability == "available"


@pytest.mark.parametrize("have_inputs", [True, False])
def test_hydro_http_dashboard_retains_genuine_acquisition_milestone(tmp_path, monkeypatch, have_inputs):
    from threading import Event
    from fastapi.testclient import TestClient
    from backend.workers.hydro.main import create_app
    from test_worker_api import terminal

    settings = prepare_hydro(tmp_path)
    monkeypatch.setattr(context_sources, "live_paths", lambda provider, component, requested, folder:
                        (sorted(folder.iterdir()), None) if have_inputs else ([], "source_unavailable"))
    entered, release = Event(), Event()
    analyze = hydro.analyze_gpm_granules
    def processing(*args):
        entered.set()
        assert release.wait(5), "Test must release the active processor"
        return analyze(*args)
    monkeypatch.setattr(hydro, "analyze_gpm_granules", processing)
    submitted = task()
    with TestClient(create_app(settings)) as client:
        assert client.post("/tasks", json=submitted.model_dump(mode="json")).status_code == 202
        try:
            if have_inputs:
                assert entered.wait(5)
                during = client.get("/dashboard/state").json()
                assert [event["state"] for event in during["events"]] == ["task_received", "dataset_located", "processing"]
        finally:
            release.set()
        assert terminal(client, submitted.task_id)["state"] == "partial"
        completed = client.get("/dashboard/state").json()
        assert [event["state"] for event in completed["events"]] == (
            ["task_received"] + (["dataset_located"] if have_inputs else [])
            + ["processing", "preparing_result", "partial"])
        assert client.get("/dashboard/state").json() == completed
        result = ContextResult.model_validate(client.get(f"/tasks/{submitted.task_id}/result").json())
        assert (any(row.availability == "available" for row in result.components)) is have_inputs
        assert entered.is_set() is have_inputs
