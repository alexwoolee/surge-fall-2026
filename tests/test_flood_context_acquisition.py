"""Catalog outcomes and genuine Flood acquisition milestones remain distinct."""

from dataclasses import replace
from datetime import datetime, timezone
import json
from unittest.mock import Mock

import pytest

from backend.shared.context_contracts import ContextResult, ContextTask
from backend.shared.status import TaskState
from backend.workers.flood import context, sentinel1
from test_sentinel1 import catalog_item, grid_bbox, mock_catalog, write_scene


def requested(**changes):
    values = dict(task_id='flood-acquisition', analysis_type='surface_water_and_terrain',
                  location_id='toddbrook', bbox=dict(west=-2.10, south=53.25, east=-1.85, north=53.40),
                  as_of='2019-08-01', start_time='2019-08-01T00:00:00Z', end_time='2019-08-02T00:00:00Z')
    values.update(changes)
    return ContextTask(**values)


def measured_scene():
    return sentinel1.Sentinel1Scene('within-window', 'https://example.test/scene.tif',
                                    '2019-08-01T17:50:24Z', (-2.10, 53.25, -1.85, 53.40))


def rows(result):
    return {row.component: row for row in ContextResult.model_validate(result).components}


def test_located_and_processing_are_emitted_after_selection_before_raster_read(tmp_path, monkeypatch):
    scene = replace(write_scene(tmp_path, [[.01, .01], [.5, .5]]), acquired_at='2019-08-01T17:50:24Z')
    bbox = dict(zip(('west', 'south', 'east', 'north'), grid_bbox(2, 2)))
    events = []
    def discover(*args, **kwargs):
        assert events == [], 'No dataset should be claimed before discovery completes.'
        return scene
    original = context.analyze_sentinel1_scene
    def analyze(*args, **kwargs):
        assert events == [TaskState.DATASET_LOCATED, TaskState.PROCESSING]
        return original(*args, **kwargs)
    monkeypatch.setattr(context, 'discover_sentinel1_scene', discover)
    monkeypatch.setattr(context, 'analyze_sentinel1_scene', analyze)
    result = context.run_flood_context(requested(bbox=bbox), events.append)
    assert events == [TaskState.DATASET_LOCATED, TaskState.PROCESSING, TaskState.PREPARING_RESULT]
    measured = rows(result)
    assert measured['sentinel1'].metrics.candidate_fraction_valid == .5
    assert measured['dem'].reason == measured['hand'].reason == 'observation_date_unverified'


def test_located_milestone_survives_a_later_raster_processing_failure(monkeypatch):
    events = []
    monkeypatch.setattr(context, 'discover_sentinel1_scene', lambda *a, **k: measured_scene())
    def failed(*args, **kwargs):
        assert events == [TaskState.DATASET_LOCATED, TaskState.PROCESSING]
        raise OSError('https://provider.test/?secret=DO_NOT_RETURN')
    monkeypatch.setattr(context, 'analyze_sentinel1_scene', failed)
    result = context.run_flood_context(requested(), events.append)
    assert rows(result)['sentinel1'].reason == 'processing_failed'
    assert events == [TaskState.DATASET_LOCATED, TaskState.PROCESSING, TaskState.PREPARING_RESULT]
    assert 'DO_NOT_RETURN' not in json.dumps(result)


@pytest.mark.parametrize('case,reason', [('empty', 'no_matching_observations'), ('provider_error', 'source_unavailable')])
def test_successful_empty_catalog_is_not_reported_as_provider_failure(monkeypatch, case, reason):
    events = []
    if case == 'empty':
        mock_catalog(monkeypatch, [])
    else:
        monkeypatch.setattr(sentinel1.Client, 'open', Mock(side_effect=OSError('DO_NOT_RETURN')))
    monkeypatch.setattr(context, 'analyze_sentinel1_scene', lambda *a, **k: pytest.fail('No scene may be read.'))
    result = context.run_flood_context(requested(), events.append)
    assert rows(result)['sentinel1'].reason == reason
    assert events == [TaskState.PROCESSING, TaskState.PREPARING_RESULT]
    assert 'DO_NOT_RETURN' not in json.dumps(result)


@pytest.mark.parametrize('acquired', ['2019-07-31T23:59:59Z', '2019-08-02T00:00:00Z'])
def test_scene_outside_request_never_sets_located_or_reads_pixels(monkeypatch, acquired):
    scene = replace(measured_scene(), acquired_at=acquired)
    monkeypatch.setattr(context, 'discover_sentinel1_scene', lambda *a, **k: scene)
    monkeypatch.setattr(context, 'analyze_sentinel1_scene', lambda *a, **k: pytest.fail('Out-of-range scene read.'))
    events = []
    result = context.run_flood_context(requested(), events.append)
    assert rows(result)['sentinel1'].reason == 'invalid_result'
    assert events == [TaskState.PROCESSING, TaskState.PREPARING_RESULT]


def test_prelaunch_request_has_no_catalog_or_located_event(monkeypatch):
    monkeypatch.setattr(sentinel1.Client, 'open', lambda *a, **k: pytest.fail('Pre-launch catalog query.'))
    events = []
    result = context.run_flood_context(requested(as_of='2007-12-09', start_time='2007-12-09T00:00:00Z',
                                               end_time='2007-12-10T00:00:00Z'), events.append)
    assert rows(result)['sentinel1'].reason == 'before_product_coverage'
    assert events == [TaskState.PROCESSING, TaskState.PREPARING_RESULT]


def test_pystac_query_preserves_exact_bbox_and_exclusive_cutoff(monkeypatch):
    scene = measured_scene()
    item = catalog_item(scene.scene_id, acquired_at=scene.acquired_at, bbox=scene.bbox)
    catalog, _ = mock_catalog(monkeypatch, [item])
    monkeypatch.setattr(context, 'analyze_sentinel1_scene', Mock(side_effect=OSError('fixture stops before raster')))
    result = context.run_flood_context(requested(), lambda _: None)
    kwargs = catalog.search.call_args.kwargs
    assert kwargs['collections'] == ['sentinel-1-rtc']
    assert kwargs['bbox'] == (-2.10, 53.25, -1.85, 53.40)
    start, end = kwargs['datetime'].split('/')
    assert datetime.fromisoformat(start.replace('Z', '+00:00')) == requested().start_time
    assert datetime.fromisoformat(end.replace('Z', '+00:00')) == datetime(2019, 8, 1, 23, 59, 59, 999999, tzinfo=timezone.utc)
    assert rows(result)['sentinel1'].reason == 'processing_failed'


def test_no_scene_is_a_distinct_subclass_compatible_with_legacy_error_handling(monkeypatch):
    mock_catalog(monkeypatch, [])
    with pytest.raises(sentinel1.Sentinel1NoSceneError) as error:
        sentinel1.discover_sentinel1_scene(requested().bbox.as_tuple(), requested().start_time, requested().end_time)
    assert isinstance(error.value, sentinel1.Sentinel1ProcessingError)


def test_real_worker_dashboard_retains_genuine_located_stage(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from backend.shared.settings import WorkerSettings
    from backend.workers.flood.main import create_app
    from test_worker_api import terminal

    scene = replace(write_scene(tmp_path, [[.01, .01], [.5, .5]]), acquired_at='2019-08-01T17:50:24Z')
    monkeypatch.setattr(context, 'discover_sentinel1_scene', lambda *a, **k: scene)
    value = requested(bbox=dict(zip(('west', 'south', 'east', 'north'), grid_bbox(2, 2))))
    with TestClient(create_app(WorkerSettings())) as client:
        assert client.post('/tasks', json=value.model_dump(mode='json')).status_code == 202
        assert terminal(client, value.task_id)['state'] == 'partial'
        dashboard = client.get('/dashboard/state').json()
        assert [event['state'] for event in dashboard['events']] == [
            'task_received', 'dataset_located', 'processing', 'preparing_result', 'partial',
        ]
        assert rows(client.get(f'/tasks/{value.task_id}/result').json())['sentinel1'].availability == 'available'
