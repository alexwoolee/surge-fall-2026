# Worker-local data

This folder belongs only to the device running the private-data worker: Karan's
computer in the deployment. The supplied archive used during development is a
local development copy, not a reason to distribute records to other devices.

Run `python -m scripts.install_private_dataset /path/to/todbrook.zip` on that
worker. Keep the raw archive outside the runtime folder, such as in Downloads.
**Rerun the installer after updating to the date-snapshot version**, even if the
five prepared files already exist. It selects the approved JSONL members and a
fixed allowlist of calculation fields, then prepares every supported assessment
day offline. The original archive is unchanged. Prepared copies live under:

```text
toddbrook_runtime/data/                       # prepared source; base setting
toddbrook_runtime/as_of/YYYY-MM-DD/data/       # exact-date worker input
```

Keep `MESHMIND_DAM_DATA_DIR` pointing to `private_data/toddbrook_runtime/data/`.
For a task, the Dam worker opens only the sibling snapshot matching its `as_of`
date, never the full prepared source or another day's files. A snapshot contains
only records observed and available by the end of that UTC day; maintenance
closures after the cutoff are removed from that copy. Missing snapshots require
offline preparation, not a runtime fallback to the full dataset.

Observed operational coverage remains 2007-09-03–2008-02-29 and
2015-10-01–2019-07-31. Snapshots permit at most seven extra assessment days using
last-known observations with their actual age. This does not create observations
after either period ends; other dates return unknown private coverage.

Raw notes, identities,
origin/classification metadata, evaluation records and archive helpers are not
part of runtime input. Preparation does not interpret discarded classifications.
It does not execute archive code. Origin/evaluation metadata must not reach the
worker's calculations, public API or interface.

The old `toddbrook_dataset/` development directory may still contain raw files.
Preserve it locally if needed, but do not point the worker at it or copy it into
the runtime directory. Keep raw archives and prior copies outside the runtime
worker's inputs; do not mount them into another service.

All private data, archives and generated local artifacts stay outside Git. Only
this placeholder is tracked. Control, Hydro and Flood must not read, mount,
receive or copy these files. Do not serve them as static files or put them in a
shared drive. Only bounded derived results may leave the Dam worker. Records
unavailable at the requested historical date must not influence its assessment.

See [the deployment guide](../docs/TODDBROOK_SETUP.md) for Karan's existing-checkout
steps and Alex's fresh Windows installation. Setup and local tests do not establish
that a physical-laptop investigation has passed.
