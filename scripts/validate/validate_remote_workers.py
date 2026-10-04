"""Phase 5 terminal checkpoint: real HTTP dispatch and honest deployment evidence.

The default uses configured remote workers. --local-check starts temporary
loopback workers with real data, but can never pass the remote phase gate.
"""

import argparse
import asyncio
from contextlib import ExitStack
from datetime import datetime, timezone
import ipaddress
import json
from pathlib import Path
import secrets
import socket
import tempfile
from urllib.parse import urlsplit

import httpx

from backend.control.coordinator import run_analysis
from backend.control.main import make_tasks, save_json
from backend.shared.contracts import TaskStatus
from backend.shared.settings import ControlSettings, ROOT, WorkerEndpoint, WorkerSettings
from scripts.validate.validate_worker_apis import _server


GPM_RESOURCES = [
    '3B-HHR.MS.MRG.3IMERG.20211115-S000000-E002959.0000.V07B.HDF5',
    '3B-HHR.MS.MRG.3IMERG.20211115-S003000-E005959.0030.V07B.HDF5',
]
SMAP_RESOURCE = 'SMAP_L4_SM_gph_20211114T223000_Vv8010_001.h5'


def _remote_address(url):
    host = urlsplit(url).hostname
    if not host or host.lower().rstrip('.') == 'localhost' or host.lower().endswith('.localhost'):
        return False
    try:
        address = ipaddress.ip_address(host)
        address = getattr(address, 'ipv4_mapped', None) or address
        return not (address.is_loopback or address.is_unspecified or address.is_multicast)
    except ValueError:
        return True  # DNS names are allowed; actual reported execution hosts are also checked.


def topology_checks(run, settings, control_host, confirmed):
    statuses = [record.task_status for record in (run.hydro, run.flood)]
    hosts = [status.execution_host if status else None for status in statuses]
    instances = [status.process_instance_id if status else None for status in statuses]
    normalized = [host.lower().rstrip('.') if host else None for host in [control_host, *hosts]]
    return {
        'non_loopback_worker_urls': all(_remote_address(endpoint.url) for endpoint in (settings.hydro, settings.flood)),
        'three_distinct_reported_hosts': all(normalized) and len(set(normalized)) == 3,
        'distinct_worker_processes': all(instances) and len(set(instances)) == 2,
        'operator_confirmed_three_physical_laptops': confirmed,
    }


async def _authentication_check(endpoint, timeout):
    async with httpx.AsyncClient(base_url=endpoint.url, timeout=timeout, trust_env=False,
                                 follow_redirects=False) as client:
        # An absent token must fail before any task is submitted.
        async with asyncio.timeout(timeout):
            async with client.stream('GET', '/status') as response:
                return response.status_code == 401


async def _duplicate_check(endpoint, task, record, timeout):
    if record.task_status is None or record.outcome != 'complete':
        return False
    headers = {'Authorization': f'Bearer {endpoint.token}'} if endpoint.token else {}
    async with httpx.AsyncClient(base_url=endpoint.url, timeout=timeout, trust_env=False,
                                 follow_redirects=False, headers=headers) as client:
        async with asyncio.timeout(timeout):
            async with client.stream('POST', '/tasks', json=task.model_dump(mode='json')) as response:
                if response.status_code != 202:
                    return False
                body = bytearray()
                async for part in response.aiter_bytes():
                    body.extend(part)
                    if len(body) > 64 * 1024:
                        return False
                status = TaskStatus.model_validate_json(body)
    return status == record.task_status


async def validate(settings, tasks, *, local_check, confirmed, output):
    report = {
        'phase': '5', 'validation': 'RUNNING', 'phase_gate': 'NOT_READY',
        'control_host': socket.gethostname(), 'task_id': tasks[0].task_id,
        'execution_mode': 'sequential', 'scope': 'local_loopback' if local_check else 'configured_remote_workers',
        'endpoints': {'hydro': settings.hydro.url, 'flood': settings.flood.url},
        'requests': [task.model_dump(mode='json') for task in tasks],
        'limitations': [
            'Hostnames and process UUIDs are worker-reported evidence, not hardware attestation.',
            'A client timeout does not cancel remote work; retry only the identical task ID and request.',
            'This sequential checkpoint does not establish parallel execution.',
        ],
    }
    save_json(output, report)
    try:
        report['authentication'] = {}
        for endpoint in (settings.hydro, settings.flood):
            if not endpoint.token:
                raise ValueError('Remote checkpoint requires configured worker tokens.')
            passed = await _authentication_check(endpoint, settings.request_timeout)
            report['authentication'][endpoint.expected_worker_id] = passed
            if not passed:
                raise ValueError('Worker must reject unauthenticated requests.')
        print(f'Task {tasks[0].task_id}: dispatching Hydro then Flood...', flush=True)
        run = await run_analysis(*tasks, settings)
        report['dispatch'] = run.model_dump(mode='json')
        save_json(output, report)  # Keep returned evidence even if a subsequent check fails.
        checks = topology_checks(run, settings, report['control_host'], confirmed)
        report['topology_checks'] = checks
        report['duplicate_submission'] = {}
        for endpoint, task, record in zip((settings.hydro, settings.flood), tasks, (run.hydro, run.flood)):
            print(f'{record.worker_id}: {record.outcome}', flush=True)
            if record.task_status:
                print(f'  host={record.task_status.execution_host} '
                      f'start={record.task_status.started_at} end={record.task_status.completed_at}', flush=True)
            report['duplicate_submission'][endpoint.expected_worker_id] = await _duplicate_check(
                endpoint, task, record, settings.request_timeout)
        successful = all(record.outcome == 'complete' and record.result is not None for record in (run.hydro, run.flood))
        if not successful or not all(report['duplicate_submission'].values()):
            report.update(validation='FAIL', phase_gate='NOT_READY')
        elif local_check:
            report.update(validation='PASS_LOCAL_ONLY', phase_gate='PENDING_REMOTE_LAPTOPS')
        elif all(checks.values()):
            report.update(validation='PASS', phase_gate='PENDING_USER')
        else:
            report.update(validation='PASS_HTTP_ONLY', phase_gate='PENDING_PHYSICAL_DEPLOYMENT_CHECK')
    except (ValueError, OSError, httpx.HTTPError, TimeoutError):
        report.update(validation='FAIL', phase_gate='NOT_READY',
                      error='Remote checkpoint failed; check connectivity, authentication and worker configuration.')
    report['completed_at'] = datetime.now(timezone.utc).isoformat()
    save_json(output, report)
    print(f"Phase 5: {report['validation']}; checkpoint: {report['phase_gate']}", flush=True)
    print(f'Terminal evidence: {output}', flush=True)
    return 0 if report['validation'] in {'PASS', 'PASS_LOCAL_ONLY'} else 1


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=ROOT / 'config/test_case.example.json')
    parser.add_argument('--output', type=Path, default=ROOT / 'outputs/debug/remote-workers/result.json')
    parser.add_argument('--gpm-resources', nargs='+', default=GPM_RESOURCES)
    parser.add_argument('--smap-resource', default=SMAP_RESOURCE)
    parser.add_argument('--local-check', action='store_true', help='Real data on this machine; cannot pass the remote gate.')
    parser.add_argument('--confirm-separate-laptops', action='store_true',
                        help='Operator confirms Control, Hydro and Flood run on three physical laptops.')
    args = parser.parse_args(argv)
    try:
        if args.local_check and args.confirm_separate_laptops:
            parser.error('--local-check cannot confirm separate laptops.')
        config = json.loads(args.config.read_text(encoding='utf-8-sig'))
        tasks = make_tasks(config, args.gpm_resources, args.smap_resource)
        if args.local_check:
            token = secrets.token_urlsafe(32)
            worker_settings = WorkerSettings.from_env()
            with tempfile.TemporaryDirectory(prefix='meshmind-dispatch-') as temp, ExitStack() as stack:
                endpoints = []
                for kind in ('hydro', 'flood'):
                    client = stack.enter_context(_server(kind, worker_settings, token, Path(temp)))
                    endpoints.append(WorkerEndpoint(url=str(client.base_url), expected_worker_id=f'{kind}-worker', token=token))
                settings = ControlSettings(hydro=endpoints[0], flood=endpoints[1])
                return asyncio.run(validate(settings, tasks, local_check=True, confirmed=False, output=args.output))
        settings = ControlSettings.from_env()
        return asyncio.run(validate(settings, tasks, local_check=False,
                                    confirmed=args.confirm_separate_laptops, output=args.output))
    except (ValueError, KeyError, TypeError, OSError, RuntimeError):
        print('Checkpoint setup failed; check environment variables, config and Python dependencies.')
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
