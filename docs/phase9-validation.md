# Phase 9 — Real Control UI and downloadable briefing

> Historical checkpoint record. For current startup use [README](../README.md)
> or [developer setup](../DEVELOPER_SETUP.md); project status is in
> [project progress](../PROJECT_PROGRESS.md). MeshMind now ignores internal
> tokens, including missing or invalid values. Authentication requirements
> and 401 checks below record the earlier implementation. External OpenAI
> and NASA Earthdata credentials remain subject to those services.

Current checkout: use `main` for all roles. The user authorized branch
consolidation after Phase 9 acceptance; branch names in this validation history
identify the original development lanes. Their commits remain in `main`.

Branch: `codex/briefing-integration`, from accepted Phase 8 merge `807865f`.
Kazi's existing `kazi/frontend-ui` work at `5ae2919` was merged with its design
and history preserved. Phase 9 implementation, automated checks and the live
browser investigation passed on October 4, 2026. The user subsequently reported
**“all passed”** for the six manual checks below, completing human acceptance.
Tested implementation `ccd0de8932e2f26351cf939d714173797b9bbeeb` and this acceptance
record are merged into `codex/parallel-dispatch`. Phase 10 has not started.

**Subsequent scope clarification:** “all passed” covered the six Mac-side manual
checks listed here. The user then required the worker screens on Kazi's and
Karan's physical laptops to show the same investigation. That additional
three-screen checkpoint passed with user acceptance on `codex/worker-viewers`; see
[setup and coordinated test](phase9-worker-viewers.md). The prior merge and
technical evidence remain valid. The new shared session was
`c51fd780-8b4d-4eea-906b-5fea0bfff690`; the user's “Yes both pass” confirms the
two remote screens and their refresh checks. Phase 9 is accepted in full;
Phase 10 has not started.

## Execution boundary

The browser uses the existing provider interface. Real Control is the default;
the fixture provider requires the explicit build-time
`NEXT_PUBLIC_MESHMIND_MODE=demo` setting. A failed Control request never switches
to fixtures. The UI gets server-owned history and independent worker snapshots;
there are no simulated execution timers in real mode.

The local Next.js route `/api/control/*` proxies a fixed set of endpoints to the
local Python API. The proxy adds a private server-side bearer token, checks
same-origin writes, rejects arbitrary paths/destinations and bounds request and
response sizes/time. Neither worker tokens nor the model key reach browser
configuration. Both servers bind to loopback and run as local operator tools.
Remote access/hosting and multi-user authentication are separate deployment work.

The operator chooses either retained-evidence review or new execution at startup.
The browser supplies only a bounded prompt and idempotency request ID; it cannot
select worker addresses, source paths, thresholds, area, dates or execution mode.
The Phase 8 model selects the configured investigation or declines. Every
measurement and rule decision still comes from the validated Python pipeline.

Only one session executes at a time. The bounded history is stored as private,
atomic JSON files. Restart marks unfinished sessions interrupted and does not
automatically dispatch or retry remote work. Each mutation has a request ID;
repeating an uncertain browser request uses that same ID. A retry is explicit,
limited to one eligible missing worker and retains the other worker's evidence.
The original task ID and known worker process identity constrain reconciliation.
An ambiguous task cannot silently execute again on a restarted worker.

Briefings rebuild the deterministic evidence, context and rule results rather
than trusting cached model prose. They include all eight available/unavailable
measurements, actual source/time coverage, safe exact public resource identifiers,
processing methods and recorded durations, all review outcomes, limitations and
the required disclaimer. The HTML file is standalone, escaped and script-free.
Incomplete SAR coverage remains explicit even when both workers finish. New
processing does not make historical observations current, and concurrent dispatch
alone does not establish calibrated physical execution overlap.

## Local startup

Use native Python 3.12 with the pinned requirements and Node compatible with the
frontend lockfile. Commands below run from the repository root, except the npm
commands, which run inside `frontend/`. On Windows replace `.venv/bin/python`
with `.\.venv\Scripts\python.exe`; no shell activation is required.

Provide a long random `MESHMIND_CONTROL_API_TOKEN` in an ignored, private
`.env.phase9.local`. Set the same token and the local API origin in
`frontend/.env.local`:

```dotenv
MESHMIND_CONTROL_API_URL=http://127.0.0.1:8001
MESHMIND_CONTROL_API_TOKEN=<same-private-random-token>
```

These variables are server-only. Do not give them a `NEXT_PUBLIC_` prefix.
Never commit private environment files. Continue using the explicit private
OpenAI settings and worker configuration; existing worker checkouts need no
Phase 9 update. On this Mac the OpenAI file is `env.phase8.download` and the
worker file is `.env.phase5.local`. Other laptops provide their own settings.
Private files accept literal assignments; no shell expansion or execution occurs.

For a new investigation (workers must already be running):

```sh
.venv/bin/python -m backend.control.serve --execute --config config/test_case.example.json --rules config/rules.example.json --control-env-file .env.phase9.local --openai-env-file env.phase8.download --worker-env-file .env.phase5.local --gpm-resources 3B-HHR.MS.MRG.3IMERG.20211115-S000000-E002959.0000.V07B.HDF5 3B-HHR.MS.MRG.3IMERG.20211115-S003000-E005959.0030.V07B.HDF5 --smap-resource SMAP_L4_SM_gph_20211114T223000_Vv8010_001.h5 --history-dir outputs/debug/phase9/live-history
```

Append `--check-config` to validate configuration without serving or contacting
OpenAI/workers. For a clearly labeled historical review instead:

```sh
.venv/bin/python -m backend.control.serve --input outputs/debug/parallel-workers/physical-7bde416/result.json --config config/test_case.example.json --rules config/rules.example.json --control-env-file .env.phase9.local --openai-env-file env.phase8.download --history-dir outputs/debug/phase9/review-history
```

In another terminal, inside `frontend/`:

```sh
npm ci
npm run test
npm run lint
npm run build
npm run start
```

Open `http://localhost:3000`. The UI explicitly shows the configured area and
dates and states that the original request is retained in private history.
One supported submission normally makes at most two bounded model requests.
Do not refresh into a new request after a timeout; check history and the retained
session first. Do not restart workers to clear uncertain tasks.

## Required validation and checkpoint

```sh
.venv/bin/python -m pytest -q
.venv/bin/python -m pip check
git diff --check
```

The validation record must distinguish automated fixtures, retained real evidence
and new physical execution. Required browser checks include submitting a supported
case, observing independent worker updates, retained partial evidence/unavailable
conditions, history/reload, the complete briefing, and an actual browser download.
Do not treat an HTML string or a link alone as proof that downloading works.

## Verification results — October 4, 2026

| Check | Result |
| --- | --- |
| Python 3.12.14, `.venv/bin/python -m pytest -q` | **1,327 passed**, zero failures/skips; existing Rasterio/NumPy deprecation warnings remain |
| `.venv/bin/python -m pip check` | PASS; no broken requirements |
| `git diff --check` | PASS |
| `npm ci` | PASS; pinned lockfile installed |
| `npm run test` | **25 passed** |
| `npm run lint` | PASS |
| `npm run build` | PASS; production compilation and TypeScript checks |
| Read-only worker preflight from Control | Both authenticated **200**, unauthenticated **401**, idle before submission |
| Actual local HTTP authentication/proxy checks | All **6 PASS**: API auth, normal proxy access, hostile Host/Origin rejection, valid localhost alias reaches input validation |
| Live browser, new physical worker execution | PASS; one investigation submitted, independent worker completion observed |
| Reference comparison, export and restart checks | All **16 PASS** |
| Human acceptance | **PASS — user reported “all passed” for all six manual checks on October 4** |

The acceptance merge check reran the full Python suite: **1,327 passed** in
23.23 seconds, with `git diff --check` also passing. This rerun made no live
model or worker investigation requests. Its local log is
`outputs/debug/phase9/acceptance-pytest.log`.

The build script uses Next's supported Webpack mode. Turbopack could not create
its build socket in this environment; the same required `npm run build` command
now completes with Webpack. Dependency versions and the existing frontend design
were preserved. These are Mac Control/frontend results, not a new claim that the
Phase 9 suite has run on Windows or Linux. Worker checkouts were not changed.

Automated API tests cover strict authenticated inputs, duplicate requests,
single-session concurrency, bounded history, interrupted startup, partial
evidence, failed Flood components, report/request binding, sanitized failures,
and a single explicit retry with the original task ID and known process identity.
Failed persistence cannot consume a retry or silently launch work. Uppercase UUID
aliases cannot evade retry limits. Frontend checks cover no fixture fallback,
idempotent request handling, response bounds, actual Host and Origin validation,
and safe download headers. Controlled failure/retry scenarios use test fixtures;
the physical workers were not deliberately interrupted to manufacture failures.

### New physical investigation

Browser session and shared task ID:
`ad711f78-ae40-4c31-b5ee-1c5a68551f51`.

The operator submitted the configured Abbotsford / Sumas Prairie request through
the production UI. The bounded two-request Responses workflow completed, including
its grounded explanation. No additional investigation or paid review was submitted
for reload, download, or restart checks. Per-request billing usage is not retained
by the current client, so no exact price is claimed for this run.

| Worker | Host | Process identity | Recorded processing duration |
| --- | --- | --- | --- |
| Hydro | Boni (Kazi, Windows) | `53fc2374-3636-4519-acde-08842ff14173` | 0.225877 seconds |
| Flood | ARE (Karan, Linux) | `10da6d30-3823-4d14-9260-eb8549caf4ad` | 77.704457 seconds |

Both returned `complete` typed results and retained their preflight process
identities. Control submitted at `2026-10-04T09:03:39Z`; Flood completed at
`2026-10-04T09:04:57Z`. These are recorded worker times, not a new calibrated
clock/overlap proof. The accepted Phase 6 overlap evidence remains unchanged.

All eight environmental values, units and valid fractions match the accepted
physical reference at `outputs/debug/parallel-workers/physical-7bde416/result.json`.
All five rule outcomes match: **4 triggered, 1 not triggered, 0 not assessable**.
The raw reference still has SHA-256
`493bc176185c05142e0511438bfa106deeef6a5515f225228b11fd3778ecc75d`.

The UI showed Hydro complete while Flood was still active. At completion it
showed **2 of 2 investigations validated**, with **Partial result** because SAR
coverage is 97.6354% and the observations do not cover the entire requested time
window. No retry is offered for those completed results. The full briefing includes
all eight measurements, all five conditions including the untriggered root-zone
condition, exact public source IDs, methods, sensitivity, durations and limitations.

The actual browser download was captured at
`~/Downloads/meshmind-ad711f78-ae40-4c31-b5ee-1c5a68551f51-briefing.html`.
Its bytes match the validated standalone renderer and remain unchanged after
Control restarts. SHA-256:
`f8083293507466cdd8d1e81dcdffa4bac4470e51376382c4ce01f49677613a8c`.
It contains no scripts, external assets, private credentials or infrastructure
addresses. Browser history/reload and a local Control restart restored exactly
one session without new dispatch. The completed session's SHA-256 is
`662d0d362b80ebfb0b95f3d08260a462c21c51ad7dbe20b32b2fb6295e218958`.
The in-app browser blocks direct `file:` navigation. Automated work verified
the actual download and its complete contents; the user's subsequent manual
acceptance includes opening and visually checking the downloaded HTML in a
normal browser.

The final production UI was reloaded after two presentation fixes: running
activity uses Control's actual description, and a busy composer refreshes its
configuration so it can become available when work finishes. The briefing fits
the observed 680-pixel browser viewport without page-level horizontal overflow;
long provenance tables retain their own horizontal scroll area.

Local, ignored evidence is under `outputs/debug/phase9/`:

- `worker-preflight.json`, `local-http-checks.json`, `pytest.log`
- `live-history/ad711f78-ae40-4c31-b5ee-1c5a68551f51.json` (private original session)
- `live-browser-progress.json`, `live-public-state.json`, `live-validation.json`
- `downloaded-briefing.html`, `live-independent-workers.png`, `live-briefing.png`

These files and all private environment settings stay untracked. The validation
record above is portable; it does not imply ignored data exists on another laptop.

## Phase 9 human checkpoint — ACCEPTED October 4, 2026

The user was given exact steps for the following six checks and replied
**“all passed”**:

| Manual check | User-reported result |
| --- | --- |
| Both workers complete; 2 of 2 investigations validated; expected partial coverage | PASS |
| All eight measurements and their units | PASS |
| Historical scope, coverage, scientific explanation and limitations | PASS |
| All five conditions, source provenance and processing methods | PASS |
| History/search and reload preserve the same investigation | PASS |
| Downloaded standalone HTML opens and is readable with all required sections | PASS |

This records the current user's acceptance, not a new test run or a separate
named confirmation from either worker owner. Original raw validation reports
retain their historical `PENDING_USER` status; this document records the later
human decision. The manual review can be repeated using these saved-session steps:

Open the saved investigation at
`http://127.0.0.1:3000/session/ad711f78-ae40-4c31-b5ee-1c5a68551f51` while the
two local servers are running. No new worker run is needed for this review.

1. Confirm the investigation shows two completed workers and retained measurements.
2. Open the partial briefing. Confirm the historical dates, one-hour rainfall
   coverage, 97.6354% valid SAR coverage, demonstration conditions and limits are
   clear enough for the demo.
3. Open the downloaded HTML and confirm it is readable as a standalone report.

The initial automated, live and six Mac-side human checks pass.
The accepted development base is now `main`; it preserves the original
`codex/briefing-integration` implementation history. The additional three-screen
check on `codex/worker-viewers` also passed with human acceptance. Phase 10 has not started and
still needs its own reliability and final demo checkpoint.
