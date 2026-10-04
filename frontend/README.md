# MeshMind frontend

Kazi's isolated frontend lane for MeshMind: Control on Laptop 1, Hydrometeorology on Laptop 2, and Surface Water & Terrain on Laptop 3. The application follows the supplied environmental-analysis PNG designs while replacing their obsolete Fire, Seismic, Air Quality, and Company concepts.

**This is an explicitly labeled frontend demonstration.** Activity, timings, measurements, provenance, and review outcomes are deterministic fixtures. No environmental data source or remote worker is contacted. No backend endpoint is assumed.

## Run locally

Use a current Node.js version compatible with Next.js 16 and npm. Run all commands inside `frontend/`:

```bash
npm install
npm run dev
```

Open [http://localhost:3000](http://localhost:3000). The lockfile is included; `npm ci` can be used for repeatable installation.

```bash
npm run test
npm run lint
npm run build
npm run start
```

`npm run start` serves the production build after `npm run build`. No Python dependencies, backend services, API keys, or environment variables are needed for the demo.

## Explore the demo

Enter a question on Home, choose a demo scenario, and select **Run Analysis**. Enter submits; Shift+Enter adds a line. The original question is retained, while new demo runs use the fixed Abbotsford / Sumas Prairie example area and observation window. The demo does not parse arbitrary locations or retrieve current observations.

| Route | Purpose |
| --- | --- |
| `/` | Home, composer, current architecture, recent investigations |
| `/history` | Searchable investigation history grouped by time |
| `/history?search=1` | History with search focused |
| `/session/[id]` | Investigation activity and outcome |
| `/session/[id]/briefing` | Complete or partial briefing |
| `/worker/hydro` | Hydrometeorology execution view; defaults to the running example |
| `/worker/flood` | Surface Water & Terrain execution view; defaults to the running example |
| `/worker/flood?session=partial` | Laptop 3 unavailable example |

Stable seeded session IDs:

| ID | Demonstrated state |
| --- | --- |
| `ready` | Complete investigation, analyst-review conditions, downloadable briefing |
| `running` | Both workers processing; frozen example for inspection |
| `partial` | Validated hydro evidence retained; surface-water and terrain evidence missing |
| `checks-failed` | Returned surface-water evidence fails validation and is excluded |
| `failed` | Dispatch failure; neither specialist returns evidence |

Examples: `/session/ready/briefing`, `/session/partial`, `/worker/hydro?session=ready`. Control-facing pages have the main sidebar; worker pages use focused execution views. Search is available through the sidebar and Ctrl/Cmd+K.

## Workflow and persistence

A newly started complete demo takes 12 simulated seconds. Both workers begin together. Hydro returns at 7 seconds, Flood at 9 seconds, validation occurs at 10 seconds, review conditions at 11 seconds, and the briefing at 12 seconds. These times illustrate independent states; they are not measured remote execution or proof of physical parallelism.

The partial scenario makes Laptop 3 unreachable during processing. Its missing evidence remains unavailable, and dependent review rules say **Not assessable**. Retry dispatches only the missing Surface Water & Terrain investigation while retaining validated hydrometeorology.

Sessions use browser local storage key `meshmind.frontend-demo.v1`. Reloading or opening another worker view resumes the same simulated run from its saved start time. This is local browser persistence, not shared multi-laptop state. If storage is blocked or full, the provider falls back to memory. The provider exposes `resetDemo()` for development; it is not an infrastructure-administration action.

Downloads use native HTML links with encoded data URLs and descriptive `.html` filenames. The standalone document contains the same briefing model, demo notice, provenance, limitations, and disclaimer. User text is escaped. Failed validation never produces a downloadable combined briefing.

## Integration and ownership

See [IMPLEMENTATION.md](./IMPLEMENTATION.md) for file groups, design mapping, dependencies, provider semantics, and the exact backend information needed for integration.

The frontend uses shadcn's `radix-nova` setup with Button, Input, and Textarea. Animate UI Fade and its in-view hook are adapted to a stable div wrapper without `asChild`; custom conic CSS spheres preserve the supplied status-orb design.

All project changes for this lane belong to `frontend/**`, on `kazi/frontend-ui` in an isolated worktree. The root README remains the architecture authority. Backend code, shared contracts, Python tests, data, and root configuration are outside this lane.

## Validation

Final `npm run lint`, `npm run build`, and all 12 provider/download tests passed. Browser checks covered the live workflow, all outcomes, focused workers, retry, history/search, sidebar keyboard focus, and desktop/laptop/narrow layouts (1440, 1024, and 390 px).

The in-app browser's download capture timed out. The native download link and encoded HTML are covered by tests; a captured browser download has not been verified.

The provider tests cover independent worker completion, partial evidence, targeted retry, invalid evidence exclusion, dispatch failure, reload/shared browser state, malformed/blocked/quota-limited storage, invalid dates, deterministic examples, and safe HTML generation.

> MeshMind is an environmental analysis and analyst-support system. It is not an operational emergency-response or evacuation system.
