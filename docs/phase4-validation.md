# Phase 4 — Shared contracts and worker APIs

Branch: `codex/worker-apis`, based on the accepted Phase 3C checkpoint `163a73f`.
Numerical Hydro, terrain, Sentinel-1 and Flood processors remain unchanged.

## Terminal checkpoint

From the repository root, using the existing Python 3.12 environment:

```sh
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m scripts.validate.validate_worker_apis --download-hydro
.venv/bin/python -m pytest -v
git diff --check
```

The download option uses the saved local Earthdata login. To establish one,
enter credentials in your own terminal, never in chat or repository files:

```sh
.venv/bin/python -c "import earthaccess; earthaccess.login(strategy='interactive', persist=True)"
```

The validation command downloads the configured two GPM granules and one SMAP
state, starts temporary Hydro and Flood HTTP processes on loopback, submits
bounded tasks, polls actual lifecycle states, retrieves typed results and checks
JSON serialization, authentication and duplicate submissions. Both servers stop
after validation. It saves only a terminal/JSON checkpoint, without HTML.

For existing NASA files, configure `MESHMIND_GPM_DIR` and `MESHMIND_SMAP_DIR`,
and replace `--download-hydro` with `--gpm-resources <names...> --smap-resource
<name>`. Requests contain basenames only. Without either option, the command
runs a clearly labeled synthetic Hydro fixture and leaves `PENDING_LIVE_HYDRO`;
it never calls that a completed real Hydro gate.

The downloader is deliberately limited to validation inputs: all GPM granules
in the configured interval (up to one day), and the earliest SMAP state returned
for the configured SMAP window. The selected SMAP state can precede the search
start because its temporal coverage intersects the start boundary. It reproduces
the established Phase 2 test; it is not a general antecedent-state selection rule.
The NASA smoke scripts now pass bbox tuples, as required by installed earthaccess.

## API contract

Start each worker in its own terminal with one Uvicorn process:

```sh
.venv/bin/python -m uvicorn backend.workers.hydro.main:create_app --factory --host 127.0.0.1 --port 8002
.venv/bin/python -m uvicorn backend.workers.flood.main:create_app --factory --host 127.0.0.1 --port 8003
```

| Endpoint | Behavior |
| --- | --- |
| `POST /tasks` | Accept a bounded `AnalysisTask`; return HTTP 202 and `TaskStatus` |
| `GET /status` | Worker identity, idle/busy state, active task and retention capacity |
| `GET /tasks/{task_id}` | Observed lifecycle state and UTC receipt/start/completion times |
| `GET /tasks/{task_id}/result` | Validated `HydroResult` or `FloodResult` |

Task/result IDs and the AOI must match. Flood results also match the requested
threshold/date interval; Hydro results match the requested resource IDs.
Typed contracts reject invalid settings, nonfinite numerical values, mismatched
summaries, malformed coverage and conflicting evidence. Full processor evidence
remains available; timestamps in typed fields normalize to ISO date/time values.
`CombinedAnalysis` only collects typed results; fusion/review rules are later work.

Request limits:

- AOI: at most 2 degrees in longitude and latitude, non-wrapping WGS84.
- Flood search: positive interval of at most 7 days; VV threshold −40 to 0 dB.
  Existing raster/cell and catalog limits still apply during processing.
- Hydro: 1–48 unique GPM basenames plus one SMAP basename from configured folders.
  Absolute paths, URLs, traversal and symlinks outside those folders are rejected.
- HTTP JSON body: at most 64 KiB; extra fields, duplicate keys and nonfinite
  JSON numbers are rejected without echoing supplied values in errors.

One task is active per worker. An identical retry of the same task ID returns its
existing status without another execution. Conflicting reuse returns 409; a
second distinct active task returns 429; a full history returns 503. Unknown
IDs return 404. Results not ready, or runtime failures without valid results,
return 409. Partial or all-component-failed Flood results remain available as
structured results so successful evidence and component errors can be inspected.

Actual states are `task_received`, `dataset_located`, `processing`,
`preparing_result`, and `complete`/`partial`/`failed`. A fast transition can occur
between polls; percentages or invented work stages are not emitted.

## Settings and deployment boundary

`WorkerSettings` reads exported variables documented in `.env.example`:
`MESHMIND_GPM_DIR`, `MESHMIND_SMAP_DIR`, `MESHMIND_MAX_TASKS` (default 128), and
optional `MESHMIND_WORKER_TOKEN`. When set, every endpoint requires
`Authorization: Bearer <token>`. The terminal validator generates an ephemeral
token for its own processes and verifies rejection of an incorrect token.
It never prints the token or reads user credentials into a report.

The registry is process-local and held in memory. Completed records are retained
until restart; new submissions are rejected at capacity rather than evicting
completed evidence. Do not run multiple Uvicorn workers or reload mode for this
registry. Restart loses its history. Shutdown waits for accepted work; there is
no cancellation endpoint or durable queue in this phase.

Discovery must finish before the Flood service receives its resources. A
catalog failure therefore ends the task without a partial numerical result.
Partial preservation applies to component processing after resource discovery.

## Recorded validation

- Full automated suite: **390 passing tests**.
- Real Flood HTTP processing, contract round trip, authentication and identical
  task retry: **PASS**.
- Real Hydro HTTP processing with NASA GPM/SMAP: **PASS**.
- Synthetic HDF5 Hydro arithmetic over real loopback HTTP: **PASS** (5 mm
  known rainfall fixture, explicitly labeled synthetic).
- Updated GPM and SMAP access smoke tests: **PASS** using the saved login and cached resources.
- `pip check` and `git diff --check`: **PASS**.

Real-data values match the accepted checkpoints: mean rainfall 6.6504165 mm,
maximum cell rainfall 15.5700 mm, surface/root-zone soil moisture 0.4084949 /
0.3924146 m³/m³, and candidate-water area 88.0997 km² with 97.6354% valid SAR
coverage. DEM/HAND means remain 254.308864 / 45.452025 m.

On 2026-10-04 UTC (2026-10-03 locally), Hydro executed from
03:30:59.600383 to 03:30:59.930565 UTC; Flood executed from
03:31:00.860264 to 03:32:10.552826 UTC. These intervals were sequential.

Detailed numerical results, acquisition provenance and actual execution times
are saved under ignored `outputs/debug/worker-apis/result.json`. Deprecation
warnings remain visible from the existing geospatial stack and the HTTP test
client; they are not failures.

This validates two HTTP processes on **this Mac**. The checkpoint runs them
sequentially. It does not establish remote laptop execution or simultaneous
execution; those are Phases 5 and 6.

## Phase boundary

**PASS — user approved advancing to Phase 5 on 2026-10-03.**

The necessary checks run in the terminal. No new visual/HTML approval is needed.
The implementation stays on its separate branch and nothing is pushed remotely.
The Phase 4 checkpoint is accepted. Phase 5 now covers real remote worker communication.

Primary API references: [FastAPI background execution](https://fastapi.tiangolo.com/tutorial/background-tasks/)
and [Pydantic strict validation](https://docs.pydantic.dev/latest/concepts/strict_mode/).
