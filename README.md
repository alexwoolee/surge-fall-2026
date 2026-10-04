# Amalga

Amalga combines rainfall, soil moisture, satellite observations and available site
records into a flood-risk assessment. Independent workers analyze the requested
location and historical dates; Control checks their results and uses AI to explain
how the evidence fits together in a summary and downloadable report. Risk scores
are screening indicators, not flood probabilities.

Hydro and Flood run for every resolved request. Toddbrook Reservoir in Whaley
Bridge, Derbyshire also uses its dedicated Dam worker. Use `main` for the
integrated application.

## Setup

Install **Git, Python 3.12, Node.js 20.9+ and npm**, then clone the project:

```sh
git clone --branch main https://github.com/alexwoolee/surge-fall-2026.git
cd surge-fall-2026
```

Create and activate a Python environment.

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

Install dependencies and save your NASA Earthdata login on the Hydro computer:

```sh
python -m pip install -r requirements.txt
python -c "import earthaccess; earthaccess.login(strategy='interactive', persist=True)"
```

Create the ignored `.env.phase8.local` file in the repository root with your own
OpenAI settings. Only Control needs this file:

```dotenv
OPENAI_API_KEY=your_api_key
OPENAI_MODEL=gpt-5.4-mini
```

Keep credentials out of Git and chat. Internal service tokens are not required.
Internet access is needed for the data providers and AI interpretation.

## Run locally

Open four terminals from the repository root. Activate the Python environment in
each Python terminal using the command above. Stop an existing service before
starting another on the same port.

**Terminal 1 — Hydro**

```sh
python -m scripts.run_worker hydro
```

**Terminal 2 — Flood**

```sh
python -m scripts.run_worker flood
```

**Terminal 3 — Control**

```sh
python -m backend.control.serve --generic --openai-env-file .env.phase8.local
```

**Terminal 4 — interface**

```sh
cd frontend
npm ci
npm run build
npm run start
```

The interface prints its link and opens [Amalga](http://127.0.0.1:3000). Hydro and
Flood also open their own dashboards. For headless operation, add
`--no-open-dashboard` to a worker command or `-- --no-open-dashboard` to
`npm run start`. Stop services with **Ctrl+C**.

Enter a request and click **Run Analysis** once:

> Assess flood risk at Abbotsford / Sumas Prairie as of 2021-11-15. Explain how the available factors combine, then give the risk level and supporting evidence.

Use ISO dates (`YYYY-MM-DD`). One date selects that UTC day; an inclusive range can
span up to seven days. Toddbrook and Abbotsford are registered place names. For
another area, include a WGS84 box such as `bbox=[-1.94,53.29,-1.90,53.32]`.
Workers query the requested dates and exclude later observations. Hydro downloads
up to four matching files concurrently and processes the full selected set.

Review the opening summary and assessment, then download the report. Each new
investigation makes at most one bounded OpenAI request after the worker results
are checked. Reopening history makes no new model request. To run without AI
credentials, omit `--openai-env-file`; the report retains the worker findings and
identifies the independent screening fallback.

## Team and Toddbrook setup

Use [the four-laptop deployment guide](docs/TODDBROOK_SETUP.md) for Kazi's Hydro,
Alex's Flood, Karan's Dam, and Ryan's Control, including copyable commands and
prompts for **2007-12-09** and **2019-08-01**. The prepared Dam bundle is included
under `private_data`; no installer or separate transfer is needed. Only the Dam
worker reads those inputs during an investigation. Owner-only storage is simulated
in this shared-repository demonstration.

- [Developer commands](DEVELOPER_SETUP.md)
- [Architecture, progress and development checkpoints](PROJECT_PROGRESS.md)
- [Frontend setup](frontend/README.md)
