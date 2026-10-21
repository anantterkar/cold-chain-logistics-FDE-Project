# Local Desktop Setup (No EC2, No Legacy DB)

This project now runs fully on your local machine with:
- local telemetry data from data/raw/dynamic_supply_chain_logistics_dataset.csv
- local SOP retrieval from files in data/policy
- local audit logs stored in data/cache/agent_audit.db

## 1. Create environment and install dependencies

Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## 2. Ensure local Ollama model is available

Install Ollama and pull a model:

```powershell
ollama pull qwen2.5:7b
```

Optional: set a different local model in .env:

```env
OLLAMA_MODEL=qwen2.5:7b
```

## 3. Run local checks

```powershell
python src\agent_tools.py
python src\orchestrator.py
```

## 4. Launch local app

```powershell
streamlit run src\ui.py
```

## 5. Example test prompts

Prompt 1:

```text
Find any active shipments near Los Angeles (Latitude ~33.8, Longitude ~-118.1). Check the local weather there, and tell me if the current cargo temperature violates the SOP for fresh perishables.
```

Prompt 2:

```text
I'm a new dispatcher on the night shift. Can you quickly explain the difference between a Tier 1 and Tier 2 escalation?
```

## Notes

- Legacy EC2 + MSSQL ingestion is removed from the runtime path.
- You do not need to run scripts/ingest_legacy_data.py.
- You do not need to provision SQL users, views, or security scripts.