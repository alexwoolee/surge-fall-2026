# Phase 6 — Real parallel execution

Phase 5 is accepted. Phase 6 runs on `codex/parallel-dispatch`, based on that
accepted checkpoint. Its physical-laptop and human gates remain pending until
the new validator proves actual overlapping processing on the remote workers.

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
Windows/Linux reruns on the Phase 6 branch and physical-laptop overlap remain
pending. No Phase 6 completion is claimed from these local results.

Kazi's Windows rerun at `633306f` reported **756 passed, 1 failed, 1 expected
symlink-privilege skip**. The failing concurrency unit test received equal host
wall-clock timestamps and passed when rerun alone. Its observation clock is now
deterministic, while the shared asynchronous barrier, strict interval assertion,
serialization check and rejection of sequential classification remain intact.
Production clocks, real deadlines and physical overlap validation are unchanged.
Another full Windows rerun is required; Karan's update confirmation remains pending.

After the physical run passes, compare numerical results, obtain human acceptance
and stop at the Phase 6 checkpoint. No HTML review is needed. Later phases are
outside the current request.
