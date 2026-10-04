# MeshMind

MeshMind combines rainfall, soil moisture, satellite surface-water observations,
terrain and available site records into a flood-risk screening briefing. Control
sends the same location and historical dates to independent workers, checks their
results, and asks AI to interpret their combined context in a plain-language
opening summary, risk assessment and downloadable report.
Missing data remains explicit; risk scores are screening indicators, not flood
probabilities or emergency guidance.

This branch adds a Dam records worker for **Toddbrook Reservoir, Whaley Bridge,
Derbyshire, England**. Hydro and Flood run for every resolved request; only
Toddbrook requests also use the Dam worker. The feature remains separate from
`main` until approved.

## Install

You need Git, **Python 3.12**, **Node.js 20.9+** and npm. For the team's four-laptop
setup, use [the deployment guide](docs/TODDBROOK_SETUP.md).

```sh
git clone --branch codex/toddbrook-private-worker https://github.com/alexwoolee/surge-fall-2026.git
cd surge-fall-2026
```

Create and activate a Python environment:

**macOS / Linux**

```sh
python3.12 -m venv .venv
source .venv/bin/activate
```

**Windows PowerShell**

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
```

Then install dependencies and save NASA Earthdata login on the Hydro computer:

```sh
python -m pip install -r requirements.txt
python -c "import earthaccess; earthaccess.login(strategy='interactive', persist=True)"
```

Hydro queries NASA for the requested area and dates when a job runs, downloading
or reusing exactly matching files. Flood queries public satellite observations.
This dated mode excludes DEM/HAND terrain whose observation dates cannot be
verified, before discovering or reading it. Internet access is required. No fixed
input ZIP or preselected recent hours are used by this mode. Hydro downloads up to
four matching files concurrently and processes the full selected set, without
sampling away observations. Internal API tokens are not required. AI interpretation
uses an OpenAI key on Control only; worker laptops do not need that key.

## Run

For a local Hydro/Flood setup, open four terminals from the repository root.
Activate the Python environment in each Python terminal. Reuse an existing server
only if it is running this branch's code; do not start two servers on the same port.

**Terminal 1 — Hydro**

```sh
python -m scripts.run_worker hydro
```

**Terminal 2 — Flood**

```sh
python -m scripts.run_worker flood
```

**Terminal 3 — Control**

Create the ignored `.env.phase8.local` file in the repository root with your own
private values, or reuse an existing OpenAI settings file:

```dotenv
OPENAI_API_KEY=your_api_key
OPENAI_MODEL=gpt-5.4-mini
```

```sh
python -m backend.control.serve --generic --openai-env-file .env.phase8.local
```

Keep the key out of Git and chat. Each new investigation makes at most one bounded
OpenAI Responses API request after the worker results are checked. Reopening saved
history makes no new model request. Without configured credentials, omit the flag;
the report clearly labels AI interpretation as unavailable and retains the checked
worker evidence. A failed or invalid AI response uses the same labeled fallback.

**Terminal 4 — interface**

```sh
cd frontend
npm ci
npm run build
npm run start
```

The interface prints its link and opens [MeshMind](http://127.0.0.1:3000).
The workers open their own [Hydro](http://127.0.0.1:8002/dashboard) and
[Flood](http://127.0.0.1:8003/dashboard) dashboards. Add `--no-open-dashboard` to a
worker command, or `-- --no-open-dashboard` to `npm run start`, for headless use.

Paste a request and click **Run Analysis** once:

> Assess flood risk at Abbotsford / Sumas Prairie as of 2021-11-15. Begin with a plain-language explanation of how the available factors combine, then give the risk level and supporting technical evidence.

Use ISO dates (`YYYY-MM-DD`). One date selects that UTC day, with an end-of-day
cutoff; an inclusive date range may span up to seven days. Modern reprocessing of
historical environmental observations is allowed, but observations after the
cutoff are excluded. Other areas work with an explicit WGS84 box,
for example `bbox=[-1.94,53.29,-1.90,53.32]`. Place names without coordinates are
currently registered for Toddbrook and Abbotsford. Dates before a product existed,
missing observations and failed downloads remain unavailable.

For Toddbrook, configure Karan's Dam worker using [the deployment guide](docs/TODDBROOK_SETUP.md),
which includes the exact four-device commands and prompts for **2007-12-09** and
**2019-08-01**. Pull the code and start Dam: its prepared date bundle is included
at `private_data/toddbrook_runtime/as_of.zip`, with no installer, extraction or
separate data transfer. Dam reads only the requested day's model-needed fields;
future observations and future maintenance closures are absent. Its base setting
stays `private_data/toddbrook_runtime/data/`. Up to seven days after an observed
period ends, Dam may use last-known evidence with its actual age; recorded coverage
is not extended. The local Hydro/Flood setup above still produces a briefing if
Dam is unavailable, with that worker's status shown explicitly.

This demonstration intentionally shares the prepared bundle through Git, so anyone
with repository access can read it. Only Dam consumes it during investigations;
production storage restricted to the data owner is simulated here. The original
raw archive, evaluation files and archive helpers are not tracked.

The AI considers relationships in the evidence—for example whether rainfall adds
concern to recorded spillway issues, or wet soil changes the meaning of rainfall.
These are contextual questions, not mandatory combined-risk threshold rules.
Unavailable products remain source notes; they are not invented as measurements.

Wait for the opening summary, review the supporting measurements, and download the report.
Stop each service with Ctrl+C when its job is finished. Keep distributed services
on a trusted private network; internal API tokens are ignored.

## More information

- [Four-device setup, historical prompts and Codex handoffs](docs/TODDBROOK_SETUP.md)
- [Developer setup and the existing configured example](DEVELOPER_SETUP.md)
- [Architecture, progress, validation and development process](PROJECT_PROGRESS.md)
- [Frontend details](frontend/README.md)
