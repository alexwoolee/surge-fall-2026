# MeshMind
MeshMind is a multi-agent, multi-workstation environmental intelligence system.
One natural-language request launches specialist investigations across approved environmental data systems. Real Python processing executes on separate workstations, structured results return to Control, deterministic validation and review rules are evaluated, and MeshMind produces one combined downloadable briefing.
---
# Current Status
Last reviewed: 2026-10-03.

The active checkpoint is **Phase 2 — GPM regression fixes and manual recheck**.
The previous Phase 1 and Phase 2 manual checks were reported complete; Phase 3
was only partially checked. The current GPM changes require another real-data
check before the Phase 2 gate can close.

| Phase | Implementation | Test gate |
| --- | --- | --- |
| 0 — Repository setup | Complete | Repository and ignore rules checked |
| 1 — Dataset access | All five smoke scripts exist | Prior real-data PASS reported; not rerun on this checkout |
| 2 — GPM | Temporal filtering and validity fixes complete | 35 processor tests + 14 CLI/download tests pass; manual recheck pending |
| 3 — SMAP | Existing processor and tests | Manual check incomplete; audit follow-ups pending |
| 4 — Hydro worker | Existing local-file service and tests | Independent real-data integration check pending |
| 5 — DEM / HAND | Placeholder files | Not started |
| 6 — Sentinel-1 | Placeholder file | Not started; visual inspection required |

The remaining phases are planned, not implemented. Phase 4 currently returns a
Python dictionary; shared Pydantic contracts and HTTP endpoints are later phases.

Latest automated run: **61 passed** with `.venv/bin/python -m pytest -q` on
2026-10-03 (Python 3.12). This includes the existing SMAP and hydro-service tests.
Live dataset tests were not rerun; manual Phase 2 approval remains open.
Work is paused at this checkpoint pending the incoming repository update and
the user's signal to resume.

## Current constraints
- This checkout has no cached real GPM or SMAP granules.
- Python 3.12 or newer is required by the pinned hydro dependencies.
- On this Mac, the full dependency install stops at `rasterio==1.5.2` because
  a local GDAL build is required. Hydro tests can run independently with
  `requirements-hydro.txt`; the GIS setup must be resolved before terrain work.

## Next checkpoint
Run the Phase 2 regression suite and the real-data review in
[`docs/manual-test-checklist.md`](docs/manual-test-checklist.md), then report
PASS or the discrepancy. Do not advance dependent work until that gate passes.

## Phase 1 Result
**PASS**
Verified integrations:
- GPM IMERG V07 through NASA `earthaccess`
- SMAP L4 through NASA `earthaccess`
- Sentinel-1 GRD through STAC
- Copernicus DEM GLO-30 through STAC
- GLO-30 HAND through ASF STAC/public S3
Verified capabilities:
- Earthdata authentication
- STAC search
- real granule/scene discovery
- real HDF5 downloads
- HDF5 variable inspection
- remote Cloud Optimized GeoTIFF access
- real raster pixel reads
- elevation-value inspection
- HAND-value inspection
Important implementation findings:
- GPM granules are global and must be spatially subset to the requested AOI.
- SMAP processing must use the actual discovered geophysical soil-moisture variables.
- Sentinel-1 scenes contain real SAR polarization raster assets and require proper preprocessing before candidate-water classification.
- DEM and HAND AOIs may span multiple 1-degree tiles.
- Production terrain processing must handle all intersecting tiles and clip results to the requested AOI.
- HAND returned no explicit NoData value in the tested raster, so value semantics must be validated before production statistics are trusted.
# Project Goal
The core demonstration is:
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
The project must demonstrate real distributed work.
We should not claim multiple laptops are required because these small hackathon datasets need extra compute.
The reason for multiple machines is that different systems can own different approved data resources, permissions and processing capabilities.
---
# System Architecture
```text
                         USER
                          |
                          v
                 LAPTOP 1 - CONTROL
                          |
                          |
             +------------+------------+
             |                         |
             v                         v
     LAPTOP 2 - HYDRO          LAPTOP 3 - FLOOD
           WORKER                    WORKER
             |                         |
       +-----+-----+            +------+------+
       |           |            |             |
   GPM IMERG    SMAP L4    Sentinel-1      Terrain
                                             |
                                         DEM + HAND
       |                                   |
       v                                   v
   HydroResult                        FloodResult
       |                                   |
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
## Laptop 1 - Control
Laptop 1 is the MeshMind coordinator.
Responsibilities:
- main application UI
- natural-language user request
- OpenAI agent orchestration
- task creation
- worker selection
- task dispatch
- parallel execution coordination
- worker-state tracking
- structured result collection
- result validation
- evidence fusion
- deterministic analyst-review rules
- report generation
- history
- application state
Laptop 1 should not use the LLM to calculate authoritative environmental measurements.
Python processing produces the numerical results.
---
## Laptop 2 - Hydrometeorology Worker
Laptop 2 owns the hydrometeorological investigation.
Approved resources:
- GPM IMERG
- SMAP L4
Responsibilities:
- search approved rainfall data
- search approved soil-moisture data
- read real environmental observations
- filter data to the requested area and time period
- calculate deterministic statistics
- return structured findings to Control
Primary result:
`HydroResult`
---
## Laptop 3 - Surface Water and Terrain Worker
Laptop 3 owns the surface-water and terrain investigation.
Approved resources:
- Sentinel-1 SAR
- Copernicus DEM
- HAND
Responsibilities:
- search Sentinel-1 scenes
- read SAR data
- derive candidate surface-water observations
- read terrain data
- calculate deterministic terrain metrics
- return structured findings to Control
Primary result:
`FloodResult`
---
# Environmental Data Sources
## 1. GPM IMERG
Purpose:
- rainfall observations
- precipitation accumulation
- rainfall intensity summaries
- antecedent rainfall context
Python access:
`earthaccess`
Planned worker:
Laptop 2
---
## 2. SMAP L4
Purpose:
- surface soil moisture
- root-zone soil moisture where appropriate
- land-state context
Python access:
`earthaccess`
Planned worker:
Laptop 2
---
## 3. Sentinel-1 SAR
Purpose:
- surface-water observations
- candidate flood-related water extent
Python access:
`pystac-client`
Planned worker:
Laptop 3
Important wording:
Use:
- candidate surface-water extent
- observed surface-water signal
- possible flood-related surface water
Do not automatically claim:
- confirmed flooding
- emergency flood conditions
- evacuation requirement
unless the data and implemented method genuinely support those conclusions.
---
## 4. Copernicus DEM
Purpose:
- elevation
- terrain context
- supporting flood-susceptibility analysis
Planned worker:
Laptop 3
---
## 5. HAND
HAND means:
**Height Above Nearest Drainage**
Purpose:
- drainage-relative terrain context
- low-lying terrain identification
- supporting flood-susceptibility context
Planned worker:
Laptop 3
HAND should be treated as supporting terrain evidence rather than an automatic flood detector.
---
# Core Engineering Rules
1. Python calculates authoritative numerical results.
2. The LLM does not invent rainfall, soil-moisture, surface-water or terrain measurements.
3. Agents determine what supported investigation is required.
4. MeshMind determines where the investigation executes.
5. Workers execute bounded approved tools.
6. Deterministic code decides whether configured analyst-review conditions are triggered.
7. Do not claim emergency-response capability.
8. Do not claim disaster detection unless the implemented system genuinely supports that conclusion.
9. Do not display fake progress.
10. Do not claim parallel execution unless the two worker jobs actually overlap in time.
11. Do not expose API keys.
12. Do not expose unnecessary infrastructure details in the primary UI.
13. Large downloaded geospatial datasets must not be committed to Git.
14. Every major component must pass testing before dependent functionality is built on top of it.
---
# Development Method
Every major phase follows the same process:
```text
IMPLEMENT
    |
    v
RUN
    |
    v
MANUALLY CHECK
    |
    v
PASS?
 /   \
NO   YES
 |     |
FIX   NEXT PHASE
```
Do not continue building dependent components when the current component has not passed its test gate.
---
# Repository Structure
```text
MeshMind/
|
|-- README.md
|-- .gitignore
|-- .env.example
|
|-- backend/
|   |
|   |-- control/
|   |   |-- __init__.py
|   |   |-- main.py
|   |   |-- coordinator.py
|   |   |-- fusion.py
|   |   |-- alerts.py
|   |   |-- reporting.py
|   |   `-- state.py
|   |
|   |-- shared/
|   |   |-- __init__.py
|   |   |-- contracts.py
|   |   |-- settings.py
|   |   `-- status.py
|   |
|   `-- workers/
|       |
|       |-- hydro/
|       |   |-- __init__.py
|       |   |-- main.py
|       |   |-- service.py
|       |   |-- gpm.py
|       |   `-- smap.py
|       |
|       `-- flood/
|           |-- __init__.py
|           |-- main.py
|           |-- service.py
|           |-- sentinel1.py
|           |-- terrain.py
|           `-- hand.py
|
|-- scripts/
|   `-- smoke/
|       |-- smoke_gpm.py
|       |-- smoke_smap.py
|       |-- smoke_sentinel1.py
|       |-- smoke_dem.py
|       `-- smoke_hand.py
|
|-- config/
|   |-- test_case.example.json
|   `-- rules.example.json
|
|-- tests/
|   |-- fixtures/
|   |-- test_contracts.py
|   |-- test_hydro.py
|   |-- test_flood.py
|   `-- test_rules.py
|
|-- data/
|   |-- cache/
|   |   `-- .gitkeep
|   |
|   `-- fixtures/
|       `-- .gitkeep
|
|-- outputs/
|   |-- debug/
|   |   `-- .gitkeep
|   |
|   `-- reports/
|       `-- .gitkeep
|
`-- docs/
    |-- architecture.md
    `-- manual-test-checklist.md
```
The frontend will be generated later with the Next.js project generator rather than creating placeholder frontend files manually.
---
# File Responsibilities
## `backend/control/main.py`
FastAPI entry point for Laptop 1.
Eventually responsible for exposing Control application endpoints.
---
## `backend/control/coordinator.py`
Responsible for:
- investigation creation
- worker selection
- task dispatch
- parallel worker execution
- result collection
- execution coordination
---
## `backend/control/fusion.py`
Responsible for combining validated environmental evidence from:
- `HydroResult`
- `FloodResult`
The fusion layer must remain grounded in actual worker results.
---
## `backend/control/alerts.py`
Contains deterministic analyst-review rules.
Examples may eventually use evidence such as:
- rainfall
- soil moisture
- observed candidate surface water
- HAND
- elevation
Configured thresholds must be clearly identified as review criteria rather than universal scientific disaster thresholds.
---
## `backend/control/reporting.py`
Generates the final downloadable briefing.
Initial preferred format:
HTML
PDF can be added later if reliable.
---
## `backend/control/state.py`
Tracks application state including:
- investigations
- worker tasks
- task status
- worker status
- completed results
- failures
SQLite may be integrated here or separated later if required.
---
# Hydrometeorology Worker Files
## `backend/workers/hydro/main.py`
FastAPI entry point for Laptop 2.
---
## `backend/workers/hydro/service.py`
Coordinates the Laptop 2 hydrometeorology workflow.
Expected flow:
```text
Task Received
     |
     +--> GPM analysis
     |
     +--> SMAP analysis
     |
     v
HydroResult
```
---
## `backend/workers/hydro/gpm.py`
Responsible for:
- GPM search
- data access
- file reading
- area/time filtering
- precipitation calculations
- deterministic rainfall output
---
## `backend/workers/hydro/smap.py`
Responsible for:
- SMAP search
- data access
- file reading
- area/time filtering
- soil-moisture calculations
- deterministic soil-state output
---
# Flood Worker Files
## `backend/workers/flood/main.py`
FastAPI entry point for Laptop 3.
---
## `backend/workers/flood/service.py`
Coordinates the Laptop 3 surface-water and terrain workflow.
Expected flow:
```text
Task Received
     |
     +--> Sentinel-1 analysis
     |
     +--> DEM analysis
     |
     +--> HAND analysis
     |
     v
FloodResult
```
---
## `backend/workers/flood/sentinel1.py`
Responsible for:
- Sentinel-1 discovery
- scene selection
- raster reading
- SAR preprocessing required by the selected method
- candidate surface-water processing
- deterministic output
---
## `backend/workers/flood/terrain.py`
Responsible for:
- Copernicus DEM access
- raster reading
- AOI clipping
- elevation calculations
- terrain context
---
## `backend/workers/flood/hand.py`
Responsible for:
- HAND data access
- raster reading
- AOI clipping
- HAND calculations
- drainage-relative terrain context
---
# Shared Files
## `backend/shared/contracts.py`
Contains shared Pydantic contracts.
Expected models include:
- `AnalysisTask`
- `HydroResult`
- `FloodResult`
- `WorkerStatus`
- `CombinedAnalysis`
All three laptops must agree on these structures.
---
## `backend/shared/settings.py`
Contains shared application settings.
Examples:
- Control host
- Control port
- worker URLs
- environment configuration
- local paths
Secrets should be loaded from environment variables rather than committed files.
---
## `backend/shared/status.py`
Contains standardized states for:
- investigations
- worker tasks
- worker availability
- processing progress
Only real backend states should be exposed to the UI.
---
# Smoke Test Scripts
The first executable project code will live in:
`scripts/smoke/`
These scripts are deliberately small and independent.
Their purpose is to answer:
```text
Can we find the dataset?
Can we access it?
Can Python open it?
Can we inspect real fields or assets?
Does the chosen area/time window return usable data?
```
They should not contain:
- OpenAI agent orchestration
- FastAPI worker logic
- frontend logic
- fusion logic
- alert rules
---
# Phase 0 - Repository Setup
## Status
**DONE**
## Completed
- Git repository initialized and pushed to GitHub
- folders and placeholder files created
- `.gitignore`, `.gitattributes`, `.env.example`, and README created
- folder structure and ignore rules checked
- initial Git commit exists

## Pass Criteria
Phase 0 passes when:
- repository structure exists
- README is readable
- `.gitignore` works
- `.env` is ignored
- cache files are ignored
- generated debug files are ignored
- initial commit exists
- working tree is clean
---
# Phase 1 - Dataset Access Smoke Tests
Each data source is tested independently before any complete environmental analysis pipeline is built.
Required scripts:
```text
scripts/smoke/smoke_gpm.py
scripts/smoke/smoke_smap.py
scripts/smoke/smoke_sentinel1.py
scripts/smoke/smoke_dem.py
scripts/smoke/smoke_hand.py
```
## Gate
```text
GPM IMERG       PASS (prior real-data manual run)
SMAP L4         PASS (prior real-data manual run)
Sentinel-1      PASS (prior real-data manual run)
Copernicus DEM  PASS (prior real-data manual run)
HAND           PASS (prior real-data manual run)
```
For a source to PASS, we must confirm:
- search works
- access works
- Python can open the data
- actual variables/assets can be inspected
- AOI intersects the source
- requested time range is valid where applicable
---
# Phase 2 - GPM Processing
File:
`backend/workers/hydro/gpm.py`
Goal:
Build deterministic rainfall processing.
Tests should cover:
- AOI filtering
- temporal filtering
- valid-data handling
- missing-data handling
- precipitation statistics
- repeatable output
---
# Phase 3 - SMAP Processing
File:
`backend/workers/hydro/smap.py`
Goal:
Build deterministic soil-moisture processing.
Tests should cover:
- correct variables
- timestamps
- fill values
- AOI extraction
- valid-pixel handling
- deterministic statistics
---
# Phase 4 - Hydrometeorology Worker
Directory:
`backend/workers/hydro/`
Pipeline:
```text
GPM
 +
SMAP
 |
 v
HydroResult
```
## Gate
Laptop 2 must be able to independently produce a structured `HydroResult` without:
- OpenAI
- frontend
- Laptop 1 orchestration
---
# Phase 5 - Terrain Processing
Files:
```text
backend/workers/flood/terrain.py
backend/workers/flood/hand.py
```
Validate:
- CRS
- raster bounds
- AOI overlap
- no-data values
- elevation values
- HAND values
Debug maps may be created under:
`outputs/debug/`
---
# Phase 6 - Sentinel-1 Processing
File:
`backend/workers/flood/sentinel1.py`
Goal:
Create a deterministic candidate surface-water result from an approved Sentinel-1 scene.
Manual visual inspection is required.
The initial method should favor reliability and explainability over unnecessary complexity.
---
# Phase 7 - Flood / Terrain Worker
Directory:
`backend/workers/flood/`
Pipeline:
```text
Sentinel-1
     +
DEM + HAND
     |
     v
FloodResult
```
## Gate
Laptop 3 must independently produce a structured `FloodResult` without:
- OpenAI
- frontend
- Laptop 1 orchestration
---
# Phase 8 - Shared Contracts
File:
`backend/shared/contracts.py`
Expected contracts:
```text
AnalysisTask
HydroResult
FloodResult
WorkerStatus
CombinedAnalysis
```
Tests must verify serialization and deserialization.
---
# Phase 9 - Worker HTTP Communication
Technology:
FastAPI
Laptop 2 and Laptop 3 will expose bounded worker operations.
Manual test:
A request initiated from Laptop 1 must visibly cause real Python processing to execute on the selected remote laptop.
---
# Phase 10 - Real Parallel Execution
Laptop 1 dispatches both investigations concurrently.
Expected behavior:
```text
Hydro started
Flood started
Hydro working
Flood working
```
Their execution intervals must overlap.
Sequential execution does not count as parallelism.
---
# Phase 11 - Fusion and Analyst Review Rules
Files:
```text
backend/control/fusion.py
backend/control/alerts.py
```
Control:
1. validates both structured results
2. combines evidence
3. evaluates deterministic review conditions
The LLM does not decide whether numerical thresholds were crossed.
---
# Phase 12 - OpenAI Agent Integration
OpenAI integration is added only after the deterministic worker pipeline functions.
The AI layer may:
- understand the user request
- determine which supported investigations are required
- request bounded application tools
- summarize structured findings
- produce grounded explanations
The AI layer must not:
- invent environmental measurements
- fabricate dataset results
- calculate authoritative statistics instead of Python
- invent unsupported causal relationships
- secretly execute unrestricted operations on worker machines
---
# Phase 13 - Frontend
Planned stack:
- Next.js
- TypeScript
- Tailwind
The frontend will be generated later using the official Next.js project setup.
## Control Screen
Only the main Control/Home screen has the navigation sidebar.
Expected primary state:
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
Each agent card updates independently.
## Worker Screens
Laptop 2:
```text
Hydrometeorology Agent
Executing tools on Laptop 2
```
Laptop 3:
```text
Surface Water & Terrain Agent
Executing tools on Laptop 3
```
Worker screens should remain simple live-status pages.
Do not expose on primary screens:
- IP addresses
- raw JSON
- internal hashes
- payload IDs
- network topology
- long logs
- fake percentages
- unnecessary telemetry
---
# Phase 14 - Final Report
Generate one downloadable environmental briefing.
Start with HTML.
The report should include:
- original request
- study area
- requested time window
- actual data time coverage
- rainfall observations
- soil-moisture observations
- candidate surface-water findings
- terrain context
- combined observations
- triggered analyst-review conditions
- source provenance
- processing provenance
- limitations
Disclaimer:
MeshMind is an environmental analysis and analyst-support system.
It is not an operational emergency-response or evacuation system.
---
# Phase 15 - Failure Testing
Required manual tests include:
- Laptop 2 offline
- Laptop 3 offline
- invalid AOI
- no matching GPM observations
- no matching SMAP observations
- no suitable Sentinel-1 scene
- DEM access failure
- HAND access failure
- unreadable raster
- worker timeout
- OpenAI unavailable
- coordinator restart
One worker failing must not destroy valid completed work from another worker.
---
# Local Data Policy
## Downloaded Data
Temporary downloaded environmental data belongs in:
`data/cache/`
Large files in this directory are ignored by Git.
---
## Test Fixtures
Small deterministic test data may be stored in:
`data/fixtures/`
Only small files appropriate for source control should be committed.
---
## Debug Outputs
Manual verification images belong in:
`outputs/debug/`
Examples:
- rainfall visualization
- soil-moisture visualization
- Sentinel-1 input image
- candidate water mask
- DEM visualization
- HAND visualization
Generated debug files are ignored by Git.
---
## Reports
Generated MeshMind briefings belong in:
`outputs/reports/`
Generated reports are ignored by Git.
---
# Environment Files
`.env.example` documents expected configuration variables.
Real credentials belong in:
`.env`
`.env` must never be committed.
Current placeholder variables include:
```text
OPENAI_API_KEY=
CONTROL_HOST=
CONTROL_PORT=
HYDRO_WORKER_URL=
FLOOD_WORKER_URL=
```
Additional variables will be added only when integrations require them.
---
# Machine Setup Strategy
Every laptop uses the same Git repository.
## Laptop 1
Runs:
```text
backend/control/
frontend/
```
## Laptop 2
Runs:
```text
backend/workers/hydro/
```
## Laptop 3
Runs:
```text
backend/workers/flood/
```
Separate repositories are not required.
---
# Technology Stack
## Frontend
Planned:
- Next.js
- TypeScript
- Tailwind
## Backend / Coordinator
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
## Environmental Data
Planned:
- `earthaccess`
- `pystac-client`
- raster-processing libraries selected during implementation
Additional packages should only be added when they meaningfully simplify implementation.
Avoid unnecessary heavyweight GIS infrastructure.
---
# Demo Language
Preferred explanation:
> MeshMind lets an analyst ask one environmental question. Specialist investigations are dispatched in parallel to the workstations that own the approved data resources. Those machines perform the real environmental processing, return structured evidence to Control, and MeshMind validates and combines the results into one briefing.
Correct:
> The Hydrometeorology Agent is executing tools on Laptop 2.
Incorrect:
> The OpenAI model is running locally on Laptop 2.
The cloud AI layer and the physical worker execution must not be confused.
---
# Current Progress Tracker
The table under **Current Status** is the authoritative phase tracker.

## Verification commands
Use Python 3.12 or newer. From the repository root:

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements-hydro.txt
.venv/bin/python -m pytest -q
```

The automated tests use small synthetic fixtures. They do not prove NASA or
STAC access, validate a real scene visually, or close a manual phase gate.
The full geospatial dependency set remains in `requirements.txt`.

## Remaining work through Phase 6
1. Recheck Phase 2 GPM results after the regression fixes.
2. Finish Phase 3 timestamp, fill-value, invalid-file, shape, and determinism checks;
   manually inspect real SMAP output.
3. Verify Phase 4 using the actual processors and real local files on Laptop 2.
4. Resolve GIS dependencies; implement and test Phase 5 DEM/HAND handling of all
   intersecting tiles, AOI clipping, CRS, coverage, and value semantics; inspect results.
5. Implement and test Phase 6 Sentinel-1 preprocessing and candidate-water output;
   visually inspect the input scene and derived mask.

Each gate follows IMPLEMENT → RUN → MANUALLY CHECK → PASS or FIX.

## CUT FOR NOW
Until the core pipeline works:
- frontend implementation
- OpenAI agent implementation
- complex ML flood models
- elaborate GIS infrastructure
- optional sponsor integrations
- unnecessary dashboards
- fake telemetry
- unsupported disaster predictions
