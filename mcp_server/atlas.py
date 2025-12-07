from datetime import datetime
import json
import sqlite3
from typing import Dict, Any, Optional
from mcp.server.fastmcp import FastMCP
import sys
import logging
import base64
from openai import OpenAI
from dotenv import load_dotenv 
import os 
import fitz  # PyMuPDF
from typing import List
from pydantic import BaseModel, Field
DB_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "invoice_system.db"))
load_dotenv() 
logging.basicConfig(
    filename='server_debug.log', 
    level=logging.DEBUG, 
    format='%(asctime)s - %(levelname)s - %(message)s',
    force=True
)
class LineItem(BaseModel):
    description: str = Field(
        description="Item description exactly as shown, or 'UNREADABLE'."
    )
    quantity: str = Field(
        description="Quantity exactly as written in the image, or 'UNREADABLE'."
    )
    rate: str = Field(
        description="Rate or unit price exactly as printed, or 'UNREADABLE'."
    )
    amount: str = Field(
        description="Line item amount exactly as printed, or 'UNREADABLE'."
    )


class DetectedFields(BaseModel):
    invoice_number: str = Field(
        description="Invoice number as shown in the document, or 'UNREADABLE'."
    )
    invoice_date: str = Field(
        description="Invoice date exactly as shown, or 'UNREADABLE'."
    )
    vendor_name: str = Field(
        description="Vendor or supplier name, or 'UNREADABLE'."
    )
    bill_to: str = Field(
        description="Bill-to customer name or block of text, or 'UNREADABLE'."
    )
    po_number: str = Field(
        description="Purchase order number if present, otherwise 'UNREADABLE'."
    )
    line_items: List[LineItem] = Field(
        description="Extracted table rows for invoice items."
    )
    total_amount: str = Field(
        description="Total invoice amount exactly as shown, or 'UNREADABLE'."
    )


class InvoiceOCR(BaseModel):
    raw_text: str = Field(
        description="Full invoice text extracted exactly as it appears."
    )
    detected_fields: DetectedFields = Field(
        description="Structured fields extracted from the invoice."
    )


client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
mcp = FastMCP("ATLAS_Server")

def pdf_to_images_pymupdf(pdf_path, output_dir="output_images", dpi=300):
    os.makedirs(output_dir, exist_ok=True)

    doc = fitz.open(pdf_path)
    image_paths = []

    for page_num in range(doc.page_count):
        page = doc.load_page(page_num)
        pix = page.get_pixmap(dpi=dpi)

        output_path = os.path.join(output_dir, f"page_{page_num + 1}.png")
        pix.save(output_path)
        image_paths.append(output_path)

    doc.close()
    return image_paths

prompt =  """You are an OCR extraction engine specialized in financial documents. 
Your job is to extract ONLY the textual content that physically appears in the invoice image.

STRICT RULES:
1. Do NOT infer, guess, assume, or hallucinate any values.
2. If a field is partially visible or unreadable, return `"UNREADABLE"` instead of guessing.
3. Preserve all formatting EXACTLY as it appears (capitalization, punctuation, spacing, line breaks).
4. Extract text in a top-to-bottom, left-to-right reading order.
5. Do NOT rewrite, summarize, or interpret the meaning of text — only extract raw text.
6. Do NOT generate fields that are not present in the image.
7. Do NOT normalize dates, currency, numbers, or words — extract exactly as shown.
8. Return output ONLY in valid UTF-8."""


# Function to encode the image
def encode_image(image_path):
    with open(image_path, "rb") as image_file:
        return base64.b64encode(image_file.read()).decode("utf-8")


@mcp.tool()
async def health_check() -> str:
    return "ATLAS Server is Ready"

# --- NEW TOOL ---

@mcp.tool()
async def ocr_extract(file_path: str) -> str:
    """
    1. Reads PDF from disk.
    2. Converts to Image.
    3. Sends to LLM Vision Model for Structured Extraction.
    """
    logging.info(f"👁️ [ATLAS] Starting OCR on file: {file_path}")

   
    
    if not os.path.exists(file_path):
        # FALLBACK FOR DEMO: If file doesn't exist, we can't run real OCR.
        # We return the Mock logic so your agent doesn't crash during testing without real PDFs.
        logging.warning(f"⚠️ File not found at {file_path}. Using MOCK fallback.")
        
    # B. ENCODE IMAGE
    img_paths = pdf_to_images_pymupdf(file_path)
    # # Path to your image
    image_path = img_paths[0]
    print(image_path)
    # # Getting the Base64 string
    base64_image = encode_image(image_path)
    if not base64_image:
        return json.dumps({"status": "error", "message": "Failed to convert PDF to image"})

    # C. CALL LLM (Real Logic)
    try:
       
        
        response = client.responses.parse(
            model="gpt-4.1",
            input=[
                {
                    "role": "user",
                    "content": [
                        { "type": "input_text", "text":prompt  },
                        {
                            "type": "input_image",
                            "image_url": f"data:image/jpeg;base64,{base64_image}",
                        },
                    ],
                }
            ],
            text_format = InvoiceOCR
        )

        # Extract parsed object
        extracted_data = response.output_text
        
        # Convert to Dict
        # model_dump() converts Pydantic -> Dict
        json_output = json.loads(extracted_data)
        
        logging.info("✅ OCR Successful")
        logging.debug(f"Extracted: {json_output}")
        json_string = json.dumps(json_output)
        return json_string # json_output

    except Exception as e:
        logging.exception("❌ OpenAI API Error")
        return json.dumps({"status": "error", "message": str(e)})

# ... (Previous imports)

@mcp.tool()
async def enrich_vendor(normalized_name: str, source: str = "vendor_db") -> str:
    """
    Fetches external data: Tax IDs, Credit Scores, Address, Email.
    """
    # 1. Log to file
    logging.info(f"🌍 [ATLAS] Enriching '{normalized_name}' via {source}...")
    
    # 2. Normalize Key for Lookup (Upper case, stripped)
    lookup_key = normalized_name.upper().strip() if normalized_name else "UNKNOWN"

    # 3. Dynamic Mock Data
    # Includes ACME (Generic), SHADY (Fail test), and BRIGHTTECH (Your specific test)
    mock_db = {
        "ACME CORP": {
            "tax_id": "US-99887766",
            "address": "123 Coyote Way, NV",
            "credit_score": 750,
            "risk_score": 10, 
            "credit_limit": 50000,
            "email": "finance@acmecorp.com"
        },
        "SHADY SHELL CO": {
            "tax_id": None, 
            "address": "Unknown",
            "credit_score": 300,
            "risk_score": 90, # High risk (>75 triggers flag)
            "credit_limit": 1000,
            "email": "admin@shadyshell.com"
        },
        # ✅ YOUR SPECIFIC TEST VENDOR
        "BRIGHTTECH SOLUTIONS": {
            "tax_id": "US-BTS-2024-X",
            "address": "404 Cloud Blvd, Server City, CA",
            "credit_score": 820,
            "risk_score": 5, # Low risk
            "credit_limit": 100000,
            "email": "billing@brighttech.solutions" 
        }
    }
    
    # 4. Lookup Logic
    data = mock_db.get(lookup_key)
    
    if not data:
        logging.warning(f"⚠️ Vendor '{lookup_key}' not found in Mock DB. Using fallback.")
        data = {
            "tax_id": None,
            "address": "Unknown Address",
            "risk_score": 50, # Medium risk
            "credit_limit": 5000,
            "email": None
        }
    
    # 5. Return Result
    return json.dumps({
        "status": "success",
        "vendor_data": {
            "name": normalized_name, # Keep original casing for display
            **data
        },
        "source_used": source
    })


# ... (Previous imports)


@mcp.tool()
async def fetch_erp_data(vendor_name: str, po_number: str = "", erp_system: str = "mock_erp") -> str:
    """
    Queries the SQLite ERP table for the PO.
    """
    print(f"🏭 [ATLAS] Fetching ERP Data for PO: {po_number}")
    
    if not po_number:
        return json.dumps({"status": "error", "message": "PO Number required"})

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute("SELECT full_po_json FROM erp_purchase_orders WHERE po_number = ?", (po_number,))
    row = cursor.fetchone()
    conn.close()

    if row:
        po_json = json.loads(row[0])
        # Return structured exactly how retrieval node expects it
        return json.dumps({
            "status": "success",
            "data": {
                "purchase_orders": [po_json['purchase_order']], # Wrap in list
                "grns": [], # Empty for now
                "history": []
            }
        })
    else:
        return json.dumps({"status": "success", "data": {"purchase_orders": []}})

# ... (Previous imports)

@mcp.tool()
async def accept_or_reject_invoice(invoice_id: str, decision: str, notes: str = "", reviewer: str = "unknown") -> str:
    """
    Logs the Human Decision (ACCEPT/REJECT) to the external system audit trail.
    """
    sys.stderr.write(f"👮‍♂️ [ATLAS] Processing Human Decision for {invoice_id}: {decision}")
    sys.stderr.flush()
    # Mocking External System Audit Log
    # In a real scenario, this sends a POST to SAP/NetSuite to unblock the invoice or void it.
    
    audit_entry = {
        "action": "HUMAN_REVIEW_COMPLETED",
        "outcome": decision,
        "timestamp": "2024-10-27T12:00:00Z",
        "notes": notes,
        "performed_by": reviewer
    }
    
    return json.dumps({
        "status": "success",
        "audit_id": "AUDIT-999-LOG",
        "message": f"Invoice marked as {decision} in system."
    })

# ... (Previous imports)

@mcp.tool()
async def post_to_erp(entries: list[dict], erp_system: str = "mock_erp") -> str:
    """
    Posts the debit/credit journal entries to the ERP system.
    Returns: A Transaction ID (TXN-ID) confirmation.
    """
    sys.stderr.write(f"🏃 [ATLAS] Posting {len(entries)} lines to {erp_system}...")
    sys.stderr.flush()
    # Mock ERP Logic
    total_debit = sum(e.get('amount', 0) for e in entries if e.get('type') == 'DEBIT')
    total_credit = sum(e.get('amount', 0) for e in entries if e.get('type') == 'CREDIT')
    
    # Simple validation check simulated on ERP side
    if abs(total_debit - total_credit) > 0.05:
         return json.dumps({
            "status": "error",
            "message": "Unbalanced Journal Entry rejected by ERP."
        })

    # Simulate success
    txn_id = f"ERP-TXN-{int(datetime.now().timestamp())}"
    
    return json.dumps({
        "status": "success",
        "txn_id": txn_id,
        "message": "Journal posted successfully"
    })

@mcp.tool()
async def schedule_payment(invoice_id: str, amount: float, vendor: str, due_date: str = "") -> str:
    """
    Schedules a bank transfer/check via the AP module.
    """
    sys.stderr.write(f"💸 [ATLAS] Scheduling Payment of ${amount} to {vendor}...")
    sys.stderr.flush()
    # Mock Payment Logic
    payment_id = f"PAY-{invoice_id}-{int(datetime.now().timestamp())}"
    effective_date = due_date if due_date else datetime.now().strftime("%Y-%m-%d")
    
    return json.dumps({
        "status": "success",
        "payment_id": payment_id,
        "scheduled_date": effective_date,
        "method": "ACH"
    })

# ... (Previous imports)

@mcp.tool()
async def send_notification(recipient: str, subject: str, body: str, channel: str = "email", provider: str = "sendgrid") -> str:
    """
    Sends a notification via Email or Slack.
    """
    sys.stderr.write(f"✉️ [ATLAS] Sending {channel} via {provider} to: {recipient}")
    sys.stderr.write(f"   └─ Subject: {subject}")
    sys.stderr.flush()
    # Mock Sending Logic
    message_id = f"MSG-{int(datetime.now().timestamp())}-{channel.upper()}"
    
    return json.dumps({
        "status": "success",
        "message_id": message_id,
        "provider": provider,
        "timestamp": datetime.now().isoformat()
    })

if __name__ == "__main__":
    mcp.run(transport="stdio")