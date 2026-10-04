"""Check honest live/synthetic gating and deterministic NASA fixture selection."""

from contextlib import contextmanager
import json
from pathlib import Path
from types import SimpleNamespace

import earthaccess
import pytest

from backend.shared.settings import WorkerSettings
from scripts.validate import validate_worker_apis as validation


@pytest.fixture
def config():
    return json.loads((validation.ROOT/'config/test_case.example.json').read_text())


def test_download_selects_all_gpm_and_earliest_smap_with_bounded_queries(tmp_path,config,monkeypatch):
    def granule(name,date):
        return {'meta':{'native-id':name},'umm':{'TemporalExtent':{'RangeDateTime':{'BeginningDateTime':date}}}}
    gpm=[granule('gpm-second','2021-11-15T00:30:00Z'),granule('gpm-first','2021-11-15T00:00:00Z')]
    smap=[granule('smap-later','2021-11-15T00:00:00Z'),granule('smap-prior','2021-11-14T21:00:00Z')]
    calls=[]; downloaded=[]
    monkeypatch.delenv('EARTHDATA_TOKEN',raising=False);monkeypatch.delenv('EARTHDATA_USERNAME',raising=False)
    def login(**kwargs):
        assert kwargs=={'strategy':'netrc'}
        return SimpleNamespace(authenticated=True)
    def search(**kwargs):
        calls.append(kwargs)
        return gpm if kwargs['short_name']=='GPM_3IMERGHH' else smap
    def download(items,folder,**kwargs):
        downloaded.append([item['meta']['native-id'] for item in items])
        paths=[]
        for item in items:
            path=folder/(item['meta']['native-id']+'.h5');path.write_bytes(b'fixture');paths.append(path)
        return paths
    monkeypatch.setattr(earthaccess,'login',login)
    monkeypatch.setattr(earthaccess,'search_data',search)
    monkeypatch.setattr(earthaccess,'download',download)
    names,soil=validation._download_hydro(config,WorkerSettings(gpm_dir=tmp_path/'gpm',smap_dir=tmp_path/'smap'))
    assert names==['gpm-first.h5','gpm-second.h5'] and soil=='smap-prior.h5'
    assert downloaded==[['gpm-first','gpm-second'],['smap-prior']]
    assert calls[0]['bounding_box']==tuple(config['bbox'])
    assert calls[0]['count']==49 and '00:59:59.999999' in calls[0]['temporal'][1]


def test_failed_saved_login_never_searches_or_downloads(config,monkeypatch):
    monkeypatch.setattr(earthaccess,'login',lambda **kwargs:SimpleNamespace(authenticated=False))
    monkeypatch.setattr(earthaccess,'search_data',lambda **kwargs:pytest.fail('No search without authentication'))
    with pytest.raises(RuntimeError,match='saved Earthdata'):
        validation._download_hydro(config,WorkerSettings())


def test_fixture_check_explicitly_keeps_live_hydro_gate_pending(tmp_path,monkeypatch):
    @contextmanager
    def server(*args):
        yield object()
    monkeypatch.setattr(validation,'_server',server)
    monkeypatch.setattr(validation,'_request',lambda *args: {'result':{'summary':{'rainfall':{'area_mean_total_accumulation_mm':5}}}})
    output=tmp_path/'result.json'
    assert validation.main(['--output',str(output)])==0
    report=json.loads(output.read_text())
    assert report['validation']=='PASS' and report['phase_gate']=='PENDING_LIVE_HYDRO'
    assert report['workers']['hydro']['data_source']=='synthetic_HDF5_fixture'
    assert not list(tmp_path.glob('*.html'))


def test_failure_invalidates_previous_pass_and_hides_exception_data(tmp_path,monkeypatch,capsys):
    output=tmp_path/'result.json';output.write_text('{"validation":"PASS"}')
    def fail_settings():
        assert json.loads(output.read_text())['validation']=='RUNNING'
        raise RuntimeError('https://user:password@example.test/file?sig=secret-sentinel-123')
    monkeypatch.setattr(validation.WorkerSettings,'from_env',fail_settings)
    assert validation.main(['--output',str(output)])==1
    report=json.loads(output.read_text())
    assert report['validation']=='FAIL' and report['phase_gate']=='NOT_READY'
    assert 'secret-sentinel-123' not in output.read_text()+capsys.readouterr().out
