# MeshMind

MeshMind is a multi-agent, multi-workstation environmental intelligence system.

MeshMind runs bounded environmental investigations on separate workstations and returns structured results to Control for deterministic validation and review. Phase 9 connects natural-language requests and the existing frontend to those results and produces a downloadable combined briefing. Its implementation, automated checks, live browser validation and six manual checks passed. Phase 9 is accepted and merged into `codex/parallel-dispatch`.

> MeshMind is an environmental analysis and analyst-support system. It is not an operational emergency-response, evacuation, or disaster-detection system.

---

# Continue on Another Laptop — Start Here

**Handoff updated October 4, 2026 (America/Vancouver).** Kazi Boni Amin is moving
development to a friend's laptop/Codex session. This README is the continuation
brief; inspect the actual code and applicable `AGENTS.md` files before editing.
The original handoff did not accept Phase 7. After the Mac review below, the
user explicitly instructed **“proceed”** on October 4, accepting this checkpoint
and authorizing the accepted phase merge and Phase 8. Historical raw reports
retain their original `PENDING_USER` status.
The user subsequently authorized Phase 9 if the grounded explanation passed
review and requested the identified completeness fixes. Those fixes and the
offline evidence review now pass, satisfying that condition and accepting
Phase 8. This records the current user's conditional authorization, not a new
worker-owner confirmation, physical-laptop run or API test.
On October 4 the user reported **“all passed”** for all six Phase 9 manual checks,
accepting the integrated UI and downloaded briefing. That acceptance is recorded
separately from the original raw reports, whose historical statuses are unchanged.

## Exact checkpoint and branches

| Work | Verified state at handoff | Where to find it |
| --- | --- | --- |
| Phases 1–6 backend | Implemented, real-data validated, human accepted | `origin/codex/parallel-dispatch` at `b8a74b698ce476a90b5418aab65f4fd53678e61d` |
| Phase 7 implementation | Implemented, validated and human accepted October 4 | `origin/codex/fusion-review`; tested implementation `ea4f322ae2c4359a3dfb807365e389056e1f6830`, followed by this README handoff |
| Phase 7 pull request | **Merged** into `codex/parallel-dispatch` at `0aa918f`; historical draft metadata remains | [PR #1](https://github.com/alexwoolee/surge-fall-2026/pull/1) |
| Existing frontend | Original design and history preserved in the Phase 9 integration | `origin/kazi/frontend-ui` at `5ae2919ff551848b7abae1119f17ca4b992acd5d`, merged at `5770c49` |
| `main` | Behind the accepted backend work | **Do not use it as the continuation base** |
| Phase 8 | Accepted after the requested explanation fixes and completeness review; merged into `codex/parallel-dispatch` | Tested implementation `25e48d57eabc942184892cbdb5fb009bd6da487f` on `codex/agent-integration`; [Phase 8 checkpoint](docs/phase8-validation.md) |
| Phase 9 | All technical and six manual checks PASS; human accepted October 4 and merged into `codex/parallel-dispatch` | Tested implementation `ccd0de8932e2f26351cf939d714173797b9bbeeb` on `codex/briefing-integration`; [Phase 9 checkpoint](docs/phase9-validation.md) |
| Phase 10 | Not implemented | Reliability, final demo and submission work remains |

Fetch and verify this snapshot against the remote before acting; another owner
may have advanced it. README-only commits after `ea4f322` do not represent a new
implementation test run. `main` has not been pushed or merged during this lane.
GitHub's draft label is a review state, and the PR's zero hosted checks is not
evidence that the locally run tests failed.

## What has actually been completed

- **Phases 1–3:** real access to GPM IMERG, SMAP L4, Sentinel-1 RTC, Copernicus
  DEM and HAND; deterministic Hydro and Flood processing, coverage/provenance,
  multi-tile terrain, partial-component preservation and real-data validation.
- **Phase 4:** Pydantic contracts and bounded authenticated worker HTTP APIs;
  task/status/result handling, duplicate-submission behavior and local real-data
  HTTP checks. Each worker has one Uvicorn process and an in-memory registry.
- **Phase 5:** Control dispatched to Hydro on Kazi's Windows laptop and Flood on
  Karan's Linux laptop. Authentication, deployment, duplicate handling and result
  comparisons passed; both owners' activity/acceptance was recorded.
- **Phase 6:** concurrent dispatch and calibrated clock bounds proved **0.227333
  seconds of guaranteed execution overlap** for task
  `f1f4cc63-1b2c-4a29-a924-f3c7490b554f`. Both results matched Phase 5; human
  confirmation completed the phase. Tested implementation: `7bde416`.
- **Phase 7:** strict evidence fusion, explicit configurable review rules,
  offline JSON replay, optional Control `--rules` integration, input binding,
  atomic output and failure preservation. Missing data is unavailable or
  `not_assessable`, never fabricated zero. Kazi selected **clearly labeled
  demonstration thresholds**, not a validated severity policy.
- **Phase 8:** bounded Responses API interpretation and validated fact selection;
  Python-rendered explanations now always include all eight measurements, all
  review outcomes, study-area/time/coverage context, source products, processing
  methods and scientific limits. Radar sensitivity is checked before display.
  Original request retention requires the explicit local `--include-request`
  opt-in and labels that text as untrusted context, not environmental evidence.
- **Frontend lane:** Home, history/search, investigation/worker views, complete,
  partial and failed outcomes, bounded demo retry and an HTML briefing demo are
  implemented. Its activity/timing/measurements are explicitly labeled fixtures;
  browser-local storage is not live distributed state. Existing frontend checks
  historically recorded 12 tests, lint and production build passing. Phase 9
  now preserves that design with real Control integration and a verified download.

**Historical Phase 8 verification:** macOS Python 3.12.14, **1,239 passed**, zero
failures/skips; dependency and diff checks pass. All nine offline completeness
checks pass against retained real evidence. Controlled API-failure replay keeps
the same measurements and review outcomes. The earlier live `gpt-5.4-mini` check
passed (three requests, estimated $0.0037 USD); the model catalog and API boundary
are unchanged, and the rendering fixes required no new API requests or worker
dispatches. Phase 8 is accepted under the user's conditional authorization; see
[Phase 8 validation](docs/phase8-validation.md). The downloadable standalone
HTML briefing and actual browser download now pass the Phase 9 checks below.

**Current Phase 9 verification:** Mac Control Python 3.12.14, **1,327 passed**;
frontend **25 passed**, lint and production build passed. Both physical workers
passed authenticated checks and completed browser-submitted investigation
`ad711f78-ae40-4c31-b5ee-1c5a68551f51`. All eight measurements and all five review
outcomes match the accepted reference. The UI observed independent worker
completion, kept source-coverage limits visible, and downloaded the standalone
briefing successfully. Saved history and identical briefing bytes survived a
Control restart. All 16 comparison/export/restart checks passed. See
[Phase 9 evidence and human review steps](docs/phase9-validation.md).
**Phase 9 accepted October 4:** the user reported “all passed” for all six manual
checks, including the downloaded HTML visual review. The accepted implementation
is merged into `codex/parallel-dispatch`; Phase 10 has not started.

**Historical Phase 7 verification:** Windows Python 3.12, **906 passed and 1 expected
symlink-privilege skip**; `pip check` and `git diff --check` passed. Independent
code review and manual artifact QA found no outstanding issues. This is the
Phase 7 Windows result, not a claim that Phase 7 was tested on every OS. The
accepted Phase 6 baseline was 758 passing tests on macOS and 757 plus the expected
skip on Windows; Karan reported the Linux suite passed at that phase.

**Historical Phase 7 real evidence:** local execution of the accepted processors returned
complete typed Hydro/Flood results for task
`b0e3a0d4-3152-434e-8159-61f6b805e10a`. All 15 reference checks matched. The demo
policy produced **4 triggered, 1 not triggered, 0 not assessable**. Four controlled
omissions (Hydro, Flood, both, Sentinel component only) preserved valid independent
evidence. This is local real processing and offline review, not a new physical
remote run or overlap proof. Full values, methods and limitations are in
[the Phase 7 validation record](docs/phase7-validation.md).

## First steps on the friend's laptop

Prefer a separate development checkout. Leave any running Control/worker checkout,
private environment files, cached datasets and unrelated local edits intact.
Use an unused destination directory; do not reset an existing checkout to make
these commands succeed.

Fresh checkout (macOS/Linux shell or PowerShell):

```sh
git clone --branch codex/parallel-dispatch https://github.com/alexwoolee/surge-fall-2026.git surge-fall-2026-phase10
cd surge-fall-2026-phase10
git status --short --branch
git log -3 --oneline
git merge-base --is-ancestor ccd0de8932e2f26351cf939d714173797b9bbeeb HEAD
```

For an existing **separate development checkout**, inspect `git status` first,
then fetch, switch to `codex/parallel-dispatch`, and pull with `--ff-only`. Preserve
local edits and investigate any refusal instead of using a reset or force push.
The ancestor check above verifies that the tested Phase 9 implementation is
included in the accepted base. When Phase 10 is authorized, create a separate
`codex/*` branch from that accepted base and preserve existing work. Selecting `main`
on GitHub shows older documentation.

Read this README, `requirements.txt`, `.env.example`, and the linked
[Phase 4](docs/phase4-validation.md), [Phase 5](docs/phase5-validation.md),
[Phase 6](docs/phase6-validation.md) and [Phase 7](docs/phase7-validation.md)
records. Inspect `backend/control/`, `backend/shared/`, the two worker services,
`scripts/validate/` and their tests before designing changes. Control has both
the terminal CLI and a local authenticated web API in `backend/control/web.py`,
with durable sessions in `sessions.py` and explicit startup in `serve.py`.
Shared contracts and processors already work; extend them rather than restarting
the project. Read [Phase 9 startup and validation](docs/phase9-validation.md).

Create a fresh Python 3.12 environment; do not copy one from another OS.

macOS/Linux:

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m pytest -q
.venv/bin/python -m pip check
git diff --check
```

Windows PowerShell:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m pip check
git diff --check
```

Keep the pinned requirements and platform markers: macOS versions before 15 use
the compatible Rasterio 1.4.4 wheel; other supported platforms use 1.5.2. Report
actual results on the new laptop rather than copying the Windows test result.
Unit tests and offline report replay do not require worker tokens or an OpenAI key.

## Evidence and files that Git does not transfer

`data/cache/`, `outputs/debug/`, `outputs/reports/`, `.env`, `.env.local`,
`.env.*.local`, NASA login files and virtual environments are ignored. Other
names such as `.env.production` are not covered by the current ignore rules;
verify the exact filename before saving secrets. A clone contains code and
checkpoint documentation, not these local resources.

Kazi has the sanitized bundle **`MeshMind-Phase7-review-ea4f322.zip`** at:

```text
C:\Users\kazib\Documents\Codex\2026-10-03\ca\outputs\MeshMind-Phase7-review-ea4f322.zip
```

Transfer it separately if the new reviewer needs the exact Phase 7 evidence.
It contains `real-inputs.json`, `review.json`, `preservation.json`, the policy,
test log, phase documentation and SHA-256 manifest under `phase7-review/`.
The archived handoff refers to the tested implementation; this README contains
the newer continuation instructions. No credentials or cached rasters are included.

The input's SHA-256 is
`f314f5446c94d3194154902d58a4ccfe7f6903535d50e2a445653c699420b18e`.
After extracting, copy `real-inputs.json` into this checkout's
`outputs/debug/phase7/` and replay on macOS/Linux:

```sh
.venv/bin/python -m scripts.validate.validate_fusion --input outputs/debug/phase7/real-inputs.json --rules config/rules.example.json --output outputs/debug/phase7/replayed-review.json
```

On Windows replace the interpreter with `.\.venv\Scripts\python.exe`. Expected:
`PASS / PENDING_USER`, four triggered conditions, one not triggered, zero not
assessable. Replay makes no new worker or data-source calls. Keep the original
artifact separate from output. Alternatively, Ryan may already have the accepted
Phase 6 report; the Phase 7 document explains that input format and requested-date
flags. Missing evidence files are not a failed scientific result; obtain the
sanitized artifact or generate clearly identified real evidence when needed.

The local Phase 7 acquisition worked around Windows GDAL certificate-chain errors
with a bounded, read-only loopback Range proxy and verified upstream HTTPS.
That ignored helper and its local CA/cache setup are not production code and do
not transfer through Git. Do not disable TLS validation to reproduce a run.

## Deployment and private configuration

These are the last validated deployment roles, **not a current health check**:

| Role | Owner / host | Existing endpoint or checkout |
| --- | --- | --- |
| Control | Ryan's Mac | Tailscale `100.100.3.5`; existing repo `/Users/diamster/Stormhacks 2026/surge-fall-2026` |
| Hydro | Kazi Boni Amin / Windows hostname `Boni` | `http://100.100.3.2:8002`; `C:\Users\kazib\surge-fall-2026-worker`, last verified clean at `7bde416` |
| Flood | Karan / Linux hostname `ARE` | `http://100.100.3.4:8003`; separate worker checkout described in Phase 6 |

`Boni` is Kazi's hostname, not a fourth team member. Kazi's main project is
`D:\Projects\MeshMind`; preserve its local `README_FINAL.md` and `hydro-inputs.zip`.
His separate frontend checkout is under
`C:\Users\kazib\Documents\Codex\2026-10-03\ca\work\meshmind-frontend`.

For remote dispatch, export `HYDRO_WORKER_URL`, `FLOOD_WORKER_URL`,
`HYDRO_WORKER_TOKEN` and `FLOOD_WORKER_TOKEN` privately on Control. Each token
matches the destination's existing `MESHMIND_WORKER_TOKEN`. Current entry points
read exported environment variables; merely creating `.env` does not load them.
Keep existing tokens private and stable; never print or commit them. The optional
`MESHMIND_CONTROL_SOURCE_IP=100.100.3.5` is specific to Ryan's Mac; leave it unset
on another machine unless binding to that machine's verified local address.

The worker needs its own data folders/settings and existing NASA authentication;
Control needs connectivity to both workers for a real distributed run. Workers
must use one Uvicorn process, without reload. Registry state is lost on restart.
Do not stop, update or restart a deployed worker just to review accepted evidence
or continue development; coordinate any later required deployment with its owner. The exact
startup, authentication and clock-calibration commands remain in the Phase 5/6
documents. Do not repeat their accepted physical checkpoints merely because the
development checkout moved laptops.

## Next actions and remaining phases

1. **Phase 7 human checkpoint accepted October 4.** Following the Mac review
   (907 passing tests, preserved real evidence and all five demonstration outcomes),
   the user instructed “proceed.” This records the current user’s approval; it does
   not invent a separate named worker-owner confirmation. Original raw reports
   remain unchanged. PR #1 was merged into **`codex/parallel-dispatch`** at
   `0aa918ff3468a25e58ba543970855c51ab9342fa` using Git access. The connector
   could not update the historical draft flag or PR description; GitHub confirms
   the merged state. `main` was not changed.
2. **Phase 8 — Accepted after completeness fixes.** The implementation on
   `codex/agent-integration` uses the Responses API directly for bounded request
   interpretation and supported fact selection. Python owns measurements,
   threshold decisions and explanation text. The final narrative always includes
   eight measurements, source/method context, validated radar sensitivity when
   available, every rule outcome and scientific limits. An optional saved request
   is explicitly untrusted context. Automated checks, the earlier live API check
   and the updated offline completeness review pass. The user's authorization to
   proceed once that review passed is now satisfied. Tested implementation
   **`25e48d57eabc942184892cbdb5fb009bd6da487f`** is merged into
   **`codex/parallel-dispatch`**, the accepted Phase 9 base. See
   [Phase 8 validation](docs/phase8-validation.md).
3. **Phase 9 — Accepted October 4; merged into `codex/parallel-dispatch`.**
   Tested implementation `ccd0de8932e2f26351cf939d714173797b9bbeeb` is preserved
   on `codex/briefing-integration`. It starts from the accepted
   Phase 8 merge and preserves the frontend's original history. Inspect
   the preserved frontend instructions, including `frontend/AGENTS.md`,
   `frontend/README.md` and `frontend/IMPLEMENTATION.md`. Preserve that work and
   the approved design. The existing provider boundary is
   `frontend/src/lib/data-provider.ts`; `api-provider.ts` now uses the real local
   Control API. Sessions, history and bounded retry are owned by Python. Fixtures
   require explicit demo mode; never present simulated timers, demo measurements
   or browser-local state as live execution. Preserve independent worker cards,
   partial results and unavailable review conditions. The standalone HTML briefing
   and actual browser download have passed validation, with real observations,
   provenance and limitations. PDF is optional. Run `npm ci`, `npm run test`,
   `npm run lint` and `npm run build` inside `frontend/`, plus backend checks for
   backend changes. The user reported “all passed” for the six manual checks,
   including the standalone HTML visual review. Preserve this accepted checkpoint.
4. **Phase 10 — Reliability and submission.** Finish failure/recovery checks,
   portable startup/reset instructions, deployment guidance, final README,
   demo preparation and submission materials. Ask for the actual event deadline,
   submission format and required assets rather than inventing them. Run final
   end-to-end validation and stop for the final human checkpoint.

For every phase: implement → run → real/manual validation → necessary automated
tests → review/commit/push a separate `codex/*` branch → human acceptance → merge
the accepted phase. Preserve existing passing assertions, run the full Python
suite and `git diff --check` before finalizing code, and report exact commands,
PASS/FAIL, limitations and remaining work. Treat historical test counts as history.
Do not overwrite unrelated work or push `main`. Moving the development checkout
does not require repeating accepted physical-laptop checkpoints; run the checks
appropriate to new implementation changes before advancing their phase.

## Scientific boundaries that must survive integration

- GPM's accepted example covers supplied observations totaling **one hour**, not
  the requested multiday event. Current worker results do not validate interval
  boundaries or continuity merely because resource filenames contain dates.
- SMAP is a state snapshot, not accumulated rainfall or an observed trend.
- Sentinel-1 gives **candidate** surface water, not confirmed flooding. Preserve
  the **97.6354%** valid SAR fraction; completed processing is not full coverage.
- DEM/HAND statistics cover the AOI, not specifically candidate-water pixels.
- No common-grid water/terrain overlay, water depth, causation, operational hazard
  classification or validated disaster severity has been computed.
- Missing/invalid results and unavailable prerequisites must remain explicit;
  an unassessable condition is not a passing threshold comparison.
- User-visible activity describes observable events, not fabricated model
  reasoning. Keep secrets, infrastructure addresses and raw long logs out of the
  primary UI. Retain the environmental-analysis/analyst-support disclaimer.

## Prompt to give the next Astra session

```text
Continue MeshMind in alexwoolee/surge-fall-2026. Fetch origin and read the latest
README on codex/parallel-dispatch, starting with "Continue on Another Laptop".
Preserve existing checkouts, private environment files, data and running workers.
Phases 1–9 are accepted and merged into codex/parallel-dispatch. Verify that
tested Phase 9 implementation ccd0de8932e2f26351cf939d714173797b9bbeeb is an
ancestor of your continuation branch.
Phase 8 uses bounded Responses API interpretation and Python-rendered grounded
explanations. Check docs/phase8-validation.md for current checks, historical live
API evidence and scientific limitations. The separate Agents API/SDK are not used.
Read docs/phase9-validation.md and frontend/AGENTS.md; preserve the integrated UI,
local Control API, durable sessions and standalone HTML briefing. Phase 9 manual
checks were accepted by the user. Phase 10 has not started: when authorized, use
a separate codex/* branch from the accepted base, obtain the actual event deadline,
submission format and required assets, and follow its final checkpoint. Do not start from main,
redo accepted phases, invent measurements, expose
secrets or claim fixture/local/replayed activity is fresh distributed execution.
Report missing evidence or credentials while continuing independent work.
```

---

# Current Status

## Current Phase

**Phases 1–9 accepted and merged; Phase 10 reliability and submission work is next.**

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
- accepted Phase 6 automated baseline: **758 passing tests on macOS**
- Phase 6 Windows verification: **757 passed, 1 expected symlink-privilege skip**
- real-data Control dispatch to separate Windows Hydro and Linux Flood laptops: **PASS; Phase 5 accepted**
- concurrent Control dispatch, authenticated clock samples and conservative overlap proof
- Phase 6 real-data parallel execution on Windows and Linux workers: **PASS; human checkpoint complete**
- structured source-evidence combination and explicitly configured demonstration review rules
- Phase 7 new local real-data processing and review: **PASS; all 15 reference checks match**
- Phase 7 Windows Python 3.12 suite: **906 passed, 1 expected symlink-privilege skip**
- missing-worker and partial-component review preserves available real measurements
- bounded Responses API request interpretation and deterministic grounded explanations
- Phase 8 live API validation passed; requested completeness fixes and offline review passed
- Phase 8 accepted under the user's authorization to proceed after a successful review
- Phase 9 local authenticated Control API, durable sessions and existing frontend integration
- Phase 9 new physical worker investigation, grounded HTML download and restart persistence: PASS
- Phase 9 automated checks: 1,327 Python tests; 25 frontend tests, lint and production build PASS
- Phase 9 six manual checks, including standalone HTML visual review: PASS; human accepted October 4

Current focus:

**Phase 9 is complete and accepted. Preserve the integrated frontend, local Control API and downloadable briefing. Phase 10 has not started; its work requires the actual event deadline, submission format and required assets. See [the accepted Phase 9 checkpoint](docs/phase9-validation.md).**

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
Control Fusion          PHASE 7 PASS; HUMAN ACCEPTED OCTOBER 4
Agent Integration       PHASE 8 PASS; ACCEPTED AFTER COMPLETENESS REVIEW
Frontend                PHASE 9 PASS; HUMAN ACCEPTED OCTOBER 4
Final Report            STANDALONE HTML AND BROWSER DOWNLOAD PASS
```

## Immediate Next Steps

Phase 9 is accepted following the user’s “all passed” response to the six manual
checks. Tested implementation `ccd0de8` and its acceptance record are merged into
`codex/parallel-dispatch`. Preserve [the accepted checkpoint](docs/phase9-validation.md).
Phase 10 has not started; obtain its actual submission constraints before planning
the deadline-dependent work.
The Phase 8 evidence and API boundaries remain documented in
[its validation record](docs/phase8-validation.md).

[Phase 7 validation and policy semantics](docs/phase7-validation.md) describe
offline replay, optional Control CLI integration, real-data evidence and limits.

**Repository base:** remote `main` does not contain the accepted backend phases.
Use the accepted Phase 9 merge on `origin/codex/parallel-dispatch`, which includes
tested implementation `ccd0de8932e2f26351cf939d714173797b9bbeeb`. Preserve the
separate worker checkouts and existing `kazi/frontend-ui` work.

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

Implemented responsibilities through Phase 6:

- task creation
- worker selection
- task dispatch
- concurrent execution coordination
- worker-state tracking
- result collection
- deterministic result validation

Phase 7 adds evidence combination and deterministic analyst-review rules.
Natural-language/agent orchestration is Phase 8. The existing demonstration UI,
live UI boundary and downloadable HTML briefing are connected in Phase 9.
Control sessions have durable private JSON history; worker registries remain
in memory and are not automatically reconstructed after worker restarts.

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

Latest Phase 7 Windows run: **906 passed and one expected symlink-privilege skip**.
Accepted Phase 6 baseline: **758 tests on macOS; 757 passed and one expected
Windows skip**. Phase 7 verification is recorded in
[the Phase 7 checkpoint](docs/phase7-validation.md). Older counts in historical
phase records describe those milestones, not the current suite.

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

## Control, Fusion, and Review Tests

- concurrent dispatch, clock uncertainty and conservative overlap proof
- bounded deadlines, ambiguous submissions and independent result preservation
- request/task/AOI/resource binding and revalidation of mutated model instances
- explicit policy units/domains, equality boundaries and nonfinite rejection
- unavailable evidence and coverage/duration prerequisites
- strict JSON, offline replay, atomic writes, input-alias protection and stale-attempt handling

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
  HUMAN ACCEPTANCE
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

GitHub default branch: `main` (behind accepted backend work).

Current development branches:

```text
codex/parallel-dispatch    accepted implementation through Phase 9
codex/fusion-review        accepted Phase 7 implementation
codex/agent-integration    accepted Phase 8 implementation
codex/briefing-integration accepted Phase 9 implementation and checkpoint
kazi/frontend-ui          original frontend, preserved in Phase 9
codex/<next-phase>        create only from the verified accepted checkpoint
```

Use separate `codex/*` phase branches based on the latest accepted backend
checkpoint. Merge only after the phase's human acceptance. Remote `main` is
currently behind the accepted backend baseline; do not start new work from it.

---

# Repository Structure

Selected implemented files; this is not an exhaustive listing:

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
|   |   |-- state.py
|   |   `-- timing.py
|   |
|   |-- shared/
|   |   |-- __init__.py
|   |   |-- contracts.py
|   |   |-- settings.py
|   |   |-- status.py
|   |   |-- worker_api.py
|   |   `-- worker_runners.py
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
|   |-- smoke/
|   |   |-- smoke_gpm.py
|   |   |-- smoke_smap.py
|   |   |-- smoke_sentinel1.py
|   |   |-- smoke_dem.py
|   |   `-- smoke_hand.py
|   `-- validate/
|       |-- prepare_hydro_data.py
|       |-- validate_terrain.py
|       |-- validate_sentinel1.py
|       |-- validate_flood.py
|       |-- validate_worker_apis.py
|       |-- validate_remote_workers.py
|       |-- validate_dispatch_failures.py
|       |-- validate_parallel_workers.py
|       `-- validate_fusion.py
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
|   |-- test_coordinator.py
|   |-- test_control_timing.py
|   |-- test_fusion.py
|   |-- test_reporting.py
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
    |-- phase3b-validation.md
    |-- phase3c-validation.md
    |-- phase4-validation.md
    |-- phase5-validation.md
    |-- phase6-validation.md
    |-- phase7-validation.md
    `-- manual-test-checklist.md
```

The Next.js/TypeScript/Tailwind UI from `origin/kazi/frontend-ui` is preserved
and integrated in Phase 9. Read its own instructions before editing. Its optional
fixture mode is separate from the real Control provider.
`docs/architecture.md` is currently an empty placeholder; use this README, the
phase records and implemented contracts for the actual architecture.

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
contract. Remote and parallel execution were accepted in Phases 5 and 6.

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

Implemented terminal entry point for concurrent HTTP dispatch. Optional
`--rules <policy.json>` adds deterministic Phase 7 review while retaining the
original requests and independent dispatch results. Control does not yet expose
a web API.

### `backend/control/coordinator.py`

Implemented bounded HTTP dispatch, concurrent branch execution, independent
result preservation, validation, deadlines and process identity checks.

### `backend/control/fusion.py`

Phase 7: revalidate original request/result bindings, preserve full source
evidence and errors, and expose measurements with units, observation context,
coverage and explicit unavailable states. This is structured evidence assembly;
no common-grid overlay or additional environmental measurements are computed.

### `backend/control/alerts.py`

Phase 7: explicit configurable demonstration thresholds, coverage/duration
prerequisites and `triggered` / `not_triggered` / `not_assessable` results.

### `backend/control/reporting.py`

Phase 7: strict, atomic structured review artifacts and offline replay support.
The downloadable HTML briefing is implemented in `backend/control/briefing.py`
and served through the Phase 9 local Control API.

### `backend/control/state.py`

Implemented validated dispatch records and the independent collection envelope.
Phase 9 `sessions.py` persists these records in bounded private JSON history;
database-backed storage such as SQLite remains later work.

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

Implemented, validated and human accepted October 4 after the Mac review:

- validate both worker results
- combine evidence
- deterministic configured review conditions

Demonstration thresholds are explicitly configured in `config/rules.example.json`;
they are not validated hazard or severity policy. Missing evidence remains
unavailable/not assessable. Requested event windows remain separate from the
actual one-hour rainfall accumulation, individual snapshots and static terrain.
See [Phase 7 validation](docs/phase7-validation.md).

The LLM does not decide whether numerical thresholds were crossed.

## Phase 8 — OpenAI Agent Integration

Implemented on `codex/agent-integration` from the accepted Phase 7 merge
`0aa918f`; accepted after the requested completeness fixes and review. Automated
checks and the earlier live API verification pass; new rendering was verified
offline without more paid requests or worker dispatches. Tested implementation
`25e48d57eabc942184892cbdb5fb009bd6da487f` is merged into the accepted base,
`codex/parallel-dispatch`. See
[Phase 8 validation](docs/phase8-validation.md) for setup, commands and evidence.
The opt-in interface uses the OpenAI Responses API with bounded function calling
and structured fact selection; Python owns orchestration and explanation text.
The separate Agents API and Agents SDK are not used.

Every explanation now includes all eight measurements, all review outcomes,
study-area/time/coverage context, source products, processing methods and limits.
Radar threshold sensitivity is displayed only after consistency checks. The
original request is omitted by default; `--include-request` saves it locally as
quoted, untrusted user context. Phase 9 now provides the complete standalone
HTML report and verified browser download.

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

Implemented on `codex/briefing-integration`, preserving `kazi/frontend-ui` and
the accepted Phase 8 base. Automated, live browser and six manual checks pass.
The user accepted Phase 9 on October 4; it is merged into `codex/parallel-dispatch`.
See [the Phase 9 validation record](docs/phase9-validation.md) for startup,
verification and the checkpoint. The browser uses a local authenticated Python
API through a server-only Next.js proxy. Real execution is the default; fixtures
require explicit demo mode. Server-owned history, independent worker snapshots
and one explicit eligible-worker retry preserve validated evidence across reloads.
The standalone HTML briefing contains actual measurements, sources, processing
context, all demonstration-rule outcomes and scientific limitations.

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

# Maintaining Accepted Work

The current continuation instructions are in [Continue on Another Laptop](#continue-on-another-laptop--start-here).
Protect the accepted Hydro and Flood processors, shared contracts and worker APIs,
Control dispatch/timing, and Phase 7 evidence/rule behavior. Extend these components
only for a concrete requirement and keep their existing assertions green. Smoke
tests exercise real access; production calculations belong in `backend/`.

Update progress at each validated phase and record human acceptance separately
from raw execution reports. Commit and push on `codex/*` branches, then merge the
accepted phase only after its checkpoint. Historical Phases 3–6 are documented
above and in `docs/`; they are not a new work queue for the next agent.

---

# UI Direction

MeshMind should feel like a calm AI workspace, not a network-administration dashboard.

## Control Screen

Control-facing pages (Home, history, sessions and briefings) use the sidebar;
worker pages use focused execution views.

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

Real credentials belong in private environment variables or ignored local files:

`.env`

Never commit `.env` or `.env.*.local`. Current entry points do not automatically
load these files; explicitly load/export the required variables in the process
that starts Control or a worker. Never print secrets while checking configuration.

Current placeholders (see `.env.example` for the full template; `CONTROL_HOST`
and `CONTROL_PORT` do not mean a Control web API has been implemented):

```text
OPENAI_API_KEY=
CONTROL_HOST=
CONTROL_PORT=
HYDRO_WORKER_URL=
FLOOD_WORKER_URL=
HYDRO_WORKER_TOKEN=
FLOOD_WORKER_TOKEN=
MESHMIND_WORKER_TOKEN=
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

Current direct dependencies are pinned in `requirements.txt`:

```text
earthaccess==0.19.0
h5py==3.16.0
numpy==2.5.3
planetary-computer==1.0.0
pystac-client==0.9.0
pytest==9.1.1
rasterio==1.4.4; sys_platform == "darwin" and platform_release < "24.0"
rasterio==1.5.2; sys_platform != "darwin" or platform_release >= "24.0"
pydantic==2.13.5
fastapi==0.142.2
uvicorn==0.54.0
httpx==0.28.1
```

Additional dependencies should only be introduced when the current implementation phase requires them.

---

# Application Stack and Remaining Integration

## Frontend

Implemented as a separate demonstration branch; real backend integration remains:

- Next.js
- TypeScript
- Tailwind

## Backend

Implemented:

- Python
- FastAPI
- Uvicorn
- Pydantic

SQLite/durable history remains planned.

## Worker Communication

Implemented:

- HTTP
- `httpx` with bounded requests, authentication and independent failure records

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

Runs Control's terminal CLI or the local Phase 9 web API and frontend:

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

Deterministic Flood processing and physical remote execution are accepted.

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
- accepted Phase 6 baseline of 758 automated tests passing on macOS
- concurrent Control clients, authenticated clock observations and conservative overlap checks
- Phase 7 structured evidence fusion, explicit demonstration rules and offline JSON review
- optional Control CLI review with independent results retained on failure
- standalone frontend demonstration on `kazi/frontend-ui` with provider, pages and HTML generation

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
- Phase 7: 906 Windows tests passed, 1 expected capability skip; dependency and diff checks passed
- Phase 7: real local measurements matched 15 reference checks; four controlled evidence omissions passed
- original frontend lane: 12 tests, lint and build passed; download capture was pending at that historical checkpoint

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
the later human confirmation is recorded separately. Phase 7 now extends this
accepted baseline on a separate branch.

## PHASE 7 ACCEPTED

Implementation `ea4f322` passed the automated, real local-data, preservation and
independent review checks described in `docs/phase7-validation.md`. The policy
uses Kazi's explicitly selected demonstration thresholds. A Mac review at `8049cd2`
passed 907 tests, dependency/diff checks, independent review and offline replay
of the accepted Phase 6 evidence (four triggered, one not triggered). The original
evidence and exact typed results remained unchanged. After presentation of the
measurements, policy and scientific limits, the user instructed **“proceed”**,
accepting this checkpoint and authorizing PR #1’s merge into
`codex/parallel-dispatch` and Phase 8. This is the current user’s approval, not
a separately claimed confirmation from a named worker owner.

## PHASE 8 ACCEPTED

The user authorized Phase 9 if the grounded explanation passed review, then
requested fixes for the identified gaps. The completed explanation now includes
all measurements, request/study-area context when supplied, source products,
processing methods, checked radar sensitivity and the necessary limitations.
All nine offline completeness checks pass against retained real evidence;
automated tests pass and the earlier live API validation remains applicable to
the unchanged model catalog and transport. This satisfies the user's condition
and records Phase 8 acceptance. It does not claim a new named worker-owner check,
live API call or physical-laptop run. Original live reports retain their original
`PASS / PENDING_USER` state as historical evidence.
Tested implementation `25e48d57eabc942184892cbdb5fb009bd6da487f` is merged into
`codex/parallel-dispatch`; that accepted base supplies the Phase 9 branch.

## PHASE 9 ACCEPTED

After receiving exact manual steps, the user reported **“all passed”** on
October 4. This accepts worker completion, all eight measurements, explanation
and limitations, conditions and provenance, history/reload, and the downloaded
standalone HTML visual review. Tested implementation
`ccd0de8932e2f26351cf939d714173797b9bbeeb` is merged into
`codex/parallel-dispatch`. Original raw reports and private evidence are unchanged;
the acceptance is recorded in [the Phase 9 checkpoint](docs/phase9-validation.md).

## NEXT

**Phase 9 is accepted and merged into `codex/parallel-dispatch`. Phase 10 is next
and has not started. Preserve [the accepted validation record](docs/phase9-validation.md),
then follow the reliability/submission scope and final human checkpoint when authorized.**

## CUT FOR NOW

Until their separate accepted phases:

- remote hosting and multi-user access to the local operator UI
- further agent capabilities beyond the bounded Phase 8 workflow
- optional sponsor integrations
- unnecessary dashboards
- fake telemetry
- unsupported disaster predictions
- complex ML flood models
