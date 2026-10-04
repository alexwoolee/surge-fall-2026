# Prompt-routed investigations and the Toddbrook worker

This work is on **`codex/toddbrook-private-worker`**. Use the same branch and commit
on all four devices. **Do not merge into `main` until the user explicitly approves.**
The existing configured-case flow on `main` remains available; the new Control
flow is selected with `--generic`.

Hydro and Flood process every resolved location/date request independently. The
Dam worker participates only for **Toddbrook Reservoir, Whaley Bridge,
Derbyshire, England**. Other locations never receive Toddbrook records. A nearby
bounding box alone does not enable the Dam worker.

The registered dam/spillway point is approximately **53.327995° N, 1.990050° W**.
The [Environment Agency application](https://www.gov.uk/government/publications/canal-and-river-trust-npswr037385-application-made-to-impound-water/canal-and-river-trust-application-made-to-impound-water)
places Toddbrook Dam at Whaley Bridge, grid reference SK0076081231. Environmental
workers use `bbox=[-2.10,53.25,-1.85,53.40]`, a surrounding analysis area, not an
official catchment or flood footprint. The dam worker binds its records to that
registered site. Later incident accounts do not enter its historical risk rules.

## Device assignments

| Owner | System | Service | Listener / dashboard |
| --- | --- | --- | --- |
| Kazi | Windows | Hydro | `http://100.100.3.2:8002/dashboard` |
| Alex | Windows | Flood | `http://100.100.3.3:8003/dashboard` |
| Karan | Linux | Dam | `http://100.100.3.4:8004/dashboard` |
| Ryan | macOS | Control + web interface | API `127.0.0.1:8001`; UI `http://127.0.0.1:3000` |

Keep the services on the private Tailscale network. Internal tokens are ignored;
NASA still requires its own Earthdata login. Generic prompt resolution and risk
screening are deterministic and do not require an OpenAI key or a paid model call.
No Node installation is required on worker laptops.

The private ZIP and extracted owner records belong **only on Karan's device**.
Hydro, Flood and Control must not open, mount, receive or copy those records. They
receive only the Dam worker's bounded derived response through Control. Do not
add the ZIP, dataset, evaluation files, or generated private artifacts to Git.
Only code and the placeholder instructions in `private_data/README.md` are shared.
The already supplied development copy is not a reason to distribute records to
other runtime devices.

## Get the matching code without losing work

Wait for any current investigation to finish. Stop the service in its own terminal
with Ctrl+C before changing its checkout. Preserve existing virtual environments,
Earthdata login, caches and ignored configuration. An already running old server
must be restarted from this branch before the joint check.

In an existing **worker checkout**, first run:

```sh
git status --short
git fetch --prune origin
git switch codex/toddbrook-private-worker
git pull --ff-only origin codex/toddbrook-private-worker
git rev-parse HEAD
```

Stop and inspect if there are local edits, a conflicting branch, or divergent
commits. Do not reset, clean, force checkout, overwrite UI work, or merge `main`.
The branch must have been published before another laptop can fetch it.

For a new separate worker checkout, run from a directory where you keep projects:

```sh
git clone --branch codex/toddbrook-private-worker https://github.com/alexwoolee/surge-fall-2026.git surge-fall-2026-toddbrook-worker
cd surge-fall-2026-toddbrook-worker
```

The commands below use this fresh dedicated checkout, leaving the prior `main`
checkout and UI work in place. If you intentionally reuse a clean existing worker
checkout, substitute its path without copying private data between devices.

Use **Python 3.12** and the existing pinned `requirements.txt`. Create a virtual
environment only if the checkout does not already have one. Do not upgrade to a
new Python major/minor version for this test.

## Kazi — Windows Hydro, live NASA acquisition

Use the separate worker checkout, for example:

```powershell
cd C:\Users\kazib\surge-fall-2026-toddbrook-worker
```

For a new environment only:

```powershell
py -3.12 -m venv .venv
```

Install/check dependencies, then save Earthdata authentication **on Kazi's device**:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe -c "import earthaccess; earthaccess.login(strategy='interactive', persist=True)"
```

Enter the NASA username/password in the terminal prompt, not in chat or a command
argument. Saved credentials remain local. Ensure this laptop can reach NASA's
services over the Internet. Hydro queries matching GPM/SMAP resources at runtime
for each resolved date/window and area, then downloads or reuses matching cached
files. **Do not supply the old fixed Hydro input ZIP as the generic input.** It is
not coverage for arbitrary historical requests. Products unavailable for a date
stay explicitly unavailable.

Start and leave this terminal running:

```powershell
.\.venv\Scripts\python.exe -m scripts.run_worker hydro --host 100.100.3.2 --port 8002
```

The launcher opens Kazi's own Hydro dashboard. It does not submit a job. Do not
install or inspect the private Toddbrook dataset on this device.

## Alex — Windows Flood, public geospatial acquisition

Use a separate worker checkout rather than overwriting UI work. If cloned in the
home directory:

```powershell
cd "$HOME\surge-fall-2026-toddbrook-worker"
```

For a new environment only:

```powershell
py -3.12 -m venv .venv
```

Then:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe -m scripts.run_worker flood --host 100.100.3.3 --port 8003
```

Flood queries public Sentinel-1, DEM and HAND sources for the resolved area and
historical request. It needs Internet access. Reusing or copying **nonprivate
geospatial caches only** is optional; it is not required to start. Do not copy
`private_data`, the owner ZIP, private record files, or another person's credentials.
A period before a product's coverage is reported as unavailable. Static terrain is
context and does not become a historical observation at the requested date.

## Karan — Linux Dam, local owner records only

Use the existing worker checkout, or clone the branch separately:

```sh
cd ~/surge-fall-2026-toddbrook-worker
```

For a new environment only:

```sh
python3.12 -m venv .venv
```

Then install pinned dependencies:

```sh
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m pip check
```

Transfer the user-supplied ZIP **directly to Karan**, using an approved private
method. Keep it outside the repository, for example `~/Downloads/todbrook.zip`.
Do not upload it to GitHub or another worker. Run the repository's installer;
do not run helpers bundled inside the ZIP:

```sh
.venv/bin/python -m scripts.install_private_dataset "$HOME/Downloads/todbrook.zip"
.venv/bin/python -m pytest -q tests/test_install_private_dataset.py tests/test_dam_worker.py
.venv/bin/python -m scripts.run_worker dam --host 100.100.3.4 --port 8004
```

Adjust only the ZIP pathname if its local filename differs. The installer extracts
exactly these five files from `toddbrook_dataset/data/` into the repository's ignored
`private_data/toddbrook_dataset/data/`:

- `weekly_ops_logs.jsonl`
- `se_reports.jsonl`
- `inspections_s10.jsonl`
- `maintenance_requests.jsonl`
- `instrumentation_log.jsonl`

Archive scripts, bytecode, documents, design records, timelines and evaluation
files are not extracted. ZIP paths, entry types, sizes, UTF-8 JSON-object lines,
record IDs, duplicate fields and finite numbers are checked before a complete data
directory is published. Limits are 32 MiB compressed, 512 entries, 4 MiB per member,
64 MiB total declared content, 10,000 records per consumed file and 64 KiB per line.
The worker additionally validates the fields used for the requested assessment.

An identical install is safe to repeat and preserves any pre-existing extra local
files without reading or replacing them. If required files differ or are missing
from an existing install, installation stops. Preserve and inspect that local
folder; do not force an overwrite. An interrupted install may leave a lock; first
confirm no installer is running before investigating it locally. The archive is
never executed, and the installer has no network operation.

## Ryan — macOS Control and interface

Use the matching branch in the Control checkout:

```sh
cd "/Users/diamster/Stormhacks 2026/surge-fall-2026"
.venv/bin/python -m pip install -r requirements.txt
```

Create ignored `.env.reservoir.local` in the repository root:

```dotenv
HYDRO_WORKER_URL=http://100.100.3.2:8002
FLOOD_WORKER_URL=http://100.100.3.3:8003
DAM_WORKER_URL=http://100.100.3.4:8004
MESHMIND_CONTROL_SOURCE_IP=100.100.3.5
```

The source-IP line is optional; when set, it must belong to Ryan's Mac. The three
worker URLs must be different origins. Do not add private-data paths, NASA
credentials or internal tokens. Keep existing legacy `.env` files intact.

Start Control in one terminal:

```sh
.venv/bin/python -m backend.control.serve --generic --worker-env-file .env.reservoir.local --history-dir outputs/debug/reservoir/history
```

Start the interface in another terminal after stopping any old UI listener:

```sh
cd "/Users/diamster/Stormhacks 2026/surge-fall-2026/frontend"
npm ci
npm run build
npm run start
```

The UI defaults to Control at `http://127.0.0.1:8001`. Reuse an existing matching
UI process only if its production build contains this branch's changes. Leave
Control's own listener on loopback. This generic command needs neither a fixed
GPM/SMAP file list nor OpenAI configuration. Control must not read the ZIP or
private dataset; Karan's worker performs that analysis.

## Joint historical checks

Toddbrook and Abbotsford / Sumas Prairie are registered place names. An otherwise
unregistered location requires an explicit `bbox=[west,south,east,north]` in WGS84,
within two degrees per axis. Control does not guess its geometry.

Before submitting anything, confirm the same Git commit on all devices and that
all three worker dashboards are open. Submit one investigation at a time from
Ryan's UI and wait for its terminal result. Do not resubmit simply because a worker
finishes between browser polls. Hydro downloads may take longer for an uncached
date; missed data remains a coverage limitation rather than zero rainfall.

Use this prompt, replacing only the ISO date for each requested comparison:

> Assess flood risk at Toddbrook Reservoir, Whaley Bridge, Derbyshire, England as of 2007-12-04. Combine Hydro, Flood and available dam records; explain risk level, evidence confidence and coverage gaps.

Dates to compare:

| Period | As-of dates |
| --- | --- |
| 2007 | `2007-12-04`, `2007-12-09`, `2007-12-16` |
| 2019 | `2019-03-01`, `2019-07-26`, `2019-07-31` |

A single ISO date requests that **UTC calendar day** from Hydro/Flood. An explicit
ordered range is inclusive, bounded to at most seven days. The final date is the
historical cutoff. The Dam worker uses only records both observed and available
by that cutoff; recurring operational indicators use an inclusive preceding
90-day window, bounded by the supported private period. Private operational
coverage is **2007-09-03 through 2008-02-29** and **2015-10-01 through 2019-07-31**.
Other historical dates can still run Hydro/Flood; Toddbrook's Dam result outside
those windows must show unknown/unavailable private evidence, not borrow later
records. SMAP and Sentinel-1 do not cover the 2007 dates, so missing products there
are expected and must remain explicit.

Confirm shared task/session identity, independently completed or explicitly
unavailable worker evidence, matching location/dates, actual product coverage,
risk index, evidence confidence, and the exported briefing. High/critical concern
must be prominent. Risk and confidence are screening/coverage indicators,
**not calibrated flood or dam-failure probabilities**. These results do not provide
breach hydraulics, evacuation instructions, or a determination that an area is safe.
Do not require a particular risk level before reading the returned evidence.

Negative routing check (the following box is **operator-supplied for testing**, not
an official or independently verified reservoir/catchment boundary):

> Investigate Combs Reservoir on 2019-07-31 using bbox=[-1.94,53.29,-1.90,53.32]. Review rainfall, soil moisture, candidate surface water and terrain, with coverage limitations.

Only Hydro and Flood should appear in that session. Karan's Dam dashboard must
retain its previous task with no new accepted task for this request. The Control
briefing must not use Toddbrook private evidence. Missing product evidence is
still a valid explicitly partial outcome; it is not a reason to call the Dam worker.
Keep the branch unmerged until the user reviews the joint results and approves.

Date-coverage check:

> Assess flood risk at Toddbrook Reservoir, Whaley Bridge, Derbyshire, England as of 2020-07-31. Explain risk level, evidence confidence and coverage gaps.

Hydro and Flood must query that date; Dam must return unknown private coverage
without substituting its 2019 records. More recent requests work the same way,
subject to publication delays and source coverage. This is historical analysis,
not a forecast for dates that have not occurred.

## Copyable Codex handoffs

**Kazi — Hydro**

> In my separate Windows worker checkout, read docs/TODDBROOK_SETUP.md and use codex/toddbrook-private-worker. Preserve all UI work, credentials, caches and local edits; do not reset, clean, merge or push. Confirm Python 3.12, install the pinned requirements, and run the appropriate offline tests. Help me save Earthdata login interactively on this device without printing credentials. Hydro must query NASA at runtime for Control's requested location/dates; do not use the old fixed input ZIP as generic coverage. Do not receive, inspect or mount any private Toddbrook records. Start one Hydro process with scripts.run_worker on 100.100.3.2:8002 and leave its own dashboard open. Report commit, test summary and readiness only; wait for Ryan to submit the joint task.

**Alex — Flood**

> In a separate Windows worker checkout, read docs/TODDBROOK_SETUP.md and use codex/toddbrook-private-worker. Preserve my other work and local settings; do not reset, clean, merge or push. Confirm Python 3.12, install pinned requirements and run the appropriate offline tests. Flood uses public live acquisition for the requested historical location/dates and static terrain context. Only nonprivate geospatial caches may be reused; do not receive, inspect or mount the private Toddbrook ZIP or records. Start one Flood process with scripts.run_worker on 100.100.3.3:8003 and leave its own dashboard open. Report commit, test summary and readiness; do not submit extra tasks or claim a joint run passed yet.

**Karan — Dam**

> On my Linux worker checkout, read docs/TODDBROOK_SETUP.md and use codex/toddbrook-private-worker. Preserve existing work and owner data; do not reset, clean, merge, push or upload private files. Receive the owner ZIP directly on this device only and run scripts.install_private_dataset with its local path; never execute ZIP helpers. If the installer finds conflicting existing data, preserve it and report the fixed diagnostic rather than overwriting. Run the installer and Dam tests using their test fixtures, then start one Dam process with scripts.run_worker on 100.100.3.4:8004. Keep the owner records local; only bounded derived results may leave the worker. Leave the dashboard open and report commit, test summary and readiness without raw records, labels, archive contents or credentials. Wait for Ryan's Toddbrook task and verify a non-Toddbrook task does not reach this worker.

**Ryan — Control**

> In the Mac Control checkout, read docs/TODDBROOK_SETUP.md and use codex/toddbrook-private-worker without merging or pushing. Preserve other work and existing configuration. Configure the three worker URLs in ignored .env.reservoir.local, start backend.control.serve with --generic and the separate reservoir history directory, and build/start the UI on loopback. This deterministic mode needs no OpenAI key or paid call. Do not open, mount or copy the private ZIP/dataset on Control, Hydro or Flood. Wait for all owners to confirm the same commit and readiness before submitting one agreed historical request. Validate returned aggregate evidence, conditional Dam routing, honest coverage, risk/confidence wording and the standalone download. Keep the branch unmerged until I explicitly approve.
