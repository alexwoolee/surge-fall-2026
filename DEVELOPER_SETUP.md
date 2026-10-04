# Team deployment setup

Use `main` on all four laptops. Preserve the existing
`codex/toddbrook-private-worker` branch; it is not needed to run the integrated
application, but must not be deleted. The detailed first-time setup and Codex
handoffs are in [docs/TODDBROOK_SETUP.md](docs/TODDBROOK_SETUP.md).

These commands use the team's Python 3.12 environments, Tailscale addresses and
existing private configuration. Keep each service terminal open. Wait for a job
to finish before stopping a service with **Ctrl+C**, and avoid starting duplicate
servers on the same port.

## Update each checkout

Run from that laptop's repository root. Inspect local changes before switching;
preserve them rather than resetting or cleaning the checkout.

```sh
git status --short
git fetch --prune origin
git switch main
git pull --ff-only origin main
git rev-parse HEAD
```

All devices should report the same commit. Reuse the existing virtual environment,
NASA login, downloaded caches and ignored configuration. Install updated Python
dependencies with that environment's executable when `requirements.txt` changes.

## Kazi — Windows Hydro

In PowerShell, use the existing worker checkout:

```powershell
cd C:\Users\kazib\surge-fall-2026-worker
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m scripts.run_worker hydro --host 100.100.3.2 --port 8002
```

Hydro opens [its dashboard](http://100.100.3.2:8002/dashboard). It discovers NASA
observations for each request and reuses matching files from `data/cache/gpm` and
`data/cache/smap`. Preserve custom `MESHMIND_GPM_DIR` or `MESHMIND_SMAP_DIR` values.
If this checkout has no saved Earthdata login, run this once before starting:

```powershell
.\.venv\Scripts\python.exe -c "import earthaccess; earthaccess.login(strategy='interactive', persist=True)"
```

## Alex — Windows Flood

In PowerShell, from Alex's dedicated worker checkout:

```powershell
cd $HOME\surge-fall-2026-toddbrook-worker
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m scripts.run_worker flood --host 100.100.3.3 --port 8003
```

Flood opens [its dashboard](http://100.100.3.3:8003/dashboard). It needs Internet
access to the public satellite services. No NASA login, Node.js or OpenAI key is
needed on this laptop.

## Karan — Linux Dam

```sh
cd ~/surge-fall-2026-worker
.venv/bin/python -m pip install -r requirements.txt
export MESHMIND_DAM_DATA_DIR="$PWD/private_data/toddbrook_runtime/data"
.venv/bin/python -m scripts.run_worker dam --host 100.100.3.4 --port 8004
```

Dam opens [its dashboard](http://100.100.3.4:8004/dashboard) and reads the requested
date directly from the tracked `private_data/toddbrook_runtime/as_of.zip` bundle.
No installation or extraction is required. Hydro, Flood and Control do not read
that bundle during investigations. Keep any original archives and earlier local
copies separate from the runtime inputs.

## Ryan — macOS Control

Create or update ignored `.env.reservoir.local` in the repository root with these
addresses. Preserve any existing custom timeout settings:

```dotenv
HYDRO_WORKER_URL=http://100.100.3.2:8002
FLOOD_WORKER_URL=http://100.100.3.3:8003
DAM_WORKER_URL=http://100.100.3.4:8004
MESHMIND_CONTROL_SOURCE_IP=100.100.3.5
```

The source address must belong to Ryan's Mac; omit that line if using another
machine. Reuse `env.phase8.download` for the private OpenAI key/model settings.

**Terminal 1 — Control API**

```sh
cd "/Users/diamster/Stormhacks 2026/surge-fall-2026"
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m backend.control.serve --generic --worker-env-file .env.reservoir.local --openai-env-file env.phase8.download --history-dir outputs/debug/reservoir-cutoff/history
```

**Terminal 2 — Amalga interface**

```sh
cd "/Users/diamster/Stormhacks 2026/surge-fall-2026/frontend"
npm ci
npm run build
npm run start
```

The interface prints and opens [its dashboard](http://127.0.0.1:3000). Control stays
on `127.0.0.1:8001`. Rebuild after frontend changes; for later starts with unchanged
code, `npm run start` is sufficient. `npm run dev` also opens the dashboard.

Internal worker, Control and viewer token settings are accepted and ignored.
NASA and OpenAI credentials remain private external-service credentials. Existing
`MESHMIND_` environment names remain supported after the Amalga rebrand.

## Run an investigation

Confirm the matching commits and open worker dashboards, then submit one request
from Ryan's interface:

> Assess flood risk at Toddbrook Reservoir, Whaley Bridge, Derbyshire, England as of 2019-08-01. Explain how rainfall, soil moisture and dam condition combine, then show the risk level and supporting evidence.

Wait for the assessment and download its report. The dashboard follows the real
acquisition and processing stages; an uncached date takes longer while files are
downloaded. Worker dashboards retain their latest task until the next request or
process restart. Control retains saved sessions across restarts.

Use [the deployment guide](docs/TODDBROOK_SETUP.md) for the 2007 comparison,
conditional-routing checks and first-time installations. Keep the earlier
`.env.phase5.local`, configured Abbotsford inputs and historical session folders
intact; they remain separate from the current four-laptop setup.

## Development checks

```sh
.venv/bin/python -m pytest -q
git diff --check
```

On Windows, use `.\.venv\Scripts\python.exe` in place of `.venv/bin/python`.
From `frontend/`, run `npm run test`, `npm run lint` and `npm run build` for interface
changes. Architecture, phase history and checkpoint records remain in
[PROJECT_PROGRESS.md](PROJECT_PROGRESS.md).
