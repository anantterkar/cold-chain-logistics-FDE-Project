# Cold Chain Logistics FDE Project (Local-First)

A local-first intelligent dispatch assistant for cold-chain logistics.

This project lets operations users chat with fleet telemetry, corridor weather conditions, and compliance SOPs from one interface, with all core components running on a local desktop.

## What This Project Does

- Answers dispatch questions using tool-augmented reasoning.
- Queries local telemetry data from CSV (SQL-like access through a controlled tool).
- Checks live weather for route/corridor context.
- Retrieves SOP clauses from a local vector index.
- Records agent traces to a local audit log database.

## Local-Only Architecture

The project has been refactored to remove EC2, legacy MSSQL ingestion, and cloud vector DB dependencies.

Current runtime stack:

- App UI: Streamlit
- Reasoner: Ollama (local model)
- Telemetry source: `data/raw/dynamic_supply_chain_logistics_dataset.csv`
- SOP knowledge base: local FAISS index from `data/policy`
- Audit logs: SQLite at `data/cache/agent_audit.db`

## Repository Structure

```text
requirements.txt
README.md

data/
  raw/
    dynamic_supply_chain_logistics_dataset.csv
  policy/
    Cold_Chain_Incident_SOP_v2.md
  cache/
    agent_audit.db
    sop_faiss_index/               # created after SOP ingestion script runs

scripts/
  ingest_sop_pinecone.py           # now builds local FAISS index

src/
  agent_tools.py                   # tool implementations (telemetry/weather/SOP)
  orchestrator.py                  # LangGraph + local Ollama reasoner
  ui.py                            # Streamlit app + local audit view
  prompts/
    system_prompt.txt
```

## Quick Start (Windows PowerShell)

### 1) Create and activate virtual environment

```powershell
Set-Location "C:\Users\adibr\Desktop\Anant\cold-chain-logistics-FDE-Project-main"
python -m venv .venv
& ".\.venv\Scripts\Activate.ps1"
python -m pip install --upgrade pip
pip install -r requirements.txt
```

### 2) Install Ollama and pull model

If `ollama` is not in PATH, install with winget:

```powershell
winget install -e --id Ollama.Ollama --accept-package-agreements --accept-source-agreements
```

Pull model (use full executable path if needed):

```powershell
& "C:\Users\adibr\AppData\Local\Programs\Ollama\ollama.exe" pull qwen2.5:7b
```

### 3) Build local SOP index (recommended once)

```powershell
python .\scripts\ingest_sop_pinecone.py
```

### 4) Run the app

```powershell
$env:OLLAMA_NUM_GPU="0"
python -m streamlit run .\src\ui.py
```

Then open the Streamlit URL shown in terminal (typically `http://localhost:8501`).

## Configuration

Optional `.env` values:

```env
OLLAMA_MODEL=qwen2.5:7b
OLLAMA_NUM_GPU=0
```

Notes:

- `OLLAMA_NUM_GPU=0` forces CPU inference and avoids GPU/CUDA crashes on unsupported setups.
- No OpenAI/Pinecone/MSSQL credentials are required for the local workflow.

## Example Prompts

Use these in the Dispatch Console:

1. `How many shipments are currently within safe temperature range 0°C to 4°C? Return the count and percentage of total records.`
2. `Find active shipments near Los Angeles (Latitude around 33.8, Longitude around -118.1), compare Current_Temperature_C with SOP thresholds for fresh perishables, and identify any breaches.`
3. `List 10 shipments where Current_Temperature_C > 4.0 with Latitude, Longitude, Risk_Classification, and a two-step SOP action plan.`

## Validation Commands

```powershell
python -m compileall src scripts
python -c "from src.agent_tools import query_telemetry_db; print(query_telemetry_db.invoke('SELECT COUNT(*) AS total FROM VW_ACTIVE_FLEET'))"
```

## Troubleshooting

### `ollama : The term 'ollama' is not recognized`

Use full path command or open a new terminal after install:

```powershell
& "C:\Users\adibr\AppData\Local\Programs\Ollama\ollama.exe" --version
```

### CUDA / llama-server error (`0xc0000409`, `shared object initialization failed`)

Run in CPU mode:

```powershell
$env:OLLAMA_NUM_GPU="0"
python -m streamlit run .\src\ui.py
```

### Agent says telemetry is unavailable

- Clear session in UI using **Purge Dispatch Workspace Session**.
- Retry query.
- Telemetry aliases are supported (`telemetry_view` and `VW_ACTIVE_FLEET`).

## Security and Data Scope

- Telemetry operations are restricted to read-only SQL-like SELECT queries in tool logic.
- Audit logs are local-only (SQLite).
- No outbound cloud dependency is required for telemetry/SOP indexing.
- Weather calls use a public Open-Meteo endpoint.

## Change Summary (Local Refactor)

- Removed EC2 deployment path from active runtime workflow.
- Removed legacy MSSQL ingestion/security script dependency from runtime path.
- Replaced Pinecone retrieval with local FAISS index.
- Replaced DB audit logging with local SQLite.
- Added tool/query reliability fixes and session prompt seeding in UI.

## License

Add your preferred license file if this repository will be shared publicly.
