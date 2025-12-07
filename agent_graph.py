import uuid
import sqlite3
import json
import uvicorn
from datetime import datetime
from typing import List, Optional, Dict, Any, Literal, TypedDict
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from langgraph.graph import StateGraph, END, START
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from mcp_wrapper import mcp_client 
from agent_core import langie
# ==========================================
# 1. DATABASE SETUP (Real Persistence)
# ==========================================

DB_PATH = "invoice_system.db"

def init_db():
    """Initialize both LangGraph checkpoints and Business tables."""
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    cursor = conn.cursor()
    
    # 1. Table for UI Querying (The Human Queue)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS human_queue (
        checkpoint_uid TEXT PRIMARY KEY,
        thread_id TEXT,
        invoice_id TEXT,
        vendor_name TEXT,
        amount REAL,
        created_at TEXT,
        reason_for_hold TEXT,
        review_url TEXT,
        status TEXT DEFAULT 'PENDING'
    )
    """)
    conn.commit()
    conn.close()

def get_db_connection():
    return sqlite3.connect(DB_PATH, check_same_thread=False)

# ==========================================
# 2. API MODELS (Pydantic)
# ==========================================

class InvoiceInput(BaseModel):
    invoice_id: str
    vendor_name: str
    amount: float
    attachments: List[str]

class DecisionRequest(BaseModel):
    checkpoint_uid: str
    decision: Literal["ACCEPT", "REJECT"]
    notes: Optional[str] = ""
    reviewer_id: str

class QueueItem(BaseModel):
    checkpoint_uid: str
    invoice_id: str
    vendor_name: str
    amount: float
    created_at: str
    reason_for_hold: str
    review_url: str

# ==========================================
# 3. CONFIG & TOOLS
# ==========================================

WORKFLOW_CONFIG = {
    "match_threshold": 0.90,
}

class MCPClient:
    """Real Logic for Internal Tools, Mock for External"""
    
    def route(self, tool: str, payload: Dict):
        # 1. Internal Logic: Write to Human Queue Table
        if tool == "save_state_for_human_review":
            conn = get_db_connection()
            cursor = conn.cursor()
            try:
                cursor.execute("""
                    INSERT INTO human_queue 
                    (checkpoint_uid, thread_id, invoice_id, vendor_name, amount, created_at, reason_for_hold, review_url)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    payload['checkpoint_uid'],
                    payload['thread_id'],
                    payload['invoice_id'],
                    payload['vendor_name'],
                    payload['amount'],
                    payload['created_at'],
                    payload['reason_for_hold'],
                    payload['review_url']
                ))
                conn.commit()
            except Exception as e:
                print(f"DB Error: {e}")
            finally:
                conn.close()
            return payload['checkpoint_uid']

        # 2. Mock Logic for Compute Match
        if tool == "compute_match_score":
            # Simulating a score based on payload to test logic
            return payload.get("_force_score", 0.85) 
        if tool == "ocr_extract":
            return {"invoice_text": "RAW TEXT...", "currency": "USD", "date": "2023-10-01"}
        if tool == "compute_match_score":
            # Simulating a score based on payload to test logic
            return payload.get("_force_score", 0.85) 
        if tool == "save_state_for_human_review":
            return str(uuid.uuid4()) # Returns checkpoint_uid
            
        return {"status": "success", "data": f"Result from {tool}"}

    

mcp = MCPClient()
class BigtoolPicker:
    """
    Simulates the 'Bigtool' logic from the JSON.
    In a real agent, this might use an LLM to select the best tool based on context.
    """
    @staticmethod
    def select(capability: str, context: Dict = None) -> str:
        pools = {
            "ocr": ["google_vision", "tesseract", "aws_textract"],
            "enrichment": ["clearbit", "people_data_labs", "vendor_db"],
            "erp_connector": ["sap_sandbox", "netsuite", "mock_erp"],
            "db": ["postgres", "sqlite", "dynamodb"],
            "email": ["sendgrid", "smartlead", "ses"]
        }
        # Logic: Select the first available or based on specific context rules
        selected = pools.get(capability, ["default"])[0]
        print(f"🔧 Bigtool selected '{selected}' for capability '{capability}'")
        return selected
# ==========================================
# 4. LANGGRAPH STATE & NODES
# ==========================================

class InvoiceState(TypedDict):
    invoice_payload: Dict
    match_score: float
    match_result: str
    attachments: Optional[List[str]]
    po_number: Optional[str]
    po_amount: Optional[float]
    invoice_amount: Optional[float]
    thread_id: Optional[str]
    agent_decision: Optional[str]
    agent_reason: Optional[str]
    
    vendor_profile: Optional[Dict]
    validation_flags: Optional[List[str]]
    matched_pos: Optional[List[Dict]]   # New
    matched_grns: Optional[List[Dict]]  # New
    erp_txn_id: Optional[str]   # New
    payment_id: Optional[str]   # New
    history: Optional[List[Dict]] 
    accounting_entries: Optional[List[Dict]]
    # HITL Fields
    checkpoint_uid: Optional[str]
    human_decision: Optional[str]
    reviewer_notes: Optional[str]
    status: str

async def intake(state: InvoiceState):
    print(f"--- [INTAKE] Processing {state['invoice_payload']['invoice_id']} ---")
    
    # Call the real MCP Tool
    # Note: We pass the Dict directly. FastMCP handles the conversion if set up correctly, 
    # but passing as a single argument "invoice_data" matches our server signature.
    result = await mcp_client.route(
        "COMMON", 
        "accept_invoice_payload", 
        {"invoice_data": state['invoice_payload']}
    )
    
    # Parse the JSON response from the tool
    # (The mcp_wrapper tries to return a dict, but let's be safe)
    if isinstance(result, str):
        response_data = json.loads(result)
    else:
        response_data = result

    if response_data.get("status") == "error":
        print(f"❌ Intake Validation Failed: {response_data.get('message')}")
        # In a real app, you might route to an error state here
        return {"status": "VALIDATION_FAILED"}

    print(f"✅ Intake Successful. Raw ID: {response_data.get('raw_id')}")
    return {"status": "INTAKE_COMPLETE", "raw_id": response_data.get("raw_id")}

# async def understand(state: InvoiceState) -> InvoiceState:
#     print("\n--- [UNDERSTAND] Running OCR & Parsing ---")
    
#     # 1. Bigtool: Select OCR Provider
#     ocr_provider = BigtoolPicker.select("ocr")
    
#     # 2. ATLAS: Run OCR
#     # We assume the first attachment is what we want
#     attachments = state['invoice_payload'].get('attachments', [])

#     file_path = attachments[0] if attachments else "unknown_file.pdf"
#     print(f"   📡 OCR File: {file_path}")
#     ocr_result_json = await mcp_client.route(
#         "ATLAS", 
#         "ocr_extract", 
#         {"file_path": file_path}
#     )
#     print(f"   📝 OCR Result: {ocr_result_json}")
    

#     # 3. COMMON: Parse Data
#     parse_result_json = await mcp_client.route(
#         "COMMON",
#         "parse_line_items",
#         {"raw_text": ocr_result_json}
#     )
    
#     if isinstance(parse_result_json, str):
#         parse_result = json.loads(parse_result_json)
#     else:
#         parse_result = parse_result_json

#     parsed_data = parse_result.get("parsed_data", {})
#     print(f"   🧠 Parsed Data: PO={parsed_data.get('po_number')}, Total={parsed_data.get('total_amount')}")
#     state['po_number'] = parsed_data.get('po_number')
#     # print("debug po number in state", state['po_number'])
#     # 4. Update State
#     return {
#         "status": "UNDERSTOOD",
#         "parsed_invoice": parsed_data,
#          "po_number": parsed_data.get("po_number")
#     }

async def understand(state: InvoiceState) -> InvoiceState:
    print("\n--- [UNDERSTAND] Analyzing Document Strategy ---")
    
    # 1. Prepare Context for Langie
    attachments = state['invoice_payload'].get('attachments', [])
    filename = attachments[0] if attachments else "unknown_file.pdf"
    
    context = {
        "filename": filename,
        "file_extension": filename.split('.')[-1] if '.' in filename else "unknown",
        "file_size_kb": 150, # Mock size, real app would measure this
        "priority": "High" if state['invoice_payload'].get('amount', 0) > 5000 else "Standard"
    }
    
    # 2. Define Options
    ocr_pool = ["gpt-4o", "tesseract", "aws_textract"]
    
    # 3. ASK LANGIE
    decision = langie.select_tool("UNDERSTAND", ocr_pool, context)
    
    selected_tool = decision["tool"]
    reasoning = decision["reasoning"]
    
    print(f"   🤖 Agent Decision: Selected '{selected_tool}'")
    print(f"      Reasoning: {reasoning}")

    # 4. Execute (Pass selected tool to MCP)
    ocr_result_json = await mcp_client.route(
        "ATLAS", 
        "ocr_extract", 
        {"file_path": filename}
    )
    
    # 3. COMMON: Parse Data
    parse_result_json = await mcp_client.route(
        "COMMON",
        "parse_line_items",
        {"raw_text": ocr_result_json}
    )
    
    if isinstance(parse_result_json, str):
        parse_result = json.loads(parse_result_json)
    else:
        parse_result = parse_result_json

    parsed_data = parse_result.get("parsed_data", {})
    print(f"   🧠 Parsed Data: PO={parsed_data.get('po_number')}, Total={parsed_data.get('total_amount')}")
    state['po_number'] = parsed_data.get('po_number')
    # print("debug po number in state", state['po_number'])
    # 4. Update State
    return {
        "status": "UNDERSTOOD",
        "parsed_invoice": parsed_data,
         "po_number": parsed_data.get("po_number"), 
        "agent_decision": selected_tool,
        "agent_reason": reasoning
    
    }

    


async def prepare(state: InvoiceState) -> InvoiceState:
    print("\n--- [PREPARE] Normalizing & Enriching ---")
    
    # 1. Get raw vendor name from previous steps
    # Fallback to payload if not found in parsed data
    raw_vendor = state.get("parsed_invoice", {}).get("vendor_name") 
    if not raw_vendor:
        raw_vendor = state["invoice_payload"].get("vendor_name", "Unknown")

    # 2. COMMON: Normalize Vendor Name
    norm_res_json = await mcp_client.route(
        "COMMON", 
        "normalize_vendor", 
        {"raw_name": raw_vendor}
    )
    norm_res = json.loads(norm_res_json) if isinstance(norm_res_json, str) else norm_res_json
    normalized_name = norm_res.get("normalized_name", raw_vendor)
    
    print(f"   🧹 Normalized: '{raw_vendor}' -> '{normalized_name}'")

    # 3. Bigtool: Select Enrichment Source
    enrich_tool = BigtoolPicker.select("enrichment")

    # 4. ATLAS: Enrich Vendor
    enrich_res_json = await mcp_client.route(
        "ATLAS",
        "enrich_vendor",
        {"normalized_name": normalized_name, "source": enrich_tool}
    )
    enrich_res = json.loads(enrich_res_json) if isinstance(enrich_res_json, str) else enrich_res_json
    vendor_profile = enrich_res.get("vendor_data", {})

    # 5. COMMON: Compute Validation Flags
    # We pass the full vendor profile and the invoice amount
    invoice_amount = state["invoice_payload"].get("amount", 0.0)
    
    flags_res_json = await mcp_client.route(
        "COMMON",
        "compute_flags",
        {"enrichment_data": vendor_profile, "invoice_amount": invoice_amount}
    )
    flags_res = json.loads(flags_res_json) if isinstance(flags_res_json, str) else flags_res_json
    
    flags = flags_res.get("flags", [])
    if flags:
        print(f"   🚩 Flags Raised: {flags}")
    else:
        print("   ✅ No Risk Flags detected.")

    # 6. Update State
    return {
        "status": "PREPARED",
        "vendor_profile": {
            "name": normalized_name,
            **vendor_profile
        },
        "validation_flags": flags
    }

async def retrieve(state: InvoiceState) -> InvoiceState:
    print("\n--- [RETRIEVE] Fetching ERP Data (PO, GRN, History) ---")
    
    # 1. Bigtool: Select ERP Connector
    erp_tool = BigtoolPicker.select("erp_connector")
    
    # 2. Prepare Inputs
    vendor_profile = state.get("vendor_profile", {})
    # Use safe .get() chain to avoid NoneType errors
    vendor_name = vendor_profile.get("name") or state["invoice_payload"].get("vendor_name", "Unknown")
    
    po_number = state.get("po_number") 
    # print(f"   📡 Fetcompute_match_scoreching PO: {state}")
    # SANITIZATION: FastMCP (Pydantic) prefers Strings. 
    # If po_number is None, convert to empty string or handle explicitly.
    safe_po_number = po_number if po_number else ""

    if not safe_po_number:
        print("   ⚠️ No PO Number found. Retrieval will rely on Vendor Name.")

    # 3. MCP: ATLAS -> Fetch Data
    print(f"   📡 Calling ATLAS: fetch_erp_data(vendor='{vendor_name}', po='{safe_po_number}')")
    
    erp_response = await mcp_client.route(
        "ATLAS",
        "fetch_erp_data",
        {
            "vendor_name": vendor_name,
            "po_number": safe_po_number,
            "erp_system": erp_tool
        }
    )
    
    # 4. Defensive Parsing
    erp_data = {}
    
    # Case A: Wrapper already parsed it into a Dict
    if isinstance(erp_response, dict):
        # Check if the tool returned an internal error dict
        if erp_response.get("status") == "error":
             print(f"   ❌ Tool returned error: {erp_response}")
        else:
             erp_data = erp_response.get("data", {})

    # Case B: Wrapper returned a String (JSON or Error Text)
    elif isinstance(erp_response, str):
        try:
            parsed_json = json.loads(erp_response)
            erp_data = parsed_json.get("data", {})
        except json.JSONDecodeError:
            print(f"   ❌ CRITICAL: Expected JSON from MCP but got raw text.")
            print(f"   📝 RAW OUTPUT: '{erp_response}'")
            # Fallback to empty to prevent crash
            erp_data = {}
    else:
        print(f"   ❌ Unknown response type: {type(erp_response)}")

    # 5. Extract Results
    pos = erp_data.get("purchase_orders", [])
    grns = erp_data.get("grns", [])
    history = erp_data.get("history", [])
    
    print(f"   📦 Found {len(pos)} POs, {len(grns)} GRNs, {len(history)} Historical Invoices.")
    
    # 6. Update State
    return {
        "status": "RETRIEVED",
        "matched_pos": pos,
        "matched_grns": grns,
        "history": history
    }


# async def match_two_way(state: InvoiceState) -> InvoiceState:
#     print("\n--- [MATCH_TWO_WAY] Comparing Invoice vs PO ---")
    
#     # 1. Get Inputs
#     parsed_invoice = state.get("parsed_invoice", {})
#     matched_pos = state.get("matched_pos", [])
    
#     # Fallback: If OCR failed to parse amount, use the input payload amount
#     if not parsed_invoice.get("total_amount"):
#         parsed_invoice["total_amount"] = state["invoice_payload"].get("amount", 0.0)
    
#     # 2. Identify the Target PO
#     # We look for the PO that matches the PO Number found in the invoice
#     target_po_num = parsed_invoice.get("po_number")
    
#     target_po_data = {}
#     if target_po_num:
#         # Find the specific PO object in the list
#         target_po_data = next((po for po in matched_pos if po.get("po_number") == target_po_num), {})
    
#     if not target_po_data and matched_pos:
#         # Heuristic: If we have POs but OCR didn't find a number, match against the first one
#         # (In a real app, this would be smarter)
#         print("   ⚠️ specific PO not found by ref, trying first available PO from vendor.")
#         target_po_data = matched_pos[0]
#     print("debug", parsed_invoice, target_po_data)
#     # 3. MCP: COMMON -> Compute Score
#     match_res_json = await mcp_client.route(
#         "COMMON",
#         "compute_match_score",
#         {
#             "invoice_data": parsed_invoice,
#             "po_data": target_po_data
#         }
#     )
    
#     if isinstance(match_res_json, str):
#         match_res = json.loads(match_res_json)
#     else:
#         match_res = match_res_json
        
#     score = match_res.get("score", 0.0)
#     notes = match_res.get("notes", "")
    
#     # 4. Determine Result based on Threshold
#     threshold = WORKFLOW_CONFIG["match_threshold"] # 0.90
#     result = "MATCHED" if score >= threshold else "FAILED"
    
#     print(f"   ⚖️  Match Score: {score} (Threshold: {threshold})")
#     print(f"   📝 Notes: {notes}")
#     print(f"   👉 Result: {result}")

#     # 5. Update State
#     return {
#         "match_score": score,
#         "match_result": result,
#         "status": f"MATCH_{result}"
#     }

async def match_two_way(state: InvoiceState) -> InvoiceState:
    print("\n--- [MATCH_TWO_WAY] Langie is performing 3-Way Semantic Match ---")
    
    # 1. Get Inputs
    parsed_invoice = state.get("parsed_invoice", {})
    matched_pos = state.get("matched_pos", [])
    
    # Fallback: If OCR failed to parse amount, use the input payload amount
    if not parsed_invoice.get("total_amount"):
        parsed_invoice["total_amount"] = state["invoice_payload"].get("amount", 0.0)
    
    # 2. Identify the Target PO
    # We look for the PO that matches the PO Number found in the invoice
    target_po_num = parsed_invoice.get("po_number")
    
    target_po_data = {}
    if target_po_num:
        # Find the specific PO object in the list
        target_po_data = next((po for po in matched_pos if po.get("po_number") == target_po_num), {})
    
    if not target_po_data and matched_pos:
        # Heuristic: If we have POs but OCR didn't find a number, match against the first one
        # (In a real app, this would be smarter)
        print("   ⚠️ specific PO not found by ref, trying first available PO from vendor.")
        target_po_data = matched_pos[0]
    print("debug", parsed_invoice, target_po_data)
    # 2. Ask Langie to Match
    # Instead of calling MCP 'compute_match_score' (Python math), we ask the Brain
    reasoning_result = langie.semantic_match(parsed_invoice, target_po_data)
    
    score = reasoning_result["score"]
    result = reasoning_result["result"] # MATCHED or FAILED
    notes = reasoning_result["notes"]
    
    print(f"   🤖 Langie Reasoning: {notes}")
    print(f"   ⚖️  Score: {score} -> {result}")

    # 3. Update State
    return {
        "match_score": score,
        "match_result": result,
        "status": f"MATCH_{result}",
        # We can store the reasoning note for the human reviewer to see!
        "reviewer_notes": f"AI Note: {notes}" 
    }


async def checkpoint_hitl(state: InvoiceState, config):
    print("\n--- [HITL] Pausing for Human Review ---")
    
    # 1. Get Context
    thread_id = config["configurable"]["thread_id"]
    
    # 2. Generate Unique Ticket ID (Business Logic ID)
    checkpoint_uid = str(uuid.uuid4())
    
    # 3. Prepare Payload for DB
    # Note: We need to be careful to pull data that actually exists
    invoice_id = state['invoice_payload'].get('invoice_id', 'UNKNOWN')
    vendor_name = state.get('vendor_profile', {}).get('name') or state['invoice_payload'].get('vendor_name', 'UNKNOWN')
    amount = state['invoice_payload'].get('amount', 0.0)
    
    queue_payload = {
        "checkpoint_uid": checkpoint_uid,
        "thread_id": thread_id, # CRITICAL: Needed to resume the specific graph thread
        "invoice_id": invoice_id,
        "vendor_name": vendor_name,
        "amount": amount,
        "created_at": datetime.now().isoformat(),
        "reason_for_hold": f"Match Score {state.get('match_score', 0)} < Threshold",
        "review_url": f"http://localhost:8000/review/{checkpoint_uid}"
    }
    
    # 4. MCP: COMMON -> Save to DB
    # We pass the payload directly. FastMCP expects arguments matching the tool signature.
    # Our tool signature is `save_state_for_human_review(payload: Dict)`.
    response = await mcp_client.route(
        "COMMON", 
        "save_state_for_human_review", 
        {"payload": queue_payload}
    )
    
    print(f"   💾 Saved to Queue. Review URL: {queue_payload['review_url']}")
    
    # 5. Update State and Return
    # The 'interrupt_before' in main execution will actually stop the graph after this node returns.
    return {
        "checkpoint_uid": checkpoint_uid,
         "thread_id": thread_id,
        "status": "PAUSED"
    }

async def hitl_decision(state: InvoiceState) -> InvoiceState:
    print("\n--- [HITL_DECISION] Finalizing Human Action ---")
    
    # 1. Retrieve Data Injected by the API
    decision = state.get("human_decision", "UNKNOWN")
    notes = state.get("reviewer_notes", "")
    # You might want to pass reviewer_id from the API too if added to state
    
    invoice_id = state['invoice_payload'].get('invoice_id')

    # 2. MCP: ATLAS -> Audit the Decision
    # This ensures the external ERP knows a human manually approved/rejected it
    await mcp_client.route(
        "ATLAS",
        "accept_or_reject_invoice",
        {
            "invoice_id": invoice_id,
            "decision": decision,
            "notes": notes,
            "reviewer": "human_reviewer" # Could be dynamic from state
        }
    )
    
    # 3. Handle Logic
    if decision == "REJECT":
        print(f"   ⛔ Invoice REJECTED by Human. Notes: {notes}")
        return {
            "status": "REQUIRES_MANUAL_HANDLING",
            "human_decision": "REJECT" # Ensure strict casing
        }
    
    print(f"   ✅ Invoice ACCEPTED by Human. Resuming workflow...")
    return {
        "status": "APPROVED_BY_HUMAN",
        "human_decision": "ACCEPT"
    }


async def reconcile(state: InvoiceState) -> InvoiceState:
    print("\n--- [RECONCILE] Generating Accounting Entries ---")
    
    # 1. Gather Data
    # Prefer parsed data, fallback to raw payload
    parsed = state.get("parsed_invoice", {})
    payload = state.get("invoice_payload", {})
    
    # Construct a data object for the MCP tool
    invoice_data = {
        "invoice_id": parsed.get("invoice_id") or payload.get("invoice_id"),
        "total_amount": parsed.get("total_amount") or payload.get("amount"),
        "currency": parsed.get("currency") or payload.get("currency", "USD"),
        "line_items": parsed.get("line_items", [])
    }
    
    vendor_name = state.get("vendor_profile", {}).get("name") or payload.get("vendor_name")

    # 2. MCP: COMMON -> Build Entries
    res_json = await mcp_client.route(
        "COMMON",
        "build_accounting_entries",
        {
            "invoice_data": invoice_data,
            "vendor_name": vendor_name
        }
    )
    
    if isinstance(res_json, str):
        res = json.loads(res_json)
    else:
        res = res_json

    entries = res.get("entries", [])
    
    # 3. Log Output
    print(f"   📘 Ledger Generated: {len(entries)} entries.")
    for entry in entries:
        print(f"      {entry['type']} | {entry['account_code']} | ${entry['amount']}")

    # 4. Update State (Store entries for Posting stage)
    return {
        "status": "RECONCILED",
        "accounting_entries": entries
    }

def approve(state: InvoiceState) -> InvoiceState:
    """Stage 9: APPROVE (Deterministic)"""
    print("\n--- 9. APPROVE ---")
    return {"approval_status": "APPROVED"}

async def posting(state: InvoiceState) -> InvoiceState:
    print("\n--- [POSTING] Finalizing in ERP ---")
    
    # 1. Bigtool: Select ERP Connector
    erp_tool = BigtoolPicker.select("erp_connector")
    
    # 2. Prepare Data
    entries = state.get("accounting_entries", [])
    if not entries:
        print("   ⚠️ No accounting entries found to post!")
        return {"status": "POSTING_FAILED"}

    # 3. MCP: ATLAS -> Post Journal Entries
    print(f"   📡 Posting Journal Entries...")
    post_res_json = await mcp_client.route(
        "ATLAS", 
        "post_to_erp", 
        {"entries": entries, "erp_system": erp_tool}
    )
    
    # Defensive Parse: Journal Posting
    if isinstance(post_res_json, str):
        try:
            post_res = json.loads(post_res_json)
        except json.JSONDecodeError:
            print(f"   ❌ JSON Error in post_to_erp: {post_res_json}")
            return {"status": "ERP_ERROR"}
    else:
        post_res = post_res_json
    
    if post_res.get("status") == "error":
        print(f"   ❌ ERP Error: {post_res.get('message')}")
        return {"status": "ERP_ERROR"}
        
    txn_id = post_res.get("txn_id")
    print(f"   ✅ Posted to Ledger. TXN ID: {txn_id}")

    # 4. MCP: ATLAS -> Schedule Payment
    # Gather payment details
    invoice_payload = state.get("invoice_payload", {})
    parsed_invoice = state.get("parsed_invoice") or {} # Ensure dict
    
    inv_id = invoice_payload.get("invoice_id")
    amount = invoice_payload.get("amount")
    vendor = state.get("vendor_profile", {}).get("name", "Unknown")
    
    # SANITIZATION: Ensure due_date is a string, even if empty
    raw_due_date = parsed_invoice.get("parsed_dates", {}).get("due_date")
    safe_due_date = raw_due_date if raw_due_date else ""

    print(f"   💸 Scheduling Payment for {inv_id}...")
    
    pay_res_json = await mcp_client.route(
        "ATLAS",
        "schedule_payment",
        {
            "invoice_id": inv_id,
            "amount": amount,
            "vendor": vendor,
            "due_date": safe_due_date # Pass sanitized string
        }
    )
    
    # Defensive Parse: Schedule Payment
    pay_res = {}
    if isinstance(pay_res_json, str):
        try:
            pay_res = json.loads(pay_res_json)
        except json.JSONDecodeError:
            print(f"   ❌ CRITICAL: 'schedule_payment' returned invalid JSON.")
            print(f"   📝 RAW OUTPUT: '{pay_res_json}'")
            # Return partial success to avoid crashing entire workflow
            return {"status": "PARTIAL_POSTED", "erp_txn_id": txn_id}
    else:
        pay_res = pay_res_json
        
    payment_id = pay_res.get("payment_id")
    print(f"   ✅ Payment Scheduled. ID: {payment_id}")

    # 5. Update State
    return {
        "status": "POSTED",
        "erp_txn_id": txn_id,
        "payment_id": payment_id
    }


async def notify(state: InvoiceState) -> InvoiceState:
    print("\n--- [NOTIFY] Alerting Stakeholders ---")
    
    # 1. Bigtool: Select Email Provider
    email_tool = BigtoolPicker.select("email")
    
    # 2. Gather Context
    invoice_payload = state.get("invoice_payload", {})
    invoice_id = invoice_payload.get("invoice_id", "UNKNOWN")
    amount = invoice_payload.get("amount", 0.0)
    vendor_profile = state.get("vendor_profile", {})
    vendor_name = vendor_profile.get("name", "Vendor")
    
    # Fallback email if enrichment didn't provide one
    vendor_email = vendor_profile.get("email", "vendor.contact@example.com")
    internal_finance_email = "accounts.payable@ourcompany.com"
    
    payment_id = state.get("payment_id", "PENDING")

    # 3. Notify Vendor (External)
    vendor_subject = f"Payment Scheduled: Invoice {invoice_id}"
    vendor_body = f"Dear {vendor_name},\n\nWe have approved your invoice for ${amount}. Payment ID: {payment_id}.\n\nRegards,\nFinance Team"
    
    await mcp_client.route(
        "ATLAS",
        "send_notification",
        {
            "recipient": vendor_email,
            "subject": vendor_subject,
            "body": vendor_body,
            "channel": "email",
            "provider": email_tool
        }
    )

    # 4. Notify Finance Team (Internal)
    # If the decision was human-made, mention that
    approver = "Human Reviewer" if state.get("human_decision") == "ACCEPT" else "Auto-Approval Policy"
    
    internal_subject = f"Processed: {vendor_name} - {invoice_id}"
    internal_body = f"Invoice {invoice_id} for ${amount} has been posted to ERP.\nApprover: {approver}\nTXN ID: {state.get('erp_txn_id')}"
    
    await mcp_client.route(
        "ATLAS",
        "send_notification",
        {
            "recipient": internal_finance_email,
            "subject": internal_subject,
            "body": internal_body,
            "channel": "slack", # Example of multi-channel
            "provider": "slack_webhook"
        }
    )
    
    print(f"   ✅ Notifications sent to {vendor_email} and Finance Team.")

    # 5. Update State
    return {
        "status": "NOTIFIED"
    }

async def complete(state: InvoiceState) -> InvoiceState:
    print("\n--- [COMPLETE] Wrapping Up ---")
    
    # 1. Safe Data Extraction (Ensure pure dicts/strings)
    # Pydantic models (if any) must be converted to dicts
    def sanitize(data):
        if hasattr(data, "dict"): return data.dict()
        if isinstance(data, (str, int, float, bool, type(None))): return data
        if isinstance(data, list): return [sanitize(x) for x in data]
        if isinstance(data, dict): return {k: sanitize(v) for k, v in data.items()}
        return str(data) # Fallback to string

    clean_state_snapshot = {
        "invoice_payload": sanitize(state.get("invoice_payload", {})),
        "parsed_invoice": sanitize(state.get("parsed_invoice", {})),
        "vendor_profile": sanitize(state.get("vendor_profile", {})),
        "erp_txn_id": str(state.get("erp_txn_id", "")),
        "payment_id": str(state.get("payment_id", "")),
        "match_score": state.get("match_score", 0),
        "validation_flags": state.get("validation_flags", []),
        "human_decision": state.get("human_decision"),
        "reviewer_notes": state.get("reviewer_notes"), 
        "thread_id": state.get("thread_id")
    }
    
    # 2. Debug Print BEFORE calling MCP
    print("   📡 Sending Final Payload to MCP...")
    
    try:
        result_json = await mcp_client.route(
            "COMMON",
            "output_final_payload",
            {"workflow_state": clean_state_snapshot}
        )
        print(f"   ✅ MCP Response: {result_json}")
        
    except Exception as e:
        print(f"   ❌ MCP Call Failed in COMPLETE: {e}")
        return {"status": "FAILED_TO_LOG"}
    
    return {"status": "COMPLETED"}
# ==========================================
# 5. GRAPH CONSTRUCTION
# ==========================================

workflow = StateGraph(InvoiceState)
workflow.add_node("INTAKE", intake,mode="deterministic")
workflow.add_node("UNDERSTAND", understand, mode="deterministic")
workflow.add_node("PREPARE", prepare)
workflow.add_node("RETRIEVE", retrieve)
workflow.add_node("MATCH_TWO_WAY", match_two_way)
workflow.add_node("CHECKPOINT_HITL", checkpoint_hitl)
workflow.add_node("HITL_DECISION", hitl_decision)
workflow.add_node("RECONCILE", reconcile)
workflow.add_node("APPROVE", approve)
workflow.add_node("POSTING", posting)
workflow.add_node("NOTIFY", notify)
workflow.add_node("COMPLETE", complete)

workflow.add_edge(START, "INTAKE")
workflow.add_edge("INTAKE", "UNDERSTAND")
workflow.add_edge("UNDERSTAND", "PREPARE")
workflow.add_edge("PREPARE", "RETRIEVE")
workflow.add_edge("RETRIEVE", "MATCH_TWO_WAY")

def route_match(state):
    if state["match_result"] == "FAILED":
        return "CHECKPOINT_HITL"
    return "RECONCILE"

workflow.add_conditional_edges("MATCH_TWO_WAY", route_match, ["CHECKPOINT_HITL", "RECONCILE"])
workflow.add_edge("CHECKPOINT_HITL", "HITL_DECISION")

def route_human(state):
    if state["human_decision"] == "REJECT":
        return END
    return "RECONCILE"

workflow.add_conditional_edges("HITL_DECISION", route_human, ["RECONCILE", END])

# Resume normal path after Human Decision
workflow.add_edge("RECONCILE", "APPROVE")
workflow.add_edge("APPROVE", "POSTING")
workflow.add_edge("POSTING", "NOTIFY")
workflow.add_edge("NOTIFY", "COMPLETE")
workflow.add_edge("COMPLETE", END)
# ==========================================
# 6. FASTAPI SERVER SETUP
# ==========================================
# In main.py

def get_db_connection():
    # timeout=30.0 means "Wait up to 30 seconds if the DB is busy"
    return sqlite3.connect(DB_PATH, check_same_thread=False, timeout=30.0)
# Initialize DB on startup
@asynccontextmanager
async def lifespan(app: FastAPI):
    # 1. Initialize DB structure
    init_db()
    
    # 2. ENABLE WAL MODE (The Magic Fix)
    # This allows simultaneous reads and writes
    conn = get_db_connection()
    try:
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.commit()
        print("🚀 SQLite WAL Mode Enabled (High Concurrency)")
    except Exception as e:
        print(f"⚠️ Could not enable WAL mode: {e}")
    finally:
        conn.close()
        
    yield
    # Cleanup logic if needed...

app = FastAPI(title="Invoice Agent API", lifespan=lifespan)


# ALLOW UI TO COMMUNICATE WITH API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # In production, set this to the specific UI URL
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Helper to run graph in background
# In main.py
def log_workflow_step(thread_id: str, node_name: str, output: Dict):
    """Writes a single graph step to the DB."""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Sanitize output for JSON (handle non-serializable objects)
        def json_default(obj):
            return str(obj)

        cursor.execute("""
            INSERT INTO workflow_logs (thread_id, node_name, output_json, timestamp)
            VALUES (?, ?, ?, ?)
        """, (
            thread_id,
            node_name,
            json.dumps(output, default=json_default),
            datetime.now().isoformat()
        ))
        conn.commit()
    except Exception as e:
        print(f"❌ Failed to log step: {e}")
    finally:
        conn.close()

async def run_agent_background(thread_id: str, input_data: Optional[Dict]):
    """Runs the graph using AsyncSqliteSaver and astream"""
    
    # Use AsyncSqliteSaver with the context manager
    # 'check_same_thread' is not strictly needed for aiosqlite but we pass the DB path
    async with AsyncSqliteSaver.from_conn_string(DB_PATH) as checkpointer:
        
        # Compile the graph with the async checkpointer
        graph_app = workflow.compile(
            checkpointer=checkpointer, 
            interrupt_before=["HITL_DECISION"]
        )
        
        config = {"configurable": {"thread_id": thread_id}}
        
        print(f"▶️  Starting/Resuming Thread: {thread_id}")
        
        try:
            # Now we use 'async for' to iterate over the async generator
            async for event in graph_app.astream(input_data, config):
                # pass
                for node_name, output in event.items():
                    print(f"   📍 Node Completed: {node_name}")
                    
                    # --- HOOK: LOG TO DB ---
                    log_workflow_step(thread_id, node_name, output)
                    # -----------------------
        except Exception as e:
            print(f"❌ Error in background agent: {e}")
            import traceback
            traceback.print_exc()

# --- ENDPOINTS ---

@app.post("/invoice/submit")
async def submit_invoice(invoice: InvoiceInput, background_tasks: BackgroundTasks):
    """
    1. Accepts Invoice
    2. Starts Agent in Background
    """
    thread_id = str(uuid.uuid4())
    payload = {"invoice_payload": invoice.model_dump()}
    print(payload)
    
    # Run agent in background so API returns immediately
    background_tasks.add_task(run_agent_background, thread_id, payload)
    
    return {"message": "Invoice submitted", "thread_id": thread_id}

@app.get("/human-review/pending", response_model=Dict[str, List[QueueItem]])
def list_pending_reviews():
    """
    Returns list of items currently sitting in the 'human_queue' table.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT checkpoint_uid, invoice_id, vendor_name, amount, created_at, reason_for_hold, review_url FROM human_queue WHERE status='PENDING'")
    rows = cursor.fetchall()
    conn.close()
    
    items = []
    for row in rows:
        items.append(QueueItem(
            checkpoint_uid=row[0],
            invoice_id=row[1],
            vendor_name=row[2],
            amount=row[3],
            created_at=row[4],
            reason_for_hold=row[5],
            review_url=row[6]
        ))
    
    return {"items": items}

@app.post("/human-review/decision")
async def process_decision(request: DecisionRequest, background_tasks: BackgroundTasks):
    """
    1. Looks up thread_id from DB using checkpoint_uid.
    2. Updates LangGraph state with decision.
    3. Resumes execution.
    """
    print("debug human review", request)
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # 1. Find the Thread ID associated with this checkpoint
    cursor.execute("SELECT thread_id FROM human_queue WHERE checkpoint_uid = ?", (request.checkpoint_uid,))
    row = cursor.fetchone()
    
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Checkpoint not found")
    
    thread_id = row[0]
    
    # 2. Update DB status
    cursor.execute("UPDATE human_queue SET status = ? WHERE checkpoint_uid = ?", ("COMPLETED", request.checkpoint_uid))
    conn.commit()
    conn.close()
    
    # 3. Resume LangGraph
    # We need to reconstruct the graph object with the same checkpointer
    async with AsyncSqliteSaver.from_conn_string(DB_PATH) as checkpointer:
        
        # Compile the graph with the async checkpointer
        graph_app = workflow.compile(
            checkpointer=checkpointer, 
            interrupt_before=["HITL_DECISION"]
        )
        
        config = {"configurable": {"thread_id": thread_id}}
        
        print(f"▶️  Starting/Resuming Thread: {thread_id}")
        # A. Inject the Human's Decision into the state
        graph_app.aupdate_state(config, {
            "human_decision": request.decision, 
            "reviewer_notes": request.notes
        })
        
        try:
            background_tasks.add_task(run_agent_background, thread_id, None)
        except Exception as e:
            print(f"❌ Error in background agent: {e}")
            import traceback
            traceback.print_exc()
    
    # # A. Inject the Human's Decision into the state
    # graph_app.update_state(config, {
    #     "human_decision": request.decision, 
    #     "reviewer_notes": request.notes
    # })
    
    # # B. Resume the graph (passing None as input resumes from current state)
    # # We do this in background to not block response
    # background_tasks.add_task(run_agent_background, thread_id, None)
    
    return {"status": "Decision recorded", "next_stage": "RECONCILE" if request.decision == "ACCEPT" else "TERMINATED"}


@app.get("/audit/logs")
def get_audit_logs():
    """Fetches completed workflow logs"""
    conn = get_db_connection()
    cursor = conn.cursor()
    # Fetch most recent 50 logs
    cursor.execute("""
        SELECT audit_id, thread_id, invoice_id, vendor_name, final_status, total_amount, completed_at 
        FROM audit_logs 
        ORDER BY completed_at DESC 
        LIMIT 50
    """)
    rows = cursor.fetchall()
    conn.close()
    
    return {
        "logs": [
            {
                "audit_id": r[0],
                "thread_id": r[1],
                "invoice_id": r[2],
                "vendor": r[3],
                "status": r[4],
                "amount": r[5],
                "timestamp": r[6]
            }
            for r in rows
        ]
    }
@app.get("/erp/purchase-orders")
def get_erp_purchase_orders():
    """
    Fetches all Purchase Orders from the Mock ERP Database.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute("""
            SELECT po_number, vendor_name, total_amount, currency, full_po_json 
            FROM erp_purchase_orders
        """)
        rows = cursor.fetchall()
        
        items = []
        for row in rows:
            # Parse the stored JSON string back into a dict for the UI
            try:
                details = json.loads(row[4])
            except:
                details = {}

            items.append({
                "po_number": row[0],
                "vendor_name": row[1],
                "total_amount": row[2],
                "currency": row[3],
                "details": details
            })
            
        return {"items": items}
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()


class PurchaseOrderInput(BaseModel):
    po_json: Dict[str, Any]

@app.post("/erp/purchase-orders")
def create_purchase_order(data: PurchaseOrderInput):
    """
    Manually creates or updates a Purchase Order in the ERP Database.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        raw_data = data.po_json
        
        # 1. Validation & Extraction
        # We expect structure: { "purchase_order": { ... } }
        po_root = raw_data.get("purchase_order", {})
        
        po_number = po_root.get("po_number")
        vendor_name = po_root.get("vendor", {}).get("name")
        currency = po_root.get("summary", {}).get("currency", "USD")
        total_amount = po_root.get("summary", {}).get("total_amount")

        if not po_number or not vendor_name:
            raise HTTPException(status_code=400, detail="JSON must contain 'po_number' and 'vendor.name'")

        # 2. Insert into DB (OR REPLACE allows updating existing POs)
        cursor.execute("""
            INSERT OR REPLACE INTO erp_purchase_orders 
            (po_number, vendor_name, total_amount, currency, full_po_json)
            VALUES (?, ?, ?, ?, ?)
        """, (
            po_number,
            vendor_name,
            total_amount,
            currency,
            json.dumps(raw_data)
        ))
        
        conn.commit()
        return {"status": "success", "message": f"PO {po_number} created/updated successfully."}

    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()
  
  
  
@app.get("/audit/trace/{thread_id}")
def get_workflow_trace(thread_id: str):
    """Fetches the step-by-step history of a specific thread."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT node_name, output_json, timestamp 
        FROM workflow_logs 
        WHERE thread_id = ? 
        ORDER BY log_id ASC
    """, (thread_id,))
    
    rows = cursor.fetchall()
    conn.close()
    
    steps = []
    for r in rows:
        try:
            output = json.loads(r[1])
        except:
            output = r[1]
            
        steps.append({
            "node": r[0],
            "output": output,
            "timestamp": r[2]
        })
        
    return {"thread_id": thread_id, "steps": steps}
if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)