# Phase gates through Phase 6

Follow the README sequence: IMPLEMENT → RUN → MANUALLY CHECK → PASS or FIX.
Automated fixture tests and a successful command exit do not replace a real-data
manual check. Record the result of each gate before advancing dependent work.

## Current checkpoint

- Phase 0: repository layout and ignore rules checked.
- Phase 1: all five real-data smoke tests previously reported PASS.
- Phase 2: prior manual check reported; current GPM corrections need a recheck.
- Phase 3: existing implementation, manual review incomplete.
- Phase 4: existing local-file service, independent integration gate pending.
- Phases 5 and 6: not implemented.

2026-10-03 verification: **61 automated tests passed**, including 35 GPM
processor tests, 11 validation-CLI tests, 3 smoke-download workflow tests, and
12 existing SMAP/hydro-service tests. These use synthetic or mocked inputs.
Work is paused at the user's request before an incoming repository update.

## Environment

Run commands from the repository root. Use Python 3.12 or newer:

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements-hydro.txt
.venv/bin/python -m pytest -q
```

This checkout already has a Python 3.12 `.venv` with the hydro dependencies.
On Windows, use `.venv\Scripts\python.exe` in place of `.venv/bin/python`.
The full `requirements.txt` additionally installs STAC and raster libraries. The
pinned Rasterio install needs GDAL on this Mac; that setup remains open for Phase 5.

## Phase 2 — GPM real-data review

1. Use the real IMERG V07 files from the earlier smoke run, or download all files
   for the configured one-hour smoke window. NASA Earthdata authentication is
   required for the download; enter credentials only in your local terminal.

   ```sh
   .venv/bin/python scripts/smoke/smoke_gpm.py --all-in-window
   ```

   The default smoke command without this flag still downloads one granule.
   A single half-hour file is insufficient to verify the configured full hour.
   Downloads stay under the ignored `data/cache/gpm_smoke/` directory.

2. Run the phase-specific tests, then process the real files:

   ```sh
   .venv/bin/python -m pytest tests/test_hydro.py tests/test_validate_gpm.py tests/test_gpm_smoke.py -q
   .venv/bin/python -m scripts.validate.validate_gpm
   ```

   Use `--gpm-dir /path/to/granules` for another directory, or `--gpm-files` followed
   by explicit paths. Use `--start` and `--end` to override the configured UTC
   window. The interval is half-open: start is included and end is excluded.

3. Open `outputs/debug/phase2-gpm.json` and check:

   - The requested AOI matches `config/test_case.example.json`.
   - The actual selected coordinates lie inside that AOI.
   - The contributing filenames and UTC intervals match the requested window.
   - The configured 00:00–01:00 UTC example has two distinct half-hour observations,
     one observed hour, complete temporal coverage, and no missing intervals.
   - Pixel coverage describes valid observations across every contributing file.
     Missing values are excluded; zero rainfall remains valid.
   - Rainfall values are finite and nonnegative. For one full half-hour observation,
     mean accumulation equals mean rainfall rate multiplied by 0.5 hours. Across
     files, totals use cells valid in every contributing observation; means may
     therefore differ from adding single-file means when their valid masks differ.
   - A partially intersecting granule contributes only its overlap duration. This
     assumes its reported half-hour mean rate is constant over that overlap.
   - Repeating the command produces the same result.

4. Test a window outside all cached observations; expect a clear failure and no new
   successful output. Do not mistake an older JSON file for this failed run.

   ```sh
   .venv/bin/python -m scripts.validate.validate_gpm \
     --start 2000-01-01T00:00:00Z --end 2000-01-01T01:00:00Z \
     --output outputs/debug/phase2-no-match.json
   ```

5. Report **Phase 2 PASS** with the real filenames, observed interval, and any
   coverage limitations, or report the discrepancy. The generated status remains
   `manual_review_required`; the CLI never grants manual approval.

This checkout currently contains no real HDF5 cache files, so no new real-data
processing result has been verified here. Synthetic tests are not real observations.

## Remaining gates

These are checkpoints to complete in order, not claims of completed work.

| Phase | Automated and implementation work | Manual evidence required |
| --- | --- | --- |
| 3 — SMAP | Validate timestamps, spatial selection, explicitly declared fill values, finite values, dimensions, unreadable inputs, and repeatability | Inspect real surface/root-zone variables, timestamp, selected pixels, valid ranges and soil-moisture statistics |
| 4 — Hydro | Exercise both actual processors together, test errors and strict JSON serialization | Laptop 2 independently produces a structured result from real GPM + SMAP files; verify source and time coverage |
| 5 — Terrain | Resolve GIS dependencies; implement all intersecting DEM/HAND tiles, CRS handling, clipping, coverage and no-data semantics | Inspect AOI alignment and elevation/HAND maps and values, including tile edges; explicitly resolve HAND no-data meaning |
| 6 — Sentinel-1 | Implement approved-scene selection, required SAR preprocessing and deterministic candidate-water processing | Visually inspect the real scene and mask, AOI alignment, missing data and false detections; record scene, polarization and processing settings |

Phase 6 results must retain the README's candidate-surface-water wording. A dark
SAR return alone does not establish confirmed flooding. Phase 7 work begins only
after the Phase 6 visual gate passes.
