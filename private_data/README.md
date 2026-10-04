# Amalga Dam inputs

The repository includes the prepared date bundle for this demonstration:

```text
toddbrook_runtime/as_of.zip
```

**Pull and start the worker. No installer, extraction or separate copy is needed.**
Keep `MESHMIND_DAM_DATA_DIR` pointing to `private_data/toddbrook_runtime/data/`;
the worker reads the sibling `as_of.zip` directly, preferring it over older
extracted snapshots. It opens only the five members for the requested `as_of`
day, never another day's contents or the full prepared source. Each day contains
only records observed and available by its UTC end-of-day cutoff; later
maintenance closures are absent from that copy. Missing or invalid dated inputs
fail explicitly rather than falling back to the full dataset.

The user authorized sharing this prepared bundle in Git for the demonstration.
Every repository checkout includes it, and repository users can read it. Only the
Dam service consumes these records during an investigation; Control, Hydro and
Flood use their own inputs and the returned aggregates. Production storage that
restricts access to the record owner is simulated, not enforced by this checkout.

Observed operational coverage remains 2007-09-03–2008-02-29 and
2015-10-01–2019-07-31. Snapshots permit at most seven extra assessment days using
last-known observations with their actual age. This does not create observations
after either period ends; other dates return unknown private coverage.

The bundle includes only the fixed allowlist of model-needed fields. Raw notes,
identities, origin/classification metadata, evaluation records and archive helpers
are excluded. Preparation does not interpret discarded classifications or execute
archive code. Origin/evaluation metadata must not reach calculations, the public
API or the interface. The original raw archive, evaluation files and helpers are
not tracked.

The old `toddbrook_dataset/` development directory may still contain raw files.
Preserve it locally if needed, but do not point the worker at it. Keep original
archives and prior development copies outside runtime inputs. Do not serve the
bundle as a static asset or send its contents through the worker API; only bounded
derived results leave Dam at runtime. Records unavailable at the requested
historical date must not influence its assessment.

See [the deployment guide](../docs/TODDBROOK_SETUP.md) for Karan's existing-checkout
steps and Alex's fresh Windows installation. Setup and local tests do not establish
that a physical-laptop investigation has passed.
