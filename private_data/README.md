# Worker-local data

This folder belongs only to the device running the private-data worker: Karan's
computer in the deployment. The supplied archive used during development is a
local development copy, not a reason to distribute records to other devices.

Run `python -m scripts.install_private_dataset /path/to/todbrook.zip` on that
worker. Keep the raw archive outside the runtime folder, such as in Downloads.
The installer selects the approved JSONL members and a fixed allowlist of fields
needed for calculations, then publishes only sanitized runtime files under
the following path. The original archive is unchanged; only the runtime copy
omits discarded fields:

```text
toddbrook_runtime/data/
```

The Dam worker reads that runtime directory. Raw notes, identities,
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
