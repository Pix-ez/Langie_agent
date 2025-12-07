import asyncio
import json
from mcp_wrapper import mcp_client

async def test_connection():
    print("--- TESTING MCP CONNECTION ---")
    
    # Payload for audit log
    mock_state = {
         "invoice_id": "TEST-OCR-1",
    "vendor_name": "Ignored", 
    "amount": 0,
    "file_path": "invoice1.pdf" 
    }

    print("1. Calling COMMON server...")
    try:
        # This calls output_final_payload tool
        response = await mcp_client.route(
            "ATLAS", 
            "ocr_extract", 
            {"file_path": "invoice1.pdf"}
        )
        print("\n✅ RESPONSE RECEIVED:")
        output = json.loads(response)
        print(output['detected_fields'])
    except Exception as e:
        print(f"\n❌ SCRIPT CRASHED: {e}")

if __name__ == "__main__":
    asyncio.run(test_connection())
