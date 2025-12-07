
***

# 🤖 Langie – Autonomous Invoice Processing Agent

**Langie** is an intelligent agent built with **LangGraph**, **Model Context Protocol (MCP)**, and **OpenAI (GPT)**. It automates the end-to-end processing of invoices—from ingestion and OCR to 3-way matching and ERP posting—while keeping a human in the loop (HITL) for high-risk decisions.

---

## 🌟 Key Features

*   **🧠 Cognitive Architecture**: Uses an LLM (GPT-4.1) to make dynamic decisions (e.g., selecting the best OCR tool based on file type, performing semantic fuzzy matching between Invoice and PO).
*   **🔌 MCP Architecture**: Decouples logic into separate servers:
    *   **ATLAS Server**: Handles external interactions (OCR, ERP, Email).
    *   **COMMON Server**: Handles internal logic (Calculations, DB Persistence).
*   **⏸️ Human-in-the-Loop (HITL)**: Automatically detects discrepancies (e.g., mismatching amounts) and pauses the workflow, generating a review ticket for a human operator.
*   **💾 Robust State Management**: Uses SQLite with Write-Ahead Logging (WAL) and LangGraph Checkpointing to persist state across server restarts.
*   **🔍 Full Observability**: Tracks every step, reasoning decision, and tool output in a traceable audit log.

---

## 📂 Project Structure

```text
├── agent_core.py       # 🧠 The Brain: Class defining Langie's LLM reasoning capabilities
├── agent_graph.py      # 🚀 The Backend: FastAPI server + LangGraph workflow definitions
├── db_setup.py         # 🛠️ Utility: Scripts to seed DB and create tables
├── ui.py               # 💻 The Frontend: Streamlit dashboard for interaction
├── mcp_wrapper.py      # 🔌 Client: Python client to manage subprocess connections to MCP servers
├── mcp_server/         # 📦 The ToolShed: Standalone FastMCP servers
│   ├── atlas.py        #    - External Tools (OCR, ERP Fetch, Notifications)
│   └── common.py       #    - Internal Tools (Parsing, Matching Math, Audit Logging)
├── invoice1.pdf        # 📄 Sample Data
└── output_images/      # 🖼️ Temp storage for PDF-to-Image conversion
```

---

## 🚀 Installation & Setup

### 1. Prerequisites
*   Python 3.10+


### 2. Install Dependencies
```bash
pip install -r requirements.txt
```

### 3. Configure Environment
Set your OpenAI API key (required for the Agent Brain and OCR).
```bash
export OPENAI_API_KEY="sk-..."
```

### 4. Initialize Database
Run the setup script to create the SQLite database (`invoice_system.db`) and seed mock ERP data.
```bash
python db_setup.py
```

---

## 🏃‍♂️ How to Run

You need **two terminal windows** to run the full stack.

### Terminal 1: Backend (FastAPI + Agent)
This starts the REST API and the LangGraph engine. It also automatically launches the MCP servers as subprocesses.
```bash
python agent_graph.py
```
*Server runs at: http://localhost:8000*

### Terminal 2: Frontend (Streamlit UI)
This starts the web interface for submitting invoices and managing reviews.
```bash
streamlit run ui.py
```
*UI runs at: http://localhost:8501*

---

## 🧠 Workflow & Agent Flow

Langie follows a **12-Step Directed Acyclic Graph (DAG)**. Unlike a standard script, specific nodes use the **Agent Brain (`agent_core.py`)** to think before acting.

### The 12 Stages

1.  **INTAKE 📥**: Accepts raw PDF/JSON. Persists raw payload to DB.
2.  **UNDERSTAND 🧠 (Agentic)**:
    *   *Reasoning*: Langie looks at the file extension and priority.
    *   *Action*: Selects the best OCR tool (e.g., GPT-4.1 Vision for PDFs, Tesseract for simple text).
    *   *MCP*: Calls `ATLAS.ocr_extract`.
3.  **PREPARE 🛠️ (Agentic)**:
    *   *Reasoning*: Selects the best enrichment source based on Vendor Name.
    *   *Action*: Normalizes vendor name and fetches Tax IDs/Risk Scores.
4.  **RETRIEVE 📚**: Fetches the Purchase Order (PO) and history from the ERP (Mock DB).
5.  **MATCH_TWO_WAY ⚖️ (Agentic)**:
    *   *Reasoning*: Langie compares Invoice Line Items vs. PO Line Items semantically (understanding that "Cloud Hosting" == "Hosting Sub").
    *   *Action*: Logic handles valid tax discrepancies vs. invalid price variance.
6.  **CHECKPOINT_HITL ⏸️**:
    *   *Trigger*: Runs **only** if Match Score < Threshold (0.9).
    *   *Action*: Pauses execution, saves state to DB, and creates a generic Review URL.
7.  **HITL_DECISION 👨‍💼**:
    *   *Action*: Resumes workflow once Human accepts/rejects via UI.
8.  **RECONCILE 📘**: Generates GL (General Ledger) entries (Debits/Credits).
9.  **APPROVE 🔄**: Checks approval limits (Auto-approve vs. Manager required).
10. **POSTING 🏃**: Commits transaction to ERP and schedules payment.
11. **NOTIFY ✉️**: Sends emails/Slack alerts to Vendor and Finance.
12. **COMPLETE ✅**: Writes final sanitized payload to the `audit_logs` table.

---

## 🛠️ Architecture Explained

### 1. The Brain (`agent_core.py`)
This is the "Thinking" component. It does not perform actions itself. It constructs prompts containing context (e.g., "The invoice is $50,000") and asks GPT-4.1: *"Which tool should I use?"* or *"Does this invoice match this PO?"*. It returns structured decisions.

### 2. The Body (`mcp_server/`)
These are **FastMCP** servers running as independent processes.
*   They expose "Tools" (Functions) like `ocr_extract`, `fetch_erp`, `post_to_erp`.
*   They are "dumb"—they just execute what they are told.
*   **Why split them?** Separation of concerns. You can swap the Python Atlas server for a Node.js one without changing the Agent code.

### 3. The Nervous System (`mcp_wrapper.py`)
This is the bridge. The main application uses this wrapper to route commands:
> `Main App` -> `Wrapper` -> `Stdio Pipe` -> `MCP Server Process`

### 4. Database (`sqlite3` + `WAL`)
We use **Write-Ahead Logging (WAL)** to handle concurrency.
*   **`checkpoints` table**: Stores LangGraph state (allows pausing/resuming).
*   **`human_queue` table**: Stores pending tickets for the UI.
*   **`audit_logs` table**: Stores the final immutable record of the transaction.
*   **`workflow_logs` table**: Stores a verbose trace of every step for debugging.

---

## 🧪 Testing Scenarios

### Happy Path (Auto-Approval)
1.  Go to **"📦 ERP Data"** in UI and ensure a PO exists (e.g., `PO-556644` for $230).
2.  Go to **"📥 Submit Invoice"**.
3.  Submit an invoice JSON with amount `$253.00` (Subtotal $230 + Tax).
4.  **Result**: Langie sees the match is valid (Tax logic), skips Human Review, and completes instantly.

### Fail Path (Human Review)
1.  Submit an invoice JSON with amount `$9999.00`.
2.  **Result**: Langie detects a massive mismatch.
3.  Status becomes `PAUSED`.
4.  Go to **"👨‍💼 Human Review Queue"**. You will see the ticket.
5.  Click **"✅ APPROVE"**.
6.  Go to **"📊 Audit Logs"**. You will see the workflow resumed and finished.