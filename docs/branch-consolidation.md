# One shared branch for every laptop

The user requested consolidation and pruning on October 4, 2026, after accepting
the complete three-laptop Phase 9 checkpoint. **`main` is the sole permanent
branch.** Control, Hydro, Flood and the frontend run the same code; their entry
points, input data and private settings select their roles.

## Preserved work

The accepted integration at `d9876a8b74b9312ce43942d9e98999c6a853d584` contains
every remote branch tip at the cleanup audit, including the original frontend
commit `5ae2919`, all data smoke tests, Hydro processors and Phases 1–9. Both
local and remote `main` were ancestors, allowing a normal fast-forward. No
accepted runtime code or dependency pins were changed by this cleanup.

The local-only `codex/phase2-validation` branch had one distinct commit,
`fb9910680daa0ebb97e89139adbeece7a5cd8b5c`. It was the earlier experiment the user
asked to abandon and redo after the README refresh. Its processing behavior is
not part of the accepted implementation. The annotated archive tag
**`archive/phase2-validation-2026-10-04`** retains that exact commit locally and
on GitHub. It was preserved before pruning the branch, without merging the
experiment into the validated processors.

Completed `codex/*`, `data/*`, `feature/*` and `kazi/frontend-ui` branches can be
removed because their commits are reachable from `main`, except for the
explicitly tagged experiment. GitHub had no open pull requests at the audit.
Remote tips are checked against their audited commit IDs before deletion, so
concurrent new work must be retained and reviewed instead of silently removed.
Historical branch names in phase records remain provenance, not setup targets.

## Existing laptops

No worker restart is required merely because remote branch names were pruned.
Running processes, local checkouts, virtual environments, input files and private
tokens remain in place. On the next planned update, run inside each checkout:

```sh
git status --short
git fetch --prune origin
git switch main
git pull --ff-only origin main
git rev-parse --short HEAD
```

`git switch main` uses the existing local branch or creates one tracking
`origin/main` when only the remote branch exists. If the initial status reports
local changes, preserve them before switching. If Git refuses the switch or
fast-forward, stop and inspect the divergence; do not reset, clean or force-push.
For an active worker, schedule the update and normal service restart when idle.
Keep the same environment, role-specific startup command and credentials.

An old local phase branch can be removed with `git branch -d BRANCH_NAME` after
switching and verifying it is merged into `main`. Run that command only for
branches whose work is preserved; this cleanup does not remotely delete local
branches or uncommitted changes on another person's laptop.

For a fresh clone:

```sh
git clone --branch main https://github.com/alexwoolee/surge-fall-2026.git
```

## Future work

Create one temporary `codex/<active-work>` branch from updated `main` only when
starting a concrete change. Follow the existing development, test and human
checkpoint process. Merge accepted work into `main`, then delete its branch.
No permanent branch per laptop or service is needed. Phase 10 remains unstarted.

The accepted source tree and previous test evidence remain unchanged by this
documentation and reference cleanup. Ancestry, unchanged runtime files, clean
diffs and live read-only listener checks verify consolidation; they do not
claim another physical investigation or another automated test-suite run.
