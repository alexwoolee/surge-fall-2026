"""Prepare the Phase 2 manual check using local, downloaded IMERG granules.

Run from the repository root with ``python -m scripts.validate.validate_gpm``.
This command does not download data or mark the manual test gate as passed.
"""

import argparse
import json
import math
import os
from pathlib import Path
import sys
import tempfile
from typing import Sequence

from backend.workers.hydro.gpm import GPMProcessingError, analyze_gpm_granules


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = PROJECT_ROOT / "config" / "test_case.example.json"
DEFAULT_GPM_DIR = PROJECT_ROOT / "data" / "cache" / "gpm_smoke"
DEFAULT_OUTPUT = PROJECT_ROOT / "outputs" / "debug" / "phase2-gpm.json"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group()
    source.add_argument(
        "--gpm-dir", type=Path, default=DEFAULT_GPM_DIR,
        help="Directory containing downloaded HDF5 granules (default: data/cache/gpm_smoke).",
    )
    source.add_argument(
        "--gpm-files", type=Path, nargs="+",
        help="Explicit local granules with observation times in IMERG filenames or FileHeader metadata.",
    )
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--start", help="UTC start, overriding config gpm_smoke_start.")
    parser.add_argument("--end", help="UTC end (exclusive), overriding config gpm_smoke_end.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser


def _read_config(path: Path) -> dict:
    with path.open(encoding="utf-8-sig") as stream:
        config = json.load(stream)
    if not isinstance(config, dict):
        raise ValueError("Test-case config must be a JSON object.")
    bbox = config.get("bbox")
    if (
        not isinstance(bbox, list)
        or len(bbox) != 4
        or any(
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            for value in bbox
        )
    ):
        raise ValueError("Config bbox must contain four finite numbers: west, south, east, north.")
    return config


def _local_files(args: argparse.Namespace) -> list[Path]:
    if args.gpm_files:
        files = args.gpm_files
    else:
        if not args.gpm_dir.is_dir():
            raise ValueError(
                f"GPM cache directory does not exist: {args.gpm_dir}. "
                "Supply downloaded granules with --gpm-dir or --gpm-files."
            )
        files = sorted(
            path for path in args.gpm_dir.iterdir()
            if path.is_file() and path.suffix.lower() in {".h5", ".hdf5", ".hdf"}
        )
    if not files:
        raise ValueError(
            "No local GPM HDF5 granules were found. "
            "Supply downloaded granules with --gpm-dir or --gpm-files."
        )
    for path in files:
        if not path.is_file():
            raise ValueError(f"GPM granule is not a readable local file: {path}")
    return files


def _write_report(path: Path, report: dict) -> None:
    # Encode before touching the destination. Replacing a completed temporary
    # file also preserves any previous report if writing is interrupted.
    encoded = json.dumps(report, indent=2, allow_nan=False) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent,
            prefix=f".{path.name}.", suffix=".tmp", delete=False,
        ) as stream:
            temporary_path = Path(stream.name)
            stream.write(encoded)
        os.replace(temporary_path, path)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        config = _read_config(args.config)
        start = args.start or config.get("gpm_smoke_start")
        end = args.end or config.get("gpm_smoke_end")
        if not isinstance(start, str) or not isinstance(end, str) or not start or not end:
            raise ValueError(
                "Provide --start and --end, or gpm_smoke_start and gpm_smoke_end in the config."
            )
        files = _local_files(args)
        protected_paths = {args.config.resolve(), *(path.resolve() for path in files)}
        if args.output.resolve() in protected_paths:
            raise ValueError("Output path must differ from the config and input granules.")
        result = analyze_gpm_granules(
            files, tuple(config["bbox"]), start_time=start, end_time=end,
        )
        report = {
            "phase": 2,
            "validation": {
                "status": "manual_review_required",
                "instructions": (
                    "Inspect the AOI, actual temporal coverage, missing intervals, "
                    "valid-pixel coverage, and rainfall statistics. Record the manual "
                    "gate outcome before continuing to the next phase."
                ),
            },
            "test_case": {"id": config.get("id"), "name": config.get("name")},
            "requested_window": {"start_utc": start, "end_utc_exclusive": end},
            "result": result,
        }
        _write_report(args.output, report)
    except (GPMProcessingError, OSError, ValueError, TypeError) as exc:
        print(f"Phase 2 validation failed: {exc}", file=sys.stderr)
        return 1

    print(f"Phase 2 processing complete. Manual review required: {args.output}")
    print(f"Granules used: {result['granule_count']}; observed duration: {result['total_duration_hours']} hours.")
    print("Temporal coverage (including missing expected intervals):")
    print(json.dumps(result["temporal_coverage"], indent=2, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
