"""Phase 6: concurrent real-data HTTP dispatch with conservative overlap evidence.

The remote gate needs three physical laptops and validated clock samples
before and after execution. --local-check exercises the same path locally but
cannot complete the physical-laptop checkpoint.
"""

import argparse
import asyncio
from contextlib import ExitStack
from datetime import datetime, timezone
import json
from pathlib import Path
import secrets
import socket
import tempfile
import time

import httpx

from backend.control.coordinator import run_analysis
from backend.control.main import make_tasks, save_json
from backend.control.timing import ClockCheckError, assess_overlap, sample_clocks
from backend.shared.settings import ControlSettings, ROOT, WorkerEndpoint, WorkerSettings
from scripts.validate.validate_remote_workers import (
    GPM_RESOURCES, SMAP_RESOURCE, _authentication_check, _duplicate_check, topology_checks,
)
from scripts.validate.validate_worker_apis import _server


async def validate(settings, tasks, *, local_check, confirmed, output):
    report = {
        'phase': '6', 'validation': 'RUNNING', 'phase_gate': 'NOT_READY',
        'execution_mode': 'parallel', 'task_id': tasks[0].task_id,
        'authentication_policy': 'credentials_ignored',
        'control_host': socket.gethostname(), 'control_source_ip': settings.local_address,
        'scope': 'local_loopback' if local_check else 'configured_remote_workers',
        'endpoints': {'hydro': settings.hydro.url, 'flood': settings.flood.url},
        'requests': [task.model_dump(mode='json') for task in tasks],
        'dispatch_attempted': False,
        'limitations': [
            'Worker hostnames and process UUIDs support operator confirmation, not hardware attestation.',
            'Clock bounds assume stable clocks between samples; raw timestamps are retained.',
            'A Control timeout does not cancel remote processing; never retry with a new task ID automatically.',
        ],
    }
    save_json(output, report)  # Replace stale PASS evidence before doing any work.
    stage = 'preflight'
    wall_start = datetime.now(timezone.utc)
    monotonic_start = time.monotonic()
    try:
        if not local_check and not confirmed:
            raise ValueError('Physical laptop confirmation is required.')
        report['authentication'] = {}
        for endpoint in (settings.hydro, settings.flood):
            passed = await _authentication_check(endpoint, settings.request_timeout, settings.local_address)
            report['authentication'][endpoint.expected_worker_id] = passed
            if not passed:
                raise ValueError('Worker must accept missing and arbitrary credentials.')
        stage = 'clock_preflight'
        report['clock_before'] = await sample_clocks(settings)
        save_json(output, report)
        print(f'Task {tasks[0].task_id}: clock preflight passed; dispatching both workers concurrently...', flush=True)
        stage = 'dispatch'
        report['dispatch_attempted'] = True
        save_json(output, report)
        run = await run_analysis(*tasks, settings, execution_mode='parallel')
        report['dispatch'] = run.model_dump(mode='json')
        save_json(output, report)  # Preserve independent results if a later check fails.
        for record in (run.hydro, run.flood):
            print(f'{record.worker_id}: {record.outcome}', flush=True)
            if record.task_status:
                print(f'  host={record.task_status.execution_host} '
                      f'start={record.task_status.started_at} end={record.task_status.completed_at}', flush=True)
        stage = 'clock_postflight'
        report['clock_after'] = await sample_clocks(settings)
        elapsed_wall = (datetime.now(timezone.utc) - wall_start).total_seconds()
        elapsed_monotonic = time.monotonic() - monotonic_start
        report['control_clock_continuity'] = {
            'elapsed_wall_seconds': elapsed_wall,
            'elapsed_monotonic_seconds': elapsed_monotonic,
            'passed': abs(elapsed_wall - elapsed_monotonic) <= 0.020,
            'maximum_difference_seconds': 0.020,
        }
        report['overlap'] = assess_overlap(run, report['clock_before'], report['clock_after'])
        report['topology_checks'] = topology_checks(run, settings, report['control_host'], confirmed)
        report['completed_results_preserved'] = (
            run.combined.hydro == run.hydro.result and run.combined.flood == run.flood.result
        )
        first, second = sorted((run.hydro, run.flood), key=lambda record: record.control_completed_at)
        report['control_completion_order'] = [first.worker_id, second.worker_id]
        report['control_completion_gap_seconds'] = (second.control_completed_at - first.control_completed_at).total_seconds()
        report['duplicate_submission'] = {}
        stage = 'duplicate_checks'
        for endpoint, task, record in zip((settings.hydro, settings.flood), tasks, (run.hydro, run.flood)):
            report['duplicate_submission'][endpoint.expected_worker_id] = await _duplicate_check(
                endpoint, task, record, settings.request_timeout, settings.local_address,
            )
        passed = (
            all(record.outcome == 'complete' and record.result is not None for record in (run.hydro, run.flood))
            and report['overlap']['passed'] and report['control_clock_continuity']['passed']
            and report['completed_results_preserved'] and all(report['duplicate_submission'].values())
        )
        if not passed:
            report.update(validation='FAIL', phase_gate='NOT_READY')
        elif local_check:
            report.update(validation='PASS_LOCAL_ONLY', phase_gate='PENDING_REMOTE_LAPTOPS')
        elif all(report['topology_checks'].values()):
            report.update(validation='PASS', phase_gate='PENDING_USER')
        else:
            report.update(validation='FAIL', phase_gate='PENDING_PHYSICAL_DEPLOYMENT_CHECK')
    except (ClockCheckError, ValueError, OSError, httpx.HTTPError, TimeoutError):
        report.update(validation='FAIL', phase_gate='NOT_READY', failed_stage=stage,
                      error='Parallel checkpoint failed; inspect clock readiness, connectivity and worker configuration.')
    report['completed_at'] = datetime.now(timezone.utc).isoformat()
    save_json(output, report)
    overlap = report.get('overlap', {}).get('guaranteed_overlap_seconds')
    if overlap is not None:
        print(f'Guaranteed processing overlap after clock uncertainty: {overlap:.6f} seconds', flush=True)
    print(f"Phase 6: {report['validation']}; checkpoint: {report['phase_gate']}", flush=True)
    print(f'Terminal evidence: {output}', flush=True)
    return 0 if report['validation'] in {'PASS', 'PASS_LOCAL_ONLY'} else 1


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=ROOT / 'config/test_case.example.json')
    parser.add_argument('--output', type=Path, default=ROOT / 'outputs/debug/parallel-workers/result.json')
    parser.add_argument('--gpm-resources', nargs='+', default=GPM_RESOURCES)
    parser.add_argument('--smap-resource', default=SMAP_RESOURCE)
    parser.add_argument('--local-check', action='store_true', help='Real data on Control; never passes the physical-laptop gate.')
    parser.add_argument('--confirm-separate-laptops', action='store_true', help='Confirm three physical laptops, not local processes.')
    args = parser.parse_args(argv)
    try:
        # A failed new setup attempt must not leave an older PASS looking current.
        save_json(args.output, {
            'phase': '6', 'validation': 'FAIL', 'phase_gate': 'NOT_READY',
            'execution_mode': 'parallel', 'dispatch_attempted': False,
            'failed_stage': 'setup', 'attempted_at': datetime.now(timezone.utc).isoformat(),
            'error': 'Parallel checkpoint setup has not completed successfully.',
        })
        if args.local_check and args.confirm_separate_laptops:
            parser.error('--local-check cannot confirm separate laptops.')
        if not args.local_check and not args.confirm_separate_laptops:
            parser.error('Remote validation requires --confirm-separate-laptops.')
        config = json.loads(args.config.read_text(encoding='utf-8-sig'))
        tasks = make_tasks(config, args.gpm_resources, args.smap_resource)
        if args.local_check:
            token = secrets.token_urlsafe(32)
            worker_settings = WorkerSettings.from_env()
            with tempfile.TemporaryDirectory(prefix='meshmind-parallel-') as temp, ExitStack() as stack:
                endpoints = []
                for kind in ('hydro', 'flood'):
                    client = stack.enter_context(_server(kind, worker_settings, token, Path(temp)))
                    endpoints.append(WorkerEndpoint(str(client.base_url), f'{kind}-worker', token=token))
                settings = ControlSettings(hydro=endpoints[0], flood=endpoints[1])
                return asyncio.run(validate(settings, tasks, local_check=True, confirmed=False, output=args.output))
        return asyncio.run(validate(ControlSettings.from_env(), tasks, local_check=False,
                                    confirmed=args.confirm_separate_laptops, output=args.output))
    except (ValueError, KeyError, TypeError, OSError, RuntimeError):
        print('Checkpoint setup failed; check explicit worker settings, config and Python dependencies.')
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
