"""Terminal entry point for sequential Control dispatch (Phase 5).

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
    args = parser.parse_args(argv)
    try:
        settings = ControlSettings.from_env()
        config = json.loads(args.config.read_text(encoding='utf-8-sig'))
        hydro, flood = make_tasks(config, args.gpm_resources, args.smap_resource, args.task_id)
    except (ValueError, KeyError, TypeError, OSError):
        print('Invalid Control configuration; check worker URLs, tokens, bounds and resource names.')
        return 2
    print(f'Task {hydro.task_id}: dispatching Hydro then Flood over HTTP.', flush=True)
    # Persist the ID and exact bounded requests before any possibly ambiguous POST.
    save_json(args.output, {'validation': 'RUNNING', 'task_id': hydro.task_id,
                           'requests': [task.model_dump(mode='json') for task in (hydro, flood)]})
    run = asyncio.run(run_analysis(hydro, flood, settings))
    save_json(args.output, {'requests': [task.model_dump(mode='json') for task in (hydro, flood)],
                           'dispatch': run.model_dump(mode='json')})
    for record in (run.hydro, run.flood):
        print(f'{record.worker_id}: {record.outcome}', flush=True)
        if record.error:
            print(record.error.message, flush=True)
    print(f'Control evidence: {args.output}', flush=True)
    return 0 if all(record.outcome == 'complete' for record in (run.hydro, run.flood)) else 1


if __name__ == '__main__':
    raise SystemExit(main())
