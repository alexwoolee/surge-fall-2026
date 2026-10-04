# Amalga frontend implementation handoff

## Scope and integration

The frontend from `origin/frontend` and the prompt-routed worker integration are combined on `main`. Visual direction, navigation, and core components are preserved; the optional Dam worker extends the original two-worker interface. Frontend changes remain inside `frontend/**`; Python Control owns processing, validation, rule evaluation, session persistence, and report generation. The [root README](../README.md) covers setup; [DEVELOPER_SETUP.md](../DEVELOPER_SETUP.md) and [PROJECT_PROGRESS.md](../PROJECT_PROGRESS.md) hold development instructions and phase checkpoints.

## File groups

| Files/folder | Responsibility |
| --- | --- |
| `scripts/start-control.mjs`, `src/lib/control-startup.test.ts` | Cross-platform Control dashboard startup, readiness checks, browser opening and headless/custom-port tests |
| `package.json`, `package-lock.json` | Frontend dependencies and dev/test/lint/build/start commands |
| `components.json` | shadcn configuration and Animate UI registry |
| `next.config.ts`, `tsconfig.json`, `postcss.config.mjs`, `eslint.config.mjs`, `.gitignore` | Frontend-only tooling |
| `src/app/layout.tsx`, `src/app/globals.css`, `src/app/icon.png` | Metadata, visual system, brand asset |
| `src/app/(workspace)/page.tsx`, `src/app/(workspace)/history/page.tsx` | Home and history routes |
| `src/app/(workspace)/session/[id]/page.tsx`, `src/app/(workspace)/session/[id]/briefing/page.tsx` | Investigation and briefing routes |
| `src/app/viewer/[role]/page.tsx`, `src/app/not-found.tsx` | Optional legacy viewers and missing-page handling |
| `src/components/ui/` | shadcn Button, Input, Textarea |
| `src/components/animate-ui/primitives/effects/fade.tsx` | Adapted Animate UI Fade/Fades with a stable div wrapper |
| `src/components/meshmind/session-sidebar.tsx`, `home-view.tsx`, `history-view.tsx`, `composer.tsx` | Control shell, navigation/search, input, history |
| `src/components/meshmind/agent-status.tsx`, `session-badge.tsx`, `logo.tsx` | Identity and explicit status labels |
| `src/components/meshmind/session-view.tsx`, `activity-card.tsx`, `status-timeline.tsx` | Observable activity, independent worker state, focused execution views |
| `src/components/meshmind/analyst-review-banner.tsx`, `partial-result-card.tsx`, `validation-failure-card.tsx`, `briefing-card.tsx` | Review and outcome components |
| `src/components/meshmind/briefing-view.tsx`, `download-briefing-button.tsx` | Detailed briefing and download |
| `src/hooks/use-meshmind.ts` | Provider-backed reads, refresh, and error handling |
| `src/hooks/use-is-in-view.tsx`, `src/lib/utils.ts` | UI support helpers |
| `src/lib/types.ts`, `data-provider.ts` | Frontend view models and provider selection |
| `src/lib/mock-data.ts`, `mock-provider.ts` | Fixtures, simulated state transitions, persistence, retry |
| `src/lib/mock-download.ts` | Escaped standalone HTML and browser download |
| `src/lib/api-provider.ts` | Real Control adapter, response validation, cancellation, explicit idempotent mutations |
| `src/lib/control-proxy.ts`, `src/app/api/control/[...path]/route.ts` | Bounded local server proxy; credential isolation and same-origin write checks |
| `src/lib/api-provider.test.ts`, `control-proxy.test.ts` | Real transport, malformed/error responses, replay safety, proxy boundaries |
| `src/lib/mock-provider.test.ts` | Provider, persistence, and download safety tests |
| `README.md`, `IMPLEMENTATION.md` | Frontend-only startup and handoff |

## Dependencies and components

The app was generated inside `frontend/` using Next.js App Router, TypeScript, Tailwind, npm, and `src/`. All shadcn/Animate UI configuration and source remain there.

The manifest includes Next.js 16, React 19, Tailwind 4, TypeScript 5, ESLint 9/Next configuration, and `tsx` for Node tests. UI dependencies are `radix-ui`, `class-variance-authority`, `cn`, `lucide-react`, `tw-animate-css`, and `motion`. The lockfile supplies exact resolved versions. The shadcn CLI and unused Base UI dependency were removed from runtime dependencies after generation.

shadcn setup: **radix-nova**. Components retained: **Button, Input, Textarea**; unused Card, Badge, and Separator primitives were removed. Amalga behavior lives outside generic primitives. Animate UI registry: `https://animate-ui.com/r/{name}.json`. Its generated **Fade/Fades** and `use-is-in-view` hook were adapted to use a stable `motion.div` wrapper and ref handling. The unused `asChild`/Slot adapter was removed to avoid creating component types during render and satisfy React lint rules.

The sphere uses custom CSS conic/radial shading to match the reference geometry, with a 3.4-second spin and 2.6-second halo for active work. A generic icon would not reproduce that sphere. Reduced motion disables CSS animation/transitions and makes Fade immediate; all status meanings remain explicit text. This handling was code-reviewed, without changing the host's motion preference.

## Original design mapping

| Reference | Applied direction |
| --- | --- |
| Home — empty state and history | Wide composer, whitespace, sidebar, compact agent chips, recent rows |
| History — page view, grouped by time | Today/Yesterday/Earlier this week groups, dividers, outcome pills |
| Session 4 — agents working, live thinking | Activity-card layout, monospace events, independent orbs; contents replaced with observable system events |
| Session 1 — fire analysis, report | Prompt bubble, result hierarchy, download actions; translated to current workers |
| Partial result — Laptop 3 offline, Phase 15 | Retained/missing evidence, amber outcome, unavailable findings, partial download |
| Session 3 — checks failed | Restrained red rejection treatment and named failure reasons |
| Final briefing — downloadable, Phase 14 | Long-form evidence, provenance, limitations, HTML download |
| Worker screen — Laptop 2, executing | Focused worker identity, large sphere, bounded timeline, no full sidebar |
| Worker screen — Laptop 3, not reachable | Grey sphere, unreachable state, failed current step and unreached later steps |
| Agent status component | Sphere, name/location/divider/status word, restrained active motion |
| Company 1/2/3 server pages | Surface, border, spacing, and typography only |
| Chladni plate — motif origin | Low-contrast decorative atmosphere only |
| Session 2 — seismic, urgent alert | Outcome hierarchy only; urgency semantics replaced with analyst-review language |

Original design exclusions (the later Dam worker is now supported): Fire/Seismic/Air Quality capabilities; Company labels; server dashboards; job/queue counts, node load, uptime, paths, mounts, server/job IDs, heartbeat claims, and infrastructure administration. The decorative motif is not topology or scientific data and has no "Dither field" product control.

Fake tool menus, voice, and model modes were omitted. Real measurements come from validated Control evidence; illustrative measurements remain isolated in the explicit demo provider. Activity describes accepted requests, resources, processing, returned evidence, and validation. Candidate surface-water evidence and configured review conditions do not establish a confirmed flood or emergency-response capability.

## Provider boundary

`src/lib/data-provider.ts` chooses the real API provider by default. Only build-time `NEXT_PUBLIC_MESHMIND_MODE=demo` enables fixtures; network failure never changes provider. The browser sends relative `/api/control` requests. Python exposes these endpoints:

| Route | Contract |
| --- | --- |
| `GET /config` | Configured case, execution/review mode, notice, and whether a request can start |
| `GET /sessions` | `{sessions: SessionSummary[]}` |
| `POST /sessions` | `{prompt, requestId}` → accepted `{id}` |
| `GET /sessions/{id}` | Existing `AnalysisState` plus `isDemo:false`, `executionMode`, `executionNotice`, `retryableWorkers` |
| `POST /sessions/{id}/retry` | `{worker, requestId}` → accepted same-session `{id}` |
| `GET /sessions/{id}/briefing` | Standalone HTML attachment |

The API adapter validates response shapes and rejects fixture flags in live responses. Caller IDs are UUIDs. Private backend error text is not reflected into the UI. All numerical values, scientific prose, provenance, and rule outcomes originate in Python. `unknown` means execution has not been observed; `complete` describes returned work without claiming current worker availability.

Session polling is sequential, abortable, and stops on terminal status. Errors retain last received evidence with a stale-state notice. History reloads from Control. Retry buttons use `retryableWorkers`, support either missing specialist, and disappear when the bounded retry is unavailable. Neither start nor retry automatically replays a network failure. An explicit repeat reuses the same idempotency key; a small pending-action map persists in session storage where available.

The server route accepts only the fixed route/method allowlist and loopback Control origins. It validates JSON bodies, prompt byte/character bounds, UUIDs, and same-origin POSTs before forwarding the request. Internal token values are ignored unconditionally and no Authorization header is constructed. The default Control origin is `http://127.0.0.1:8001`. It passes no caller cookies/authentication headers, follows no redirects, and bounds body sizes and total request duration. Backend error bodies, cookies, and arbitrary filenames are excluded. The native download uses a fixed same-origin URL and safe attachment headers. Default npm servers bind only to 127.0.0.1 because this is a local operator workspace without public user authentication.

`BriefingViewModel.executionNotice` distinguishes retained evidence from current execution. The visible briefing renders all measurements and sections. Source and processing provenance are safe projections supplied by Python. Original request text is explicitly user context, not a finding.

## Prompt routing and conditional Dam assessment

`ControlConfig.routingMode="prompt"` enables generic composer guidance and server-provided example prompts. `availableWorkers` controls whether Dam Condition appears as available in Home/sidebar; the actual session `workers` controls all observed activity. Hydro and Flood are required, Dam is optional, and unknown worker roles are rejected. Dam activity is included only for sessions that dispatch that worker. Legacy configured-case servers, two-worker history and the explicit fixture demo remain supported.

`risk.ts` accepts only the public assessment fields with finite 0–100 risk score (unknown requires null), 0–1 evidence-confidence score, known levels, and high/critical alert consistency. Session and briefing assessments must match. `risk-summary.tsx` renders high/critical assessments as accessible alerts, preserves unknown and lower levels, escapes text through React, and distinguishes both scores from failure probabilities or certainty of an environmental event. The UI does not calculate scores or decide whether private owner records apply. The API's optional risk fields are absent on old reports.

## Worker-owned static dashboards

The primary worker display is served directly by each Python worker at `/dashboard`. Its fixed local assets live under `backend/shared/dashboard_assets/` and need no Next.js runtime or build. The browser reads only same-origin `/dashboard/state`, follows accepted tasks automatically, retains true lifecycle events after fast processing, and shows recorded duration in milliseconds. It never calls Control or submits/retries tasks. Completed worker processing does not imply completed Control fusion review. The launcher opens the local page by default; `--no-open-dashboard` opts out.

## Optional Control-hosted legacy viewers

`src/proxy.ts` applies the viewer-mode Host/method/path boundary to every request. `viewer-auth.ts` validates the exact configured Tailscale or loopback Host authority, permits Hydro, Flood and Dam viewer pages/read endpoints and required assets, and rejects methods other than GET. Dashboard requests need no browser login or credentials. The operator proxy independently rejects viewer mode; the viewer page and API independently recheck the listener boundary. Internal Python API credentials are accepted unconditionally. Real OpenAI authentication remains separate and unchanged.

`viewer-proxy.ts` selects a fixed loopback `/viewer/{role}` endpoint, defaulting to `http://127.0.0.1:8001`. Internal token values, incoming browser credentials, and cookies are ignored and never forwarded; no authentication challenge reaches the browser. Its schema parser excludes unexpected fields and foreign worker identities, bounds the event history, and validates observation timestamps. Responses have no shared cache, backend cookies, untrusted redirects, or private error text.

`worker-follower.tsx` is a focused screen without operator navigation or actions. `viewer-polling.ts` follows the server's latest execution snapshot every second, without overlapping requests, including after completion. It preserves observed event history instead of inventing animation time for fast work; a failed read labels prior data as stale. New execution IDs replace the complete view.

The portable `scripts/start-viewers.mjs` accepts and ignores the optional legacy `--env-file` flag, validates loopback/Tailscale bind addresses and a loopback upstream, forces runtime viewer mode, clears privileged inherited credentials, and starts Next without a shell. Its npm command uses `node --` so a legacy `--env-file` reaches the launcher instead of Node’s own environment-file parser. It uses the same production build as the local operator listener. `viewer.test.ts` covers login-free access to the worker viewers, Host/method/path isolation, independent endpoint guards, unconditional acceptance of missing/arbitrary internal credentials, fixed upstream/redaction, absence of browser authentication challenges, malformed projections, terminal-to-new-run following, abort/nonoverlap behavior, and safe launcher parsing.

## Preserved fixture implementation

The following simulation semantics apply only when explicitly enabled in demo mode. They never describe the real Control provider.

## Simulation semantics

These timings are **frontend simulation**, not telemetry. `createMockProvider({ now, storage, seed })` accepts an injected clock and storage for tests. State is derived on reads; no background computation or remote call occurs.

| Elapsed time | Complete scenario |
| --- | --- |
| 0 seconds | Request accepted; both investigations dispatched |
| 1 second | Both workers independently active |
| 3 seconds | Hydro rainfall calculation; Flood SAR reading |
| 5 seconds | Hydro soil-moisture processing; Flood terrain processing |
| 7 seconds | Hydro returned; Flood remains active |
| 9 seconds | Flood returned |
| 10 seconds | Control validation |
| 11 seconds | Configured review conditions available |
| 12 seconds | Combined briefing ready |

Partial: Flood becomes unreachable at 5 seconds, Hydro still completes and validates, and a partial briefing appears at 12 seconds. Validation failure: returned Flood evidence fails at 10 seconds. Dispatch failure: neither worker returns evidence after the simulated failure at 2 seconds.

Agent `ready` means available; a completed worker is ready for future work. `active` means working, `down` means unreachable with no returned result, and `failed` means dispatch or validation failed. Step states are `pending`, `active`, `complete`, `failed`. Investigation states are `running`, `briefing-ready`, `partial`, `checks-failed`, and `failed`. Explicit words accompany status colors and motion. No numeric progress percentages are shown; sample coverage percentages describe validation evidence.

## Fixtures, persistence, retry, download

All sample values, coverage, provenance, scientific prose, limitations, review conditions, and clock timings live in `src/lib/mock-data.ts`. These are illustrative fixtures, not current observations or reproduced validated backend outputs. New prompts retain user text but use the fixed Abbotsford / Sumas Prairie demo area/window. Named seed sessions are examples, not geocoded runs.

Seed IDs: `ready`, `running`, `partial`, `checks-failed`, `failed`. Seed `running` is frozen at 5 seconds for inspection. New runs advance normally. Use the selected session transcript for per-worker activity; standalone worker pages are served by each Python worker.

Local storage key `meshmind.frontend-demo.v1` stores versioned compact records. Reads reload persisted records so reloads, route changes, and tabs on the same origin share the run/retry. This is not cross-laptop synchronization. Malformed data is rejected; storage failure falls back to memory. A failed write cannot replace newer memory with older persisted state.

Only a completed partial run can call `retryWorker(id, "flood")`. Flood starts again; Hydro stays returned, validated, and complete. The eventual combined briefing retains the same hydro measurements. Invalid evidence is not reclassified as a missing-worker retry.

Missing Flood evidence produces no available surface-water extent or terrain finding. Rules R-04/R-05 say not assessable. Validation failure is distinct: evidence returned, failed checks, and `briefing` remains null.

`renderMockBriefingHtml()` creates a standalone HTML document from the same briefing model, including gaps, provenance, review outcomes, limitations, demo notice, and disclaimer. Dynamic values, including the original question, are escaped. `getMockBriefingDownload()` returns a percent-encoded `data:text/html;charset=utf-8,` URL and complete/partial `.html` filename. The UI uses a native anchor with `href` and `download`; there is no imperative click helper or backend write.

## Validation

Run in `frontend/`:

```bash
npm ci
npm run test
npm run lint
npm run build
```

The build uses Next's documented `--webpack` option after Turbopack's build-process socket was denied with `EPERM` in the sandbox. Dependency versions are unchanged. Development and production npm servers bind to loopback.

The 12 original provider/download tests remain, alongside real API/proxy boundary tests. These exercise malformed/fixture responses, abort propagation, explicit idempotent replay after a lost response, targeted retries, same-origin and route restrictions, private error/header redaction, streaming size bounds, and bounded native download responses.

The original UI lane had passed desktop/laptop/narrow visual checks, with a browser download capture limitation. Phase 9 browser/live execution/download evidence and the human checkpoint are recorded separately in root validation notes. Historical fixture checks must not be presented as proof of current remote execution.

## Control dashboard startup

`npm run start` and `npm run dev` use `scripts/start-control.mjs`. The launcher retains loopback binding, prints the dashboard URL, and opens the local browser once. It explicitly supplies the port so Next dev cannot select a different occupied-port fallback. It first observes its own child’s bound-listener message, then confirms `/icon.png` responds with a PNG before printing/opening; Next’s early readiness log alone does not prove configuration succeeded. Failed startup or a stopped child cannot trigger browser opening. `--no-open-dashboard` prints the same link without launching a browser. macOS, Windows and Linux use their platform opener without a shell, with a manual-link fallback on opener failure. Tests cover startup/exit races, headless and custom-port behavior, occupied ports, readiness failure and platform commands.
