import os
import sys
import uuid
import json
import sqlite3
from pathlib import Path
from dotenv import load_dotenv
import streamlit as st
import pandas as pd
from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage

# ==========================================
# 1. IMMEDIATE PATH & ENVIRONMENT RESOLUTION
# ==========================================
script_dir = Path(__file__).resolve().parent  # points to src/
project_root = script_dir.parent              # climbs to project root

if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

load_dotenv(project_root / ".env")

# Import the compiled graph and tools list dynamically
from src.orchestrator import fde_agent

# ==========================================
# 2. LOCAL AUDIT DB (SQLITE)
# ==========================================
audit_db_path = project_root / "data" / "cache" / "agent_audit.db"
audit_db_path.parent.mkdir(parents=True, exist_ok=True)


def initialize_audit_db():
    with sqlite3.connect(audit_db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS AgentAuditLog (
                LogID INTEGER PRIMARY KEY AUTOINCREMENT,
                Timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                SessionID TEXT,
                NodeExecuted TEXT,
                ToolName TEXT,
                Content TEXT
            )
            """
        )
        conn.commit()


initialize_audit_db()

def write_audit_log(session_id, node_name, tool_name, content):
    """Silently writes agent execution traces to a local SQLite audit table."""
    try:
        with sqlite3.connect(audit_db_path) as conn:
            conn.execute(
                """
                INSERT INTO AgentAuditLog (SessionID, NodeExecuted, ToolName, Content)
                VALUES (?, ?, ?, ?)
                """,
                (session_id, node_name, tool_name, content),
            )
            conn.commit()
    except Exception as e:
        print(f"Audit Log Failed (Silent): {e}")

# ==========================================
# 3. PAGE CONFIGURATION & ENTERPRISE THEME
# ==========================================
st.set_page_config(
    page_title="FDE Supply Chain Dispatch Console",
    page_icon="🧊",
    layout="wide",
    initial_sidebar_state="expanded"
)

st.markdown("""
<style>
    .stApp { background-color: #0B0E14; color: #E2E8F0; }
    div[data-testid="stSidebar"] { background-color: #111622; border-right: 1px solid #1E293B; }
    .stMarkdown code { background-color: #1E293B !important; color: #38BDF8 !important; }
</style>
""", unsafe_allow_html=True)

# ==========================================
# 4. MULTI-USER STATE & THREAD MANAGEMENT
# ==========================================
if "thread_id" not in st.session_state:
    st.session_state.thread_id = str(uuid.uuid4())

if "ui_messages" not in st.session_state:
    st.session_state.ui_messages = []

if "is_thread_seeded" not in st.session_state:
    st.session_state.is_thread_seeded = False

thread_config = {"configurable": {"thread_id": st.session_state.thread_id}}


def load_system_prompt() -> str:
    prompt_path = project_root / "src" / "prompts" / "system_prompt.txt"
    try:
        return prompt_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return "You are a helpful AI assistant."


def ensure_thread_initialized() -> None:
    if st.session_state.is_thread_seeded:
        return

    system_instructions = load_system_prompt()
    fde_agent.invoke(
        {"messages": [SystemMessage(content=system_instructions)]},
        config=thread_config,
    )
    st.session_state.is_thread_seeded = True

# ==========================================
# 5. SIDEBAR NAVIGATION & METADATA
# ==========================================
with st.sidebar:
    st.image(str(script_dir / "image_L25X5q.png") if (script_dir / "image_L25X5q.png").exists() else "https://cdn-icons-png.flaticon.com/512/2830/2830305.png", width=65)
    st.title("FDE Command Center")
    
    app_mode = st.radio("System Mode", ["🧊 Dispatch Console", "🛡️ Security & Audit Logs"])
    
    st.markdown("---")
    st.caption(f"Session Token: `{st.session_state.thread_id[:8]}...`")
    st.markdown(f"**Reasoning Architecture:** `OLLAMA/{os.getenv('OLLAMA_MODEL', 'qwen2.5:7b')}`")
    
    st.markdown("---")
    if st.button("🗑️ Purge Dispatch Workspace Session", use_container_width=True):
        st.session_state.ui_messages = []
        st.session_state.thread_id = str(uuid.uuid4())
        st.session_state.is_thread_seeded = False
        st.rerun()

# ==========================================
# 6. VIEW ROUTING (DISPATCH VS AUDIT)
# ==========================================

if app_mode == "🧊 Dispatch Console":
    # ------------------------------------------
    # TAB 1: CHAT UI & AGENT EXECUTION
    # ------------------------------------------
    st.title("Cold-Chain Incident Control Dashboard")
    st.caption("Production Data Engineering Pipeline • Real-Time Decision Optimization Platform")

    ensure_thread_initialized()

    for entry in st.session_state.ui_messages:
        with st.chat_message(entry["role"], avatar="👤" if entry["role"] == "user" else "🤖"):
            if "traces" in entry:
                for trace in entry["traces"]:
                    if trace["type"] == "tool_input":
                        st.markdown(f"**⚡ Intent Recognized:** `{trace['name']}`")
                        with st.expander(f"📥 View Generated Input ({trace['name']})", expanded=False):
                            st.json(trace["args"])
                    elif trace["type"] == "tool_output":
                        with st.expander(f"📤 View Raw Output ({trace['name']})", expanded=False):
                            st.code(trace["content"], language="text")
            st.markdown(entry["content"])

    if user_input := st.chat_input("Query fleet telemetry, corridor updates, or compliance thresholds..."):
        
        st.session_state.ui_messages.append({"role": "user", "content": user_input})
        with st.chat_message("user", avatar="👤"):
            st.markdown(user_input)

        with st.chat_message("assistant", avatar="🤖"):
            final_response = ""
            current_traces = [] 
            
            with st.status("🧠 Initializing Core Reasoner Node...", expanded=True) as status:
                events = fde_agent.stream(
                    {"messages": [HumanMessage(content=user_input)]}, 
                    config=thread_config,
                    stream_mode="updates"
                )
                
                for event in events:
                    for node_name, node_state in event.items():
                        
                        if node_name == "reasoner":
                            latest_msg = node_state["messages"][-1]
                            
                            # A. Intercept Tool Call Requests (Inputs)
                            if hasattr(latest_msg, "tool_calls") and latest_msg.tool_calls:
                                status.update(label="🧠 Agent generated tool parameters...")
                                for tool_call in latest_msg.tool_calls:
                                    st.markdown(f"**⚡ Intent Recognized:** `{tool_call['name']}`")
                                    with st.expander(f"📥 View Generated Input ({tool_call['name']})", expanded=False):
                                        st.json(tool_call['args'])
                                    
                                    current_traces.append({
                                        "type": "tool_input",
                                        "name": tool_call['name'],
                                        "args": tool_call['args']
                                    })
                                    
                                    write_audit_log(
                                        session_id=st.session_state.thread_id,
                                        node_name="reasoner",
                                        tool_name=tool_call['name'],
                                        content=json.dumps(tool_call['args'])
                                    )
                            
                            # B. Intercept Final Generation
                            if latest_msg.content:
                                final_response = latest_msg.content
                                status.update(label="📝 Generating Operational Resolution Report...")
                                
                                write_audit_log(
                                    session_id=st.session_state.thread_id,
                                    node_name="reasoner_final",
                                    tool_name="LLM Text Synthesis",
                                    content=final_response
                                )
                                
                        elif node_name == "tools":
                            status.update(label="🔧 Executing Enterprise Subsystem Tools...")
                            for msg in node_state.get("messages", []):
                                if isinstance(msg, ToolMessage):
                                    with st.expander(f"📤 View Raw Output ({msg.name})", expanded=False):
                                        st.code(msg.content, language="text")
                                        
                                    current_traces.append({
                                        "type": "tool_output",
                                        "name": msg.name,
                                        "content": msg.content
                                    })
                                    
                                    write_audit_log(
                                        session_id=st.session_state.thread_id,
                                        node_name="tools",
                                        tool_name=msg.name,
                                        content=msg.content
                                    )
                
                status.update(label="Incident Matrix Evaluation Complete", state="complete", expanded=False)
                
            if final_response:
                st.markdown(final_response)
                st.session_state.ui_messages.append({
                    "role": "assistant",
                    "content": final_response,
                    "traces": current_traces
                })
            else:
                error_fallback = "⚠️ Execution Timeout: System engine encountered an unresolved processing edge case."
                st.error(error_fallback)


elif app_mode == "🛡️ Security & Audit Logs":
    # ------------------------------------------
    # TAB 2: LOCAL AUDIT LOG VIEWER
    # ------------------------------------------
    st.title("🛡️ Local Agent Audit Trail")
    st.caption("Inspection of local SQLite logs in data/cache/agent_audit.db")

    col1, col2 = st.columns([3, 1])
    with col1:
        st.markdown("Review all tool inputs/outputs captured during this local session history.")
    with col2:
        if st.button("Clear Logs", use_container_width=True):
            with sqlite3.connect(audit_db_path) as conn:
                conn.execute("DELETE FROM AgentAuditLog")
                conn.commit()
            st.success("Local audit logs cleared.")

    try:
        with sqlite3.connect(audit_db_path) as conn:
            df = pd.read_sql_query(
                """
                SELECT LogID, Timestamp, SessionID, NodeExecuted, ToolName, Content
                FROM AgentAuditLog
                ORDER BY Timestamp DESC
                """,
                conn,
            )

        if not df.empty:
            st.dataframe(
                df,
                column_config={
                    "LogID": st.column_config.NumberColumn("ID", format="%d"),
                    "Timestamp": st.column_config.DatetimeColumn("Execution Time", format="DD/MM/YYYY-h:mm a"),
                    "SessionID": "Session Token",
                    "NodeExecuted": "Graph Node",
                    "ToolName": "Tool Triggered",
                    "Content": "Raw Payload Data",
                },
                hide_index=True,
                use_container_width=True,
                height=600,
            )
        else:
            st.info("No audit logs found yet. Run a query in Dispatch Console first.")
    except Exception as e:
        st.error(f"Local audit log read failed: {e}")