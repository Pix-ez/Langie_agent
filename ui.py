import streamlit as st
import requests
import json
import pandas as pd
from datetime import datetime

# CONFIGURATION
API_URL = "http://localhost:8000"

st.set_page_config(page_title="Invoice Agent AI", layout="wide", page_icon="🤖")

st.title("🤖 Autonomous Invoice Processing Agent")

# Sidebar Navigation
page = st.sidebar.radio(
    "Navigation", 
    ["📥 Submit Invoice", "👨‍💼 Human Review Queue", "📊 Audit Logs", "📦 ERP Data"] # Added ERP Data
)
# ==========================================
# PAGE 1: SUBMIT INVOICE
# ==========================================
if page == "📥 Submit Invoice":
    st.header("Submit New Invoice")
    # st.info("Agent Config: Invoices > $900.00 will trigger Human Review.")

    col1, col2 = st.columns(2)
    
    with col1:
        st.subheader("Invoice Details")
        # Default JSON Templates
        example_trigger = {
            "invoice_id": f"INV-{int(datetime.now().timestamp())}",
            "vendor_name": "Acme Corp",
            "amount": 1000.00,
            "attachments": ["invoice1.pdf"]
        }  
        json_input = st.text_area("Invoice Payload (JSON)", value="", height=250)
    
    with col2:
        st.subheader("Action")
        if st.button("🚀 Start Agent Workflow", type="primary"):
            try:
                payload = json.loads(json_input)
                with st.spinner("Submitting to Agent..."):
                    res = requests.post(f"{API_URL}/invoice/submit", json=payload)
                
                if res.status_code == 200:
                    data = res.json()
                    st.success(f"✅ Workflow Started!")
                    st.json(data)
                else:
                    st.error(f"Error: {res.text}")
            except json.JSONDecodeError:
                st.error("Invalid JSON format.")
            except Exception as e:
                st.error(f"Connection Error: {e}")

# ==========================================
# PAGE 2: HUMAN REVIEW QUEUE
# ==========================================
elif page == "👨‍💼 Human Review Queue":
    st.header("Pending Human Reviews")
    
    if st.button("🔄 Refresh Queue"):
        st.rerun()

    try:
        res = requests.get(f"{API_URL}/human-review/pending")
        if res.status_code == 200:
            items = res.json().get("items", [])
            
            if not items:
                st.success("🎉 No pending reviews! All clear.")
            else:
                for item in items:
                    with st.expander(f"🔴 HOLD: {item['vendor_name']} - ${item['amount']} ({item['invoice_id']})", expanded=True):
                        c1, c2, c3 = st.columns([2, 2, 1])
                        
                        with c1:
                            st.write(f"**Reason:** {item['reason_for_hold']}")
                            st.write(f"**Checkpoint UID:** `{item['checkpoint_uid']}`")
                            st.caption(f"Review URL: {item['review_url']}")
                        
                        with c2:
                            notes = st.text_input("Reviewer Notes", key=f"note_{item['checkpoint_uid']}")
                            reviewer = st.text_input("Reviewer ID", value="admin_user", key=f"user_{item['checkpoint_uid']}")
                        
                        with c3:
                            st.write("Decision:")
                            if st.button("✅ APPROVE", key=f"approve_{item['checkpoint_uid']}", type="primary"):
                                decision_payload = {
                                    "checkpoint_uid": item['checkpoint_uid'],
                                    "decision": "ACCEPT",
                                    "reviewer_id": reviewer,
                                    "notes": notes or "Manual Approval via UI"
                                }
                                r = requests.post(f"{API_URL}/human-review/decision", json=decision_payload)
                                if r.status_code == 200:
                                    st.toast("Approved! Agent resuming...", icon="🚀")
                                    st.rerun()
                                else:
                                    st.error(r.text)

                            if st.button("⛔ REJECT", key=f"reject_{item['checkpoint_uid']}"):
                                decision_payload = {
                                    "checkpoint_uid": item['checkpoint_uid'],
                                    "decision": "REJECT",
                                    "reviewer_id": reviewer,
                                    "notes": notes or "Manual Rejection via UI"
                                }
                                r = requests.post(f"{API_URL}/human-review/decision", json=decision_payload)
                                if r.status_code == 200:
                                    st.toast("Rejected. Workflow terminated.", icon="🛑")
                                    st.rerun()
                                else:
                                    st.error(r.text)
        else:
            st.error("Failed to fetch queue.")
            
    except Exception as e:
        st.error(f"Could not connect to backend: {e}")

# ==========================================
# PAGE 3: AUDIT LOGS
# ==========================================
# elif page == "📊 Audit Logs":
#     st.header("Workflow History")
    
#     if st.button("🔄 Refresh Logs"):
#         st.rerun()

#     try:
#         res = requests.get(f"{API_URL}/audit/logs")
#         if res.status_code == 200:
#             logs = res.json().get("logs", [])
            
#             if logs:
#                 df = pd.DataFrame(logs)
#                 # Reorder columns for display
#                 df = df[['timestamp', 'invoice_id', 'vendor', 'amount', 'status', 'audit_id']]
                
#                 # Dynamic Status Coloring
#                 def color_status(val):
#                     color = 'green' if val == 'COMPLETED' else 'red'
#                     return f'color: {color}'

#                 st.dataframe(df.style.applymap(color_status, subset=['status']), use_container_width=True)
#             else:
#                 st.info("No audit logs found yet.")
#         else:
#             st.warning("Ensure the /audit/logs endpoint is added to main.py")
            
#     except Exception as e:
#         st.error(f"Could not connect to backend: {e}")
elif page == "📊 Audit Logs":
    st.header("Workflow History & Observability")
    
    col_a, col_b = st.columns([4, 1])
    with col_b:
        if st.button("🔄 Refresh Logs"):
            st.rerun()

    try:
        # 1. Fetch High-Level Logs
        res = requests.get(f"{API_URL}/audit/logs")
        if res.status_code == 200:
            logs = res.json().get("logs", [])
            
            if logs:
                # --- MAIN TABLE ---
                df = pd.DataFrame(logs)
                st.dataframe(
                    df[['timestamp', 'invoice_id', 'vendor', 'amount', 'status']], 
                    use_container_width=True,
                    hide_index=True
                )

                st.divider()
                st.subheader("🕵️‍♂️ Workflow Trace Explorer")
                st.caption("Select an invoice above to see exactly how the AI processed it step-by-step.")
                
                # --- SELECTOR ---
                # Create a map for the dropdown: "INV-001 (Acme)" -> Row Data
                invoice_map = {
                    f"{row['invoice_id']} | {row['vendor']} | {row['timestamp']}": row 
                    for row in logs
                }
                
                selected_label = st.selectbox("Select Transaction to Inspect:", options=list(invoice_map.keys()))
                
                if selected_label:
                    selected_row = invoice_map[selected_label]
                    thread_id = selected_row.get('thread_id')
                    
                    if not thread_id:
                        st.warning("⚠️ No Trace ID found for this record.")
                    else:
                        st.info(f"Viewing Trace for Thread ID: `{thread_id}`")
                        
                        # 2. Fetch Detailed Trace
                        trace_res = requests.get(f"{API_URL}/audit/trace/{thread_id}")
                        
                        if trace_res.status_code == 200:
                            steps = trace_res.json().get("steps", [])
                            
                            if not steps:
                                st.warning("No step logs found. (Ensure 'log_workflow_step' is active in backend)")
                            else:
                                # --- RENDER STEPS ---
                                for i, step in enumerate(steps):
                                    node_name = step['node']
                                    timestamp = step['timestamp']
                                    output = step['output']
                                    
                                    # Icons based on Node Type
                                    icon = "📍"
                                    if node_name == "INTAKE": icon = "📥"
                                    elif node_name == "UNDERSTAND": icon = "🧠"
                                    elif node_name == "MATCH_TWO_WAY": icon = "⚖️"
                                    elif node_name == "CHECKPOINT_HITL": icon = "⏸️"
                                    elif node_name == "HITL_DECISION": icon = "👨‍💼"
                                    elif node_name == "POSTING": icon = "🏃"
                                    elif node_name == "COMPLETE": icon = "✅"
                                    elif node_name == "ERROR": icon = "❌"

                                    # Expander for each step
                                    with st.expander(f"{icon} {timestamp} - **{node_name}**"):
                                        st.write(f"**Node:** `{node_name}`")
                                        
                                        # Special formatting for certain outputs to make them readable
                                        if isinstance(output, dict):
                                            # If it has a match score, highlight it
                                            if "match_score" in output:
                                                score = output["match_score"]
                                                color = "green" if score >= 0.9 else "red"
                                                st.markdown(f"**Match Score:** :{color}[{score}]")
                                            
                                            # If status is present
                                            if "status" in output:
                                                st.write(f"**Status:** {output['status']}")
                                                
                                            st.json(output)
                                        else:
                                            st.write(output)
                                            
                                # Connecting line visual
                                st.caption("🏁 End of Workflow Trace")
                                
                        else:
                            st.error("Failed to fetch trace details.")
            else:
                st.info("No audit logs found.")
        else:
            st.error(f"API Error: {res.text}")
            
    except Exception as e:
        st.error(f"Frontend Error: {e}")
       
# # ==========================================
# # PAGE 4: ERP DATA VIEW
# # ==========================================
# elif page == "📦 ERP Data":
#     st.header("ERP System Data (Mock)")
#     st.info("This view shows the Purchase Orders currently available in the system for 3-Way Matching.")
    
#     if st.button("🔄 Refresh Data"):
#         st.rerun()

#     try:
#         res = requests.get(f"{API_URL}/erp/purchase-orders")
#         if res.status_code == 200:
#             items = res.json().get("items", [])
            
#             if items:
#                 # 1. Summary Table
#                 st.subheader("Purchase Order Registry")
#                 df = pd.DataFrame(items)
#                 # Select only clean columns for the table
#                 display_df = df[['po_number', 'vendor_name', 'total_amount', 'currency']]
#                 st.dataframe(display_df, use_container_width=True)

#                 # 2. Detailed View
#                 st.subheader("PO Details (JSON)")
#                 for item in items:
#                     with st.expander(f"📄 {item['po_number']} - {item['vendor_name']} (${item['total_amount']})"):
#                         c1, c2 = st.columns(2)
#                         with c1:
#                             st.write(f"**PO Number:** {item['po_number']}")
#                             st.write(f"**Vendor:** {item['vendor_name']}")
#                         with c2:
#                             st.write(f"**Amount:** {item['total_amount']} {item['currency']}")
#                             st.write(f"**Line Items:** {len(item.get('details', {}).get('purchase_order', {}).get('items', []))}")
                        
#                         # Show full JSON structure
#                         st.json(item['details'])
#             else:
#                 st.warning("No Purchase Orders found in ERP Database. Run 'seed_erp.py'!")
#         else:
#             st.error(f"Error fetching data: {res.text}")
            
#     except Exception as e:
#         st.error(f"Could not connect to backend: {e}")
        

# ==========================================
# PAGE 5: NEW PO
# ==========================================
elif page == "📦 ERP Data":
    st.header("ERP System Data (Mock)")
    st.info("Manage Purchase Orders for 3-Way Matching.")

    # --- NEW SECTION: ADD PO FORM ---
    with st.expander("➕ Add / Update Purchase Order", expanded=False):
        st.write("Paste the PO JSON below. It must follow the standard schema.")
        
       
        
        with st.form("add_po_form"):
            po_input_str = st.text_area("PO JSON", value="", height=300)
            submitted = st.form_submit_button("💾 Save to ERP")
            
            if submitted:
                try:
                    po_payload = json.loads(po_input_str)
                    # Send to API
                    res = requests.post(f"{API_URL}/erp/purchase-orders", json={"po_json": po_payload})
                    
                    if res.status_code == 200:
                        st.success("✅ Purchase Order Saved!")
                        st.rerun() # Refresh page to show in table below
                    else:
                        st.error(f"Error: {res.text}")
                except json.JSONDecodeError:
                    st.error("❌ Invalid JSON format.")
                except Exception as e:
                    st.error(f"❌ Connection Error: {e}")

    # --- EXISTING DISPLAY LOGIC ---
    if st.button("🔄 Refresh Data"):
        st.rerun()

    try:
        res = requests.get(f"{API_URL}/erp/purchase-orders")
        if res.status_code == 200:
            items = res.json().get("items", [])
            
            if items:
                # 1. Summary Table
                st.subheader("Purchase Order Registry")
                df = pd.DataFrame(items)
                display_df = df[['po_number', 'vendor_name', 'total_amount', 'currency']]
                st.dataframe(display_df, use_container_width=True)

                # 2. Detailed View
                st.subheader("PO Details (JSON)")
                for item in items:
                    with st.expander(f"📄 {item['po_number']} - {item['vendor_name']} (${item['total_amount']})"):
                        st.json(item['details'])
            else:
                st.warning("No Purchase Orders found.")
        else:
            st.error(f"Error fetching data: {res.text}")
            
    except Exception as e:
        st.error(f"Could not connect to backend: {e}") 
#und.")
   