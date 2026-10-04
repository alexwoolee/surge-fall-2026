# Phase 3C — Combined Flood worker

Branch: `codex/flood-worker`, based on the accepted Phase 3B checkpoint `37aeb2d`.
The user approved Phase 3B and requested that terminal checks run automatically
at phase boundaries. Additional HTML is unnecessary here: this phase combines
the previously reviewed evidence without changing its calculations or maps.

## Terminal checkpoint

Run from the repository root with the existing Python 3.12 environment:

```sh
.venv/bin/python -m scripts.validate.validate_flood --check-repeatability
.venv/bin/python -m pytest -v
git diff --check
```

The real-data command discovers the public resources, invokes the production
worker, verifies the combined result, and repeats with reversed DEM/HAND tile
order. It prints the numerical summary and PASS/FAIL, and saves a JSON report
at `outputs/debug/flood/result.json`. No new HTML or raster files are generated.
Use `--config`, `--output`, or `--threshold-db` when intentionally changing the
investigation; existing results do not approve different settings automatically.

## Service behavior

`backend/workers/flood/service.py` exposes `run_flood_analysis()` with a selected
Sentinel-1 RTC VV scene, DEM tiles, HAND tiles, and one WGS84 bbox. Discovery
remains outside the service. It calls the existing deterministic processors,
then combines their structured evidence and compact summaries.

- Task identity, approved collections, resource limits, AOI and numeric settings
  are validated before processing begins.
- Components run independently and sequentially. Each is attempted even when
  another has a processing or source-access error.
- `complete` means all three processors succeeded. `partial` means one or two
  succeeded, and `failed` means none succeeded. Successful evidence is retained.
- Missing summary/evidence fields mean unavailable results, never zero values.
  Errors name the failed component without copying upstream URLs or credentials.
- **Processing status and geographic coverage are separate.** All processors
  can complete while Sentinel-1 still has partial valid AOI coverage.
- Summaries copy the underlying numerical evidence. Source identities, coverage,
  counts, numerical consistency and strict JSON serialization are checked before
  a component is accepted. Signed query strings are omitted from provenance.
- The payload contains `task_id`, `worker_id`, `analysis_type`, `status`, `bbox`,
  `summary`, `evidence`, `coverage`, `sources`, `errors`, and `limitations`.

The structured dictionary is the Phase 3C result boundary. Pydantic contracts,
HTTP APIs, remote execution and parallel execution remain Phases 4–6.

## Real-data result

Run date: 2026-10-03. Test case: `abbotsford-flood-2021`.
AOI: `[-122.45, 48.95, -121.95, 49.30]`.

| Check | Result |
| --- | --- |
| Combined worker status | complete |
| Component errors | none |
| Sentinel-1 acquisition | 2021-11-16 14:20:44.368208 UTC, VV |
| Candidate surface-water area at −17 dB | 88.0997 km² |
| Candidate fraction of valid SAR pixels | 6.3567% |
| SAR valid AOI coverage | 97.6354% |
| DEM source tiles / valid cells | 4 / 2,271,061 |
| DEM mean / median | 254.308864 / 106.801689 m |
| HAND source tiles / valid cells | 4 / 2,271,061 |
| HAND mean / median | 45.452025 / 6.590429 m |
| DEM / HAND valid coverage | 100% / 100% |
| Summary/evidence/provenance consistency | PASS |
| Strict JSON round trip | PASS |
| Comparison with accepted 3A/3B evidence | Exact match, excluding artifact paths |
| Reversed-source repeatability | PASS |

The scene is
`S1B_IW_GRDH_1SDV_20211116T142031_20211116T142056_029614_0388BC_rtc`.
The selected scene's southern gap remains excluded. The SAR real-data gate
requires full rectangular source extent coverage and at least 95% valid AOI
pixels; terrain requires complete valid AOI coverage. These gate thresholds do
not turn partial SAR coverage into full coverage.

Automated suite: **249 passing tests**, including all 184 prior
tests. The 897 warnings are deprecations from the existing geospatial dependency
stack; the final run had no failures. `git diff --check` is clean. No existing processor or protected Hydro test
was rewritten, no dependency was added, and no remote push was performed.

## Phase boundary — APPROVED

The necessary terminal checks have been run. No additional visual/manual task
is required for this integration because its source calculations and maps were
already accepted in Phases 3A and 3B. The commands above are available for a
repeat check. The JSON report starts with `manual_review: PENDING` and does not
advance the project automatically.

The user confirmed 249 passing tests and approved starting Phase 4 on
2026-10-03. Phase 3C is accepted and merged into local main before shared
contracts and worker API development.

## Limits

The three components share an AOI but use different grids, coverage and source
dates. This worker combines AOI-level evidence; it does not intersect candidate
water with DEM or HAND cells. In particular, terrain statistics describe the
whole AOI rather than terrain underneath the candidate-water mask.

The Sentinel-1 threshold remains a candidate-water heuristic, including permanent
water and possible false positives. No new inundation, water-depth, severity,
causal or emergency-response conclusion is inferred. Every original component
limitation is retained in the combined result. See the accepted
[terrain](manual-test-checklist.md) and [SAR](phase3b-validation.md) checkpoints.
