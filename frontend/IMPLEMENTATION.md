# MeshMind frontend implementation handoff

## Scope and isolation

This lane implements the Next.js frontend only, on `kazi/frontend-ui` in a separate worktree. Project changes belong exclusively to `frontend/**`. Backend processors, APIs, Python contracts/tests, root dependencies/documentation/configuration, and datasets are outside this change.

The repository README supplies architecture; the PNGs supply visual direction. There are exactly two specialist workers: Hydrometeorology on Laptop 2, using GPM IMERG and SMAP L4; Surface Water & Terrain on Laptop 3, using Sentinel-1 SAR, Copernicus DEM, and HAND. Laptop 1 coordinates, validates, evaluates review conditions, combines evidence, and prepares briefings.

No merge into `main` is part of this lane. Final commit/push status belongs in the coordinating agent's verified handoff.

## File groups

| Files/folder | Responsibility |
| --- | --- |
| `package.json`, `package-lock.json` | Frontend dependencies and dev/test/lint/build/start commands |
| `components.json` | shadcn configuration and Animate UI registry |
| `next.config.ts`, `tsconfig.json`, `postcss.config.mjs`, `eslint.config.mjs`, `.gitignore` | Frontend-only tooling |
| `src/app/layout.tsx`, `src/app/globals.css`, `src/app/icon.svg` | Metadata, visual system, brand asset |
| `src/app/page.tsx`, `src/app/history/page.tsx` | Home and history routes |
| `src/app/session/[id]/page.tsx`, `src/app/session/[id]/briefing/page.tsx` | Investigation and briefing routes |
| `src/app/worker/[workerId]/page.tsx`, `src/app/not-found.tsx` | Worker route validation and missing-page handling |
| `src/components/ui/` | shadcn Button, Input, Textarea |
| `src/components/animate-ui/primitives/effects/fade.tsx` | Adapted Animate UI Fade/Fades with a stable div wrapper |
| `src/components/meshmind/session-sidebar.tsx`, `home-view.tsx`, `history-view.tsx`, `composer.tsx` | Control shell, navigation/search, input, history |
| `src/components/meshmind/agent-status.tsx`, `session-badge.tsx`, `logo.tsx` | Identity and explicit status labels |
| `src/components/meshmind/session-view.tsx`, `activity-card.tsx`, `status-timeline.tsx`, `worker-view.tsx` | Observable activity, independent worker state, focused execution views |
| `src/components/meshmind/analyst-review-banner.tsx`, `partial-result-card.tsx`, `validation-failure-card.tsx`, `briefing-card.tsx` | Review and outcome components |
| `src/components/meshmind/briefing-view.tsx`, `download-briefing-button.tsx` | Detailed briefing and download |
| `src/hooks/use-meshmind.ts` | Provider-backed reads, refresh, and error handling |
| `src/hooks/use-is-in-view.tsx`, `src/lib/utils.ts` | UI support helpers |
| `src/lib/types.ts`, `data-provider.ts` | Frontend view models and provider selection |
| `src/lib/mock-data.ts`, `mock-provider.ts` | Fixtures, simulated state transitions, persistence, retry |
| `src/lib/mock-download.ts` | Escaped standalone HTML and browser download |
| `src/lib/api-provider.ts` | Documented placeholder; no guessed requests |
| `src/lib/mock-provider.test.ts` | Provider, persistence, and download safety tests |
| `README.md`, `IMPLEMENTATION.md` | Frontend-only startup and handoff |

## Dependencies and components

The app was generated inside `frontend/` using Next.js App Router, TypeScript, Tailwind, npm, and `src/`. All shadcn/Animate UI configuration and source remain there.

The manifest includes Next.js 16, React 19, Tailwind 4, TypeScript 5, ESLint 9/Next configuration, and `tsx` for Node tests. UI dependencies are `radix-ui`, `class-variance-authority`, `cn`, `lucide-react`, `tw-animate-css`, and `motion`. The lockfile supplies exact resolved versions. The shadcn CLI and unused Base UI dependency were removed from runtime dependencies after generation.

shadcn setup: **radix-nova**. Components retained: **Button, Input, Textarea**; unused Card, Badge, and Separator primitives were removed. MeshMind behavior lives outside generic primitives. Animate UI registry: `https://animate-ui.com/r/{name}.json`. Its generated **Fade/Fades** and `use-is-in-view` hook were adapted to use a stable `motion.div` wrapper and ref handling. The unused `asChild`/Slot adapter was removed to avoid creating component types during render and satisfy React lint rules.

The sphere uses custom CSS conic/radial shading to match the reference geometry, with a 3.4-second spin and 2.6-second halo for active work. A generic icon would not reproduce that sphere. Reduced motion disables CSS animation/transitions and makes Fade immediate; all status meanings remain explicit text. This handling was code-reviewed, without changing the host's motion preference.

## Design mapping

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

Rejected obsolete concepts: a third specialist; Fire/Seismic/Air Quality capabilities; Company labels; server dashboards; job/queue counts, node load, uptime, paths, mounts, server/job IDs, heartbeat claims, and infrastructure administration. The decorative motif is not topology or scientific data and has no "Dither field" product control.

Fake tool menus, voice, and model modes were omitted. Measurements are confined to demo data. Activity describes accepted requests, resources, processing, returned evidence, and validation—not hidden model reasoning or chain-of-thought. Candidate surface-water evidence and configured review conditions do not establish a confirmed flood or emergency-response capability.

## Provider boundary

The UI consumes `dataProvider` from `src/lib/data-provider.ts`:

```ts
interface MeshMindDataProvider {
  startAnalysis(prompt: string, scenario?: DemoScenario): Promise<string>;
  getAnalysis(id: string): Promise<AnalysisState | null>;
  listSessions(): Promise<SessionSummary[]>;
  retryWorker(id: string, worker: WorkerId): Promise<void>;
  resetDemo(): Promise<void>;
}
```

`dataProvider` explicitly selects `mockProvider`. There is no silent mock fallback for a failed real API. `api-provider.ts` contains no network calls or speculative endpoints.

`AnalysisState` combines request/area/window, outcome and phase, Control availability, independent worker states, observable activity, review conditions, validation failures, and an optional briefing. `WorkerStatus` distinguishes availability, step state, returned result, and validated result. These are frontend view models, not final Pydantic contracts.

### Backend information required

1. **Task creation:** actual route/method, supported request fields, area/time resolution, supported investigations, validation errors, returned ID, and idempotency.
2. **Investigation state:** status route or subscription protocol, phase/state vocabulary, ordering, terminal states, timestamps/time zone, associations, error and reconnect/resume semantics.
3. **Observable activity:** user-safe event types/text, stable identity/order, snapshot versus incremental delivery, and exclusion of private model reasoning.
4. **Worker metadata:** hydro/flood IDs and labels, laptop mapping, bounded task steps, availability/completion distinctions, and verified down/failed signals. No invented heartbeat information.
5. **Results and validation:** serialized HydroResult/FloodResult fields, units, requested/actual coverage, validation outcomes/reasons, and missing versus returned-but-invalid evidence.
6. **Review conditions:** rule IDs/descriptions, observed and configured values/units, deterministic outcomes, dependencies, and not-assessable states. The backend owns threshold evaluation.
7. **Briefings:** ordered sections, original request, area/window, coverage, source/processing provenance, limitations, disclaimer, partial status, authenticated download mechanism and content type.
8. **History:** listing/pagination/search, stable IDs, creation/update timestamps, summaries, status, retention, and analysis/session semantics.
9. **Bounded retry:** actual route/method, worker scope, authorization, idempotency, accepted run state, response, and preservation of independently validated evidence.
10. **Transport configuration:** Control base URL, authentication, CORS or same-origin proxy, timeouts, rate/polling limits or streaming, and safe user-facing errors. No secrets in public frontend variables.

Once agreed, implement the adapter, map responses into view models, and change provider selection. Disable demo-only scenario/reset controls in real mode. Replace the isolated mock download with the backend report flow. This lane makes no backend modifications.

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

Seed IDs: `ready`, `running`, `partial`, `checks-failed`, `failed`. Seed `running` is frozen at 5 seconds for inspection. New runs advance normally. Worker `?session=<id>` selects the same investigation; `/worker/flood?session=partial` demonstrates unavailable Laptop 3.

Local storage key `meshmind.frontend-demo.v1` stores versioned compact records. Reads reload persisted records so reloads, route changes, and tabs on the same origin share the run/retry. This is not cross-laptop synchronization. Malformed data is rejected; storage failure falls back to memory. A failed write cannot replace newer memory with older persisted state.

Only a completed partial run can call `retryWorker(id, "flood")`. Flood starts again; Hydro stays returned, validated, and complete. The eventual combined briefing retains the same hydro measurements. Invalid evidence is not reclassified as a missing-worker retry.

Missing Flood evidence produces no available surface-water extent or terrain finding. Rules R-04/R-05 say not assessable. Validation failure is distinct: evidence returned, failed checks, and `briefing` remains null.

`renderMockBriefingHtml()` creates a standalone HTML document from the same briefing model, including gaps, provenance, review outcomes, limitations, demo notice, and disclaimer. Dynamic values, including the original question, are escaped. `getMockBriefingDownload()` returns a percent-encoded `data:text/html;charset=utf-8,` URL and complete/partial `.html` filename. The UI uses a native anchor with `href` and `download`; there is no imperative click helper or backend write.

## Validation

Final `npm run lint` and `npm run build` passed, as did all 12 provider/download tests. The build generated Home, History, session, briefing, and worker routes successfully.

In-app browser download capture timed out. Tests verify that the native download data URI decodes to the exact escaped HTML and supplies the correct partial filename; captured browser-download delivery remains unverified.

Run inside `frontend/`:

```bash
npm install
npm run test
npm run lint
npm run build
```

Tests cover independent return times, ready-state ordering, partial evidence/unassessable rules, targeted retry retaining Hydro, validation preventing reports, dispatch failure, reload/shared state, malformed/blocked/quota storage, invalid dates, stable examples, escaped HTML, and native download encoding/filenames.

Browser verification passed: Home/composer, concurrent worker start, Hydro Ready while Flood Active, Control waiting, complete briefing and analyst review, partial evidence and targeted retry, validation and dispatch failure, history grouping/search, both focused workers, down-worker state, and final briefing. Sidebar collapse/expand, Escape focus return, and repeated New investigation reset were checked. Desktop/laptop/narrow widths of 1440, 1024, and 390 px were checked, including no page overflow on narrow Home/briefing. No browser console warnings/errors were observed. All current product labels and network-call boundaries were inspected; no obsolete specialist labels or guessed API calls remain in source.

The in-app browser did not expose a saved-download event for the native HTML data link. The rendered link's filename/content and the escaped standalone document were verified; saving to disk through that browser remains the one manual verification limit.

`npm audit --omit=dev` reported zero production vulnerabilities. The full audit reported five high-severity development-tool advisories in the Next ESLint dependency chain; no incompatible downgrade or forced audit fix was applied.
