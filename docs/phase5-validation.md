# Phase 5 — Control dispatch and remote worker checkpoint

Branch: `codex/control-dispatch`, based on accepted Phase 4 checkpoint `22c17ca`.
Control dispatches bounded HTTP tasks sequentially to Hydro and Flood. Numerical
processing stays in the existing worker services. No platform-specific network
API or Tailscale library is required by the application.

**Remote phase gate: pending execution on three physical laptops.**
Tailscale is configured and peer connectivity has been verified. Ryan is Control
on macOS, Kazi is Hydro on Windows, and Karan is Flood on Linux. The worker
servers must be started and kept running before the authenticated remote checks. Local HTTP checks cannot pass
this gate. Phase 6 starts only after this checkpoint is accepted.

## 1. Get the same code and Python environment on every laptop

Use the tested `codex/control-dispatch` branch on all machines. In an existing
clean checkout after that branch is available on origin:

```sh
git fetch origin
git switch --track origin/codex/control-dispatch
git rev-parse HEAD
```

If the branch is already checked out, use `git pull --ff-only` instead of
`git switch --track`. Do not reset a checkout with local work. Compare the full
commit hash on all three machines. The phase branch includes earlier accepted
phases; do not pull `main` expecting those local changes to be there.

For a fresh clone, use your existing GitHub access:

```sh
git clone --branch codex/control-dispatch https://github.com/alexwoolee/surge-fall-2026.git
cd surge-fall-2026
```

Create a separate Python **3.12** virtual environment on each device. Do not copy
the Mac's `.venv` to another operating system. From the repository directory:

macOS / Linux:

```sh
python3.12 -m venv .venv
.venv/bin/python --version
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m pip check
```

Windows PowerShell:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe --version
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip check
```

The Python code is portable. Dependency installation and real execution still
need verification on the actual Windows/Linux workers; the development suite
has been run on macOS. If an older `.venv` exists, check its Python version
before reusing it. The project needs Python 3.12 for the pinned earthaccess.

## 2. Connect the devices when the local network isolates clients

Install Tailscale using its official instructions for
[Windows](https://tailscale.com/docs/install/windows),
[macOS](https://tailscale.com/docs/install/mac), or
[Linux](https://tailscale.com/docs/install/linux). Sign in on each device and
join the same tailnet, or have its owner grant the appropriate device access.
Do account authentication locally. No Earthdata or Tailscale credentials belong
in chat, the repository or the validation report.

Tailscale assigns private addresses and can relay encrypted traffic when direct
connections are unavailable. It supplies connectivity; the worker service still
needs to run, and tailnet policy and each device's firewall must permit Control
to reach the selected worker port. See
[connect to devices](https://tailscale.com/docs/how-to/connect-to-devices) and
[device connectivity](https://tailscale.com/docs/reference/device-connectivity).

Find each laptop's Tailscale IPv4 address in the app. If the CLI is available:

```sh
tailscale ip -4
tailscale status
```

From Control, use `tailscale ping HYDRO_TAILSCALE_IP` and
`tailscale ping FLOOD_TAILSCALE_IP` to check the overlay. Replace these labels
with actual addresses. A successful ping alone does not prove the HTTP port is
reachable. Use the HTTP preflight below after starting the workers. There is no
need to expose either API publicly or configure router port forwarding.

## 3. Prepare NASA files on Laptop 2 (Hydro)

Either copy these **data files only** from the existing Mac cache to the matching
folders in Laptop 2's checkout:

```text
data/cache/gpm/3B-HHR.MS.MRG.3IMERG.20211115-S000000-E002959.0000.V07B.HDF5
data/cache/gpm/3B-HHR.MS.MRG.3IMERG.20211115-S003000-E005959.0030.V07B.HDF5
data/cache/smap/SMAP_L4_SM_gph_20211114T223000_Vv8010_001.h5
```

Or establish a saved Earthdata login and download them **on Laptop 2**:

macOS / Linux:

```sh
.venv/bin/python -c "import earthaccess; earthaccess.login(strategy='interactive', persist=True)"
.venv/bin/python -m scripts.validate.prepare_hydro_data
```

Windows PowerShell:

```powershell
.\.venv\Scripts\python.exe -c "import earthaccess; earthaccess.login(strategy='interactive', persist=True)"
.\.venv\Scripts\python.exe -m scripts.validate.prepare_hydro_data
```

The helper only downloads the configured two GPM granules and one SMAP state;
it does not launch both workers. Existing saved credentials on Control are not
transferred. A worker using copied files needs no Earthdata login at runtime.
Laptop 3 (Flood) reads the public Sentinel-1/DEM/HAND sources and needs outbound
Internet access during processing. Nondefault data folders can be set with
`MESHMIND_GPM_DIR` and `MESHMIND_SMAP_DIR` on Hydro.

## 4. Start one worker on each remote laptop

Create a separate random token for each worker, for example with Python's
`secrets.token_urlsafe(32)`, and share it privately with Control. Replace
`YOUR_HYDRO_TOKEN`, `YOUR_FLOOD_TOKEN` and the IP labels before running these
commands. Set environment variables in the same terminal as the server.
`.env` is not loaded automatically. Keep both terminals open and laptops awake.

Bind the worker to **that worker's Tailscale IP**. Use exactly one Uvicorn process;
`--workers 1` overrides a possible `WEB_CONCURRENCY` environment setting.
Do not add `--reload`.

Laptop 2, macOS / Linux:

```sh
export MESHMIND_WORKER_TOKEN='YOUR_HYDRO_TOKEN'
.venv/bin/python -m uvicorn backend.workers.hydro.main:create_app --factory --workers 1 --host HYDRO_TAILSCALE_IP --port 8002
```

Laptop 2, Windows PowerShell:

```powershell
$env:MESHMIND_WORKER_TOKEN = 'YOUR_HYDRO_TOKEN'
.\.venv\Scripts\python.exe -m uvicorn backend.workers.hydro.main:create_app --factory --workers 1 --host HYDRO_TAILSCALE_IP --port 8002
```

Laptop 3, macOS / Linux:

```sh
export MESHMIND_WORKER_TOKEN='YOUR_FLOOD_TOKEN'
.venv/bin/python -m uvicorn backend.workers.flood.main:create_app --factory --workers 1 --host FLOOD_TAILSCALE_IP --port 8003
```

Laptop 3, Windows PowerShell:

```powershell
$env:MESHMIND_WORKER_TOKEN = 'YOUR_FLOOD_TOKEN'
.\.venv\Scripts\python.exe -m uvicorn backend.workers.flood.main:create_app --factory --workers 1 --host FLOOD_TAILSCALE_IP --port 8003
```

Confirm the correct worker port is permitted on the Tailscale interface by host
firewall and tailnet policy. A bind error usually means the chosen address is
not assigned to this device or Tailscale is not connected. A HTTP 401 means the
API is reachable but the token is missing or different.

## 5. Configure and run Control (Laptop 1)

macOS / Linux:

```sh
export HYDRO_WORKER_URL='http://HYDRO_TAILSCALE_IP:8002'
export FLOOD_WORKER_URL='http://FLOOD_TAILSCALE_IP:8003'
export HYDRO_WORKER_TOKEN='YOUR_HYDRO_TOKEN'
export FLOOD_WORKER_TOKEN='YOUR_FLOOD_TOKEN'
.venv/bin/python -m scripts.validate.validate_remote_workers --confirm-separate-laptops
```

Windows PowerShell:

```powershell
$env:HYDRO_WORKER_URL = 'http://HYDRO_TAILSCALE_IP:8002'
$env:FLOOD_WORKER_URL = 'http://FLOOD_TAILSCALE_IP:8003'
$env:HYDRO_WORKER_TOKEN = 'YOUR_HYDRO_TOKEN'
$env:FLOOD_WORKER_TOKEN = 'YOUR_FLOOD_TOKEN'
.\.venv\Scripts\python.exe -m scripts.validate.validate_remote_workers --confirm-separate-laptops
```

Use `--confirm-separate-laptops` only after personally verifying the three
processes run on three physical laptops. Do not use it for virtual machines,
containers or multiple processes on the same laptop. Hostnames must be distinct
for this conservative gate; hostname/UUID reports support the operator's check
but do not cryptographically prove hardware identity. Tailscale relaying does
not relocate computation: each worker still runs on its own host.

The validator creates a fresh investigation ID, verifies unauthenticated calls
are rejected, runs Hydro then Flood, validates both returned results, and retries
the identical completed submissions to verify they do not execute twice. It
records actual worker receipt/start/completion times, reported hostname, process
startup UUID, Control observations, provenance and full numerical evidence in
`outputs/debug/remote-workers/result.json`. Tokens are omitted. In worker
terminals, observe the matching POST/poll requests and completed task IDs.

Expected successful checkpoint: `PASS; checkpoint: PENDING_USER`. Compare the
real values with the accepted Phase 4 run: rainfall mean **6.6504165 mm**,
surface/root-zone moisture **0.4084949 / 0.3924146 m³/m³**, candidate-water area
**88.0997 km²**, SAR valid coverage **97.6354%**, DEM/HAND means
**254.308864 / 45.452025 m**. Candidate water remains a threshold-derived surface
water proxy, not confirmed flooding.

The direct Control entry point is also available for explicit resource names:

```sh
.venv/bin/python -m backend.control.main --gpm-resources 3B-HHR.MS.MRG.3IMERG.20211115-S000000-E002959.0000.V07B.HDF5 3B-HHR.MS.MRG.3IMERG.20211115-S003000-E005959.0030.V07B.HDF5 --smap-resource SMAP_L4_SM_gph_20211114T223000_Vv8010_001.h5
```

On Windows substitute `.\.venv\Scripts\python.exe` for the Python path.
Use `--task-id ID_FROM_REPORT` with the identical inputs to reconcile a prior
ambiguous request. A new ID starts new work. Worker history is memory-only and
lost on restart, so reconciliation after restart can re-execute the task.

## Failure handling and limits

- Each dispatch has a total deadline (default 600 seconds) and each HTTP request
  has a 15-second deadline including streaming the body. Redirects are not
  followed, proxy environment variables are not used, and response JSON is
  bounded to 8 MiB. HTTPS verifies certificates normally.
- A lost POST response records acceptance as unknown. Control neither blindly
  retries with a new ID nor cancels work. A timeout ends Control's wait; the
  worker may still finish and retain its result.
- Worker rejection, transport error, timeout, malformed/changed identity and
  processing failure are distinct outcomes with sanitized diagnostics. Valid
  partial Flood evidence is retained. A Flood failure does not remove a
  completed Hydro result; both branch records stay in the collection.
- Phase 5 dispatches sequentially. After a timeout, remote work may continue
  while the next branch is dispatched, so the sequence is not a guarantee of
  non-overlapping physical execution. Phase 6 will explicitly launch both calls
  concurrently and prove overlap after checking clock agreement.
- There is no automatic failover to local processors, cancellation endpoint,
  durable queue, fusion logic, agent layer or frontend in this milestone.

Timeout environment overrides are documented in `.env.example`. They are
validated before dispatch. Longer waits are not a substitute for fixing
authentication, resource or connectivity failures.

## Development checks and checkpoint status

On Control, using the cached real NASA files:

```sh
.venv/bin/python -m scripts.validate.validate_remote_workers --local-check
.venv/bin/python -m scripts.validate.validate_dispatch_failures
.venv/bin/python -m pytest -v
.venv/bin/python -m pip check
git diff --check
```

`--local-check` starts temporary loopback servers and exercises Control over real
HTTP with real data. It must report `PASS_LOCAL_ONLY / PENDING_REMOTE_LAPTOPS`,
never a completed Phase 5. Both servers are stopped afterward. The separate failure checkpoint uses a
small synthetic Hydro fixture and controlled TCP faults: a lost POST response,
a dropped Flood connection after Hydro succeeds, and a missing Hydro file.
These negative checks never count as remote or real-data proof. No HTML review
is necessary for this phase.

Recorded on 2026-10-03 locally (2026-10-04 UTC):

- Full suite: **535 tests PASS**. Existing deprecation warnings remain visible.
- Real-data Control dispatch over loopback: **PASS_LOCAL_ONLY**. Hydro ran from
  03:47:18.683312 to 03:47:19.005585 UTC; Flood ran from 03:47:19.210113 to
  03:48:29.243139 UTC. Both reported this Mac's hostname and distinct process
  startup UUIDs. Results match the Phase 4 reference measurements above.
- Live TCP failure checkpoint: **PASS**, all three negative scenarios.
- `pip check` and `git diff --check`: **PASS**.
- Evidence: `outputs/debug/remote-workers/result.json`,
  `outputs/debug/dispatch-failures/result.json`, and `outputs/debug/phase5-pytest.log`.

Cross-platform remote execution and the user checkpoint remain pending.
The implementation is kept on `codex/control-dispatch`; it has not been merged
into `main`. Only that separate branch is intended for remote distribution.


## Windows portability follow-up and Control source address

Kazi reported the original `707f3b0` Windows checkpoint as 530 passed / 5 failed.
His NASA checksums, native imports, local real Hydro measurements and authenticated
API status checks passed. Those are useful local checks, not a completed remote gate.

The follow-up fixes preserve the existing safety checks:

- File URI conversion now handles native Windows drive and UNC paths before
  comparing output paths against raster sources. Existing actual overwrite tests
  remain; portable Windows decoding regressions also run on macOS/Linux.
- Temporary Windows validation servers use a dedicated process group, graceful
  shutdown and an owned-process-tree fallback. Parent log handles close before
  bounded sharing-lock checks. Persistent cleanup failures still fail validation.
- The real symlink test reports a capability skip only for Windows WinError 1314.
  Mandatory resolved-path containment tests still run on every OS, including a
  misleading sibling-directory prefix. Other filesystem errors remain failures.
  Enabling symlink privileges is not required to run a worker.

The updated suite must be rerun on Windows. A Windows machine without symlink
creation privileges should report that one explicit skip; do not report it as a
passed real-symlink test.

Follow-up verification on Ryan's Mac: **618 tests passed**, including the live
TCP failure scenarios and a real socket source-address binding check. `pip check`
and `git diff --check` passed. Evidence is in
`outputs/debug/phase5-portability-pytest.log`. This does not establish native
Windows cleanup behavior or the physical-laptop checkpoint. Kazi's Hydro endpoint
is reachable; Karan's Flood startup and the authenticated remote run are next.

On Ryan's Mac, normal TCP connections to the Tailscale worker IPs returned
`EADDRNOTAVAIL`, while binding the socket to the Mac's actual Tailscale address
reached Hydro and returned the expected unauthenticated HTTP 401. Control now
accepts an optional literal source IP in `MESHMIND_CONTROL_SOURCE_IP`. This uses
HTTPX's documented local-address transport setting; it does not change system
routes, worker processing or the physical-deployment gate.

For this deployment, set on Control only:

```sh
export MESHMIND_CONTROL_SOURCE_IP='100.100.3.5'
```

The setting is optional and defaults to normal OS source selection. Use an
address actually assigned to Control. The dispatcher and validator authentication
and duplicate-submission checks all use the same setting. Local fixture checks
continue to bind loopback normally.

Tests exit after completion. They do **not** leave the production worker servers
running. On each worker, pull the same updated branch, then start Uvicorn with the
commands in section 4 and leave that terminal open. Restart running workers after
pulling code; compare `git rev-parse HEAD` on all three machines before the real
physical-laptop validator. Phase 5 remains pending until that validator and the
human checkpoint pass. Phase 6 has not started.
