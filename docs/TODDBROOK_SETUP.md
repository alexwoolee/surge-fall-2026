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

The private ZIP and sanitized runtime records belong **only on Karan's device**.
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

Alex uses a fresh dedicated checkout below, leaving other projects untouched.
Karan can reuse his known clean worker checkout and its Python 3.12 environment,
or choose the fresh-clone alternative. Never copy private data between devices.

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

## Alex — fresh Windows Flood setup

**1. Install Git, Python 3.12 and Tailscale.** Open PowerShell and run:

```powershell
winget install --exact --id Git.Git --source winget
winget install --exact --id Python.Python.3.12 --source winget
winget install --exact --id Tailscale.Tailscale --source winget
```

If `winget` is missing, install or update **App Installer** from Microsoft Store
using [Microsoft's WinGet instructions](https://learn.microsoft.com/en-us/windows/package-manager/winget/).
These exact package IDs are listed in Microsoft's manifests for
[Git](https://github.com/microsoft/winget-pkgs/blob/master/manifests/g/Git/Git/2.54.0/Git.Git.locale.en-US.yaml),
[Python 3.12](https://github.com/microsoft/winget-pkgs/blob/master/manifests/p/Python/Python/3/12/3.12.9/Python.Python.3.12.locale.en-US.yaml)
and [Tailscale](https://github.com/microsoft/winget-pkgs/blob/master/manifests/t/Tailscale/Tailscale/1.102.4/Tailscale.Tailscale.yaml).
The commands select the available release of each package; they do not pin those
reference-manifest versions.

**2. Close PowerShell, reopen it, and verify the tools.** Open Tailscale from the
Start menu and sign in to the team's tailnet; see the
[official Windows setup](https://tailscale.com/docs/install/windows).

```powershell
git --version
py -3.12 --version
& "$env:ProgramFiles\Tailscale\tailscale.exe" ip -4
```

Python must report `3.12.x`. Alex's Tailscale address should be `100.100.3.3`.
If it differs, tell Ryan the actual address before using the listener command;
the bind address and Ryan's worker URL must agree. Do not guess an address.

**3. Clone into a new folder and install the project.** If GitHub asks, sign in
using Alex's account with repository access. Do not paste credentials into commands.
If the target folder already exists, preserve it and use the existing-checkout
instructions above instead of cloning over it.

```powershell
cd $HOME
git clone --branch codex/toddbrook-private-worker https://github.com/alexwoolee/surge-fall-2026.git surge-fall-2026-toddbrook-worker
cd surge-fall-2026-toddbrook-worker
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe -m pytest -q
git rev-parse HEAD
```

Use the explicit virtual-environment executable as shown; no PowerShell activation
or execution-policy change is required. No Node, OpenAI key, NASA login or owner ZIP
is needed on the Flood laptop.

**4. Start Flood and leave this terminal open:**

```powershell
.\.venv\Scripts\python.exe -m scripts.run_worker flood --host 100.100.3.3 --port 8003
```

The worker opens `http://100.100.3.3:8003/dashboard`. From another PowerShell window,
check the local listener:

```powershell
Invoke-RestMethod http://100.100.3.3:8003/status
```

Report the commit, test summary and whether `/status` reports idle to Ryan. Ryan
still needs to verify access from his Mac and run the shared investigation.

Flood queries public Sentinel-1 observations for the requested location and dates.
This generic dated mode excludes undated DEM/HAND before discovery or file reads,
reporting `observation_date_unverified`; the legacy configured flow is unchanged.
It needs Internet access. Reusing **nonprivate geospatial caches only** is optional.
Do not receive or copy `private_data`, the owner ZIP, private records, or another
person's credentials. A period before a product's coverage is unavailable. Do not
disable the Windows firewall if remote access fails; report the connection result
so the listener, tailnet policy and narrowly scoped access can be checked.

## Karan — Linux Dam, existing Python 3.12 setup

**1. Stop the old Flood service.** Wait until its current task finishes, then press
Ctrl+C in the terminal that runs Karan's old Flood worker. Karan now runs **Dam on
8004**; Alex runs Flood on 8003. Do not kill unrelated Python processes.

Reuse Karan's known worker checkout. Check for local edits first:

```sh
cd ~/surge-fall-2026-worker
git status --short
```

If that prints changed or untracked work, preserve and inspect it before switching.
If clean, update the branch and verify Python/Tailscale:

```sh
git fetch --prune origin
git switch codex/toddbrook-private-worker
git pull --ff-only origin codex/toddbrook-private-worker
git rev-parse HEAD
.venv/bin/python --version
tailscale ip -4
```

Expect Python `3.12.x` and Tailscale `100.100.3.4`. Do not reset or clean the checkout.
If the old checkout is not suitable, create a separate one instead:

```sh
cd ~
git clone --branch codex/toddbrook-private-worker https://github.com/alexwoolee/surge-fall-2026.git surge-fall-2026-toddbrook-worker
cd surge-fall-2026-toddbrook-worker
python3.12 -m venv .venv
```

If `python3.12` is unavailable through Karan's pyenv selection, use the already
installed `3.12.13` to create the **new** environment:

```sh
PYENV_VERSION=3.12.13 pyenv exec python -m venv .venv
.venv/bin/python --version
```

Choose one environment-creation command, only when `.venv` is absent. Preserve an
existing environment; do not overwrite it or change the system Python.

**2. Install dependencies and rerun offline data preparation.** This installer
rerun is required even when the earlier five runtime files already exist:

```sh
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m pip check
.venv/bin/python -m scripts.install_private_dataset "$HOME/Downloads/todbrook.zip"
.venv/bin/python -m pytest -q tests/test_install_private_dataset.py tests/test_dam_snapshots.py tests/test_dam_worker.py
```

Transfer the user-supplied ZIP **directly to Karan**, using an approved private
method, before running the installer. Adjust only the ZIP pathname if needed.
Keep the raw archive outside the runtime folder, for example in `~/Downloads/`;
do not upload it to GitHub, share it with other workers, or execute its helpers.

The installer reads the five approved JSONL members under `toddbrook_dataset/data/`
and prepares **sanitized, model-needed fields only** in ignored directories:

```text
private_data/toddbrook_runtime/data/                      # prepared source
private_data/toddbrook_runtime/as_of/YYYY-MM-DD/data/      # exact-date inputs
```

The runtime files are `weekly_ops_logs.jsonl`, `se_reports.jsonl`,
`inspections_s10.jsonl`, `maintenance_requests.jsonl` and `instrumentation_log.jsonl`.
Preparation selects a fixed field allowlist; discarded origin/classification
metadata is not interpreted or passed into runtime data. Raw notes, identities,
origin labels, evaluation data, archive scripts, bytecode, documents, design
records and timelines are excluded. Neither the worker nor the public API/UI
receives those discarded fields. The original archive is unchanged; fields are
removed only from prepared copies. The raw archive remains separate on Karan's
device.

Preparation builds the date snapshots offline. Each contains only records both
observed and available by the end of its UTC assessment day. Later maintenance
closures are absent from that snapshot. At job time, Dam opens **only the selected
day's five files**, never the full prepared source or another date's snapshot.
Missing snapshots fail explicitly; the worker cannot rebuild them from all records
or fall back to the full source during a task.

The bounded archive and record checks run before publishing the complete runtime
directories. Identical prepared data can be installed again, and the rerun adds
missing snapshots to a matching earlier installation. Conflicting or incomplete
existing snapshot sets stop installation; preserve them and investigate locally
rather than forcing an overwrite. Do not point the worker at the old raw
`private_data/toddbrook_dataset/data/` copy. Only bounded derived results may leave
the Dam worker.

**3. Start Dam and leave this terminal open:**

```sh
export MESHMIND_DAM_DATA_DIR="$PWD/private_data/toddbrook_runtime/data"
.venv/bin/python -m scripts.run_worker dam --host 100.100.3.4 --port 8004
```

Run that block from the selected repository root. Keep the base setting ending in
`runtime/data`; the worker derives its sibling `as_of/<requested-date>/data` path.
The explicit value replaces any old data-directory override. The launcher opens
`http://100.100.3.4:8004/dashboard`. From another terminal:

```sh
curl --fail http://100.100.3.4:8004/status
```

Report the commit, test summary, installer outcome and idle status to Ryan, without
raw records or classification metadata. NASA login, Node and an OpenAI key are
not required on the Dam device. A local idle response is readiness, not proof that
the new physical-laptop investigation has passed.

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
.venv/bin/python -m backend.control.serve --generic --worker-env-file .env.reservoir.local --history-dir outputs/debug/reservoir-cutoff/history
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
Use this new history directory for the cutoff-aware runs. Preserve earlier
`outputs/debug/reservoir/history` results as historical evidence; do not load them
into this run's store because the strict Dam result contract has changed.

## Joint historical checks

Toddbrook and Abbotsford / Sumas Prairie are registered place names. An otherwise
unregistered location requires an explicit `bbox=[west,south,east,north]` in WGS84,
within two degrees per axis. Control does not guess its geometry.

Before submitting anything, confirm the same Git commit on all devices and that
all three worker dashboards are open. Submit one investigation at a time from
Ryan's UI and wait for its terminal result. Do not resubmit simply because a worker
finishes between browser polls. Hydro downloads may take longer for an uncached
date; missed data remains a coverage limitation rather than zero rainfall.

Run these two requested assessments separately:

> Assess flood risk at Toddbrook Reservoir, Whaley Bridge, Derbyshire, England as of 2019-08-01. Combine Hydro, Flood and available dam records; explain risk level, evidence confidence and coverage gaps. Use observations through the end of that UTC day only.

> Assess flood risk at Toddbrook Reservoir, Whaley Bridge, Derbyshire, England as of 2007-12-09. Combine Hydro, Flood and available dam records; explain risk level, evidence confidence and coverage gaps. Use observations through the end of that UTC day only.

A single ISO date requests that **UTC calendar day** from Hydro/Flood. An explicit
ordered range is inclusive, bounded to at most seven days. The final date is the
**end-of-day cutoff** (the following midnight is an exclusive endpoint). Modern
reprocessed estimates of historical environmental observations are allowed; this
is not a recreation of the public products available on that date. Observations
after the cutoff must not enter the results. Undated DEM/HAND remain unavailable
with `observation_date_unverified` in this generic flow.

Dam uses its prepared snapshot containing only records both observed and available
by the cutoff, without future maintenance closures. Recurring operational
indicators use an inclusive preceding 90-day window, bounded by the observed
period. Private operational coverage remains **2007-09-03 through 2008-02-29** and
**2015-10-01 through 2019-07-31**. Assessment dates may extend at most seven days
beyond either endpoint, using last-known evidence with its actual age. Thus
**2019-08-01 uses July 31 or earlier observations**, not newly invented August 1
records. The final tail days are 2008-03-07 and 2019-08-07; other gaps must show
unknown/unavailable private coverage. Hydro/Flood still query their requested
dates. SMAP and Sentinel-1 do not cover 2007, so those missing products are expected
and must remain explicit.

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

> In my separate Windows worker checkout, read docs/TODDBROOK_SETUP.md and use codex/toddbrook-private-worker. Preserve all UI work, credentials, caches and local edits; do not reset, clean, merge or push. Confirm Python 3.12, install the pinned requirements, and run the appropriate offline tests. Help me save Earthdata login interactively on this device without printing credentials. Hydro must query NASA at runtime for Control's requested location/dates; do not use the old fixed input ZIP as generic coverage. Modern reprocessed historical estimates are allowed, but observations after the requested UTC day's cutoff are excluded. Do not receive, inspect or mount any private Toddbrook records. Start one Hydro process with scripts.run_worker on 100.100.3.2:8002 and leave its own dashboard open. Report commit, test summary and readiness only; wait for Ryan to submit the joint task.

**Alex — Flood**

> In a separate Windows worker checkout, read docs/TODDBROOK_SETUP.md and use codex/toddbrook-private-worker. Preserve my other work and local settings; do not reset, clean, merge or push. Confirm Python 3.12, install pinned requirements and run the appropriate offline tests. Flood queries public historical satellite observations at runtime; generic dated tasks exclude undated DEM/HAND before discovery or file reads. Modern reprocessing is allowed, but observations after the requested UTC day's cutoff are excluded. Only nonprivate geospatial caches may be reused; do not receive, inspect or mount the private Toddbrook ZIP or records. Start one Flood process with scripts.run_worker on 100.100.3.3:8003 and leave its own dashboard open. Report commit, test summary and readiness; do not submit extra tasks or claim a joint run passed yet.

**Karan — Dam**

> On my Linux worker checkout, read docs/TODDBROOK_SETUP.md and use codex/toddbrook-private-worker. Preserve existing work and owner data; do not reset, clean, merge, push or upload private files. Rerun scripts.install_private_dataset with the owner ZIP's local path even if the previous sanitized files exist: it must prepare offline exact-date inputs in private_data/toddbrook_runtime/as_of/YYYY-MM-DD/data. Keep the raw ZIP separate and never execute its helpers. Preserve and report any conflicting data rather than overwriting it. Run installer, snapshot and Dam tests using fixtures, then keep MESHMIND_DAM_DATA_DIR at this checkout's private_data/toddbrook_runtime/data and start one Dam process with scripts.run_worker on 100.100.3.4:8004. At runtime, the worker must open only the requested day's snapshot, with no future records or future closures and no fallback to the full prepared source. Keep owner records local and emit bounded derived results without origin/classification or evaluation data. Leave the dashboard open and report commit, test summary, installer outcome and readiness without raw records or credentials. Wait for Ryan's agreed August 1, 2019 and December 9, 2007 tasks; verify other locations never reach this worker.

**Ryan — Control**

> In the Mac Control checkout, read docs/TODDBROOK_SETUP.md and use codex/toddbrook-private-worker without merging or pushing. Preserve other work and existing configuration. Configure the three worker URLs in ignored .env.reservoir.local, start backend.control.serve with --generic and --history-dir outputs/debug/reservoir-cutoff/history, and build/start the UI on loopback. Preserve earlier history separately. This deterministic mode needs no OpenAI key or paid call. Do not open, mount or copy the private ZIP/dataset on Control, Hydro or Flood. Wait for matching commits and readiness, including Karan's completed snapshot preparation, before submitting the agreed August 1, 2019 and December 9, 2007 runs one at a time. Validate aggregate evidence, no observations after the cutoff, conditional Dam routing, honest coverage/age, risk/confidence wording and the standalone download. Keep the branch unmerged until I explicitly approve.
