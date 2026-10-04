"""Download the bounded real NASA checkpoint inputs on the Hydro worker only."""

import argparse
import json
from pathlib import Path

from backend.shared.settings import ROOT, WorkerSettings
from scripts.validate.validate_worker_apis import _download_hydro


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=ROOT / 'config/test_case.example.json')
    args = parser.parse_args(argv)
    try:
        config = json.loads(args.config.read_text(encoding='utf-8-sig'))
        gpm, smap = _download_hydro(config, WorkerSettings.from_env())
    except Exception:
        print('NASA preparation failed; verify the saved local Earthdata login, network and configured folders.')
        return 1
    print('Real NASA inputs ready on this machine:')
    for name in [*gpm, smap]:
        print(name)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
