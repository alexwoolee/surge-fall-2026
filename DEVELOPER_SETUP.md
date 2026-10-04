# Team deployment setup

These commands use the team's existing checkouts, Python 3.12 virtual
environments, downloaded data and private external-service configuration. For a
fresh generic setup, use [README.md](README.md). For architecture, progress,
evidence and development checkpoints, use [PROJECT_PROGRESS.md](PROJECT_PROGRESS.md).

Internal worker, Control and viewer tokens are no longer required. Existing
internal token settings are ignored and can remain in local configuration files.
Missing or invalid internal token values do not block access.
The OpenAI API key and any NASA Earthdata login are external-service credentials
and remain private. Nothing here requires replacing them or moving data.

## Before starting

For this auth update, update **all three checkouts** using the commands at the
end of this file. Stop idle services, restart both workers, then restart Control
and rebuild/start the Mac interface. Running processes and an existing frontend
build keep the previous behavior until replaced; a new Control process cannot
use an old worker that still requires a token.

Connect the laptops to Tailscale and keep the server terminals open. If the
servers are already running, open [the interface on Ryan's Mac](http://127.0.0.1:3000)
and the worker dashboards below. Do not start a second copy on the same port.
To restart, wait for work to finish, press Ctrl+C in that server's terminal,
then run its command again. Reuse worker terminals to retain any custom data
folders or local certificate settings.

## Kazi — Windows Hydro

In PowerShell:

```powershell
cd C:\Users\kazib\surge-fall-2026-worker
.\.venv\Scripts\python.exe -m scripts.run_worker hydro --host 100.100.3.2 --port 8002
```

The worker opens [its Hydro dashboard](http://100.100.3.2:8002/dashboard).
There is no token prompt or dashboard login. Its NASA inputs normally reside
under `data/cache/gpm` and `data/cache/smap`. Restore any previously customized
`MESHMIND_GPM_DIR` or `MESHMIND_SMAP_DIR` when using a new terminal. Copied NASA
files do not require an Earthdata login during processing.

## Karan — Linux Flood

In a terminal in the logged-in desktop session:

```sh
cd ~/surge-fall-2026-worker
.venv/bin/python -m scripts.run_worker flood --host 100.100.3.4 --port 8003
```

The worker opens [its Flood dashboard](http://100.100.3.4:8003/dashboard).
It needs outbound access to the public Sentinel-1, DEM and HAND services.
Neither worker needs Node.js, an OpenAI key or a Control-hosted viewer process.
Add `--no-open-dashboard` for headless use; the page remains available manually.

## Ryan — Mac Control, terminal 1

```sh
cd "/Users/diamster/Stormhacks 2026/surge-fall-2026"
.venv/bin/python -m backend.control.serve --execute \
  --config config/test_case.example.json \
  --rules config/rules.example.json \
  --openai-env-file env.phase8.download \
  --worker-env-file .env.phase5.local \
  --gpm-resources 3B-HHR.MS.MRG.3IMERG.20211115-S000000-E002959.0000.V07B.HDF5 3B-HHR.MS.MRG.3IMERG.20211115-S003000-E005959.0030.V07B.HDF5 \
  --smap-resource SMAP_L4_SM_gph_20211114T223000_Vv8010_001.h5 \
  --history-dir outputs/debug/phase9/live-history
```

Control listens on `127.0.0.1:8001`. Keep the existing files and history directory:

- `env.phase8.download` contains the private `OPENAI_API_KEY` and `OPENAI_MODEL`.
- `.env.phase5.local` selects Hydro at `http://100.100.3.2:8002`, Flood at
  `http://100.100.3.4:8003`, and the existing Control source address
  `MESHMIND_CONTROL_SOURCE_IP=100.100.3.5`. Preserve its existing timeout settings.
- `frontend/.env.local` selects `MESHMIND_CONTROL_API_URL=http://127.0.0.1:8001`.

The old `.env.phase9.local` and internal token fields are no longer needed for
access. Leave existing files intact; `--control-env-file` is unnecessary for this
command. Worker URLs and the source address remain configuration, not credentials.
Environment files are loaded only where explicitly selected by the relevant
entry point; merely creating a root `.env` does not configure the workers.

## Ryan — Mac interface, terminal 2

```sh
cd "/Users/diamster/Stormhacks 2026/surge-fall-2026/frontend"
npm ci
npm run build
npm run start
```

The interface prints [its dashboard link](http://127.0.0.1:3000) and opens it in
the default browser on Ryan's Mac once ready. Stop the previous interface process
before building. For later restarts with unchanged source and dependencies, only
`npm run start` is needed. `npm run dev` also opens the dashboard automatically.
To keep the browser closed, use `npm run start -- --no-open-dashboard` (or
`npm run dev -- --no-open-dashboard`); the link still appears in the terminal.

## Run the configured investigation

Paste this into the investigation box and click **Run Analysis** once:

```text
Investigate Abbotsford / Sumas Prairie for 14–16 November 2021 using the configured rainfall, soil moisture, candidate surface-water and terrain evidence. Explain the demonstration review conditions and coverage limitations.
```

Both worker pages should show the shared task ID. A short Hydro job may complete
between screen updates; its real events and duration remain visible. Wait for
Control to finish the briefing. **Partial result** can mean incomplete spatial
or temporal observations even when both workers complete. Use **Open partial
briefing** or **Download partial briefing** to review the result.

Each worker retains its own current-process task history in memory. Restarting a
worker clears that registry; it does not erase Control's saved sessions. Worker
completion means its result passed worker contract checks. Control's combined
validation and scientific review are separate.

## Update an existing checkout

Stop its servers when idle. Inspect the first command's output before continuing;
preserve and resolve local changes or divergence rather than resetting work.

```sh
git status --short
git fetch --prune origin
git switch main
git pull --ff-only origin main
```

Python dependencies remain in `requirements.txt`; use that checkout's existing
virtual environment when they change. Rebuild the frontend after pulling frontend
changes. Private configuration, virtual environments, cached datasets and saved
history are not supplied by Git. Detailed prior deployment checks remain in
[the project record](PROJECT_PROGRESS.md); historical authentication results
describe the former access policy.
