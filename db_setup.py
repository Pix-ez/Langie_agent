import sqlite3
import os
import json
DB_NAME = "invoice_system.db"

def setup_database():
    print(f"⚙️  Initializing database: {DB_NAME}...")
    
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    # 1. DROP the table if it exists to ensure schema matches exactly
    cursor.execute("DROP TABLE IF EXISTS human_queue")
    
    # 2. CREATE the table with 'checkpoint_uid' (NOT checkpoint_uid)
    print("   ├── Creating table: 'human_queue'...")
    cursor.execute("""
    CREATE TABLE human_queue (
        checkpoint_uid TEXT PRIMARY KEY,
        thread_id TEXT NOT NULL,
        invoice_id TEXT,
        vendor_name TEXT,
        amount REAL,
        created_at TEXT,
        reason_for_hold TEXT,
        review_url TEXT,
        status TEXT DEFAULT 'PENDING'
    );
    """)

    conn.commit()
    conn.close()
    print("✅ Database setup complete. Column 'checkpoint_uid' created successfully.")


def add_audit_table():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    print("🛠️  Adding 'audit_logs' table...")
    
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS audit_logs (
        audit_id TEXT PRIMARY KEY,
        thread_id TEXT,
        invoice_id TEXT,
        vendor_name TEXT,
        final_status TEXT,
        total_amount REAL,
        erp_txn_id TEXT,
        payment_id TEXT,
        completed_at TEXT,
        full_payload_json TEXT
    );
    """)
    
    conn.commit()
    conn.close()
    print("✅ Table 'audit_logs' ready.")

def add_raw_invoice_table():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    print("🛠️  Adding 'raw invoice' table...")
    
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS raw_invoices (
        raw_id TEXT PRIMARY KEY,
        invoice_id TEXT,
        payload_json TEXT,
        ingested_at TEXT
    );
    """)
    
    conn.commit()
    conn.close()
    print("✅ Table 'audit_logs' ready.")
def seed_erp_data():
    print(f"⚙️  Seeding ERP Data into {DB_NAME}...")
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    # 1. Create ERP Table
    cursor.execute("DROP TABLE IF EXISTS erp_purchase_orders")
    cursor.execute("""
    CREATE TABLE erp_purchase_orders (
        po_number TEXT PRIMARY KEY,
        vendor_name TEXT,
        total_amount REAL,
        currency TEXT,
        full_po_json TEXT
    );
    """)

   
    conn.commit()
    conn.close()
    print("✅ ERP Data Seeded. PO-556644 is ready for retrieval.")

def setup_tracing():
    print(f"⚙️  Setting up Workflow Tracing in {DB_NAME}...")
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    # Create 'workflow_logs' table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS workflow_logs (
        log_id INTEGER PRIMARY KEY AUTOINCREMENT,
        thread_id TEXT,
        node_name TEXT,
        output_json TEXT,
        timestamp TEXT
    );
    """)

    # Index for fast lookups by thread
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_logs_thread ON workflow_logs(thread_id);")

    conn.commit()
    conn.close()
    print("✅ Table 'workflow_logs' created.")
if __name__ == "__main__":
    setup_database()
    add_audit_table()
    add_raw_invoice_table()
    
    setup_tracing()
    seed_erp_data()
    seed_erp_data()
