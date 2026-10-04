"""Check honest live/synthetic gating and deterministic NASA fixture selection."""

from contextlib import contextmanager
import json
from pathlib import Path
import subprocess
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


class OwnedProcess:
    """A launcher process with explicit signal/wait behavior for teardown tests."""

    pid = 31415

    def __init__(self, *, waits=(), signal_error=None, returncode=None, events=None):
        self.waits = iter(waits)
        self.signal_error = signal_error
        self.returncode = returncode
        self.events = events if events is not None else []

    def poll(self):
        return self.returncode

    def send_signal(self, value):
        self.events.append(('signal', value))
        if self.signal_error is not None:
            raise self.signal_error

    def terminate(self):
        self.events.append(('terminate',))

    def kill(self):
        self.events.append(('kill',))

    def wait(self, timeout):
        self.events.append(('wait', timeout))
        outcome = next(self.waits, 0)
        if isinstance(outcome, Exception):
            raise outcome
        self.returncode = outcome
        return outcome


def test_windows_shutdown_sends_break_to_owned_group_then_waits(monkeypatch):
    process = OwnedProcess()
    monkeypatch.setattr(validation, 'signal', SimpleNamespace(CTRL_BREAK_EVENT=1))
    monkeypatch.setattr(validation.subprocess, 'run', lambda *args, **kwargs: pytest.fail('Graceful exit needs no tree kill'))
    validation._stop_server(process, windows=True)
    assert process.events == [('signal', 1), ('wait', 15)]
    assert process.returncode == 0


@pytest.mark.parametrize('headless', [False, True])
def test_windows_fallback_kills_owned_tree_before_waiting_for_launcher(monkeypatch, headless):
    process = OwnedProcess(
        waits=[] if headless else [subprocess.TimeoutExpired('server', 15)],
        signal_error=OSError('No shared console') if headless else None,
    )
    monkeypatch.setattr(validation, 'signal', SimpleNamespace(CTRL_BREAK_EVENT=1))
    monkeypatch.setenv('SystemRoot', 'windows-system-root')

    def tree_kill(args, **kwargs):
        process.events.append(('tree_kill',))
        assert args == [str(Path('windows-system-root')/'System32'/'taskkill.exe'), '/PID', '31415', '/T', '/F']
        assert '/IM' not in args and '/S' not in args
        assert kwargs == {'stdin': subprocess.DEVNULL, 'stdout': subprocess.DEVNULL,
                          'stderr': subprocess.DEVNULL, 'check': False, 'timeout': 10}
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(validation.subprocess, 'run', tree_kill)
    validation._stop_server(process, windows=True)
    expected = [('signal', 1)] + ([] if headless else [('wait', 15)]) + [('tree_kill',), ('wait', 5)]
    assert process.events == expected
    assert process.returncode == 0


def test_already_exited_launcher_is_not_killed_by_reusable_pid(monkeypatch):
    process = OwnedProcess(returncode=1)
    monkeypatch.setattr(validation.subprocess, 'run', lambda *args, **kwargs: pytest.fail('Never target an exited PID'))
    validation._stop_server(process, windows=True)
    assert process.events == []


@pytest.mark.parametrize('failure', ['kill_unavailable', 'kill_timeout', 'tree_still_running'])
def test_windows_failed_teardown_is_not_reported_as_success(monkeypatch, failure):
    waits = [subprocess.TimeoutExpired('server', 5)] if failure == 'tree_still_running' else []
    process = OwnedProcess(waits=waits, signal_error=OSError('No shared console'))
    monkeypatch.setattr(validation, 'signal', SimpleNamespace(CTRL_BREAK_EVENT=1))

    def tree_kill(*args, **kwargs):
        if failure == 'kill_unavailable':
            raise OSError('taskkill failed')
        if failure == 'kill_timeout':
            raise subprocess.TimeoutExpired('taskkill', 10)
        return SimpleNamespace(returncode=1)

    monkeypatch.setattr(validation.subprocess, 'run', tree_kill)
    with pytest.raises(RuntimeError, match='process tree did not stop'):
        validation._stop_server(process, windows=True)
    assert ('terminate',) not in process.events and ('kill',) not in process.events


@pytest.mark.parametrize('timeout', [False, True])
def test_posix_shutdown_retains_terminate_then_bounded_kill_behavior(monkeypatch, timeout):
    process = OwnedProcess(waits=[subprocess.TimeoutExpired('server', 15)] if timeout else [])
    monkeypatch.setattr(validation.subprocess, 'run', lambda *args, **kwargs: pytest.fail('No Windows command on POSIX'))
    validation._stop_server(process, windows=False)
    expected = [('terminate',), ('wait', 15)] + ([('kill',), ('wait', 5)] if timeout else [])
    assert process.events == expected


def windows_lock(code=32):
    error = PermissionError('Simulated Windows sharing violation')
    error.winerror = code
    return error


def test_transient_child_log_lock_is_retried_after_process_shutdown(tmp_path, monkeypatch):
    path = tmp_path/'hydro-server.log'
    path.write_text('temporary log')
    unlink = Path.unlink
    attempts = []
    sleeps = []

    def sharing_violation_then_release(target, **kwargs):
        attempts.append(target)
        if len(attempts) <= 2:
            raise windows_lock()
        return unlink(target, **kwargs)

    monkeypatch.setattr(Path, 'unlink', sharing_violation_then_release)
    monkeypatch.setattr(validation.time, 'sleep', sleeps.append)
    validation._remove_windows_server_log(path)
    assert not path.exists() and len(attempts) == 3
    assert sleeps == [0.05, 0.05]


def test_persistent_child_log_lock_fails_with_bounded_wait(monkeypatch, tmp_path):
    clock = iter([0, 1, 5])
    monkeypatch.setattr(validation.time, 'monotonic', lambda: next(clock))
    sleeps = []
    monkeypatch.setattr(validation.time, 'sleep', sleeps.append)
    monkeypatch.setattr(Path, 'unlink', lambda *args, **kwargs: (_ for _ in ()).throw(windows_lock(33)))
    with pytest.raises(RuntimeError, match='log remained locked'):
        validation._remove_windows_server_log(tmp_path/'hydro-server.log')
    assert sleeps == [0.05]


def test_other_log_permission_errors_are_not_ignored_or_retried(monkeypatch, tmp_path):
    monkeypatch.setattr(validation.time, 'sleep', lambda *args: pytest.fail('Only sharing errors are transient'))
    monkeypatch.setattr(Path, 'unlink', lambda *args, **kwargs: (_ for _ in ()).throw(windows_lock(5)))
    with pytest.raises(PermissionError):
        validation._remove_windows_server_log(tmp_path/'hydro-server.log')


@pytest.mark.parametrize('body_fails', [False, True])
def test_server_closes_http_and_parent_log_before_removing_windows_log(tmp_path, monkeypatch, body_fails):
    events = []
    process = OwnedProcess(events=events)
    launched = {}

    class Probe:
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def bind(self, address):
            assert address == ('127.0.0.1', 0)
        def getsockname(self):
            return ('127.0.0.1', 31416)

    class Client:
        def __init__(self, **kwargs):
            assert kwargs['trust_env'] is False
        def __enter__(self):
            return self
        def __exit__(self, *args):
            events.append(('client_closed',))
        def get(self, path, headers=None):
            return SimpleNamespace(status_code=401 if headers else 200, json=lambda: {
                'worker_id': 'hydro-worker', 'analysis_type': 'hydrometeorology',
                'status': 'idle', 'active_task_id': None, 'retained_tasks': 0, 'capacity': 16,
            })

    def launch(args, **kwargs):
        launched.update(kwargs)
        assert args[0] == validation.sys.executable
        assert args[args.index('--workers') + 1] == '1'
        assert kwargs['creationflags'] == 512 and kwargs['close_fds'] is True
        assert kwargs['stdin'] == subprocess.DEVNULL
        assert kwargs['stdout'] is kwargs['stderr']
        assert not kwargs['stdout'].closed
        return process

    def remove(path):
        assert process.returncode == 0
        assert launched['stdout'].closed
        events.append(('remove_log',))
        path.unlink()

    monkeypatch.setattr(validation, 'sys', SimpleNamespace(platform='win32', executable='venv-python.exe'))
    monkeypatch.setattr(validation, 'signal', SimpleNamespace(CTRL_BREAK_EVENT=1))
    monkeypatch.setattr(validation.socket, 'socket', Probe)
    monkeypatch.setattr(validation.httpx, 'Client', Client)
    monkeypatch.setattr(validation.subprocess, 'Popen', launch)
    monkeypatch.setattr(validation.subprocess, 'CREATE_NEW_PROCESS_GROUP', 512, raising=False)
    monkeypatch.setattr(validation, '_remove_windows_server_log', remove)

    def check():
        with validation._server('hydro', WorkerSettings(), 'test-token', tmp_path):
            if body_fails:
                raise ValueError('original validation failure')

    if body_fails:
        with pytest.raises(ValueError, match='original validation failure'):
            check()
    else:
        check()
    assert events == [('client_closed',), ('signal', 1), ('wait', 15), ('remove_log',)]
    assert not (tmp_path/'hydro-server.log').exists()
