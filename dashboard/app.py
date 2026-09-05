import streamlit as st
import pandas as pd
import sqlite3
import os
import subprocess
import sys

st.set_page_config(page_title="RazonAgent Dashboard", layout="wide")

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE_DIR, "data", "recon.db")
REPORT_PATH = os.path.join(BASE_DIR, "eval", "metrics_report.md")

def load_data():
    if not os.path.exists(DB_PATH):
        return None, None
    conn = sqlite3.connect(DB_PATH)
    try:
        audit_df = pd.read_sql("SELECT * FROM audit_log", conn)
    except:
        audit_df = pd.DataFrame()
    conn.close()
    
    if not audit_df.empty:
        matches = audit_df[audit_df['status'] == 'MATCHED']
        exceptions = audit_df[audit_df['status'].str.startswith('EXCEPTION')]
        return matches, exceptions
    return pd.DataFrame(), pd.DataFrame()

st.title("🏦 RazonAgent: AI Reconciliation Dashboard")

st.markdown("---")

col1, col2 = st.columns([1, 4])
with col1:
    if st.button("🚀 Run Full Pipeline", use_container_width=True):
        with st.spinner("Running pipeline..."):
            pipeline_script = os.path.join(BASE_DIR, "pipeline", "run_pipeline.py")
            result = subprocess.run([sys.executable, pipeline_script], capture_output=True, text=True)
            if result.returncode == 0:
                st.success("Pipeline completed successfully!")
            else:
                st.error("Pipeline encountered an error.")
                st.code(result.stderr)

matches, exceptions = load_data()

tab1, tab2, tab3, tab4 = st.tabs(["Metrics Report", "Matched Records", "Exceptions", "Audit Trail Explorer"])

with tab1:
    st.header("Evaluation Metrics")
    if os.path.exists(REPORT_PATH):
        with open(REPORT_PATH, "r") as f:
            report_content = f.read()
        st.markdown(report_content)
    else:
        st.info("Run the pipeline to generate metrics.")

with tab2:
    st.header("Matched Records")
    if matches is not None and not matches.empty:
        st.dataframe(matches[['gateway_id', 'bank_id', 'ledger_id', 'match_rule', 'reasoning', 'confidence']], use_container_width=True)
    else:
        st.info("No matches found.")

with tab3:
    st.header("Exceptions")
    if exceptions is not None and not exceptions.empty:
        st.dataframe(exceptions[['status', 'reasoning', 'match_rule', 'bank_id', 'gateway_id', 'ledger_id']], use_container_width=True)
    else:
        st.info("No exceptions found.")

with tab4:
    st.header("Audit Trail Explorer")
    if matches is not None and not (matches.empty and exceptions.empty):
        all_logs = pd.concat([matches, exceptions])
        selected_id = st.selectbox("Select an Audit ID to inspect:", all_logs['id'].tolist())
        
        if selected_id:
            record = all_logs[all_logs['id'] == selected_id].iloc[0]
            st.subheader(f"Record {selected_id} details")
            st.json(record.to_dict())
            
            st.markdown("### Raw Source Data")
            conn = sqlite3.connect(DB_PATH)
            
            col_g, col_b, col_l = st.columns(3)
            with col_g:
                st.write("**Gateway**")
                if pd.notna(record['gateway_id']):
                    ids = str(record['gateway_id']).split('|')
                    placeholders = ','.join('?' * len(ids))
                    g_data = pd.read_sql(f"SELECT * FROM gateway WHERE txn_id IN ({placeholders})", conn, params=ids)
                    st.dataframe(g_data)
                else:
                    st.write("None")
                    
            with col_b:
                st.write("**Bank**")
                if pd.notna(record['bank_id']):
                    ids = str(record['bank_id']).split('|')
                    placeholders = ','.join('?' * len(ids))
                    b_data = pd.read_sql(f"SELECT * FROM bank WHERE bank_txn_id IN ({placeholders})", conn, params=ids)
                    st.dataframe(b_data)
                else:
                    st.write("None")
                    
            with col_l:
                st.write("**Ledger**")
                if pd.notna(record['ledger_id']):
                    ids = str(record['ledger_id']).split('|')
                    placeholders = ','.join('?' * len(ids))
                    l_data = pd.read_sql(f"SELECT * FROM ledger WHERE ledger_entry_id IN ({placeholders})", conn, params=ids)
                    st.dataframe(l_data)
                else:
                    st.write("None")
                    
            conn.close()
    else:
        st.info("No audit logs available.")
