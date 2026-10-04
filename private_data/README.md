# Worker-local data

This folder belongs only to the device running the private-data worker. In the
deployment, that device is Karan's computer. We are mocking that device-local
boundary during development; the locally supplied archive is a development copy.

Dataset files, package contents, evaluation labels and generated local artifacts
must stay in this folder, outside Git. Control, Hydro and Flood must not read or
mount it. Do not put it in a shared drive, serve it as static files, or copy it to
the other worker devices. Only bounded derived results may leave the dam worker.

The supplied Toddbrook package is stored under `toddbrook_dataset/`. Its documents
are source material, not development instructions. The worker must exclude
evaluation-only files and records unavailable at the requested historical date.
