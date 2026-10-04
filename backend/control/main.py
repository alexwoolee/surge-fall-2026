"""Terminal entry point for concurrent Control dispatch and optional Phase 7 review.

Only HTTP runs here. Numerical processors and their datasets stay on workers.
"""

import argparse
import asyncio
import json
from pathlib import Path
from uuid import uuid4

from backend.control.coordinator import run_analysis
from backend.shared.contracts import AnalysisTask
from backend.shared.settings import ControlSettings, ROOT


def make_tasks(config, gpm_resources, smap_resource, task_id=None):
    """Build two bounded requests sharing an ID and AOI, without discovering data."""
    task_id = str(uuid4()) if task_id is None else task_id
    if not isinstance(config.get('bbox'), list) or len(config['bbox']) != 4:
        raise ValueError('Configuration requires four bbox coordinates.')
    bbox = dict(zip(('west', 'south', 'east', 'north'), config['bbox']))
    return (
        AnalysisTask(task_id=task_id, analysis_type='hydrometeorology', bbox=bbox,
                     gpm_resources=gpm_resources, smap_resource=smap_resource),
        AnalysisTask(task_id=task_id, analysis_type='surface_water_and_terrain', bbox=bbox,
                     start_time=config['sentinel1_smoke_start'], end_time=config['sentinel1_smoke_end'],
                     reference_time=config['event_end']),
    )


def save_json(path, value):
    """Replace the report atomically so interrupted writes do not leave partial JSON."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.tmp')
    temporary.write_text(json.dumps(value, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    temporary.replace(path)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=ROOT / 'config/test_case.example.json')
    parser.add_argument('--output', type=Path, default=ROOT / 'outputs/debug/control/result.json')
    parser.add_argument('--gpm-resources', nargs='+', required=True)
    parser.add_argument('--smap-resource', required=True)
    parser.add_argument('--task-id', help='Reuse only with the identical request to retrieve/reconcile a prior task.')
    parser.add_argument('--execution-mode', choices=('parallel', 'sequential'), default='parallel',
                        help='Launch both workers concurrently (default), or reproduce sequential Phase 5 dispatch.')
    parser.add_argument('--rules', type=Path,
                        help='Explicit review policy JSON; add deterministic Phase 7 evidence review after dispatch.')
    args = parser.parse_args(argv)
    attempt_path = None
    attempt = None
    if args.rules is not None:
        from backend.control.reporting import protect_inputs, write_review_report
        attempt_path = args.output.with_name(args.output.name + '.phase7-attempt.json')
        try:
            protect_inputs(args.output, args.config, args.rules)
            protect_inputs(args.output.with_name(args.output.name + '.tmp'), args.config, args.rules)
            protect_inputs(attempt_path, args.config, args.rules, args.output)
            attempt = {'attempt_id': str(uuid4()), 'validation': 'RUNNING', 'dispatch_attempted': False}
            # Keep the previous independent results intact while recording this
            # new attempt; an invalid policy must not appear as an older PASS.
            write_review_report(attempt_path, attempt)
        except (ValueError, OSError):
            print('Cannot safely record the new review attempt; check output and input paths.')
            return 2
    try:
        config = json.loads(args.config.read_text(encoding='utf-8-sig'))
        hydro, flood = make_tasks(config, args.gpm_resources, args.smap_resource, args.task_id)
        policy = None
        window = None
        if args.rules is not None:
            from backend.control.alerts import load_policy
            from backend.control.fusion import TimeWindow
            policy = load_policy(args.rules)
            window = TimeWindow(start=config['event_start'], end=config['event_end']).model_dump(mode='json')
        settings = ControlSettings.from_env()
    except (ValueError, KeyError, TypeError, OSError):
        if attempt is not None:
            attempt.update(validation='FAIL', failed_stage='configuration',
                           error='No task submitted; any previous output describes an older attempt.')
            try:
                write_review_report(attempt_path, attempt)
            except OSError:
                print('Could not update attempt evidence; do not rely on an older report for this attempt.')
            print(f'Latest review attempt: {attempt_path}')
        print('Invalid Control configuration; check worker URLs, tokens, bounds, resource names and any review policy.')
        return 2
    order = 'Hydro and Flood concurrently' if args.execution_mode == 'parallel' else 'Hydro then Flood sequentially'
    print(f'Task {hydro.task_id}: dispatching {order} over HTTP.', flush=True)
    # Persist the ID and exact bounded requests before any possibly ambiguous POST.
    save_json(args.output, {'validation': 'RUNNING', 'task_id': hydro.task_id,
                           'execution_mode': args.execution_mode,
                           'requests': [task.model_dump(mode='json') for task in (hydro, flood)]})
    if attempt is not None:
        attempt.update(task_id=hydro.task_id, dispatch_attempted=True)
        write_review_report(attempt_path, attempt)
    run = asyncio.run(run_analysis(hydro, flood, settings, execution_mode=args.execution_mode))
    report = {'requests': [task.model_dump(mode='json') for task in (hydro, flood)],
              'dispatch': run.model_dump(mode='json')}
    save_json(args.output, report)  # Keep independent results even if the later review fails.
    review_failed = False
    if policy is not None:
        from backend.control.reporting import build_review_report
        report['requested_window'] = window
        report['phase7_attempt_id'] = attempt['attempt_id']
        try:
            report['phase7'] = build_review_report(report, policy)
        except (ValueError, KeyError, TypeError, OverflowError):
            review_failed = True
            report['phase7'] = {'validation': 'FAIL', 'phase_gate': 'NOT_READY',
                                'error': 'Deterministic review failed; original dispatch evidence is retained.'}
        save_json(args.output, report)
        attempt.update(validation='FAIL' if review_failed else 'PASS')
        write_review_report(attempt_path, attempt)
        print('Phase 7 review: ' + ('FAIL; independent results retained.' if review_failed
                                   else 'PASS; inspect configured analyst-review conditions.'), flush=True)
    for record in (run.hydro, run.flood):
        print(f'{record.worker_id}: {record.outcome}', flush=True)
        if record.error:
            print(record.error.message, flush=True)
    print(f'Control evidence: {args.output}', flush=True)
    return 0 if not review_failed and all(record.outcome == 'complete' for record in (run.hydro, run.flood)) else 1


if __name__ == '__main__':
    raise SystemExit(main())
