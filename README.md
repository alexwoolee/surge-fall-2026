# MeshMind

MeshMind is a multi-agent, multi-workstation environmental intelligence system.

One natural-language request launches bounded specialist investigations across approved environmental data systems. Real Python processing executes on separate workstations, structured results return to Control, deterministic validation and review rules are evaluated, and MeshMind produces one combined downloadable briefing.

> MeshMind is an environmental analysis and analyst-support system. It is not an operational emergency-response, evacuation, or disaster-detection system.

---

# Current Status

## Current Phase

**Phase 6 — Real Parallel Execution: complete**

Completed so far:

- repository and GitHub setup
- all five external data-access smoke tests
- deterministic GPM IMERG processing
- deterministic SMAP L4 processing
- combined Laptop 2 hydrometeorology worker
- real GPM + SMAP integration test
- multi-tile DEM and HAND processing with approved real-data review
- calibrated Sentinel-1 RTC candidate-water processing with approved visual review
- combined deterministic Flood worker and terminal validation checkpoint
- shared Pydantic task/result/status contracts
- Hydro and Flood HTTP APIs validated with real data on loopback
- bounded Control dispatch with task/result checks, deadlines and independent branch records
- worker hostname/startup identity and cross-platform deployment instructions
- automated test suite: **758 passing tests on macOS**
- Phase 6 Windows verification: **757 passed, 1 expected symlink-privilege skip**
- real-data Control dispatch to separate Windows Hydro and Linux Flood laptops: **PASS; Phase 5 accepted**
- concurrent Control dispatch, authenticated clock samples and conservative overlap proof
- Phase 6 real-data parallel execution on Windows and Linux workers: **PASS; human checkpoint complete**

Current focus:

**The requested work through Phase 6 is complete. Remote validation at implementation commit `7bde416` proved 0.227333 seconds of guaranteed execution overlap, results match Phase 5, and the user confirmed both workers' terminal activity. Stop here; no later phase has started.**

## Status Matrix

```text
DATA ACCESS

GPM IMERG       PASS
SMAP L4         PASS
Sentinel-1 SAR  PASS
Copernicus DEM  PASS
HAND            PASS

DETERMINISTIC PROCESSING

GPM             PASS
SMAP            PASS
Hydro Worker    PASS
DEM / HAND      PASS
Sentinel-1      PASS
Flood Worker    PASS

DISTRIBUTED SYSTEM

Shared Contracts        PASS
Worker HTTP APIs        PASS (local real-data HTTP validation)
Remote Dispatch         PASS; PHASE 5 ACCEPTED
Parallel Execution      PASS; PHASE 6 COMPLETE
Control Fusion          NOT STARTED
Agent Integration       NOT STARTED
Frontend                NOT STARTED
Final Report            NOT STARTED
```

## Immediate Next Steps

The Phase 6 technical and manual checks are complete. Preserve the recorded
evidence and stop at the requested scope. Later phases require a new instruction.

Current cross-platform update commands and overlap requirements are in
[Phase 6 validation](docs/phase6-validation.md). The accepted
[Phase 5 validation](docs/phase5-validation.md) records physical remote execution.
The accepted
[Phase 4 validation](docs/phase4-validation.md) remains available. The earlier
[combined Flood](docs/phase3c-validation.md),
[terrain](docs/manual-test-checklist.md) and
[Sentinel-1](docs/phase3b-validation.md) reviews remain available.

---

# Core Demo Goal

```text
ONE natural-language request
        |
        v
TWO specialist investigations
        |
        v
TWO physical laptops execute real environmental processing
        |
        v
Structured results return to Control
        |
        v
Deterministic validation and review rules
        |
        v
ONE downloadable environmental briefing
```

The demo must show real distributed work.

Multiple laptops are not used because the hackathon datasets require extraordinary compute. They represent independent systems or departments that may own different approved datasets, permissions, and processing capabilities.

---

# System Architecture

```text
                         USER
                          |
                          v
                 LAPTOP 1 - CONTROL
                          |
             +------------+------------+
             |                         |
             v                         v
     LAPTOP 2 - HYDRO          LAPTOP 3 - FLOOD
           WORKER                    WORKER
             |                         |
       +-----+-----+            +------+------+
       |           |            |             |
   GPM IMERG    SMAP L4    Sentinel-1      Terrain
                                             |
                                         DEM + HAND
       |                                   |
       v                                   v
   HydroResult                        FloodResult
       |                                   |
       +----------------+------------------+
                        |
                        v
                  LAPTOP 1 CONTROL
                        |
                  validate results
                        |
                evaluate review rules
                        |
                  combine evidence
                        |
                        v
                 FINAL BRIEFING
```

---

# Laptop Responsibilities

## Laptop 1 — Control

Laptop 1 is the MeshMind coordinator.

Planned responsibilities:

- main application UI
- natural-language request
- OpenAI agent orchestration
- task creation
- worker selection
- task dispatch
- concurrent execution coordination
- worker-state tracking
- result collection
- deterministic result validation
- evidence fusion
- deterministic analyst-review rules
- report generation
- history
- application state

Laptop 1 must not use the LLM to calculate authoritative environmental measurements.

Python processing produces numerical results.

## Laptop 2 — Hydrometeorology Worker

**Status: deterministic core complete**

Approved resources:

- GPM IMERG
- SMAP L4

Responsibilities:

- process approved rainfall resources
- process approved soil-moisture resources
- spatially subset data to the requested AOI
- calculate deterministic statistics
- return structured hydrometeorological evidence

Primary result:

`HydroResult`

Current deterministic flow:

```text
GPM IMERG
    |
    v
Accumulated Rainfall
    |
    +-----------------+
                      |
                      v
                 Hydro Worker
                      ^
                      |
    +-----------------+
    |
SMAP L4
    |
    v
Current Soil State
```

## Laptop 3 — Surface Water and Terrain Worker

**Status: deterministic core and real-data terminal validation complete**

Approved resources:

- Sentinel-1 SAR
- Copernicus DEM GLO-30
- GLO-30 HAND

Responsibilities:

- process approved Sentinel-1 scenes
- derive candidate surface-water evidence
- process all intersecting terrain tiles
- calculate deterministic terrain metrics
- return structured surface-water and terrain evidence

Primary result:

`FloodResult`

`FloodResult` is a project data-structure name. It must not be presented as proof that a real-world flood has been confirmed.

---

# Data Sources

## GPM IMERG

Product:

`GPM_3IMERGHH`

Version:

`07`

Purpose:

- rainfall observations
- precipitation-rate summaries
- rainfall accumulation
- antecedent rainfall context

Access:

`earthaccess`

Format:

HDF5

Important verified datasets:

```text
Grid/precipitation
Grid/precipitationQualityIndex
Grid/probabilityLiquidPrecipitation
Grid/randomError
Grid/lat
Grid/lon
Grid/time
```

Verified implementation behavior:

- `Grid/precipitation` uses `mm/hr`
- half-hour granules represent 0.5 hours
- the global raster is spatially subset to the AOI
- fill/invalid values are removed
- multiple granules are accumulated cell-by-cell
- duplicate granules are rejected
- complete-coverage fraction is tracked

## SMAP L4

Product:

`SPL4SMGP`

Version:

`008`

Purpose:

- surface soil moisture
- root-zone soil moisture
- land-state context

Access:

`earthaccess`

Format:

HDF5

Verified datasets:

```text
Geophysical_Data/sm_surface
Geophysical_Data/sm_rootzone
cell_lat
cell_lon
```

Verified metadata:

```text
sm_surface
  description: Top layer soil moisture (0-5 cm)
  units: m3 m-3
  fill: -9999
  valid range: 0.0 to approximately 0.9

sm_rootzone
  description: Root zone soil moisture (0-100 cm)
  units: m3 m-3
  fill: -9999
  valid range: 0.0 to approximately 0.9
```

SMAP uses 2D `cell_lat` and `cell_lon` arrays.

SMAP soil moisture is treated as a state observation. It is not accumulated over the rainfall interval.

## Sentinel-1 SAR

Collection:

`sentinel-1-rtc`

Phase 3B migrated production and its smoke test from raw `sentinel-1-grd`
to the calibrated, radiometrically terrain-corrected VV product. Raw GRD digital
numbers are not thresholded as calibrated backscatter.

Purpose:

- real SAR observations
- candidate surface-water evidence
- flood-related surface-water context

Current Python access:

- `pystac-client`
- `planetary-computer`
- `rasterio`

Smoke-test provider:

Microsoft Planetary Computer STAC

Verified:

- STAC search
- real scene discovery
- polarization asset discovery
- real raster access
- real SAR pixel reads

Use wording such as:

- candidate surface-water extent
- observed surface-water signal
- possible flood-related surface water

Do not automatically claim:

- confirmed flooding
- emergency flood conditions
- evacuation requirement

## Copernicus DEM GLO-30

Collection:

`cop-dem-glo-30`

Purpose:

- elevation
- terrain context
- flood-susceptibility support

Access:

- `pystac-client`
- `rasterio`

Provider used in smoke test:

Element 84 Earth Search

Verified:

- STAC search
- real GeoTIFF access
- EPSG:4326
- real elevation pixel reads

Important production requirement:

The AOI can cross multiple 1-degree tiles. Production processing must use all intersecting tiles before calculating AOI statistics.

## GLO-30 HAND

HAND:

**Height Above Nearest Drainage**

Collection:

`glo-30-hand`

Purpose:

- drainage-relative terrain context
- low-lying terrain identification
- flood-susceptibility support

Access:

- ASF STAC
- public S3 fallback
- `rasterio`

Verified:

- STAC search
- real HAND tile discovery
- real GeoTIFF access
- real HAND pixel reads

Important production requirements:

- process all intersecting tiles
- clip exactly to the requested AOI
- treat HAND as supporting evidence, not a flood detector
- tested raster exposed no explicit NoData value, so value semantics must be handled carefully

---

# Validated Real-Data Results

## GPM One-Hour Test

Study area:

Abbotsford / Sumas Prairie, British Columbia

Window:

2021-11-15 00:00 UTC to 00:59:59 UTC

Granules:

2 half-hourly granules

AOI grid:

```text
6 longitude cells
4 latitude cells
24 total pixels
24 complete-coverage pixels
```

Results:

```text
Area-mean accumulated rainfall:   approximately 6.6504 mm
Maximum cell accumulation:        approximately 15.5700 mm
Minimum cell accumulation:        approximately 2.2000 mm
Coverage fraction:                1.0
```

## SMAP Test

SMAP timestamp:

`2021-11-14T22:30:00Z`

AOI:

24 valid SMAP cells

Surface soil moisture:

```text
Mean:       approximately 0.4085 m3/m3
Minimum:    approximately 0.3692 m3/m3
Maximum:    approximately 0.4424 m3/m3
```

Root-zone soil moisture:

```text
Mean:       approximately 0.3924 m3/m3
Minimum:    approximately 0.2938 m3/m3
Maximum:    approximately 0.4363 m3/m3
```

## Hydro Worker Integration

The deterministic Hydro worker successfully combined:

```text
2 GPM IMERG granules
+
1 SMAP L4 state
=
1 structured hydrometeorology result
```

Validated compact values:

```text
status: complete

rainfall:
  area_mean_total_accumulation_mm: approximately 6.6504
  max_cell_total_accumulation_mm: approximately 15.5700
  duration_hours: 1.0
  granule_count: 2

soil_moisture:
  surface_mean_m3_m3: approximately 0.4085
  rootzone_mean_m3_m3: approximately 0.3924
  smap_timestamp_utc: 2021-11-14T22:30:00Z
```

The worker also returns:

- task ID
- worker ID
- analysis type
- AOI
- source provenance
- full deterministic evidence
- structured limitations

## Flood Worker Integration

The real-data Phase 3C run combines one calibrated Sentinel-1 RTC VV scene,
four DEM tiles and four HAND tiles over the configured Abbotsford AOI.

- candidate surface-water area: **88.0997 km²** at −17 dB
- Sentinel-1 valid AOI coverage: **97.6354%**; missing cells remain excluded
- DEM mean: **254.308864 m**, with 100% valid AOI coverage
- HAND mean: **45.452025 m**, with 100% valid AOI coverage
- strict JSON serialization and repeated processing: **PASS**

Processing completion does not mean complete SAR coverage. The selected scene
has a southern missing-data strip. Terrain statistics cover the whole AOI;
they are not terrain measurements restricted to candidate-water pixels.
The worker performs no common-grid overlay, water-depth calculation, flood
confirmation or severity classification. See the [terminal checkpoint](docs/phase3c-validation.md).

## Worker API Integration

The Phase 4 terminal checkpoint runs temporary Hydro and Flood servers on
loopback and processes real resources through `POST /tasks`, task/status polling,
and result retrieval. Results reproduce the values above; typed JSON round trips,
authentication rejection and idempotent task retries passed. Processing times
and provenance are recorded in the ignored JSON report.

Run:

```sh
.venv/bin/python -m scripts.validate.validate_worker_apis --download-hydro
```

The download option uses an existing local Earthdata login. See the
[Phase 4 commands and API contract](docs/phase4-validation.md) for setup and
resource options. The API retains one active task and bounded completed history
per process. Use one Uvicorn process per worker; registry state is in memory and
is lost on restart. These local checks do not establish remote or parallel
execution. No new HTML/manual visual review is needed for this phase.

---

# Automated Tests

Current full test suite:

**390 tests passing**

Run:

```powershell
python -m pytest -v
```

## GPM Tests

- single-granule rainfall calculation
- half-hour rate-to-accumulation conversion
- multi-granule accumulation
- fill-value exclusion
- invalid-bbox rejection
- duplicate-granule rejection

## SMAP Tests

- deterministic surface/root-zone statistics
- fill-value exclusion
- valid-range filtering
- invalid-bbox rejection
- non-intersecting AOI rejection
- timestamp extraction

## Hydro Worker Tests

- GPM + SMAP result combination
- structured result output
- missing GPM resource handling
- missing SMAP resource handling
- wrapped GPM processor failure
- wrapped SMAP processor failure
- generated task IDs

## Terrain, Sentinel-1, and Flood Worker Tests

- multi-tile clipping, masking, overlap handling and provenance
- calibrated VV power conversion, deterministic scene selection and candidate area
- partial valid coverage, threshold sensitivity and artifact consistency
- combined worker summaries, source traceability and strict JSON serialization
- component failure isolation with successful evidence retained
- terminal validation, repeatability, failure reports and stale-PASS protection
- contract serialization, finite measurements and bounded request validation
- responsive HTTP status, authentication, idempotency and result/task consistency

Existing passing tests are protected behavior. New work must not silently break them.

---

# Core Engineering Rules

1. Python calculates authoritative numerical results.
2. The LLM does not invent environmental measurements.
3. Agents choose supported investigations; they do not fabricate tools or resources.
4. MeshMind decides where work executes.
5. Workers execute bounded approved tools.
6. Deterministic code evaluates configured review conditions.
7. Do not claim emergency-response capability.
8. Do not claim disaster detection unless a validated method supports it.
9. Do not show fake progress.
10. Do not claim parallelism unless execution intervals actually overlap.
11. Do not expose API keys or credentials.
12. Do not expose internal infrastructure details in the primary UI.
13. Large downloaded geospatial datasets must not be committed.
14. Every major component must pass automated and real-data/manual validation before the next dependent layer is built.
15. Raw numerical evidence must remain traceable to source data and deterministic processing code.
16. One worker failure must not destroy valid completed work from another independent worker.
17. Existing passing code should be extended rather than rewritten without a concrete reason.

---

# Development Method

```text
IMPLEMENT
    |
    v
RUN
    |
    v
MANUAL / REAL-DATA CHECK
    |
    v
AUTOMATED TESTS
    |
    v
PASS?
 /   \
NO   YES
 |     |
FIX   COMMIT
        |
        v
      MERGE
        |
        v
   NEXT PHASE
```

Before merging any implementation branch:

```powershell
python -m pytest -v
git diff --check
git status
```

Expected:

- all tests pass
- no whitespace errors
- no secrets
- no cached geospatial data staged
- only intended code/config/test changes

---

# Repository

GitHub:

`alexwoolee/surge-fall-2026`

Primary branch:

`main`

Branch strategy:

```text
data/gpm-smoke
data/smap-smoke
data/sentinel1-smoke
data/dem-smoke
data/hand-smoke

feature/gpm-processing
feature/smap-processing
feature/hydro-worker
feature/terrain-processing
feature/sentinel1-processing
feature/flood-worker
feature/shared-contracts
feature/worker-api
feature/control-dispatch
```

Use small branches and merge tested milestones into `main`.

---

# Repository Structure

```text
MeshMind/
|
|-- README.md
|-- requirements.txt
|-- .gitignore
|-- .gitattributes
|-- .env.example
|
|-- backend/
|   |
|   |-- control/
|   |   |-- __init__.py
|   |   |-- main.py
|   |   |-- coordinator.py
|   |   |-- fusion.py
|   |   |-- alerts.py
|   |   |-- reporting.py
|   |   `-- state.py
|   |
|   |-- shared/
|   |   |-- __init__.py
|   |   |-- contracts.py
|   |   |-- settings.py
|   |   `-- status.py
|   |
|   `-- workers/
|       |
|       |-- hydro/
|       |   |-- __init__.py
|       |   |-- main.py
|       |   |-- service.py
|       |   |-- gpm.py
|       |   `-- smap.py
|       |
|       `-- flood/
|           |-- __init__.py
|           |-- main.py
|           |-- service.py
|           |-- sentinel1.py
|           |-- terrain.py
|           `-- hand.py
|
|-- scripts/
|   `-- smoke/
|       |-- smoke_gpm.py
|       |-- smoke_smap.py
|       |-- smoke_sentinel1.py
|       |-- smoke_dem.py
|       `-- smoke_hand.py
|
|-- config/
|   |-- test_case.example.json
|   `-- rules.example.json
|
|-- tests/
|   |-- fixtures/
|   |-- test_contracts.py
|   |-- test_hydro.py
|   |-- test_hydro_service.py
|   |-- test_smap.py
|   |-- test_flood.py
|   `-- test_rules.py
|
|-- data/
|   |-- cache/
|   |   `-- .gitkeep
|   |
|   `-- fixtures/
|       `-- .gitkeep
|
|-- outputs/
|   |-- debug/
|   |   `-- .gitkeep
|   |
|   `-- reports/
|       `-- .gitkeep
|
`-- docs/
    |-- architecture.md
    `-- manual-test-checklist.md
```

The frontend will be generated later with the official Next.js project generator.

---

# File Responsibilities

## Hydro Worker

### `backend/workers/hydro/gpm.py`

**Implemented**

Responsibilities:

- HDF5 validation
- AOI subsetting
- invalid/fill handling
- rainfall-rate statistics
- half-hour accumulation
- multi-granule accumulation
- coverage tracking
- duplicate-resource protection

### `backend/workers/hydro/smap.py`

**Implemented**

Responsibilities:

- HDF5 validation
- SMAP variable access
- 2D geolocation/AOI filtering
- fill handling
- valid-range filtering
- surface soil-moisture statistics
- root-zone statistics
- timestamp extraction

### `backend/workers/hydro/service.py`

**Implemented**

Responsibilities:

- validate local resources
- run GPM processor
- run SMAP processor
- combine deterministic results
- produce compact summary
- attach provenance
- attach limitations
- wrap processor failures
- manage task ID

### `backend/workers/hydro/main.py`

**Implemented**

FastAPI application factory for Laptop 2; bounded Hydro tasks resolve resource
basenames inside configured data folders before calling the existing service.

## Flood Worker

### `backend/workers/flood/terrain.py`

**Implemented**

Responsibilities:

- discover all intersecting Copernicus DEM tiles
- read only needed windows where possible
- clip exactly to AOI
- combine valid values across tile boundaries
- calculate deterministic elevation statistics
- retain source/tile provenance

### `backend/workers/flood/hand.py`

**Implemented**

Responsibilities:

- discover all intersecting HAND tiles
- support ASF STAC/public-S3 asset resolution
- read only needed windows
- clip exactly to AOI
- validate HAND values
- calculate deterministic statistics
- retain source/tile provenance

### `backend/workers/flood/sentinel1.py`

**Implemented**

Responsibilities:

- select approved Sentinel-1 scene
- validate polarization asset
- clip/read AOI
- apply documented SAR preprocessing
- derive candidate surface-water evidence
- calculate deterministic area/statistics
- record limitations

### `backend/workers/flood/service.py`

**Implemented**

Combines:

```text
Sentinel-1
    +
DEM / HAND
    |
    v
FloodResult
```

The service returns a structured dictionary containing task/worker identity,
processing status, compact summaries, full component evidence, separate coverage,
safe provenance, limitations and component errors. Successful components are
retained if another fails. The API now validates the service output with the shared Pydantic `FloodResult`
contract. Distributed execution remains Phase 5.

### `backend/workers/flood/main.py`

**Implemented**

FastAPI application factory for Laptop 3; bounded tasks discover approved
resources and invoke the existing combined Flood service.

## Shared

### `backend/shared/contracts.py`

**Implemented**

Pydantic models:

```text
AnalysisTask
HydroResult
FloodResult
WorkerStatus
TaskStatus
CombinedAnalysis
```

### `backend/shared/settings.py`

Implemented worker settings: GPM/SMAP data folders, task retention capacity, and
an optional Bearer token, read from exported `MESHMIND_*` variables.
Control now requires explicit Hydro/Flood HTTP origins, separate optional tokens,
and bounded request/task/poll timeouts. No localhost destination is chosen silently.

### `backend/shared/status.py`

Implemented task states:

```text
task_received
dataset_located
processing
preparing_result
complete
partial
failed
```

## Control

### `backend/control/main.py`

Future FastAPI entry point for Laptop 1.

### `backend/control/coordinator.py`

Planned:

- task creation
- worker selection
- dispatch
- concurrency
- result collection

### `backend/control/fusion.py`

Planned:

- validate HydroResult
- validate FloodResult
- combine grounded evidence

### `backend/control/alerts.py`

Planned deterministic analyst-review rules.

### `backend/control/reporting.py`

Planned briefing generation.

HTML first.

### `backend/control/state.py`

Planned investigation/task state.

SQLite may be used later.

---

# Smoke Tests

Smoke tests live under:

`scripts/smoke/`

Purpose:

```text
Can we find the dataset?
Can we access it?
Can Python open it?
Can we inspect real fields/assets?
Can we read real environmental values?
```

Current smoke tests:

```text
smoke_gpm.py
smoke_smap.py
smoke_sentinel1.py
smoke_dem.py
smoke_hand.py
```

All five pass.

Smoke tests are not substitutes for production processors or automated unit tests.

If a production integration changes provider, asset selection, authentication, or access behavior, update the corresponding smoke test so it still verifies the real external dependency.

---

# Roadmap

## Phase 0 — Repository Setup

**PASS**

## Phase 1 — Dataset Access

**PASS**

```text
GPM IMERG       PASS
SMAP L4         PASS
Sentinel-1 SAR  PASS
Copernicus DEM  PASS
HAND            PASS
```

## Phase 2 — Hydrometeorology Processing

**PASS**

### 2A — GPM Processor

**PASS**

### 2B — SMAP Processor

**PASS**

### 2C — Hydro Worker

**PASS**

## Phase 3 — Flood / Terrain Processing

**PASS — Phase 3C checkpoint approved by the user.**

### 3A — Terrain Processor

**PASS — user review approved.**

Required:

- all intersecting DEM tiles
- all intersecting HAND tiles
- exact AOI clipping
- deterministic statistics
- provenance
- automated tests
- real-data validation

### 3B — Sentinel-1 Processor

**PASS — user review approved; 97.6354% valid scene coverage is explicit.**

Required:

- deterministic scene selection
- SAR asset validation
- documented preprocessing
- candidate-water method
- deterministic output
- visual/manual validation
- automated tests

### 3C — Flood Worker

**PASS — terminal checks and user checkpoint approved.**

Required:

- combine surface-water evidence
- combine terrain evidence
- structured FloodResult
- limitations
- failure handling
- real-data run
- automated tests

## Phase 4 — Shared Contracts and Worker APIs

**PASS — real-data HTTP, automated tests and user checkpoint approved.**

Required:

- Pydantic contracts
- FastAPI worker entry points
- task endpoint
- status endpoint
- result serialization
- contract tests

## Phase 5 — Remote Worker Communication

**Control dispatch to three physical laptops PASS; Phase 5 accepted.**

Control on Ryan's Mac dispatched real data to Hydro on Kazi's Windows laptop and
Flood on Karan's Linux laptop over Tailscale. All three used implementation commit
`070db04`; matching worker checkouts and restarts were operator-confirmed.
Authentication, duplicate submission, host/process continuity and physical
deployment checks passed. Numerical summaries and sources exactly match the
accepted Phase 4 baseline. See [the evidence and human checkpoint](docs/phase5-validation.md#physical-laptop-validation--pending-human-acceptance).
Phase 5 validated sequential dispatch and preservation of completed evidence on
other-branch failure. Timeouts stop waiting without cancelling remote work.

Required:

- Laptop 1 calls Laptop 2
- Laptop 1 calls Laptop 3
- computation physically executes on remote laptop
- result returns to Control
- failure/timeout handling

## Phase 6 — Real Parallel Execution

**Implementation, local tests, physical remote overlap and human checkpoint PASS; Phase 6 complete.**

The `codex/parallel-dispatch` branch launches both bounded HTTP clients
concurrently. Expected branch failures/timeouts retain the other result. Workers
expose authenticated clock samples, and the validator conservatively accounts
for clock uncertainty before asserting actual execution overlap. The physical
run proved 0.227333 seconds of guaranteed overlap on `Boni` and `ARE`. Both
complete results and requests match accepted Phase 5 except for the fresh task
ID. Hydro completed first and remained intact while Flood continued. All clock,
authentication, identity, duplicate and topology checks passed. See the
[Phase 6 evidence](docs/phase6-validation.md#physical-laptop-validation--accepted).

Required:

```text
Hydro starts
Flood starts

Hydro working
Flood working
```

Execution intervals must actually overlap.

Required validation:

- timestamps prove overlap
- one branch may finish before the other
- completed branch remains complete
- worker failure does not erase independent completed work

## Phase 7 — Fusion and Review Rules

Planned:

- validate both worker results
- combine evidence
- deterministic configured review conditions

The LLM does not decide whether numerical thresholds were crossed.

## Phase 8 — OpenAI Agent Integration

Planned only after deterministic workers and distributed execution work.

The AI layer may:

- understand the request
- determine supported investigations
- request bounded tools
- summarize deterministic evidence
- generate grounded explanations

It must not:

- fabricate measurements
- replace deterministic processing
- invent unsupported causal links
- receive unrestricted remote machine control

## Phase 9 — Frontend and Report

Frontend:

- Next.js
- TypeScript
- Tailwind

Report:

HTML first.

PDF only if reliable.

## Phase 10 — Reliability and Submission

- failure tests
- reset/startup scripts
- deployment
- final README
- demo video
- submission
- pitch rehearsal

---

# Astra Handoff — Phases 3 Through 6

Astra may use this README as the project source of truth.

It must also inspect the actual existing code before modifying a component.

## Protected Existing Work

Do not rewrite the following working components without a specific technical reason:

```text
backend/workers/hydro/gpm.py
backend/workers/hydro/smap.py
backend/workers/hydro/service.py
tests/test_hydro.py
tests/test_smap.py
tests/test_hydro_service.py
```

Existing behavior must remain compatible unless an intentional migration is documented.

Baseline:

**17 tests passing**

Before every merge:

```powershell
python -m pytest -v
```

All previously passing tests must remain green.

## What Astra Must Provide for Each Phase

For each completed phase, leave behind:

1. production code in the intended repository file
2. automated tests
3. updated smoke test if external integration behavior changed
4. one real-data/manual validation command
5. a clear PASS/FAIL result from that real-data run
6. provenance in structured results
7. explicit limitations
8. failure handling
9. clean `git diff --check`
10. a branch/commit suitable for merge

Do not mark a phase complete based only on unit tests when the component depends on real geospatial data.

## Branch Guidance

Recommended:

```text
feature/terrain-processing
feature/sentinel1-processing
feature/flood-worker
feature/shared-contracts
feature/worker-api
feature/control-dispatch
feature/parallel-execution
```

## Smoke-Test Guidance

Smoke tests may be updated.

They should verify real external dependencies, not duplicate the production processor.

Keep them simple:

```text
search
access
open
inspect
read real values
PASS / FAIL
```

Production calculations belong in `backend/`.

## README Update Frequency

Do not update this README after every small commit.

Update it after major milestones such as:

- deterministic Flood worker complete
- worker HTTP communication complete
- real parallel execution complete
- agent integration complete
- final demo complete

## Phase 3 Requirements

### Terrain

Must process all intersecting DEM/HAND tiles, not just the first returned tile.

Must clip to the AOI.

Must avoid double-counting overlapping pixels.

Must return deterministic statistics and source tile provenance.

### Sentinel-1

Must use a documented, explainable candidate-water method.

Do not jump to a complex ML model unless necessary.

Must save or produce a manual visual validation artifact when practical.

Do not label all dark SAR pixels as confirmed floodwater.

### Flood Worker

Must combine deterministic terrain and Sentinel-1 outputs.

Do not invent disaster severity.

## Phase 4 Requirements

Shared Pydantic contracts must be defined before remote APIs become the dependency boundary.

Contract tests must cover serialization/deserialization.

Worker APIs must accept bounded tasks and return structured status/results.

## Phase 5 Requirements

A request from Laptop 1 must visibly trigger computation on Laptop 2 or Laptop 3.

Do not fake distribution by running all processors locally.

Record:

- task ID
- worker ID
- start time
- completion/failure state

## Phase 6 Requirements

Both worker calls must be launched concurrently.

Prove overlap using actual timestamps.

A valid demonstration looks like:

```text
18:10:03 Hydro started
18:10:03 Flood started

18:10:16 Hydro completed
18:10:31 Flood completed
```

A sequential run does not qualify.

---

# UI Direction

MeshMind should feel like a calm AI workspace, not a network-administration dashboard.

## Control Screen

Only the Control/Home screen has the sidebar.

Primary state:

```text
What do you want to investigate?

[ Prompt ]

[ Run Analysis ]
```

During execution:

```text
Hydrometeorology Agent
Working on Laptop 2

Surface Water & Terrain Agent
Working on Laptop 3
```

Each card updates independently.

## Laptop 2 Screen

```text
Hydrometeorology Agent
Executing tools on Laptop 2
```

Only show real states.

## Laptop 3 Screen

```text
Surface Water & Terrain Agent
Executing tools on Laptop 3
```

Only show real states.

Do not expose:

- IP addresses
- raw JSON
- hashes
- payload IDs
- network topology
- long logs
- fake percentages
- fake telemetry

---

# Final Report

One downloadable environmental briefing.

Initial output:

HTML

Planned sections:

- original request
- study area
- requested time window
- actual data time coverage
- rainfall observations
- soil-moisture observations
- candidate surface-water findings
- terrain context
- combined observations
- analyst-review conditions
- source provenance
- processing provenance
- limitations

Required disclaimer:

> MeshMind is an environmental analysis and analyst-support system. It is not an operational emergency-response or evacuation system.

---

# Local Data Policy

Downloaded data belongs under:

`data/cache/`

Large geospatial files are ignored by Git.

Examples used locally:

```text
data/cache/gpm_smoke/
data/cache/gpm_hour/
data/cache/smap_smoke/
```

These are not committed resources.

Small safe deterministic fixtures may go under:

`data/fixtures/`

Debug outputs:

`outputs/debug/`

Generated reports:

`outputs/reports/`

---

# Authentication and Secrets

Real credentials belong in:

`.env`

Never commit `.env`.

Current placeholders:

```text
OPENAI_API_KEY=
CONTROL_HOST=
CONTROL_PORT=
HYDRO_WORKER_URL=
FLOOD_WORKER_URL=
```

Local NASA Earthdata authentication/helper files must remain ignored:

```text
.dodsrc
.urs_cookies
.netrc
```

Never commit tokens, passwords, cookies, or signed URLs.

---

# Python Environment

Current development Python:

Python 3.12

Create:

```powershell
python -m venv .venv
```

Activate on Windows:

```powershell
.\.venv\Scripts\Activate.ps1
```

Install:

```powershell
python -m pip install -r requirements.txt
```

Current direct dependencies:

```text
earthaccess==0.19.0
h5py==3.16.0
numpy==2.5.3
planetary-computer==1.0.0
pystac-client==0.9.0
pytest==9.1.1
rasterio==1.5.2
```

Additional dependencies should only be introduced when the current implementation phase requires them.

---

# Planned Application Stack

## Frontend

- Next.js
- TypeScript
- Tailwind

## Backend

Planned:

- Python
- FastAPI
- Uvicorn
- Pydantic
- SQLite

## Worker Communication

Planned:

- HTTP
- `httpx` or equivalent

## Environmental Processing

Current:

- `earthaccess`
- `h5py`
- `numpy`
- `pystac-client`
- `planetary-computer`
- `rasterio`

Avoid heavyweight GIS infrastructure unless it materially improves reliability within the hackathon time budget.

---

# Machine Setup

Every laptop uses the same repository.

## Laptop 1

Eventually runs:

```text
backend/control/
frontend/
```

## Laptop 2

Runs:

```text
backend/workers/hydro/
```

Deterministic Hydro core is implemented.

## Laptop 3

Runs:

```text
backend/workers/flood/
```

External data access passes. Deterministic worker implementation is the current focus.

---

# Demo Language

Preferred:

> MeshMind lets an analyst ask one environmental question. Specialist investigations are dispatched in parallel to the workstations that own the approved data resources. Those machines perform the real environmental processing, return structured evidence to Control, and MeshMind validates and combines the results into one briefing.

Correct:

> The Hydrometeorology Agent is executing tools on Laptop 2.

Correct:

> The Surface Water & Terrain Agent is executing tools on Laptop 3.

Incorrect:

> The OpenAI model is running locally on Laptop 2.

Incorrect:

> MeshMind detected a disaster.

The cloud AI layer and physical worker execution must not be confused.

---

# Current Progress Tracker

## DONE

- project concept
- three-machine architecture
- worker split
- environmental dataset selection
- UI direction
- test-gated development workflow
- GitHub repository structure
- Python environment
- NASA Earthdata authentication
- GPM data access
- SMAP data access
- Sentinel-1 data access
- Copernicus DEM access
- HAND access
- deterministic GPM processor
- multi-granule GPM accumulation
- deterministic SMAP processor
- deterministic Hydro worker
- real-data Hydro integration
- multi-tile DEM and HAND processors
- calibrated Sentinel-1 candidate-water processor
- combined deterministic Flood worker
- real-data Flood integration and repeatability
- shared task/result/status contracts
- both worker HTTP APIs with local real-data validation
- Control HTTP dispatch, bounded timeouts, host/process continuity and independent failure records
- 758 automated tests passing on macOS
- concurrent Control clients, authenticated clock observations and conservative overlap checks

## TESTED

- Git ignore rules
- real GPM HDF5 processing
- GPM AOI subsetting
- GPM fill handling
- GPM multi-granule accumulation
- real SMAP HDF5 processing
- SMAP AOI filtering
- SMAP fill/range validation
- combined Hydro worker
- worker resource/failure handling
- real Sentinel-1 SAR access
- real Copernicus DEM raster access
- real HAND raster access
- terrain multi-tile clipping and statistics
- Sentinel-1 candidate-water visual review
- combined Flood worker JSON, provenance and component-failure handling
- local real-data Hydro/Flood HTTP task, status and result endpoints
- request bounds, authentication, duplicate handling and capacity limits
- Control dispatch over local HTTP using real NASA and public raster evidence
- strict remote-response validation, ambiguous submissions, deadlines and branch preservation

## PHASE 5 ACCEPTED

The Phase 5 physical-laptop validator returned **PASS / PENDING_USER** for task
`64807cc5-4637-477d-80d6-f8c043ee368a`. Hydro completed on `Boni` and Flood on `ARE`;
23 reference checks passed, including exact complete-summary and source matches.
Kazi's final Windows rerun at `070db04` passed: 617 tests and 1 expected
symlink-privilege skip. The user supplied Karan's matching poll/result logs, and
Kazi confirmed completion on his Windows laptop and accepted the Hydro portion.
Kazi also reported resyncing his clock; the later Phase 6 run measured stable
clock bounds successfully. The user's conditional approval to proceed once all Phase 5 tests pass
has been satisfied: the physical run, numerical comparisons, local TCP
failure/timeout tests, automated suites and worker confirmations all passed.
Phase 5 is accepted; clock agreement and overlap belong to Phase 6.

## PHASE 6 COMPLETE

The physical-laptop validator returned **PASS / PENDING_USER** for investigation
`f1f4cc63-1b2c-4a29-a924-f3c7490b554f`. Guaranteed execution overlap was 0.227333
seconds. A live status snapshot captured Hydro complete while Flood was still
processing; both results exactly match Phase 5. Kazi reported 757 Windows tests
passed plus one expected skip, and Karan reported his Linux tests passed.
The user subsequently confirmed both owners observed this investigation's
activity, completing the remaining manual check. The Phase 6 checkpoint is
complete. The raw validator report retains its original `PASS / PENDING_USER`;
the later human confirmation is recorded separately. No later phase has started.

## NEXT

**Requested scope complete through Phase 6. Await further instructions.**

## CUT FOR NOW

Until deterministic workers and distributed execution are complete:

- frontend implementation
- OpenAI agent implementation
- optional sponsor integrations
- unnecessary dashboards
- fake telemetry
- unsupported disaster predictions
- complex ML flood models
