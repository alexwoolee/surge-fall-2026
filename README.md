# MeshMind

MeshMind combines rainfall, soil moisture, satellite surface-water observations
and terrain measurements into a grounded environmental briefing. A Control
service coordinates two Python workers, checks their results and applies explicit
review rules. The web interface shows real task progress and exports a standalone
HTML report.

The included example investigates **Abbotsford / Sumas Prairie, 14–16 November
2021**. Its observations have different dates and coverage; the app reports those
limits rather than treating missing data as zero. It supports environmental
analysis, not emergency-response or evacuation decisions.

## Run locally

This setup runs Control, both workers and the interface on one computer. For the
team's distributed deployment, see [DEVELOPER_SETUP.md](DEVELOPER_SETUP.md).

You need Git, **Python 3.12**, **Node.js 20.9 or newer** with npm, a NASA Earthdata
account for the input download, and an OpenAI API key for request interpretation
and explanation. Internal MeshMind token values are ignored; missing or invalid
internal credentials do not block access.

### 1. Install Python dependencies

```sh
git clone --branch main https://github.com/alexwoolee/surge-fall-2026.git
cd surge-fall-2026
```

Create and activate a virtual environment:

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

Then install the pinned dependencies:

```sh
python -m pip install -r requirements.txt
```

Use this activated environment for the Python commands below. Activate it again
in each new Python terminal. If PowerShell blocks activation, use
`.\.venv\Scripts\python.exe` in place of `python`.

### 2. Prepare the example inputs

From the repository root, sign in to NASA interactively and download the example
GPM and SMAP files:

```sh
python -c "import earthaccess; earthaccess.login(strategy='interactive', persist=True)"
python -m scripts.validate.prepare_hydro_data
```

Inputs are cached under `data/cache/`. Flood processing retrieves public
Sentinel-1, DEM and HAND data when a job runs, so it needs Internet access.

### 3. Configure Control

Create these local files with the contents shown. Replace the OpenAI key
placeholder privately; these files are ignored by Git. NASA and OpenAI still
require their own external-service credentials.

**`.env.openai.local`** in the repository root:

```dotenv
OPENAI_API_KEY=your-openai-api-key
OPENAI_MODEL=gpt-5.4-mini
```

**`.env.workers.local`** in the repository root:

```dotenv
HYDRO_WORKER_URL=http://127.0.0.1:8002
FLOOD_WORKER_URL=http://127.0.0.1:8003
```

The interface already defaults to Control at `http://127.0.0.1:8001`.

### 4. Start the services

Keep four terminals open. Run the Python commands from the repository root with
the virtual environment activated. If a server is already running on a port,
reuse it instead of starting another copy.

**Terminal 1 — Hydro worker**

```sh
python -m scripts.run_worker hydro
```

**Terminal 2 — Flood worker**

```sh
python -m scripts.run_worker flood
```

Each worker opens its own dashboard: [Hydro](http://127.0.0.1:8002/dashboard) and
[Flood](http://127.0.0.1:8003/dashboard). Add `--no-open-dashboard` for headless use.

**Terminal 3 — Control**

```sh
python -m backend.control.serve --execute --rules config/rules.example.json --openai-env-file .env.openai.local --worker-env-file .env.workers.local --gpm-resources 3B-HHR.MS.MRG.3IMERG.20211115-S000000-E002959.0000.V07B.HDF5 3B-HHR.MS.MRG.3IMERG.20211115-S003000-E005959.0030.V07B.HDF5 --smap-resource SMAP_L4_SM_gph_20211114T223000_Vv8010_001.h5
```

**Terminal 4 — interface** (start from the repository root)

```sh
cd frontend
npm ci
npm run build
npm run start
```

Open [MeshMind](http://127.0.0.1:3000), paste the request below and click
**Run Analysis** once:

> Investigate Abbotsford / Sumas Prairie for 14–16 November 2021 using the configured rainfall, soil moisture, candidate surface-water and terrain evidence. Explain the demonstration review conditions and coverage limitations.

Wait for both workers and the briefing. A **Partial result** can describe limited
observation coverage even when processing succeeds. Review the measurements,
source dates and conditions, then download the briefing. To stop a service, wait
for its job to finish and press Ctrl+C in its terminal.

## More information

- [Developer and distributed-machine setup](DEVELOPER_SETUP.md)
- [Architecture, scientific details, progress and development workflow](PROJECT_PROGRESS.md)
- [Frontend details](frontend/README.md)

Saved configuration, cached data and generated reports are local to each machine.
Keep distributed services on a trusted private network; internal APIs do not
check access tokens.
