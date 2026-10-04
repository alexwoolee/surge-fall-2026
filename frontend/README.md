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

The production server binds **127.0.0.1:3000**. Open [http://127.0.0.1:3000](http://127.0.0.1:3000). `npm run dev` also binds only to loopback. Keep this operator workspace local; it has no public user-login layer. Worker services remain separately authenticated and are reached by Python Control, not by the browser.

Before starting, run the Python Control service using the root README's Phase 9 instructions. Configure these **server-only** values in ignored `frontend/.env.local`:

```dotenv
MESHMIND_CONTROL_API_URL=http://127.0.0.1:8001
MESHMIND_CONTROL_API_TOKEN=replace-with-the-same-private-control-token
```

Use a token of at least 32 characters. Never put worker tokens, the Control token, or OpenAI credentials into a `NEXT_PUBLIC_` variable. The browser calls `/api/control/*`; the server route attaches the Control token. Source URLs and worker addresses are not exposed through browser requests. API failure displays an error and never substitutes demo measurements.

`npm run build` uses Next's documented Webpack option. Turbopack's local build-process socket was blocked with `EPERM` in the development sandbox; the equivalent Webpack production build succeeded without changing dependency versions.

## Workflow

Home displays the configured study area, historical dates, and whether Control is executing new worker tasks or reviewing retained evidence. Requests must match that configured case. Control's bounded model interpretation decides whether to accept a request. The UI does not silently apply arbitrary locations or dates to the fixed case.

The session view polls server state without overlapping requests. Worker availability starts **Not observed**. Returned work is **Complete**, distinct from current availability. Cards update independently, and failed polling retains the last received state with a visible warning. Polling stops after a terminal session state. History is loaded from Control, including after reload.

Review mode is prominently labeled **Retained evidence review** and never claims new remote execution. The briefing includes the original request as user context, every validated measurement, review conditions, source/processing provenance, limitations, and the required analyst-support disclaimer.

Partial results retain independently validated Hydro or Flood evidence. Missing observations remain unavailable, and dependent rules remain not assessable. Retry buttons appear only for workers explicitly allowed by Control; its bounded retry preserves the other worker. Uncertain POST responses are never replayed automatically. An explicit repeat of the same request reuses its idempotency key, including after a browser reload when session storage is available.

Downloads use a native same-origin link through the authenticated server route. The server returns the actual standalone HTML briefing with an attachment filename; no live report is assembled from frontend fixtures.

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

## Three-screen worker viewers

A separate viewer-only Next process can serve Kazi and Karan over Tailscale while Ryan's operator workspace remains on `127.0.0.1:3000`. Build once before starting either process. Start Python Control with its separate viewer-token file, as described in the root README, then run from `frontend/`:

```bash
npm run start:viewers -- --env-file ../.env.phase9-viewers.local --host 100.100.3.5 --port 3001 --upstream http://127.0.0.1:8001
```

The private file contains only two different URL-safe tokens (32–256 characters): `MESHMIND_VIEWER_HYDRO_TOKEN` and `MESHMIND_VIEWER_FLOOD_TOKEN`. Share each token privately only with its worker owner. Never embed credentials in a URL.

- Kazi opens `http://100.100.3.5:3001/viewer/hydro`, enters username `hydro`, and uses the Hydro viewer token as the browser authentication password.
- Karan opens `http://100.100.3.5:3001/viewer/flood`, enters username `flood`, and uses the Flood viewer token as the password.

These are read-only views of the same current execution session. Open both before Ryan submits the request. They automatically follow each new execution, show a shared session ID and UTC request time, and retain actual observed events when a worker completes between polls. Completed earlier work is labeled while waiting for another investigation; it is never replayed as current processing. Missing updates show a stale-state warning and stop active animations.

The launcher binds only to explicit loopback or Tailscale addresses, forces viewer mode, and clears operator, worker, and OpenAI credentials from the child process. Viewer mode rejects all mutations, operator pages, operator APIs, and the other role's viewer. Its server-side role token can read only that role's backend projection. Only the required authenticated page, read endpoint, and static assets are allowed. Browser code never receives a bearer token. Keep the browser view on its owner's laptop; use a separate browser profile when testing both roles on one computer because HTTP Basic credentials may be cached by origin.

## Explicit fixture demo

For isolated UI exploration only, set `NEXT_PUBLIC_MESHMIND_MODE=demo` **before building or starting development**. This is a public build-time switch, not a secret. Rebuild when switching modes. In demo mode only, the scenario picker, seeded examples, browser-local history, simulated timelines, and fixture HTML downloads are enabled. No backend request is made by the mock provider.

Seeded IDs: `ready`, `running`, `partial`, `checks-failed`, and `failed`. Demo storage is `meshmind.frontend-demo.v1`; the running example is frozen for inspection. All demo activity, timing, measurements, and review conditions are illustrative fixtures. Demo retry targets Flood and preserves Hydro, as in the original interface implementation.

## Validation and ownership

Frontend tests cover the original fixture provider plus real API adaptation, unknown/malformed responses, cancellation, idempotency across interrupted responses/reload, bounded targeted retry requests, fixed proxy destinations, same-origin writes, credential/error redaction, bounded bodies, and native HTML delivery headers. Browser verification and the Phase 9 human checkpoint are recorded in the root validation notes; automated frontend tests alone do not establish physical worker execution.

The implementation remains inside `frontend/**`. See [IMPLEMENTATION.md](./IMPLEMENTATION.md) for the preserved design mapping and integration boundary. The root README remains the project and phase authority.

> MeshMind is an environmental analysis and analyst-support system. It is not an operational emergency-response or evacuation system.
