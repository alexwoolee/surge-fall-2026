# Phase 7 — Structured evidence and deterministic analyst review

Branch: `codex/fusion-review`, from accepted Phase 6 baseline
`b8a74b698ce476a90b5418aab65f4fd53678e61d`. Phase 7 human acceptance is pending.
The existing `kazi/frontend-ui` checkout and running Windows Hydro checkout are
separate and unchanged. Do not update them to run this offline review.

## Scope and scientific limits

`fusion.py` revalidates the original bounded worker requests and their results,
then assembles source evidence without changing measurements. It checks task
IDs, AOI, resource names, Sentinel acquisition window and backscatter threshold.
An optional original `DispatchRun` retains errors, identities and processing
timestamps. `CombinedAnalysis` remains a collection envelope; accepted workers,
numerical processors and transport behavior are unchanged.

Five source components retain availability, units, provenance, coverage,
limitations and errors. Eight supported metrics are copied from validated
source measurements. Missing or failed components produce null values and
explicit unavailable reasons. Partial Flood evidence and a valid independent
Hydro result survive missing or failed siblings.

The reporting layer distinguishes:

- processing completion from spatial data coverage (the accepted SAR result
  has 97.6354% valid coverage despite completed processing);
- the requested event interval from observed evidence;
- one hour of supplied GPM granules from a multiday event total; existing worker
  results do not contain validated GPM start/end intervals or continuity proof;
- a single SMAP state and a Sentinel-1 acquisition from a time series;
- static DEM/HAND summaries for the entire AOI from terrain under candidate water.

There is no common-grid overlay, low-HAND water percentage, peak 24-hour
rainfall, water depth, causal relationship, flood confirmation or validated
disaster severity calculation. The historical 2021 observations do not become
current conditions because processing occurs later. New Hydro coverage metadata
consumed by rule prerequisites is checked separately from the older envelope.

## Explicit demonstration policy

The user selected **clearly labeled demonstration thresholds** for this phase.
No operational or scientifically validated threshold policy has been supplied.
Rules are never enabled implicitly: provide `--rules` for either entry point.
The example policy and every assessment carry their demonstration purpose.

| Rule | Observed metric | Demonstration condition | Prerequisite |
| --- | --- | --- | --- |
| Rainfall review | Mean supplied-granule accumulation | ≥ 5 mm | Exactly 1 accumulated hour; valid fraction ≥ 0.90 |
| Surface state review | Surface SMAP mean | ≥ 0.40 m³/m³ | Valid fraction ≥ 0.90 |
| Root-zone state review | Root-zone SMAP mean | ≥ 0.40 m³/m³ | Valid fraction ≥ 0.90 |
| Candidate-water review | Threshold-derived candidate area | ≥ 50 km² | SAR valid fraction ≥ 0.95 |
| SAR coverage review | SAR valid AOI fraction | < 0.99 | Coverage itself must be available |

The rainfall duration means the sum of the supplied granule durations; it does
not prove a contiguous observed interval. Comparisons use unrounded values.
Equality is controlled explicitly by `gte`, `gt`, `lte` or `lt`.

Each condition returns `triggered`, `not_triggered`, or `not_assessable` with
its observed value, units, configured threshold, prerequisites and reason.
Unavailable data or a failed prerequisite is never a false threshold comparison.
Unknown metrics, wrong units, invalid domains, duplicate IDs/JSON keys, strings
or booleans in numerical fields, nonfinite values and unknown configuration
fields are rejected. A triggered condition requests analyst review only.

## Offline review of an existing checkpoint

From this checkout with Python 3.12 and the pinned requirements installed:

```powershell
.\.venv\Scripts\python.exe -m scripts.validate.validate_fusion --input outputs/debug/parallel-workers/physical-7bde416/result.json --rules config/rules.example.json --requested-start 2021-11-14T00:00:00Z --requested-end 2021-11-16T23:59:59Z --output outputs/debug/phase7/review.json
```

On macOS/Linux replace the Python path with `.venv/bin/python`. The example
Phase 6 artifact may exist only on Ryan's Mac; Git does not transfer ignored
evidence. Use an actual sanitized copy, or a new local real-data artifact with
the same envelope shape. Do not treat a missing file or a synthetic fixture as
a completed real-data check.

The input must contain `requests` with the original Hydro and Flood tasks and
either `dispatch` (an accepted Control report) or `combined` (a typed collection).
A `requested_window` may be supplied in the envelope instead of command flags.
Conflicting windows are rejected; omission remains unknown, not inferred from
the scene-search interval. Original files are never overwritten. Input aliases,
including hard links, are rejected, and the output records the exact input SHA-256.

No worker token, server startup, POST, environmental processing or model call is
needed for this replay. Unknown envelope metadata is not copied into the new
report. Output is strict JSON and atomically replaced. A new failed attempt
replaces stale success when the output is writable; an I/O failure is explicitly
reported and requires inspecting the output before relying on it.

`PASS / PENDING_USER` means evidence bindings and deterministic review completed.
It does not prove arbitrary input authenticity, a new remote run, full source
coverage, disaster severity, or human acceptance. Original raw remote validation
artifacts remain the evidence for accepted Phases 5/6.

## Optional integration after a new Control dispatch

The existing Control CLI can add review with an explicit policy:

```powershell
.\.venv\Scripts\python.exe -m backend.control.main --gpm-resources 3B-HHR.MS.MRG.3IMERG.20211115-S000000-E002959.0000.V07B.HDF5 3B-HHR.MS.MRG.3IMERG.20211115-S003000-E005959.0030.V07B.HDF5 --smap-resource SMAP_L4_SM_gph_20211114T223000_Vv8010_001.h5 --rules config/rules.example.json --output outputs/debug/control/with-review.json
```

This command *does* dispatch work. Use configured worker URLs and private tokens
on the actual Control machine. Ryan's `MESHMIND_CONTROL_SOURCE_IP=100.100.3.5`
belongs only on his Mac. Phase 7 validation here uses offline/local evidence and
does not need to re-run the physical parallel checkpoint.

Invalid review configuration fails before submission. The exact requests and
independent dispatch report are saved before review; a review error preserves
them. Existing CLI behavior without `--rules` remains compatible. Review triggers
do not become transport failures or erase successful worker results.

With `--rules`, `<output>.phase7-attempt.json` records the latest attempt even
when configuration fails before dispatch. The final report references that
attempt ID. A setup failure marks the sidecar FAIL without destroying a prior
run's results; do not mistake an older report's PASS for this new attempt.

## Verification and human checkpoint

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m pip check
git diff --check
```

Tests cover threshold boundaries/equality, policy validation, nonfinite inputs,
request/measurement binding, partial and failed components, independent evidence,
mutated model instances, unavailable prerequisites, strict JSON, offline replay,
input alias protection and failure preservation.

### Recorded Phase 7 validation

- **PASS:** full Windows Python 3.12 suite, **906 passed, 1 skipped**, in 33.46 s.
  The skip is the existing Windows symlink-privilege check; mandatory resolved-path
  containment tests still run. Existing third-party deprecation warnings remain.
- **PASS:** `python -m pip check` and `git diff --check`.
- **PASS:** independent code review and manual inspection of actual review JSON;
  no outstanding findings. No frontend files changed, so frontend checks are not
  part of this phase.
- **PASS_LOCAL_REAL_DATA:** new task `b0e3a0d4-3152-434e-8159-61f6b805e10a`,
  both typed worker results complete, all 15 numerical/identity reference checks
  match the accepted values exactly. The accepted numerical processors ran
  locally; this is not a fresh physical-laptop or remote HTTP execution proof.
- **PASS / PENDING_USER:** replay of those results with the demonstration policy:
  **4 triggered, 1 not triggered, 0 not assessable**.

The generated input is `outputs/debug/phase7/real-inputs.json`, SHA-256
`f314f5446c94d3194154902d58a4ccfe7f6903535d50e2a445653c699420b18e`.
The structured review is `outputs/debug/phase7/review.json`; full test output is
`outputs/debug/phase7-pytest.log`. These are ignored local artifacts, available
separately for the checkpoint; they do not arrive through a Git pull.

Replay the new artifact without network access:

```powershell
.\.venv\Scripts\python.exe -m scripts.validate.validate_fusion --input outputs/debug/phase7/real-inputs.json --rules config/rules.example.json --output outputs/debug/phase7/review.json
```

| Retained real measurement | Value | Demonstration outcome |
| --- | --- | --- |
| Mean GPM accumulation over the supplied one hour | 6.650416513284047 mm | D-01 triggered |
| Surface SMAP state | 0.4084949195384979 m³/m³ | D-02 triggered |
| Root-zone SMAP state | 0.3924146294593811 m³/m³ | D-03 not triggered |
| Candidate surface-water area | 88.0997 km² | D-04 triggered |
| Valid SAR AOI fraction | 0.9763541059495998 (97.6354%) | D-05 triggered |
| Mean whole-AOI DEM / HAND | 254.30886352438873 / 45.45202530899935 m | Context only; no overlay rule |

The requested interval is 2021-11-14 00:00:00 UTC through 2021-11-16 23:59:59 UTC.
It is not the observed GPM interval. SMAP is the single state labeled
2021-11-14 22:30:00 UTC; the selected SAR acquisition is
2021-11-16 14:20:44.368208 UTC. GPM interval boundaries and continuity remain
unreported by the existing worker, even though the supplied durations total one
hour. All rule comparisons use the retained unrounded values.

Four controlled local omissions of this real evidence also passed:

| Omitted evidence | Triggered | Not triggered | Not assessable |
| --- | ---: | ---: | ---: |
| Flood result | 2 | 1 | 2 |
| Hydro result | 2 | 0 | 3 |
| Both results | 0 | 0 | 5 |
| Sentinel component only; DEM/HAND retained | 2 | 1 | 2 |

`outputs/debug/phase7/preservation.json` records these checks. They confirm
available components remain unchanged and unavailable measurements remain null
with reasons. They are controlled evidence omissions, not remote fault injection.

Acquisition used the existing read-only NASA cache and new public Flood raster
reads. Windows GDAL Schannel rejected the public certificate chain. A local,
ignored validation helper used a separate read-only loopback Range proxy with
Requests verifying upstream HTTPS against the trusted CA bundle; TLS verification
was never disabled. It read 121,550,681 bytes under a 1 GiB cap and 600-second
supervisor. Original sanitized resource URLs were restored before contract
validation; the input records the transport method. This helper is local validation
infrastructure, not a production transport change. The running Hydro service,
its token and checkout, the accepted processors, and the UI checkout were unchanged.

The acquisition helper and CA/cache setup are machine-local and ignored. Other
reviewers can replay the sanitized artifact, or acquire data using their configured
accepted workers and retain both original requests. The replay command alone does
not authenticate an arbitrary artifact's origin.

Before acceptance, inspect the retained real measurements, one-hour versus
requested-window distinction, partial SAR coverage, all five demonstration
outcomes, provenance and limitations. Confirm the demo policy is acceptable for
this development checkpoint. No HTML review is needed: the actual downloadable
HTML briefing and browser verification are Phase 9 work.

Pause for human acceptance before an accepted phase merge or any Phase 8 work.
