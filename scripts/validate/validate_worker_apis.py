"""Phase 4 terminal checkpoint using temporary loopback HTTP worker processes.

Flood uses public real data. Hydro uses explicit local NASA filenames when
provided; otherwise a clearly labeled synthetic HDF5 integration runs and the
live Hydro gate remains pending. This does not demonstrate remote execution.
"""

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import argparse
import json
import os
from pathlib import Path
import secrets
import signal
import socket
import subprocess
import sys
import tempfile
import time

import h5py
import httpx
import numpy as np

from backend.shared.contracts import AnalysisTask, FloodResult, HydroResult, TaskStatus, WorkerStatus
from backend.shared.settings import WorkerSettings

ROOT = Path(__file__).resolve().parents[2]
TERMINAL = {'complete', 'partial', 'failed'}


def _stop_server(process, *, windows):
    """Stop only the temporary server process created by this validator.

    On Windows a venv's python.exe may be a redirector owning the actual
    interpreter. Terminating only that PID can race its child's log-handle
    cleanup. Send Ctrl+Break to our isolated process group first, then use a
    PID-scoped tree kill if graceful shutdown is unavailable or times out.
    """
    if process.poll() is not None:
        return
    if not windows:
        process.terminate()
        try:
            process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
        return

    try:
        process.send_signal(signal.CTRL_BREAK_EVENT)
        process.wait(timeout=15)
        return
    except (OSError, subprocess.TimeoutExpired):
        # Console signals are unavailable in some headless Windows sessions.
        pass
    if process.poll() is not None:
        return
    # Do this before terminating the redirector so its child is still in the
    # owned process tree. Never kill by image name, by port, or by a shared group.
    taskkill = Path(os.environ.get('SystemRoot', r'C:\Windows'))/'System32'/'taskkill.exe'
    try:
        subprocess.run(
            [str(taskkill), '/PID', str(process.pid), '/T', '/F'],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            check=False, timeout=10,
        )
        # A nonzero taskkill exit can mean the process exited concurrently.
        # Its actual termination is the required condition, not command output.
        process.wait(timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        raise RuntimeError('Temporary worker process tree did not stop cleanly.') from None


def _remove_windows_server_log(path, *, timeout=5):
    """Require release of our log after all parent handles have been closed.

    Windows process/job termination can finish asynchronously. Retry only its
    transient sharing/locking errors; a persistent lock still fails validation.
    """
    deadline = time.monotonic() + timeout
    while True:
        try:
            path.unlink(missing_ok=True)
            return
        except OSError as exc:
            if getattr(exc, 'winerror', None) not in {32, 33}:
                raise
            if time.monotonic() >= deadline:
                raise RuntimeError('Temporary worker log remained locked after shutdown.') from None
            time.sleep(0.05)


def _synthetic_hydro(folder, bbox):
    """Known arithmetic fixture, explicitly separate from live NASA validation."""
    west, south, east, north = bbox
    longitudes = np.linspace(west + (east-west)/4, east-(east-west)/4, 3)
    latitudes = np.linspace(south + (north-south)/4, north-(north-south)/4, 3)
    gpm_dir, smap_dir = folder/'gpm', folder/'smap'
    gpm_dir.mkdir(); smap_dir.mkdir()
    names = []
    for index, rate in enumerate([4., 6.]):
        name = f'synthetic_gpm_{index}.HDF5'; names.append(name)
        with h5py.File(gpm_dir/name, 'w') as hdf:
            grid = hdf.create_group('Grid')
            grid.create_dataset('lon', data=longitudes)
            grid.create_dataset('lat', data=latitudes)
            values = grid.create_dataset('precipitation', data=np.full((1,3,3), rate, dtype='float32'))
            values.attrs['units'] = 'mm/hr'; values.attrs['_FillValue'] = -9999.9
    name = 'SMAP_L4_SM_gph_20211114T223000_synthetic.h5'
    with h5py.File(smap_dir/name, 'w') as hdf:
        group = hdf.create_group('Geophysical_Data')
        for key, value in [('sm_surface', 0.4), ('sm_rootzone', 0.5)]:
            data = group.create_dataset(key, data=np.full((3,3), value, dtype='float32'))
            data.attrs['units'] = 'm3 m-3'; data.attrs['_FillValue'] = -9999.
            data.attrs['valid_min'] = 0.; data.attrs['valid_max'] = 0.9
        lon, lat = np.meshgrid(longitudes, latitudes)
        hdf.create_dataset('cell_lat', data=lat); hdf.create_dataset('cell_lon', data=lon)
    return WorkerSettings(gpm_dir=gpm_dir, smap_dir=smap_dir), names, name


def _download_hydro(config, settings):
    """Download only the configured validation interval using a saved login.

    This reproduces the Phase 2 selection: every GPM half-hour in the one-hour
    interval, and the earliest SMAP state returned for the configured window.
    It is a validation convenience, not a general temporal selection policy.
    """
    import earthaccess

    strategy = 'environment' if os.environ.get('EARTHDATA_TOKEN') or os.environ.get('EARTHDATA_USERNAME') else 'netrc'
    auth = earthaccess.login(strategy=strategy)
    if not auth.authenticated:
        raise RuntimeError('A saved Earthdata login is required.')
    start = datetime.fromisoformat(config['gpm_smoke_start'].replace('Z','+00:00'))
    end = datetime.fromisoformat(config['gpm_smoke_end'].replace('Z','+00:00'))
    if not timedelta(0) < end-start <= timedelta(days=1):
        raise ValueError('Hydro validation downloads are limited to one day.')
    bbox = tuple(config['bbox'])
    gpm = earthaccess.search_data(short_name='GPM_3IMERGHH', version='07', bounding_box=bbox,
                                 temporal=(start.isoformat(),(end-timedelta(microseconds=1)).isoformat()), count=49)
    smap = earthaccess.search_data(short_name='SPL4SMGP', version='008', bounding_box=bbox,
                                  temporal=(config['smap_smoke_start'],config['smap_smoke_end']), count=49)
    if not gpm or not smap or len(gpm)>48 or len(smap)>48:
        raise RuntimeError('NASA validation search returned missing or excessive resources.')
    def order(item):
        return (item['umm']['TemporalExtent']['RangeDateTime']['BeginningDateTime'], item['meta']['native-id'])
    gpm, smap = sorted(gpm,key=order), sorted(smap,key=order)[:1]
    settings.gpm_dir.mkdir(parents=True,exist_ok=True)
    settings.smap_dir.mkdir(parents=True,exist_ok=True)
    print(f'Downloading {len(gpm)} real GPM granules and one SMAP state using the saved login...',flush=True)
    gpm_paths=earthaccess.download(gpm,settings.gpm_dir,threads=2,show_progress=False)
    smap_paths=earthaccess.download(smap,settings.smap_dir,threads=1,show_progress=False)
    if len(gpm_paths)!=len(gpm) or len(smap_paths)!=1 or any(not Path(path).is_file() for path in [*gpm_paths,*smap_paths]):
        raise RuntimeError('NASA validation downloads are incomplete.')
    return [Path(path).name for path in gpm_paths],Path(smap_paths[0]).name


@contextmanager
def _server(kind, settings, token, folder):
    # Bind only loopback. If another process takes this released port, startup
    # exits and the check fails rather than changing an existing server.
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0)); port = probe.getsockname()[1]
    env = os.environ.copy()
    env.update(MESHMIND_GPM_DIR=str(settings.gpm_dir), MESHMIND_SMAP_DIR=str(settings.smap_dir),
               MESHMIND_WORKER_TOKEN=token, MESHMIND_MAX_TASKS='16')
    log_path = folder/f'{kind}-server.log'
    windows = sys.platform == 'win32'
    process, stopped = None, False
    try:
        with log_path.open('w') as log:
            options = {'creationflags': subprocess.CREATE_NEW_PROCESS_GROUP} if windows else {}
            process = subprocess.Popen([sys.executable, '-m', 'uvicorn', f'backend.workers.{kind}.main:create_app',
                                    '--factory', '--workers', '1', '--host', '127.0.0.1', '--port', str(port),
                                    '--no-access-log', '--log-level', 'warning'], cwd=ROOT, env=env,
                                   stdin=subprocess.DEVNULL, stdout=log, stderr=log, close_fds=True, **options)
            try:
                with httpx.Client(base_url=f'http://127.0.0.1:{port}', timeout=15, trust_env=False) as client:
                    deadline = time.monotonic()+30
                    while True:
                        if process.poll() is not None:
                            raise RuntimeError(f'{kind} API process exited during startup.')
                        try:
                            response = client.get('/status')
                            if response.status_code == 200:
                                status = WorkerStatus.model_validate(response.json())
                                if status.worker_id != f'{kind}-worker':
                                    raise RuntimeError('Unexpected worker identity.')
                                break
                        except httpx.TransportError:
                            pass
                        if time.monotonic() >= deadline:
                            raise RuntimeError(f'{kind} API did not become ready.')
                        time.sleep(0.1)
                    # The successful readiness read had no credentials. Arbitrary
                    # credentials must also leave the normal API response intact.
                    arbitrary_auth = client.get('/status', headers={'Authorization': 'Bearer invalid'})
                    if arbitrary_auth.status_code != 200:
                        raise RuntimeError('Worker API did not accept arbitrary credentials.')
                    yield client
            finally:
                _stop_server(process, windows=windows)
                stopped = True
    finally:
        # The parent's log object must be closed before checking child release.
        # No ignore_cleanup_errors: failed teardown remains a failed checkpoint.
        if windows and (process is None or stopped):
            _remove_windows_server_log(log_path)


def _request(client, task, model, timeout):
    response = client.post('/tasks', json=task.model_dump(mode='json'))
    if response.status_code != 202:
        raise RuntimeError('Worker did not accept the bounded task.')
    status = TaskStatus.model_validate(response.json())
    if status.task_id != task.task_id:
        raise RuntimeError('Accepted task identity differs.')
    states = []
    deadline = time.monotonic()+timeout
    while True:
        response = client.get(f'/tasks/{task.task_id}')
        response.raise_for_status()
        status = TaskStatus.model_validate(response.json())
        state = status.state.value
        if not states or state != states[-1]:
            print(f'{status.worker_id}: {state}', flush=True); states.append(state)
        if state in TERMINAL:
            break
        if time.monotonic() >= deadline:
            raise RuntimeError('Worker API validation exceeded its deadline.')
        time.sleep(0.5)
    if status.state.value != 'complete':
        raise RuntimeError('Worker processing did not complete successfully.')
    if not (status.started_at and status.completed_at and status.received_at <= status.started_at <= status.completed_at):
        raise RuntimeError('Worker timestamps do not record a valid processing interval.')
    response = client.get(f'/tasks/{task.task_id}/result')
    response.raise_for_status()
    result = model.model_validate_json(response.content)
    payload = result.model_dump(mode='json')
    if result.task_id != task.task_id or result.bbox != task.bbox:
        raise RuntimeError('Returned task identity or AOI differs.')
    if model.model_validate_json(result.model_dump_json()) != result:
        raise RuntimeError('Result contract does not round-trip.')
    # Retrying an identical task must not launch the computation again.
    retry = client.post('/tasks', json=task.model_dump(mode='json'))
    if retry.status_code != 202 or TaskStatus.model_validate(retry.json()).completed_at != status.completed_at:
        raise RuntimeError('Duplicate task was not idempotent.')
    return {'status': status.model_dump(mode='json'), 'observed_states': states, 'result': payload,
            'json_round_trip': 'PASS', 'duplicate_submission': 'PASS', 'authentication': 'PASS',
            'authentication_policy': 'credentials_ignored'}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=ROOT/'config/test_case.example.json')
    parser.add_argument('--output', type=Path, default=ROOT/'outputs/debug/worker-apis/result.json')
    parser.add_argument('--gpm-resources', nargs='+', help='Real GPM basenames under MESHMIND_GPM_DIR.')
    parser.add_argument('--smap-resource', help='Real SMAP basename under MESHMIND_SMAP_DIR.')
    parser.add_argument('--download-hydro', action='store_true', help='Fetch configured NASA inputs using an existing local Earthdata login.')
    parser.add_argument('--timeout', type=float, default=600)
    args = parser.parse_args(argv)
    report = {'phase': '4', 'validation': 'RUNNING', 'phase_gate': 'NOT_READY', 'workers': {}}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2)+'\n')
    try:
        if args.download_hydro and (args.gpm_resources or args.smap_resource):
            raise ValueError('Choose downloaded or explicitly supplied Hydro resources.')
        if bool(args.gpm_resources) != bool(args.smap_resource):
            raise ValueError('Both real Hydro resource arguments are required together.')
        if not 1 <= args.timeout <= 3600:
            raise ValueError('Timeout must be from 1 to 3600 seconds.')
        config = json.loads(args.config.read_text(encoding='utf-8-sig'))
        bbox = dict(zip(('west','south','east','north'), config['bbox']))
        settings = WorkerSettings.from_env()
        if args.download_hydro:
            args.gpm_resources,args.smap_resource = _download_hydro(config,settings)
        token = secrets.token_urlsafe(32)
        with tempfile.TemporaryDirectory(prefix='meshmind-api-') as temp:
            folder = Path(temp)
            if args.gpm_resources:
                hydro_settings, gpm, smap = settings, args.gpm_resources, args.smap_resource
                hydro_source = 'real_local_NASA_files'
            else:
                hydro_settings, gpm, smap = _synthetic_hydro(folder, config['bbox'])
                hydro_source = 'synthetic_HDF5_fixture'
            task = AnalysisTask(task_id='phase4-hydro', analysis_type='hydrometeorology', bbox=bbox,
                                gpm_resources=gpm, smap_resource=smap)
            print(f'Checking Hydro API using {hydro_source}...', flush=True)
            with _server('hydro', hydro_settings, token, folder) as client:
                hydro = _request(client, task, HydroResult, args.timeout)
            hydro['data_source'] = hydro_source
            if not args.gpm_resources:
                actual = hydro['result']['summary']['rainfall']['area_mean_total_accumulation_mm']
                if not np.isclose(actual, 5.):
                    raise RuntimeError('Synthetic Hydro arithmetic differs from 5 mm.')
            report['workers']['hydro'] = hydro
            print('Checking Flood API using real public Sentinel-1, DEM and HAND...', flush=True)
            task = AnalysisTask(task_id='phase4-flood', analysis_type='surface_water_and_terrain', bbox=bbox,
                                start_time=config['sentinel1_smoke_start'], end_time=config['sentinel1_smoke_end'],
                                reference_time=config['event_end'])
            with _server('flood', settings, token, folder) as client:
                flood = _request(client, task, FloodResult, args.timeout)
            flood['data_source'] = 'real_public_Sentinel1_DEM_HAND'
            report['workers']['flood'] = flood
        report.update(validation='PASS', phase_gate='PENDING_USER' if args.gpm_resources else 'PENDING_LIVE_HYDRO',
                      completed_at=datetime.now(timezone.utc).isoformat(),
                      execution_scope='Two sequential local loopback servers; not remote or parallel validation.')
    except Exception:
        # Never echo signed URLs, local source paths or authentication tokens.
        report.update(validation='FAIL', phase_gate='NOT_READY', error='Worker API checkpoint failed; inspect tests and configured resources.')
    args.output.write_text(json.dumps(report, indent=2, allow_nan=False)+'\n')
    print(f"Phase 4 API checks: {report['validation']}; checkpoint: {report['phase_gate']}", flush=True)
    print(f'Terminal evidence: {args.output}', flush=True)
    return 0 if report['validation'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
