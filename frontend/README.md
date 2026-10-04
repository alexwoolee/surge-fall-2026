# MeshMind frontend

The existing environmental-analysis interface now connects to Control by default. Control coordinates Hydrometeorology on Laptop 2 and Surface Water & Terrain on Laptop 3, validates their independent evidence, and provides a grounded HTML briefing. The approved visual design is preserved.

## Run locally

Use Node.js compatible with the pinned Next.js version and npm. From `frontend/`:

```bash
npm ci
npm run test
npm run lint
npm run build
npm run start
```

Both `npm run start` and `npm run dev` bind **127.0.0.1:3000**, print the Control dashboard URL, and open it once in this computer’s browser after the frontend is ready. Use `npm run start -- --no-open-dashboard` (or the same flag with `dev`) for headless use. A custom port is supported with `--port 3100` or `PORT`; `--hostname` accepts only loopback addresses. Development also accepts `--webpack`, `--turbopack`, or `--turbo`. Occupied ports fail instead of silently switching ports. If the browser cannot open, use the printed [dashboard link](http://127.0.0.1:3000). Keep this operator workspace local; it has no public user-login layer. Worker services are reached by Python Control, not by the browser. Internal API credentials are not required.

Start the Python Control service using the [project setup](../README.md) or [developer setup](../DEVELOPER_SETUP.md). The frontend defaults to `http://127.0.0.1:8001`; no token or frontend environment file is required. To change the local Control port, optionally set this server-only value in ignored `frontend/.env.local`:

```dotenv
MESHMIND_CONTROL_API_URL=http://127.0.0.1:8001
```

Internal Control, worker, and viewer credential values are ignored unconditionally, including missing or malformed legacy tokens. The proxies omit Authorization headers instead of forwarding arbitrary credentials. Host, origin, route, method, body-size, and payload validation still apply. Real OpenAI API authentication remains configured privately on Python Control; never put its key into a `NEXT_PUBLIC_` variable. API failure displays an error and never substitutes demo measurements.

`npm run build` uses Next's documented Webpack option. Turbopack's local build-process socket was blocked with `EPERM` in the development sandbox; the equivalent Webpack production build succeeded without changing dependency versions.

## Workflow

Home displays the configured study area, historical dates, and whether Control is executing new worker tasks or reviewing retained evidence. Requests must match that configured case. Control's bounded model interpretation decides whether to accept a request. The UI does not silently apply arbitrary locations or dates to the fixed case.

The session view polls server state without overlapping requests. Worker availability starts **Not observed**. Returned work is **Complete**, distinct from current availability. Cards update independently, and failed polling retains the last received state with a visible warning. Polling stops after a terminal session state. History is loaded from Control, including after reload.

Review mode is prominently labeled **Retained evidence review** and never claims new remote execution. The briefing includes the original request as user context, every validated measurement, review conditions, source/processing provenance, limitations, and the required analyst-support disclaimer.

Partial results retain independently validated Hydro or Flood evidence. Missing observations remain unavailable, and dependent rules remain not assessable. Retry buttons appear only for workers explicitly allowed by Control; its bounded retry preserves the other worker. Uncertain POST responses are never replayed automatically. An explicit repeat of the same request reuses its idempotency key, including after a browser reload when session storage is available.

Downloads use a native same-origin link through the bounded server route. The server returns the actual standalone HTML briefing with an attachment filename; no live report is assembled from frontend fixtures.

## Routes

| Route | Purpose |
| --- | --- |
| `/` | Configured request composer and recent investigations |
| `/history` | Searchable server-backed history |
| `/session/[id]` | Independent worker activity and result |
| `/session/[id]/briefing` | Full or partial grounded briefing |
| `/worker/hydro?session=[id]` | Hydrometeorology activity for the selected session |
| `/worker/flood?session=[id]` | Surface Water & Terrain activity for the selected session |

A worker page without a selected session does not invent an active investigation. Sidebar worker links use the most recent known session.

## Worker-owned dashboards

The primary worker screens are served by each worker's Python API, with no Node installation or frontend build on that laptop:

- Kazi's Hydro dashboard: `http://100.100.3.2:8002/dashboard`.
- Karan's Flood dashboard: `http://100.100.3.4:8003/dashboard`.

The worker launcher opens its own dashboard automatically; `--no-open-dashboard` disables that convenience. The page reads only its own `/dashboard/state` endpoint and follows the latest accepted task. Processing duration is displayed in milliseconds, including fast Hydro work. Worker completion is distinct from Control's later evidence checks and combined briefing. Worker task APIs accept internal credentials unconditionally while retaining their route and payload checks.

The self-contained HTML, CSS, and JavaScript live in `backend/shared/dashboard_assets/`. They reuse the approved worker-screen visual design, use no external assets or Control requests, and render dynamic text without HTML injection. Tests in `src/lib/worker-dashboard.test.ts` exercise their validation, polling, truthful stages, and browser restoration behavior.

## Optional Control-hosted legacy viewers

The earlier Control-hosted viewer is optional; it is not the worker-owned dashboard described above. A separate viewer-only Next process can display Control-observed activity over Tailscale while Ryan's operator workspace remains on `127.0.0.1:3000`. Build once before starting either process. Start Python Control, then run from `frontend/`:

```bash
npm run start:viewers -- --host 100.100.3.5 --port 3001 --upstream http://127.0.0.1:8001
```

The legacy `--env-file` flag remains accepted but is optional and ignored. Missing files and invalid internal credential contents do not block startup. No browser login or upstream viewer token is required. The npm command includes Node’s option separator; when invoking the launcher directly, use `node -- scripts/start-viewers.mjs ...` so Node cannot consume the legacy flag itself.

- Kazi opens `http://100.100.3.5:3001/viewer/hydro`.
- Karan opens `http://100.100.3.5:3001/viewer/flood`.

These are read-only views of the same current execution session. Open both before Ryan submits the request. They automatically follow each new execution, show a shared session ID and UTC request time, and retain actual observed events when a worker completes between polls. Completed earlier work is labeled while waiting for another investigation; it is never replayed as current processing. Missing updates show a stale-state warning and stop active animations.

The launcher binds only to explicit loopback or Tailscale addresses, forces viewer mode, and clears operator, worker, and OpenAI credentials from the child process. Viewer mode rejects all mutations, operator pages, and operator APIs. Both read-only worker dashboards are available to anyone who can reach the configured Tailscale or loopback listener. Only the two dashboard pages, their read endpoints, and required static assets are allowed. Each read endpoint selects the fixed matching Python backend projection. No internal credential is read or sent by the viewer proxy.

## Explicit fixture demo

For isolated UI exploration only, set `NEXT_PUBLIC_MESHMIND_MODE=demo` **before building or starting development**. This is a public build-time switch, not a secret. Rebuild when switching modes. In demo mode only, the scenario picker, seeded examples, browser-local history, simulated timelines, and fixture HTML downloads are enabled. No backend request is made by the mock provider.

Seeded IDs: `ready`, `running`, `partial`, `checks-failed`, and `failed`. Demo storage is `meshmind.frontend-demo.v1`; the running example is frozen for inspection. All demo activity, timing, measurements, and review conditions are illustrative fixtures. Demo retry targets Flood and preserves Hydro, as in the original interface implementation.

## Validation and ownership

Frontend tests cover the original fixture provider plus real API adaptation, unknown/malformed responses, cancellation, idempotency across interrupted responses/reload, bounded targeted retry requests, fixed proxy destinations, same-origin writes, credential/error redaction, bounded bodies, and native HTML delivery headers. Browser verification and the Phase 9 human checkpoint are recorded in the root validation notes; automated frontend tests alone do not establish physical worker execution.

The implementation remains inside `frontend/**`. See [IMPLEMENTATION.md](./IMPLEMENTATION.md) for the preserved design mapping and integration boundary. See the [root README](../README.md) for general setup, [DEVELOPER_SETUP.md](../DEVELOPER_SETUP.md) for development instructions, and [PROJECT_PROGRESS.md](../PROJECT_PROGRESS.md) for phase history and checkpoints.

> MeshMind is an environmental analysis and analyst-support system. It is not an operational emergency-response or evacuation system.
