# Phase 3A — Terrain validation

This checkpoint starts from the updated `main` commit `22a85b7`. The README's
completed Phase 2 GPM, SMAP, and Hydro work is preserved. The earlier GPM branch
is not part of this implementation.

## Run

Use Python 3.12. From the repository root:

```sh
python -m pip install -r requirements.txt
python -m scripts.validate.validate_terrain --check-repeatability
python -m pytest -v
git diff --check
```

On this Mac, use `.venv/bin/python` for `python`. `requirements.txt` uses
Rasterio 1.4.4 on macOS before 15 (Darwin before 24); the existing 1.5.2 pin is
retained elsewhere. Both public sources are read using bounded windows. NASA
authentication is not required for this terrain command.

The command queries all DEM and HAND search pages, resolves the four tiles per
source intersecting the configured Abbotsford AOI, writes clipped rasters,
checks saved-raster statistics against the structured results, and repeats
processing with reversed tile order. It fails if valid coverage is incomplete.
Generated artifacts stay in the ignored `outputs/debug/terrain/` directory.

## Real-data run

Test date: 2026-10-03. AOI: `[-122.45, 48.95, -121.95, 49.30]`.

Full automated suite: **87 passed**, including all 17 original Hydro tests.
`git diff --check` and `pip check` passed. The run emitted deprecation warnings
from the current Rasterio/Affine/NumPy combination; no tests failed. The protected
Hydro files and the updated README have no changes in this branch.

| Check | DEM | HAND |
| --- | --- | --- |
| Public access smoke test | PASS | PASS |
| Source tiles | 4 | 4 |
| Valid AOI pixels | 2,271,061 | 2,271,061 |
| Tile coverage / valid fraction | 100% / 100% | 100% / 100% |
| Minimum | -4.255220 m | 0 m |
| Maximum | 1662.628052 m | 866.518066 m |
| Mean | 254.308864 m | 45.452025 m |
| Median | 106.801689 m | 6.590429 m |
| Saved-raster checks | PASS | PASS |
| Reversed-order repeatability | PASS | PASS |

These statistics describe the whole configured AOI, including its hills and
mountains. They are not measurements of only the flat Sumas Prairie.

Source IDs use `Copernicus_DSM_COG_10_` plus `N48_00` / `N49_00`,
`W122_00` / `W123_00`, and the `_DEM` / `_HAND` suffix. The full provenance,
coverage, transform, CRS, and limitations are recorded in `result.json`.

## User manual gate — APPROVED

The user approved advancing to the next phase on 2026-10-03 after running the
real-data checks and all 87 tests. Phase 3A is accepted for this configured AOI.
The instructions below remain available for repeat validation; generated reports
always start with `manual_review: PENDING` and do not automatically approve a run.

Open `outputs/debug/terrain/review.html` and inspect both previews. Use the
GeoTIFF links in the review if you need full-resolution GIS inspection.

- Confirm the AOI matches the configured study area.
- Confirm all four source tiles contributed and inspect the boundaries near
  49°N and 122°W for gaps or duplicated strips.
- Compare the reported ranges and pixel counts with the table above.
- Inspect low terrain versus hills, and drainage-relative HAND patterns.
- Confirm the previews' north-up orientation and the documented color scale;
  preview colors saturate at the 98th percentile, while statistics use every
  valid source-resolution cell.
- Confirm `result.json` says `real_data_check: PASS`,
  `repeatability_checked: true`, and `manual_review: PENDING`.

Report **Phase 3A PASS** or the discrepancy before continuing to Phase 3B.
This command never grants user approval or advances the phase automatically.

## Method and limits

- Includes native pixel centers within the WGS84 bbox, with a tiny floating-point
  boundary tolerance. Edge cells are not fractionally weighted.
- Statistics are equally weighted by valid pixel, not by ground area.
- Tiles must have compatible, aligned north-up grids and the same CRS and
  resolution. Mixed resolutions/CRSs are explicitly rejected. AOIs crossing
  a GLO-30 latitude-dependent resolution transition need a future documented
  resampling policy; no silent resampling is performed.
- Overlaps use the first valid value in sorted tile-ID order. Later tiles can
  fill earlier nodata; each destination pixel contributes once.
- Honors explicit nodata, internal/external masks, scale/offset, and finite
  values. Negative elevations remain valid; negative HAND values are excluded.
- Real HAND COGs have no explicit nodata tag. Zero is retained as a valid
  drainage-relative height. Unmarked positive sentinel values cannot be inferred.
- Copernicus DEM is a surface model, including vegetation/building effects,
  with EGM2008 vertical referencing. HAND provides terrain context, not flood
  detection.
- Tasks are bounded by a ten-million-cell AOI limit and explicit catalog tile
  limits. Oversized requests fail rather than truncating the returned mosaic.

Primary references: [Copernicus data specification](https://dataspace.copernicus.eu/explore-data/data-collections/copernicus-contributing-missions/collections-description/COP-DEM),
[COG tile layout](https://copernicus-dem-30m.s3.amazonaws.com/readme.html),
[ASF HAND dataset](https://glo-30-hand.s3.amazonaws.com/readme.html), and
[Rasterio windowed reads](https://rasterio.readthedocs.io/en/stable/topics/windowed-rw.html).

The existing smoke scripts continue to verify the same external providers and
access paths; both were rerun successfully. Production calculations stay in
`backend/`. The main README will be updated at the milestone frequency it requests.

## Next checkpoint

Phase 3B implementation and numerical validation are recorded in
[phase3b-validation.md](phase3b-validation.md). Its Sentinel-1 visual/manual gate
was approved by the user before the combined Phase 3C Flood worker.
