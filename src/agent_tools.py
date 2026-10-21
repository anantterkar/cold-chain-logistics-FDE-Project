import re
import sqlite3
import requests
from functools import lru_cache
from pathlib import Path

import pandas as pd
import pypdf
from dotenv import load_dotenv
from langchain_community.vectorstores import FAISS
from langchain_core.documents import Document
from langchain_core.tools import tool
from langchain_text_splitters import RecursiveCharacterTextSplitter

# ==========================================
# 1. LOCAL DATA & VECTOR INDEX ATTACHMENT
# ==========================================
script_dir = Path(__file__).resolve().parent
project_root = script_dir.parent

load_dotenv(dotenv_path=project_root / ".env")

DATASET_PATH = project_root / "data" / "raw" / "dynamic_supply_chain_logistics_dataset.csv"
POLICY_DIR = project_root / "data" / "policy"
SOP_INDEX_DIR = project_root / "data" / "cache" / "sop_faiss_index"

LEGACY_TO_VIEW_COLUMNS = {
    "timestamp": "Timestamp",
    "vehicle_gps_latitude": "Latitude",
    "vehicle_gps_longitude": "Longitude",
    "iot_temperature": "Current_Temperature_C",
    "cargo_condition_status": "Cargo_Condition_Code",
    "risk_classification": "Risk_Classification",
    "delay_probability": "Delay_Probability",
    "port_congestion_level": "Port_Congestion_Level",
    "route_risk_level": "Route_Risk_Index",
}


def get_cached_huggingface_embeddings(model_name: str):
    """
    Loads and locks the HuggingFace model weights into the machine's global RAM.
    If called again during any subsequent script rerun, it returns instantly.
    """
    import streamlit as st
    
    # Cache the local embedding model for fast reruns in Streamlit.
    @st.cache_resource(show_spinner=False)
    def _load_model(name: str):
        print(f"🧠 MEMORY SEED: Permanently caching local model [{name}] in global RAM...")
        from langchain_huggingface import HuggingFaceEmbeddings
        return HuggingFaceEmbeddings(
            model_name=name,
            model_kwargs={"device": "cpu"},
        )
    return _load_model(model_name)

local_model_target = "BAAI/bge-m3"

try:
    import streamlit as st

    if st.runtime.exists():
        embeddings = get_cached_huggingface_embeddings(local_model_target)
    else:
        from langchain_huggingface import HuggingFaceEmbeddings

        embeddings = HuggingFaceEmbeddings(
            model_name=local_model_target,
            model_kwargs={"device": "cpu"},
        )
except ImportError:
    from langchain_huggingface import HuggingFaceEmbeddings

    embeddings = HuggingFaceEmbeddings(
        model_name=local_model_target,
        model_kwargs={"device": "cpu"},
    )


def _parse_policy_file(file_path: Path) -> list[Document]:
    splitter = RecursiveCharacterTextSplitter(chunk_size=600, chunk_overlap=60)
    suffix = file_path.suffix.lower()

    if suffix in {".md", ".txt"}:
        content = file_path.read_text(encoding="utf-8", errors="ignore")
        docs = [Document(page_content=content)]
        return splitter.split_documents(docs)

    if suffix == ".pdf":
        text_parts: list[str] = []
        with open(file_path, "rb") as f:
            reader = pypdf.PdfReader(f)
            for page in reader.pages:
                page_text = page.extract_text() or ""
                if page_text.strip():
                    text_parts.append(page_text)
        docs = [Document(page_content="\n".join(text_parts))]
        return splitter.split_documents(docs)

    if suffix in {".csv", ".xlsx"}:
        df = pd.read_csv(file_path) if suffix == ".csv" else pd.read_excel(file_path)
        row_docs = []
        for _, row in df.iterrows():
            row_text = " | ".join(
                f"{col}: {val}" for col, val in row.items() if pd.notna(val) and str(val).strip()
            )
            if row_text:
                row_docs.append(Document(page_content=row_text))
        return splitter.split_documents(row_docs)

    return []


def _build_local_retriever():
    if SOP_INDEX_DIR.exists():
        vector_store = FAISS.load_local(
            str(SOP_INDEX_DIR),
            embeddings,
            allow_dangerous_deserialization=True,
        )
        return vector_store.as_retriever(search_kwargs={"k": 2})

    docs: list[Document] = []
    for pattern in ("*.md", "*.txt", "*.pdf", "*.csv", "*.xlsx"):
        for file_path in POLICY_DIR.glob(pattern):
            parsed_docs = _parse_policy_file(file_path)
            for doc in parsed_docs:
                doc.metadata["source_file"] = file_path.name
                doc.metadata["file_format"] = file_path.suffix.replace(".", "").upper() or "RAW"
            docs.extend(parsed_docs)

    if not docs:
        return None

    vector_store = FAISS.from_documents(docs, embedding=embeddings)
    return vector_store.as_retriever(search_kwargs={"k": 2})


retriever = _build_local_retriever()


@lru_cache(maxsize=1)
def _get_local_fleet_df() -> pd.DataFrame:
    df = pd.read_csv(DATASET_PATH)
    df_view = df[list(LEGACY_TO_VIEW_COLUMNS.keys())].rename(columns=LEGACY_TO_VIEW_COLUMNS)
    df_view["Timestamp"] = pd.to_datetime(df_view["Timestamp"], errors="coerce").astype(str)
    return df_view


def _to_sqlite_query(sql_query: str) -> str:
    normalized = sql_query.strip().rstrip(";")

    if not normalized.upper().startswith("SELECT"):
        raise ValueError("SECURITY BLOCK: Only SELECT operations are authorized.")

    normalized = re.sub(
        r"\bFDE_VIEWS\s*\.\s*VW_ACTIVE_FLEET\b",
        "VW_ACTIVE_FLEET",
        normalized,
        flags=re.IGNORECASE,
    )

    # Backward-compatible alias used by some model responses.
    normalized = re.sub(
        r"\btelemetry_view\b",
        "VW_ACTIVE_FLEET",
        normalized,
        flags=re.IGNORECASE,
    )

    top_match = re.search(r"(?i)^\s*SELECT\s+TOP\s+(\d+)\s+", normalized)
    if top_match:
        top_n = top_match.group(1)
        normalized = re.sub(r"(?i)^\s*SELECT\s+TOP\s+\d+\s+", "SELECT ", normalized, count=1)
        if not re.search(r"(?i)\bLIMIT\b", normalized):
            normalized = f"{normalized} LIMIT {top_n}"

    return normalized

# ==========================================
# 2. CORE FDE AGENT TOOLS
# ==========================================

@tool
def query_telemetry_db(sql_query: str) -> str:
    """
    Executes a SQL SELECT query against a local telemetry view backed by data/raw CSV.
    Columns available:
    Timestamp, Latitude, Longitude, Current_Temperature_C, Cargo_Condition_Code,
    Risk_Classification, Delay_Probability, Port_Congestion_Level, Route_Risk_Index.
    Use SELECT queries only.
    """

    try:
        sqlite_query = _to_sqlite_query(sql_query)
        local_df = _get_local_fleet_df()

        with sqlite3.connect(":memory:") as conn:
            local_df.to_sql("VW_ACTIVE_FLEET", conn, index=False, if_exists="replace")
            cursor = conn.execute(sqlite_query)
            columns = [desc[0] for desc in cursor.description] if cursor.description else []
            rows = cursor.fetchmany(10)

        if not rows:
            return "No records matched the query criteria."

        formatted_output = f"COLUMNS: {', '.join(columns)}\n"
        for row in rows:
            formatted_output += str(tuple(row)) + "\n"

        return formatted_output
    except ValueError as ve:
        return str(ve)
    except Exception as e:
        return f"Database Error: {str(e)}"

@tool
def fetch_corridor_conditions(latitude: float, longitude: float) -> str:
    """
    Fetches real-time weather and corridor conditions from a live REST API for given GPS coordinates.
    Provides temperature, wind speed, and computed corridor congestion index.
    """
    try:
        url = f"https://api.open-meteo.com/v1/forecast?latitude={latitude}&longitude={longitude}&current_weather=true"
        response = requests.get(url, timeout=6)
        response.raise_for_status()
        
        payload = response.json().get("current_weather", {})
        temp = payload.get("temperature", "N/A")
        wind = payload.get("windspeed", 0.0)
        
        congestion_index = 8.5 if wind > 10.0 else 2.5
        status_note = "High Transit Disruption" if wind > 10.0 else "Corridor Normal"
        
        return (
            f"--- LIVE CORRIDOR TELEMETRY ---\n"
            f"Target GPS: {latitude}, {longitude}\n"
            f"External Temp: {temp}°C | Wind Speed: {wind} km/h\n"
            f"Corridor Risk: {status_note} (Congestion Index: {congestion_index}/10)\n"
            f"-------------------------------"
        )
    except Exception as e:
        return f"Corridor API Communication Failure: {str(e)}"

@tool
def search_compliance_sop(query: str) -> str:
    """
    Searches enterprise Standard Operating Procedures (SOPs) indexed in local FAISS memory.
    Use this to retrieve regulatory thresholds, cold-chain breach mitigations, and rerouting rules.
    """
    try:
        if retriever is None:
            return f"No policy documents found in {POLICY_DIR}."

        matched_docs = retriever.invoke(query)
        if not matched_docs:
            return "No matching compliance clauses found."
            
        formatted_context = "\n\n".join(
            [f"[Source: {doc.metadata.get('source_file', 'SOP')} | Format: {doc.metadata.get('file_format', 'RAW')}]\n{doc.page_content}" for doc in matched_docs]
        )
        return f"--- COMPLIANCE SOP CONTEXT ---\n{formatted_context}\n------------------------------"
    except Exception as e:
        return f"Vector Store Retrieval Error: {str(e)}"

# ==========================================
# 3. LOCAL VERIFICATION
# ==========================================
if __name__ == "__main__":
    print("\n--- Testing Tool 1: SQL Telemetry View ---")
    print(query_telemetry_db.invoke("SELECT TOP 2 Latitude, Longitude, Current_Temperature_C FROM FDE_VIEWS.VW_ACTIVE_FLEET"))
    
    print("\n--- Testing Tool 2: Live Corridor API ---")
    print(fetch_corridor_conditions.invoke({"latitude": 33.77, "longitude": -118.19}))
    
    print("\n--- Testing Tool 3: Local SOP Vector Retrieval ---")
    print(search_compliance_sop.invoke("What are the temperature rules for fresh perishables?"))
