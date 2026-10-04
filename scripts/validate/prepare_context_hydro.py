"""Prepare a bounded location/date's NASA inputs on the Hydro worker only.

Uses the worker's existing saved Earthdata login. This CLI downloads public
environmental products to the normal local cache; it has no owner-record input.
"""

import argparse
from datetime import date, datetime, time, timedelta, timezone
import json

from backend.shared.context_contracts import ContextTask
from backend.shared.settings import WorkerSettings
from backend.workers.hydro.context import GPM_START, SMAP_START
from backend.workers.hydro.context_sources import NASAContextProvider, live_paths


def prepare(task: ContextTask, settings: WorkerSettings, *, max_granules=48):
    """Download only bounded matching records, and return counts, never secrets."""
    task = ContextTask.model_validate(task.model_dump(mode="json"))
    if task.analysis_type != "hydrometeorology" or type(max_granules) is not int or not 1 <= max_granules <= 336:
        raise ValueError("Preparation requires a Hydro task and a granule limit from 1 to 336.")
    if (task.end_time - task.start_time).total_seconds() / 1800 > max_granules:
        raise ValueError("The requested interval exceeds the configured download count; shorten the interval or raise --max-granules.")
    counts = {}
    provider = NASAContextProvider()
    try:
        for component, coverage_start, folder in (("gpm", GPM_START, settings.gpm_dir), ("smap", SMAP_START, settings.smap_dir)):
            if task.end_time <= coverage_start:
                counts[component] = {"cached_resources": 0, "availability": "before_product_coverage"}
                continue
            paths, reason = live_paths(provider, component, task, folder)
            counts[component] = {"cached_resources": len(paths), "availability": reason or "cached"}
    finally:
        provider.close()
    return counts


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--location-id", default="selected-location")
    parser.add_argument("--bbox", nargs=4, type=float, required=True, metavar=("WEST", "SOUTH", "EAST", "NORTH"))
    parser.add_argument("--as-of", required=True, help="YYYY-MM-DD; window ends at the following midnight UTC")
    parser.add_argument("--hours", type=int, default=24, choices=range(1, 169))
    parser.add_argument("--max-granules", type=int, default=48, help="Explicit download cap (1..336), default one day")
    args = parser.parse_args(argv)
    try:
        day = date.fromisoformat(args.as_of)
        end = datetime.combine(day, time(), tzinfo=timezone.utc) + timedelta(days=1)
        task = ContextTask(analysis_type="hydrometeorology", location_id=args.location_id,
                           bbox=dict(zip(("west", "south", "east", "north"), args.bbox)),
                           as_of=day, start_time=end - timedelta(hours=args.hours), end_time=end)
        result = prepare(task, WorkerSettings.from_env(), max_granules=args.max_granules)
    except Exception:
        print("NASA preparation did not complete. Check the bounded interval/download cap, saved Earthdata login, provider access and worker cache.")
        return 1
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
