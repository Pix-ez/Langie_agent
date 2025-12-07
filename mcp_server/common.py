import sqlite3
import json
import os
from datetime import datetime
from typing import Dict, Any, List
from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, ValidationError
import re
import sys
import logging

logging.basicConfig(
    filename='server_debug.log', 
    level=logging.DEBUG, 
    format='%(asctime)s - %(levelname)s - %(message)s',
    force=True
)
# Initialize Server
mcp = FastMCP("COMMON_Server")

# Database Path (Ensure this points to the same DB file as main.py)
# Assuming servers/ is inside the root where main.py and invoice_system.db are
DB_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "invoice_system.db"))

# --- Data Models for Validation ---
logging.basicConfig(
    filename='server_debug.log', 
    level=logging.DEBUG, 
    format='%(asctime)s - [COMMON] - %(levelname)s - %(message)s',
    force=True
)
class InvoiceSchema(BaseModel):
    invoice_id: str
    vendor_name: str
    amount: float
    currency: str = "USD"
    # This is critical: We need the filename to decide how to mock the OCR later
    attachments: List[str] = [] 
# --- TOOLS ---

@mcp.tool()
async def accept_invoice_payload(invoice_data: Dict[str, Any]) -> str:
    """
    1. Validates schema (ensures attachments exist).
    2. Persists raw JSON to SQLite.
    Returns: JSON string with raw_id and status.
    """
    logging.info(f"📥 Tool Triggered: accept_invoice_payload")
    logging.debug(f"Payload: {json.dumps(invoice_data)}")

    try:
        # 1. Validate Schema
        try:
            validated_data = InvoiceSchema(**invoice_data)
        except ValidationError as e:
            logging.error(f"❌ Validation Failed: {e.errors()}")
            return json.dumps({"status": "error", "message": f"Validation Error: {e.errors()}"})

        # 2. Prepare DB Data
        # Generate a unique Raw ID
        timestamp = int(datetime.now().timestamp())
        raw_id = f"RAW-{validated_data.invoice_id}-{timestamp}"
        
        logging.info(f"📝 Persisting to DB: {DB_PATH} (Raw ID: {raw_id})")

        # 3. Connect & Insert
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()

        # Safety: Ensure table exists (Idempotent)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS raw_invoices (
            raw_id TEXT PRIMARY KEY,
            invoice_id TEXT,
            payload_json TEXT,
            ingested_at TEXT
        );
        """)

        cursor.execute("""
            INSERT INTO raw_invoices (raw_id, invoice_id, payload_json, ingested_at)
            VALUES (?, ?, ?, ?)
        """, (
            raw_id, 
            validated_data.invoice_id, 
            json.dumps(invoice_data), 
            datetime.now().isoformat()
        ))
        
        conn.commit()
        conn.close()
        
        logging.info("✅ Persistence Successful")

        return json.dumps({
            "status": "success", 
            "raw_id": raw_id,
            "message": "Payload accepted and persisted."
        })

    except Exception as e:
        logging.exception("❌ System Error in accept_invoice_payload")
        return json.dumps({"status": "error", "message": str(e)})


# ... (Previous imports and init) ...

@mcp.tool()
async def parse_line_items(raw_text: str) -> str:
    """
    Input: JSON string from OCR (Flat Structure).
    Output: Standardized Invoice Object for the Agent.
    """
    try:
        logging.debug(f"Parsing flat JSON input: {raw_text[:100]}...")
        
        # 1. Parse the JSON string
        data = json.loads(raw_text)
        data = data['detected_fields']
        # 2. Safe Float Conversion Helper
        def to_float(val):
            try:
                return float(val)
            except (ValueError, TypeError):
                return 0.0

        # 3. Map Flat Structure -> Agent Standard Structure
        # Note: Your input doesn't have 'subtotal' or 'currency', so we derive/default them.
        
        # Calculate subtotal by summing line items (useful for matching logic)
        line_items_std = []
        calc_subtotal = 0.0
        
        raw_items = data.get("line_items", [])
        for item in raw_items:
            amt = to_float(item.get("amount"))
            calc_subtotal += amt
            
            line_items_std.append({
                "desc": item.get("description"),
                "qty": to_float(item.get("quantity")),
                "unit_price": to_float(item.get("rate")),
                "total": amt
            })

        parsed_data = {
            "invoice_id": data.get("invoice_number"),
            "po_number": data.get("po_number"),
            "vendor_name": data.get("vendor_name"),
            "bill_to": data.get("bill_to"),
            "invoice_date": data.get("invoice_date"),
            
            # Financials
            "currency": "USD", # Defaulting since not in input
            "total_amount": to_float(data.get("total_amount")),
            "subtotal": calc_subtotal, # Derived
            "tax_amount": 0.0,         # Default
            
            # Line Items
            "line_items": line_items_std
        }
        
        return json.dumps({
            "status": "success", 
            "parsed_data": parsed_data
        })

    except json.JSONDecodeError:
        return json.dumps({"status": "error", "message": "Input was not valid JSON"})
    except Exception as e:
        return json.dumps({"status": "error", "message": str(e)})
    
# ... (Previous imports: re, json, etc.)

@mcp.tool()
async def normalize_vendor(raw_name: str) -> str:
    """
    Standardizes vendor name (removes 'Inc', 'Ltd', special chars, uppercase).
    Example: "Acme Corp, Inc." -> "ACME CORP"
    """
    if not raw_name:
        return ""
    
    # 1. Uppercase
    normalized = raw_name.upper()
    
    # 2. Remove common suffixes
    suffixes = [" INC", " LTD", " LLC", " PVT", " GMBH", "."]
    for suffix in suffixes:
        normalized = normalized.replace(suffix, "")
        
    # 3. Remove special chars (keep only alphanumeric and spaces)
    normalized = re.sub(r'[^A-Z0-9 ]', '', normalized).strip()
    
    return json.dumps({
        "status": "success",
        "normalized_name": normalized
    })

@mcp.tool()
async def compute_flags(enrichment_data: Dict[str, Any], invoice_amount: float) -> str:
    """
    Analyzes vendor data to generate risk flags.
    """
    flags = []
    
    # Rule 1: High Risk Vendor (Simulated score from enrichment)
    risk_score = enrichment_data.get("risk_score", 0)
    if risk_score > 75:
        flags.append("HIGH_RISK_VENDOR")
        
    # Rule 2: Missing Tax ID
    if not enrichment_data.get("tax_id"):
        flags.append("MISSING_TAX_ID")
        
    # Rule 3: Credit Limit Check (Mock logic)
    credit_limit = enrichment_data.get("credit_limit", 10000)
    if invoice_amount > credit_limit:
        flags.append("EXCEEDS_CREDIT_LIMIT")

    return json.dumps({
        "status": "success",
        "flags": flags,
        "risk_level": "HIGH" if flags else "LOW"
    })

# ... (Previous imports)

@mcp.tool()
async def compute_match_score(invoice_data: Dict[str, Any], po_data: Dict[str, Any]) -> str:
    """
    Compare Invoice vs PO. Handles Subtotal matching logic.
    """
    # 1. Get PO Amount (PO usually is pre-tax)
    po_summary = po_data.get("summary", {})
    po_amount = po_summary.get("total_amount", 0.0)
    
    # 2. Get Invoice Amount (Prefer Subtotal for comparison, fallback to Total)
    inv_subtotal = invoice_data.get("subtotal")
    inv_total = invoice_data.get("total_amount", 0.0)
    
    # Logic: If Subtotal exists and matches PO, perfect. 
    # If not, check Total.
    target_amt = inv_subtotal if inv_subtotal else inv_total
    
    if po_amount == 0:
        score = 0.0
        note = "PO Amount not found"
    else:
        diff = abs(target_amt - po_amount)
        # Calculate percentage difference
        variance = diff / po_amount
        score = max(0.0, 1.0 - variance)
        score = round(score, 2)
        note = f"Inv Subtotal: {target_amt} vs PO: {po_amount}"

    return json.dumps({
        "status": "success",
        "score": score,
        "notes": note,
        "match_details": {"diff": diff if po_amount > 0 else 0}
    })

# ... (Previous imports)

@mcp.tool()
async def save_state_for_human_review(payload: Dict[str, Any]) -> str:
    """
    Persists the workflow state into the Human Review Queue (DB).
    Expects payload keys matching the human_queue table columns.
    """
    sys.stderr.write(f"💾 [COMMON] Saving HITL Ticket: {payload.get('checkpoint_uid')}")
    sys.stderr.flush()
    
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
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
        conn.close()
        
        return json.dumps({
            "status": "success", 
            "message": "Saved to Human Queue",
            "checkpoint_uid": payload['checkpoint_uid']
        })

    except Exception as e:
        return json.dumps({"status": "error", "message": str(e)})
    
# ... (Previous imports)

@mcp.tool()
async def build_accounting_entries(invoice_data: Dict[str, Any], vendor_name: str) -> str:
    """
    Generates General Ledger (GL) entries.
    Standard Logic: Debit Expense, Credit Accounts Payable.
    """
    sys.stderr.write("📘 [COMMON] Building Accounting Ledger Entries...")
    sys.stderr.flush()
    
    amount = float(invoice_data.get("total_amount") or invoice_data.get("amount", 0.0))
    currency = invoice_data.get("currency", "USD")
    invoice_id = invoice_data.get("invoice_id", "UNKNOWN")
    
    if amount == 0.0:
        return json.dumps({"status": "error", "message": "Zero amount invoice"})

    # 1. Credit Entry (Liability)
    credit_entry = {
        "type": "CREDIT",
        "account_code": "2000-AP-TRADE",
        "account_name": f"Accounts Payable - {vendor_name}",
        "amount": amount,
        "currency": currency,
        "description": f"Invoice Liability for {invoice_id}"
    }
    
    # 2. Debit Entries (Expense)
    # In a real system, we'd map line items to specific GL codes.
    # Here, we do a simple summary or split by line item.
    debit_entries = []
    line_items = invoice_data.get("line_items", [])
    
    if line_items:
        for item in line_items:
            # Simple logic: Check if 'qty' and 'price' exist, else guess
            item_amt = item.get("total") or (item.get("qty", 1) * item.get("unit_price", 0))
            # Fallback if calculation failed
            if item_amt == 0: item_amt = amount # simplistic fallback
            
            debit_entries.append({
                "type": "DEBIT",
                "account_code": "5000-GEN-EXP", # Default expense GL
                "account_name": item.get("desc", "General Expense"),
                "amount": item_amt,
                "currency": currency,
                "description": f"Expense: {item.get('desc')}"
            })
    else:
        # Lump sum debit if no lines parsed
        debit_entries.append({
            "type": "DEBIT",
            "account_code": "5000-GEN-EXP",
            "account_name": "Uncategorized Expenses",
            "amount": amount,
            "currency": currency,
            "description": "General Expense Allocation"
        })

    # 3. Validate Balance
    total_debit = sum(e["amount"] for e in debit_entries)
    
    # If rounding errors or missing line matches, add a 'Variance' entry to balance
    if abs(total_debit - amount) > 0.01:
        variance = amount - total_debit
        debit_entries.append({
            "type": "DEBIT",
            "account_code": "9999-VARIANCE",
            "account_name": "Rounding Variance",
            "amount": round(variance, 2),
            "currency": currency,
            "description": "Auto-balancing variance"
        })

    return json.dumps({
        "status": "success",
        "entries": [credit_entry] + debit_entries,
        "total_credits": amount,
        "total_debits": sum(e["amount"] for e in debit_entries) + (amount - total_debit if abs(total_debit - amount) > 0.01 else 0)
    })

# ... (Previous imports)

@mcp.tool()
async def output_final_payload(workflow_state: Dict[str, Any]) -> str:
    """
    Consolidates workflow data into a final structure and persists to Audit DB.
    """
    logging.info("🏁 [COMMON] Tool 'output_final_payload' triggered")
    logging.debug(f"📥 Input Keys: {list(workflow_state.keys())}")
    
    try:
        # 1. Construct Payload
        invoice_payload = workflow_state.get("invoice_payload", {})
        parsed = workflow_state.get("parsed_invoice", {})
        vendor = workflow_state.get("vendor_profile", {})
        
        # Check if we actually have data
        if not invoice_payload:
            logging.warning("⚠️ Invoice Payload is empty!")

        final_payload = {
            "metadata": {
                "processing_id": workflow_state.get("raw_id"),
                "completed_at": datetime.now().isoformat(),
                "status": "SUCCESS"
            },
            "invoice_header": {
                "id": invoice_payload.get("invoice_id"),
                "vendor_normalized": vendor.get("name"),
                "invoice_date": parsed.get("parsed_dates", {}).get("invoice_date"),
                "total_amount": invoice_payload.get("amount"),
                "currency": invoice_payload.get("currency", "USD")
            },
            "financials": {
                "erp_transaction_id": workflow_state.get("erp_txn_id"),
                "payment_reference": workflow_state.get("payment_id"),
                "gl_posted": True if workflow_state.get("erp_txn_id") else False
            },
            "risk_compliance": {
                "flags_raised": workflow_state.get("validation_flags", []),
                "match_score": workflow_state.get("match_score"),
                "human_review_performed": True if workflow_state.get("human_decision") else False,
                "approver_notes": workflow_state.get("reviewer_notes")
            }
        }
        
        audit_id = f"AUDIT-{int(datetime.now().timestamp())}"
        
        # 2. Persist to SQLite
        logging.info(f"📝 Attempting DB Insert to {DB_PATH}")
        
        # Check if DB file exists
        if not os.path.exists(DB_PATH):
            logging.error(f"❌ DB File not found at {DB_PATH}")
            return json.dumps({"status": "error", "message": "DB file not found"})

        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        # Check if table exists
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='audit_logs';")
        if not cursor.fetchone():
            logging.error("❌ Table 'audit_logs' does not exist in this DB file!")
            conn.close()
            return json.dumps({"status": "error", "message": "Table audit_logs missing"})

        cursor.execute("""
            INSERT INTO audit_logs 
            (audit_id, thread_id, invoice_id, vendor_name, final_status, total_amount, erp_txn_id, payment_id, completed_at, full_payload_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            audit_id,
            workflow_state.get("thread_id"),
            final_payload["invoice_header"]["id"],
            final_payload["invoice_header"]["vendor_normalized"],
            "COMPLETED",
            final_payload["invoice_header"]["total_amount"],
            final_payload["financials"]["erp_transaction_id"],
            final_payload["financials"]["payment_reference"],
            final_payload["metadata"]["completed_at"],
            json.dumps(final_payload)
        ))
        
        conn.commit()
        conn.close()
        
        logging.info(f"✅ Insert Successful! Audit ID: {audit_id}")
        
        return json.dumps({
            "status": "success",
            "audit_id": audit_id,
            "final_payload": final_payload
        })

    except Exception as e:
        logging.exception("❌ CRITICAL EXCEPTION") # Prints full traceback to log file
        return json.dumps({"status": "error", "message": str(e)})

if __name__ == "__main__":
    mcp.run(transport="stdio")