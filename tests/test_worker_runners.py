"""Verify API resource resolution and actual deterministic worker adapters."""

from pathlib import Path

import pytest

from backend.shared.contracts import AnalysisTask, HydroResult
from backend.shared.settings import WorkerSettings
from backend.shared.status import TaskState
from backend.shared import worker_runners as runners
from scripts.validate.validate_worker_apis import _synthetic_hydro

BBOX = [-122.45, 48.95, -121.95, 49.30]


def _task(gpm, smap):
    return AnalysisTask(task_id='runner-test', analysis_type='hydrometeorology',
                        bbox=dict(zip(('west','south','east','north'),BBOX)),
                        gpm_resources=gpm, smap_resource=smap)


def test_hydro_adapter_runs_real_processor_and_reports_observed_stages(tmp_path):
    settings, gpm, smap = _synthetic_hydro(tmp_path, BBOX)
    observed = []
    result = runners.run_hydro_task(_task(gpm,smap), observed.append, settings=settings)
    model = HydroResult.model_validate(result)
    assert model.summary.rainfall.area_mean_total_accumulation_mm == 5
    assert model.summary.soil_moisture.surface_mean_m3_m3 == pytest.approx(0.4)
    assert observed == [TaskState.DATASET_LOCATED, TaskState.PROCESSING, TaskState.PREPARING_RESULT]


def test_missing_resource_fails_before_claiming_discovery_or_processing(tmp_path):
    observed = []
    with pytest.raises(runners.WorkerResourceError) as error:
        runners.run_hydro_task(_task(['missing.HDF5'],'missing.h5'),observed.append,
                               settings=WorkerSettings(gpm_dir=tmp_path,smap_dir=tmp_path))
    assert not observed
    assert str(tmp_path) not in str(error.value)


def test_resource_cannot_escape_configured_folder_via_symlink(tmp_path):
    root = tmp_path/'resources'; root.mkdir()
    outside = tmp_path/'outside.h5'; outside.write_bytes(b'secret')
    (root/'alias.h5').symlink_to(outside)
    with pytest.raises(runners.WorkerResourceError):
        runners._resource(root, 'alias.h5')


@pytest.mark.parametrize('name', ['../outside.h5', '/tmp/private.h5', 'https://host/file', 'subdir/file.h5'])
def test_resource_boundary_also_rejects_unvalidated_paths(tmp_path,name):
    with pytest.raises(runners.WorkerResourceError):
        runners._resource(tmp_path,name)


def test_mutated_task_is_revalidated_before_access(tmp_path):
    task = _task(['gpm.HDF5'],'smap.h5')
    task.gpm_resources = ['../outside.HDF5']
    with pytest.raises(ValueError):
        runners.run_hydro_task(task, lambda state: pytest.fail('No processing expected'), settings=WorkerSettings())


def test_flood_adapter_resolves_approved_sources_then_delegates(monkeypatch):
    task = AnalysisTask(task_id='flood-runner',analysis_type='surface_water_and_terrain',
                        bbox=dict(zip(('west','south','east','north'),BBOX)),
                        start_time='2021-11-13T00:00:00Z',end_time='2021-11-18T23:59:59Z')
    events=[]
    monkeypatch.setattr(runners,'discover_sentinel1_scene',lambda *a,**k: 'scene')
    monkeypatch.setattr(runners,'discover_dem_tiles',lambda bbox: ['dem'])
    monkeypatch.setattr(runners,'discover_hand_tiles',lambda bbox: ['hand'])
    def processor(scene,dem,hand,bbox,**kwargs):
        assert (scene,dem,hand,bbox)==('scene',['dem'],['hand'],tuple(BBOX))
        assert kwargs == {'task_id':'flood-runner','threshold_db':-17.0}
        assert events==[TaskState.DATASET_LOCATED,TaskState.PROCESSING]
        return {'observed':'evidence'}
    monkeypatch.setattr(runners,'run_flood_analysis',processor)
    assert runners.run_flood_task(task,events.append,settings=WorkerSettings())=={'observed':'evidence'}
    assert events[-1]==TaskState.PREPARING_RESULT


def test_settings_read_operator_paths_and_keep_token_out_of_repr(monkeypatch,tmp_path):
    monkeypatch.setenv('MESHMIND_GPM_DIR',str(tmp_path/'gpm'))
    monkeypatch.setenv('MESHMIND_WORKER_TOKEN','private-example-token')
    monkeypatch.setenv('MESHMIND_MAX_TASKS','7')
    settings=WorkerSettings.from_env()
    assert settings.gpm_dir == tmp_path/'gpm'
    assert settings.max_tasks==7
    assert 'private-example-token' not in repr(settings)
