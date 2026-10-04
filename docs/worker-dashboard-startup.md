# Open the dashboard when a worker starts

The user requested this follow-up after the accepted Phase 9 three-screen run.
**Each worker serves its own dashboard from its own HTTP server.** Hydro's page
is hosted on Kazi's laptop; Flood's page is hosted on Karan's laptop. A thin
Python launcher opens that local worker's `/dashboard` once it is ready. No
browser login is required. Worker API tokens remain required for task submission,
status, clock and result endpoints.

The dashboard's HTML, CSS, JavaScript and read-only state all come from that
worker process. It does not fetch its page or progress from Ryan's Control
server. Control still dispatches real work and validates the combined results.

## One-time update

When the existing worker is idle, stop it with Ctrl+C in its terminal. Preserve
the existing `MESHMIND_WORKER_TOKEN`, input configuration and virtual environment.
Inside the same checkout, with no uncommitted changes:

```sh
git status --short
git fetch --prune origin
git switch main
git pull --ff-only origin main
```

If Git reports local work or divergence, preserve and inspect it before updating.
The launcher uses the existing dependencies; no Node installation is needed on
the worker laptops. Use the following command instead of the previous direct
Uvicorn command for future starts.

## Kazi — PowerShell, Hydro

From `C:\Users\kazib\surge-fall-2026-worker`, in the existing worker terminal:

```powershell
.\.venv\Scripts\python.exe -m scripts.run_worker hydro --host 100.100.3.2 --port 8002
```

## Karan — Linux, Flood

From `~/surge-fall-2026-worker`, in the existing worker terminal:

```sh
.venv/bin/python -m scripts.run_worker flood --host 100.100.3.4 --port 8003
```

The pages open at `http://100.100.3.2:8002/dashboard` for Hydro and
`http://100.100.3.4:8003/dashboard` for Flood. The launcher derives its own URL
from its bind address and port, and opens it by default. It runs one Uvicorn
worker with reload disabled. Run it in the laptop's
logged-in graphical desktop session so the default browser can open there.
Add `--no-open-dashboard` for a headless server that should not open a browser.
If the desktop cannot launch a browser, the worker stays running and the plain
dashboard URL can be opened manually. New tasks do not open additional tabs.

Each dashboard shows only its worker's latest accepted task and genuine locally
recorded transitions. Fast Hydro execution still leaves its actual event history
and processing duration visible. Completion means the worker produced a result
that passed its own contract checks; the Control briefing separately reports
combined validation and environmental coverage. A restarted worker begins idle
because its task registry is in memory; old Control history is not replayed as
new worker activity.

The optional older Control-hosted viewer at port 3001 is no longer required for
these worker dashboards. Any device allowed to reach a worker's Tailscale address
can read its public dashboard, while its task APIs still require authentication.
The public routes expose safe status and event projections only, without raw
results, source paths, credentials or write controls. No authentication token is
included in a browser URL.

The original Phase 9 acceptance remains valid historical evidence. This new
startup behavior must be distinguished from the earlier manual browser-opening
steps when reporting what was tested.

## Verification — October 4, 2026

- Full macOS Python suite: **1,452 passed** (including 40 launcher tests).
- Frontend and standalone dashboard tests: **42 passed**; lint and TypeScript
  passed. The optional central viewer's production build also passed.
- **30 live HTTP checks passed** against two isolated local worker factories:
  public pages, assets and state work, while worker task/status/clock/result
  authentication remains enforced.
- Both local worker dashboards rendered the correct idle role without a login
  or browser console warnings/errors. These checks submitted no worker tasks.
- Independent implementation review found no remaining blocker.

Local evidence is retained under `outputs/debug/worker-dashboard-startup/`.
The launcher tests verify that browser opening occurs once after successful
startup and that failure to open does not stop the server. Automatic desktop
opening on Kazi's Windows and Karan's Linux laptop remains to be checked after
they pull this update and restart with the commands above. Their existing
physical worker processes were not changed by these local checks.
