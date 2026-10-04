# Phase 6 — Real parallel execution

Phase 5 is accepted. Phase 6 runs on `codex/parallel-dispatch`, based on that
accepted checkpoint. **Physical-laptop validation and the human checkpoint
passed; Phase 6 is complete.** The validator proved 0.227333 seconds of guaranteed execution overlap
on the remote workers at implementation commit `7bde416`.

## What changed

Control launches Hydro and Flood concurrently using
`run_analysis(..., execution_mode="parallel")`. Each branch retains its own
validated result, failure or timeout; an expected failure does not cancel the
other branch. The terminal Control command defaults to parallel; use
`--execution-mode sequential` to reproduce the earlier behavior. The Phase 5
validator continues using sequential dispatch explicitly through the API default.

Workers expose an authenticated, read-only `GET /clock` with a fresh UTC sample,
hostname and process UUID. The endpoint stays responsive during processing.
Neither numerical processing nor dependency pins changed.

## Update and restart both workers

Stop each running worker with Ctrl+C in its own terminal. Preserve existing API
tokens and use the separate worker checkouts, leaving UI work alone.

Kazi, Windows PowerShell, first checkout of this branch:

```powershell
Set-Location "$HOME\surge-fall-2026-worker"
git fetch origin
git switch --track origin/codex/parallel-dispatch
git rev-parse HEAD
.\.venv\Scripts\python.exe -m pytest -q
```

Karan, Linux Bash, first checkout of this branch:

```sh
cd ~/surge-fall-2026-worker
git fetch origin
git switch --track origin/codex/parallel-dispatch
git rev-parse HEAD
.venv/bin/python -m pytest -q
```

For an existing local branch, use `git switch codex/parallel-dispatch` and
`git pull --ff-only` instead of creating it again. Git should refuse conflicting
local work; do not reset or discard it. Compare the implementation commit on all
three machines. A missing Windows symlink privilege may still yield the one
explicit capability skip; other failures need investigation.

After passing tests, restart in the same terminal with the existing
`MESHMIND_WORKER_TOKEN`. If opening a new terminal, set that same token privately.

Kazi:

```powershell
.\.venv\Scripts\python.exe -m uvicorn backend.workers.hydro.main:create_app --factory --workers 1 --host 100.100.3.2 --port 8002
```

Karan:

```sh
.venv/bin/python -m uvicorn backend.workers.flood.main:create_app --factory --workers 1 --host 100.100.3.4 --port 8003
```

Keep both laptops awake and terminals open. Hydro keeps its existing NASA files;
Flood uses its existing public data access. Do not copy credentials or virtual
environments between machines.

## Run the remote checkpoint from Control

Configure the same private worker URLs and tokens as Phase 5, including
`MESHMIND_CONTROL_SOURCE_IP=100.100.3.5` on Ryan's Mac. Environment files are not
automatically loaded. With those variables exported, run:

```sh
.venv/bin/python -m scripts.validate.validate_parallel_workers --confirm-separate-laptops
```

This submits a fresh task ID to both remote workers concurrently after the clock
preflight. It retains complete independent results and clock samples, checks
process continuity and duplicate submission, and distinguishes physical remote
proof from local validation. Expected success is **`PASS / PENDING_USER`**.

The result is `outputs/debug/parallel-workers/result.json`. Inspect:

- both dispatch outcomes `complete`, with matching source evidence and numerical
  measurements from accepted Phase 5;
- `overlap.passed: true` and positive `guaranteed_overlap_seconds`;
- successful clock continuity, topology, authentication and duplicate checks;
- different Control completion times, with the early result preserved;
- matching task activity in Kazi's and Karan's worker terminals.

Do not manually reuse the same task ID to claim fresh overlap: duplicate requests
retrieve retained evidence instead of recomputing. A failure or ambiguous timeout
must retain its original report and task ID for reconciliation.

## Clock proof and limitations

For each worker, Control collects three authenticated clock samples before and
after the run. A worker sample between Control's send/receive times bounds the
offset without assuming symmetric network latency. Pre/post bounds must agree
and identify the same process as the task. Offset uncertainty above 0.1 seconds
fails the check; UTC versus monotonic elapsed time must agree within 0.020 seconds.

Known stable skew can be accounted for. The proof conservatively shrinks both
execution intervals by their offset uncertainty, then requires a positive common
intersection. Merely overlapping HTTP waits or unadjusted wall timestamps does
not pass. Raw timestamps and derived intervals are both retained.

The calculation assumes clocks remain stable between samples. A transient clock
jump that reverses between observations cannot be detected. Worker-reported
timestamps and identities are evidence, not hardware attestation. Kazi reported
resyncing his Windows clock after Phase 5; the new measurements must verify the
current run rather than assuming that report resolves clock uncertainty.

## Development checks

```sh
.venv/bin/python -m scripts.validate.validate_parallel_workers --local-check --output outputs/debug/parallel-workers/local-real/result.json
.venv/bin/python -m scripts.validate.validate_dispatch_failures --execution-mode parallel --output outputs/debug/parallel-failures/result.json
.venv/bin/python -m pytest -q
.venv/bin/python -m pip check
git diff --check
```

The first uses real data but temporary local servers and must remain
`PASS_LOCAL_ONLY / PENDING_REMOTE_LAPTOPS`. The negative TCP checkpoint uses
synthetic data: it exercises ambiguous acceptance/timeouts, a Flood connection
drop after Hydro actually completes, and a missing-resource worker failure.
Those are failure-handling checks, not physical or environmental overlap proof.

## Recorded local verification

On 2026-10-03 America/Vancouver (2026-10-04 UTC):

- Full macOS suite: **758 passed**. Dependency and whitespace checks passed.
- Real-data HTTP validation: **PASS_LOCAL_ONLY / PENDING_REMOTE_LAPTOPS**,
  investigation `d43d8dec-1f98-46a3-80af-b11d00144a30`.
- Hydro processed from 05:45:38.248438 to 05:45:38.571195 UTC; Flood processed
  from 05:45:38.248414 to 05:46:44.294828 UTC. Both were temporary local workers.
- Conservative processing overlap: **0.321560 seconds**, with clock-offset
  uncertainty 0.001150 seconds for Hydro and 0.001206 seconds for Flood.
- Hydro completed first and remained preserved. Both complete result payloads,
  including numerical evidence and sources, match accepted Phase 5 except for
  the newly generated task ID.
- Actual TCP negative checkpoint: all three scenarios passed; the parallel
  connection-drop case observed Hydro complete before failing Flood.
- Timing evidence was rechecked with the final feasibility guard: a single
  calibrated offset must fit the entire worker execution within Control's
  observed submission/completion window. Both workers passed that guard.

Local evidence: `outputs/debug/parallel-workers/local-real/result.json`, its
`reference-comparison.json`, `outputs/debug/parallel-failures/result.json`, and
`outputs/debug/phase6-pytest.log`. These reports remain ignored local artifacts.
At that local checkpoint, Windows/Linux reruns and physical-laptop overlap were
still pending. The later remote verification is recorded below.

Kazi's Windows rerun at `633306f` reported **756 passed, 1 failed, 1 expected
symlink-privilege skip**. The failing concurrency unit test received equal host
wall-clock timestamps and passed when rerun alone. Its observation clock is now
deterministic, while the shared asynchronous barrier, strict interval assertion,
serialization check and rejection of sequential classification remain intact.
Production clocks, real deadlines and physical overlap validation are unchanged.
Kazi's subsequent full Windows rerun at `7bde416` passed: **757 passed, 1 expected
symlink-privilege skip, 0 failures**. The user also confirmed Karan pulled the
update, passed his Linux tests and restarted Flood; an exact Linux test count
was not supplied.

## Physical-laptop validation — accepted

Recorded on **2026-10-03 America/Vancouver** (2026-10-04 UTC), using implementation
commit `7bde416c701d88072f8ae8801c1d35ebb91c8ea0` on Control and operator-confirmed
matching worker updates and restarts. Later documentation commits record this
evidence without changing the implementation tested here.

The validator returned **`PASS / PENDING_USER`** for task
`f1f4cc63-1b2c-4a29-a924-f3c7490b554f`. Authenticated `/status` and `/clock` checks
confirmed both remote workers idle before dispatch; unauthenticated requests to
both routes returned 401.

| Worker | Host | Raw worker start (UTC) | Raw worker completion (UTC) | Duration |
|---|---|---|---|---:|
| Hydro / Windows | `Boni` | 06:06:17.173756 | 06:06:17.411409 | 0.237653 s |
| Flood / Linux | `ARE` | 06:06:17.202820 | 06:07:48.722587 | 91.519767 s |

After calibrating both clocks to Control and conservatively accounting for
uncertainty, the guaranteed common execution interval was
**06:06:17.207706–06:06:17.435039 UTC: 0.227333 seconds**.

| Clock bound (worker UTC minus Control UTC) | Lower | Upper | Uncertainty |
|---|---:|---:|---:|
| Hydro | −0.033950 s | −0.023630 s | 0.010320 s |
| Flood | 0.000127 s | 0.009031 s | 0.008904 s |

All pre/post sample, process identity, Control-window feasibility and clock
continuity checks passed. These measured bounds account for the remaining skew;
the clocks are not claimed to be identical. A live snapshot at approximately
06:07:36–06:07:37 UTC observed Hydro `complete` while Flood remained `processing`.
Control collected Hydro first and Flood 91.181057 seconds later. Hydro's complete
result remained preserved.

Both complete result payloads and both bounded requests exactly match accepted
Phase 5 except for the new task IDs. Rainfall remains 6.650416513284047 mm; surface
and root-zone moisture remain 0.4084949195384979 / 0.3924146294593811 m³/m³;
candidate-water area remains 88.0997 km² with 97.6354% valid SAR coverage. Sources,
AOI, threshold and the rest of the numerical evidence match as well.

Authentication, duplicate submission and all physical-topology checks passed.
The existing controlled local TCP failure checkpoint also passed, including
preserving Hydro after Flood's connection fails. This successful remote run
does not claim remote fault injection; its overlap evidence concerns the workers'
reported task-execution intervals. Stable-clock
and worker-reported evidence limitations above still apply.

Evidence in `outputs/debug/parallel-workers/physical-7bde416/`:

- `preflight.json`: authentication/readiness and operator update/test reports;
- `result.json`: full dispatch, clock bounds, overlap, results and phase gates;
- `progress-snapshot.json`: Hydro complete while Flood continued processing;
- `reference-comparison.json`: complete request/result comparison with Phase 5.

**Human checkpoint complete:** after receiving the passing results and task ID,
the user confirmed that both Kazi and Karan observed the activity. This completes
the requested manual check alongside the successful numerical comparison,
overlap proof and failure-handling tests. The confirmation and completed gate are
recorded in `human-checkpoint.json` in the evidence directory above. The raw
validator report preserves its historical `PASS / PENDING_USER` result.

Phase 6 is complete. Stop at this checkpoint; later phases remain outside the
current request. No further real-data run or HTML review is needed for closure.
