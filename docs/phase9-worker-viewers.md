# Phase 9 follow-up — three physical browser screens

The Mac-only human checklist passed, and that implementation was merged at
`fb14c2a`. The user then clarified that the demo must also show Hydro on Kazi's
Windows laptop and Flood on Karan's Linux laptop during the same investigation.
That three-screen checkpoint is now **PASS — human accepted October 4**.
Phase 10 has not started. This addition was tested on `codex/worker-viewers`;
preserve the previous evidence and the separate new run recorded below.

## What was already proved

The earlier browser submission `ad711f78-ae40-4c31-b5ee-1c5a68551f51` dispatched
real tasks to Hydro on **Boni** and Flood on **ARE** in parallel. The Mac UI
observed Hydro complete while Flood was processing, and both results matched
the reference. Browser rendering on those two worker laptops was not verified.
Phase 6 remains the recorded calibrated execution-overlap proof.

## Viewer boundary

Control's operator UI remains on `127.0.0.1:3000`, and Python remains on
`127.0.0.1:8001`. A separate viewer-only frontend listens on the Mac's explicit
Tailscale address, `100.100.3.5:3001`. It accepts a different read-only credential
for each worker role and denies operator pages and actions at the server.
Python also restricts each viewer token to its own GET endpoint. Do not expose
the operator UI or share the operator, worker-service or OpenAI credentials.

The worker pages follow the latest execution session automatically, including
when opened before a new request. They keep polling after completion to pick up
the next request. Each page shows its session ID, role and actual observed
activity. Poll failures retain evidence with a visible stale-state warning.
Control stores a bounded timeline of observed transitions; it does not invent
unobserved processing stages or extend the active animation. Hydro can complete
in less than one screen-refresh interval. A fast completion with real recorded
events is a valid result, even if nobody catches its active frame.

## Ryan's setup

Keep the existing Hydro and Flood worker processes running. No worker checkout
update, additional Node/Python installation, or new OpenAI key is needed on their
laptops for these browser displays.

Create private `.env.phase9-viewers.local` in the Control checkout with separate,
random tokens of at least 32 characters:

```dotenv
MESHMIND_VIEWER_HYDRO_TOKEN=<private-hydro-viewer-password>
MESHMIND_VIEWER_FLOOD_TOKEN=<different-private-flood-viewer-password>
```

The file is ignored by Git. Share only Hydro's value privately with Kazi and
only Flood's with Karan. These are distinct from their existing worker-service
tokens. Never put them in a URL, source file, screenshot or chat transcript.

Add this option to the existing `backend.control.serve` command from
[Phase 9 startup](phase9-validation.md#local-startup):

```sh
--viewer-env-file .env.phase9-viewers.local
```

Restart only local Control when no investigation is active. Keep the same
history directory. After installing the frontend lockfile and building with
`npm run build`, keep the normal operator `npm run start` process and run this
second process from `frontend/`:

```sh
npm run start:viewers -- --env-file ../.env.phase9-viewers.local --host 100.100.3.5 --port 3001 --upstream http://127.0.0.1:8001
```

The helper reads literal private assignments without shell expansion, uses the
viewer-only mode and binds only an explicitly allowed Tailscale/loopback address.
Existing private settings and the worker processes remain intact.

## Kazi — Windows

In PowerShell, open the Hydro screen:

```powershell
Start-Process "http://100.100.3.5:3001/viewer/hydro"
```

When the browser asks for authentication, enter username **hydro** and the
Hydro viewer password Ryan shared privately. Leave the page open. It should
identify Hydrometeorology and show a previous completed investigation or a
waiting state. Report **Hydro browser ready** to Ryan before the new submission.

## Karan — Linux

In a terminal, open the Flood screen:

```sh
xdg-open "http://100.100.3.5:3001/viewer/flood"
```

Alternatively paste that exact URL into an existing browser. When asked for
credentials, enter username **flood** and the Flood viewer password Ryan shared
privately. Leave the page open. It should identify Surface Water and Terrain
and show a previous completed investigation or a waiting state. Report
**Flood browser ready** to Ryan before the new submission.

If a page cannot connect, first confirm Tailscale is connected and run:

```sh
tailscale ping 100.100.3.5
```

A login failure requires the viewer password, not the worker-service token.
Do not work around errors by removing authentication or exposing the operator UI.

## Coordinated manual test — PASS

1. Kazi and Karan open their respective pages and both confirm readiness.
2. Ryan opens `http://127.0.0.1:3000` and submits **one** supported request:

   > Investigate Abbotsford / Sumas Prairie for 14–16 November 2021 using the configured rainfall, soil moisture, candidate surface-water and terrain evidence. Explain the demonstration review conditions and coverage limitations.

3. Record the new session ID from Ryan's investigation URL. Both worker screens
   must switch automatically to that same ID without manual refresh or URL edits.
4. Kazi confirms real Hydro events and completed validated evidence. Karan confirms
   real Flood events and completed validated evidence. The Mac must show both
   independent results. Fast Hydro execution need not remain visibly active.
5. All three leave the pages open until the briefing is ready. Check the eight
   reference values, five rule outcomes and expected source-coverage limitations
   using the existing Phase 9 checklist. Refresh each worker page once; it must
   retain the same session and completion, without starting another task.
6. Confirm the remote pages have no request composer or retry controls. The
   implementation tests and Control-side HTTP checks must additionally verify
   that remote operator routes/actions are denied, not merely hidden.
7. Record the common ID and these human results: **Ryan Control PASS; Kazi Hydro
   browser PASS; Karan Flood browser PASS**. Only then close this additional
   Phase 9 checkpoint and consider Phase 10.

## Implementation verification — October 4

- Full Python suite: **1,378 passed** (Python 3.12.14).
- Frontend: **35 tests passed**, lint, TypeScript and production build passed.
- Live viewer listener: **49 HTTP checks passed**, including both authenticated
  pages and their scripts/styles, each role's scoped API, login challenge,
  denial of other-role/operator routes and writes, and unchanged operator access.
- Direct Control viewer checks passed for both roles; the previous session file
  remained byte-for-byte unchanged.
- Independent implementation review passed. Live HTTP verification caught a
  blocked Next.js dynamic-route script; the narrow encoded-bracket correction
  and regression test pass, and both pages' advertised assets now return 200.
- `git diff --check` passed. Private settings and validation outputs are ignored.

Evidence is retained locally in `outputs/debug/phase9/worker-viewers-pytest.log`,
`worker-viewer-api-checks.json` and `worker-viewer-http-checks.json`. The last two
paths are in that same directory. The operator and viewer listeners remain
running after the accepted coordinated check.

## Coordinated physical run — October 4

Tested implementation: `01df4d7` on `codex/worker-viewers`.
The user confirmed both physical worker browser pages were open and operational,
then authorized exactly one new submission from the Control browser.

Shared session and task: **`c51fd780-8b4d-4eea-906b-5fea0bfff690`**.

| Worker | Physical host | Worker-reported execution | Retained observed events |
| --- | --- | --- | --- |
| Hydro | Boni (Kazi, Windows) | 0.300619 seconds; complete and validated | 6 |
| Flood | ARE (Karan, Linux) | 84.312377 seconds; complete and validated | 7 |

Control visibly observed Hydro complete while Flood remained active, then both
complete. Both role-specific feeds followed the new session and retained their
own genuine activity. The user confirmed both laptops saw the investigation,
and that Karan's screen moved through the steps to Complete. Kazi did not see
an active frame: Hydro finished between the viewer's one-second updates. No
Hydro processing event was observed, and none was invented or artificially
extended. Its six retained events include submission, task acceptance, reported
completion, retrieval and validated evidence.

All **15 live completion checks passed**: matching session IDs, validated worker
completion, retained terminal observations, stable repeated reads, page access,
standalone briefing attachment, both workers idle afterward, and unchanged
history bytes. Independent validation passed **27 read-only assertions**. All
eight full metric records and all five rule assessments match the prior Phase 9
session and regenerated accepted Phase 6 reference. Four conditions triggered;
the root-zone moisture condition did not. Coverage remains correctly partial.
The briefing preserves historical observation dates and scientific limitations.
This follow-up does not claim a new calibrated execution-overlap measurement.

Private evidence is in `outputs/debug/phase9/`:

- `three-screen-initial-observation.json`
- `three-screen-completion-checks.json`
- `three-screen-control-progress.png` and `three-screen-control-complete.png`
- `three-screen-briefing.html`
- `live-history/c51fd780-8b4d-4eea-906b-5fea0bfff690.json`

The new session SHA-256 is
`cc3a00fae38568d46f31fad7e2847ed5e895272a67cd1257d3244eb562e76f01`.
The previous session and original Phase 6 report remain byte-for-byte unchanged.

**Human acceptance:** after confirming both physical displays saw the same new
investigation, the user answered **“Yes both pass”** to the final refresh check:
the session ID, Complete status and Observed activity persisted, with no Run or
Retry controls. This accepts **Ryan Control PASS; Kazi Hydro browser PASS;
Karan Flood browser PASS** and closes the clarified Phase 9 checkpoint.
Phase 10 has not started.
