# Phase 3B — Sentinel-1 candidate surface water

Implementation branch: `codex/sentinel1-processing`, based on locally accepted
Phase 3A (`ff031ae`). Phase 3A was merged into local main after the user asked to
advance. No changes have been pushed remotely. Hydro processing remains unchanged.

## Run

Use the existing Python 3.12 environment from the repository root:

```sh
.venv/bin/python -m scripts.smoke.smoke_sentinel1
.venv/bin/python -m scripts.validate.validate_sentinel1 --check-repeatability
.venv/bin/python -m pytest -v
git diff --check
```

The validation command uses `config/test_case.example.json`. It writes ignored
artifacts to `outputs/debug/sentinel1/`: calibrated backscatter GeoTIFF,
0/1/255 candidate mask GeoTIFF, geographic preview PNGs, `result.json`, and
`review.html`. Optional `--config`, `--output-dir`, and `--threshold-db` arguments
support another bounded investigation. No NASA login or new dependency is needed.

## Integration and method

Production uses Microsoft Planetary Computer **`sentinel-1-rtc`**, replacing the
raw `sentinel-1-grd` access path for this calculation. The smoke test was updated
to check the same calibrated VV product. Raw integer GRD is explicitly rejected;
its digital numbers cannot be interpreted directly as calibrated backscatter.

The [official RTC collection](https://planetarycomputer.microsoft.com/api/stac/v1/collections/sentinel-1-rtc)
describes Catalyst calibration, radiometric terrain correction using PlanetDEM,
and UTM orthorectification. Microsoft's
[flood project](https://github.com/microsoft/ai4g-flood#downloading-images)
identifies these data as gamma0 in linear power scale. The collection's old
account requirement is stale; Microsoft
[confirmed its removal](https://github.com/microsoft/PlanetaryComputer/discussions/351),
and anonymous signed reads passed here.

1. Read every matching search page, failing above 128 scenes rather than silently
   truncating. Validate collection, timestamp, VV metadata and asset.
2. Rank by largest scene-bbox overlap with the AOI, then smallest absolute time
   distance to the configured event end, then ascending scene ID. The generic
   discovery function uses the search midpoint if no reference time is provided.
   Bbox overlap is a proxy, not a guarantee of valid coverage. This policy can
   select a post-reference observation if it lies inside the search window;
   the actual acquisition time is always returned.
3. Read only the AOI window in the selected COG's native WGS84 UTM grid, bounded
   to 20 million cells. Trust raster georeferencing rather than STAC projection
   fields. Include pixel centers inside the WGS84 AOI, using the same tiny
   roundoff tolerance as terrain. No computational resampling is applied.
4. Honor nodata and masks; exclude nonfinite, zero and negative power. Convert
   valid gamma0 with `10 * log10(power)`. MeshMind applies no additional smoothing,
   thermal/border filtering, or terrain-shadow filtering. Provider filtering
   details beyond the documented RTC process are not assumed.
5. Mark valid pixels at or below **−17 dB** as candidate water. This is a
   configurable, unvalidated heuristic, not a calibrated flood classifier.
   Report the same calculation at −19 and −15 dB as parameter sensitivity.
6. Calculate counts, valid-pixel fractions, backscatter statistics and approximate
   UTM planimetric area (`candidate pixels × pixel area`). Missing cells are
   excluded; no extrapolation. Native 10 m pixel spacing is not independent
   sensor resolving power.

The public processor returns safe provenance without signed URL query strings,
explicit coverage and limitations, and safe errors. Tests include local fixtures;
production discovery restricts the collection and VV polarization.

## Real-data run — numerical PASS

Run date: 2026-10-03. AOI: `[-122.45, 48.95, -121.95, 49.30]`.
Search: 2021-11-13 through 2021-11-18; reference: 2021-11-16 23:59:59 UTC.

Selected scene:
`S1B_IW_GRDH_1SDV_20211116T142031_20211116T142056_029614_0388BC_rtc`.
Acquired **2021-11-16 14:20:44.368208 UTC**, descending, relative orbit 13, VV.

| Check | Result |
| --- | --- |
| Updated RTC smoke | PASS |
| Repeated processing | Identical evidence |
| Native grid | EPSG:32610, 10 × 10 m, 3690 × 3930 output rectangle |
| AOI pixel centers | 14,194,938 |
| Valid pixels | 13,859,286 (97.6354%) |
| Missing/invalid AOI pixels | 335,652 (2.3646%) |
| Backscatter min / max | −32.122640 / 31.638376 dB |
| Backscatter mean / median | −9.257764 / −8.700089 dB |
| −17 dB candidate pixels | 880,997 |
| −17 dB candidate fraction of valid pixels | 6.3567% |
| −17 dB candidate area | 88.0997 km² |
| −19 dB candidate area | 51.4932 km² |
| −15 dB candidate area | 130.5526 km² |

**Valid coverage is partial.** The preview shows a southern scene-edge gap.
The source raster's rectangular extent covers the AOI, but that does not imply
valid measurements everywhere. Invalid pixels remain masked in both artifacts.
This gate requires full rectangular source coverage and at least **95% valid AOI
pixels**; it does not certify full valid coverage. The missing portion must be
considered during manual review and subsequent interpretation.

The saved rasters are checked against their structured metadata, clipping,
valid counts, statistics, candidate threshold, area, fractions and sensitivity.
The repeatability run recalculates the same source evidence. Numerical PASS
means access and implementation checks passed, not that classification accuracy
has been established.

## Automated validation

**184 tests passed**, including all 87 prior terrain/Hydro tests and 97 new
Sentinel-1/validation cases. `git diff --check` and `pip check` passed.
The 279 warnings are dependency deprecations in the existing Rasterio, Affine,
NumPy and Planetary Computer stack; there were no test failures in the final run.

Saved artifacts passed the final reconciliation checks after validator review.
The generated PNG was inspected directly. Browser automation could not inspect
the local HTML because its URL policy rejects `file:` pages; interactive controls
remain part of the user's manual check. No cached rasters are staged for Git.

## User manual gate — PENDING

Open `outputs/debug/sentinel1/review.html` and inspect:

- **Location:** use the coordinate labels and click a feature for an OpenStreetMap
  location link. The reference map supplies geography, not historical water truth.
- **Known water:** compare the Fraser River and familiar lakes with dark radar
  signal and blue candidates. Not every water pixel must be detected.
- **Sumas lowlands:** toggle the overlay to inspect candidate patches against
  their actual radar values. Permanent water remains included.
- **False positives and omissions:** inspect hills, roads and smooth fields,
  isolated speckle, bright rough water and urban/vegetated areas. Assess the
  southern missing-data strip explicitly; do not treat it as dry land.
- **Sensitivity:** note the substantial change from 51.49 to 130.55 km² across
  the displayed thresholds. This is parameter sensitivity, not a confidence
  interval. Adjustments require another recorded validation run.
- **Artifacts:** preview downsampling can omit small patches. Use the full
  GeoTIFFs for detailed GIS inspection. Mask codes are 0 noncandidate, 1 candidate,
  255 invalid. Numerical evidence is in `result.json`.

Report **Phase 3B PASS** or describe discrepancies before Phase 3C (the combined
Flood worker). This checkpoint is not merged into local main until that review.
The main README will be updated at the completed Flood-worker milestone, as its
update-frequency instructions request.

## Interpretation limits

This single-acquisition screen cannot identify new inundation, distinguish
permanent water, establish maximum event extent, or estimate water depth.
Dark terrain/shadow and smooth non-water surfaces can resemble water; wind,
vegetation and urban scattering can obscure it. See the
[NASA/JPL radar interpretation guide](https://airsar.jpl.nasa.gov/documents/genairsar/radar.html).
No flood-confirmation, emergency-response or disaster-severity claim is made.
