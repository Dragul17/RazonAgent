import pandas as pd
import sqlite3
import os
import re

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, 'data')
DB_PATH = os.path.join(DATA_DIR, 'recon.db')

def clean_text(text):
    if pd.isna(text):
        return ""
    text = str(text).upper()
    # Strip non-alphanumeric chars for matching
    text = re.sub(r'[^A-Z0-9]', '', text)
    return text

def ingest_data():
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)
        
    conn = sqlite3.connect(DB_PATH)
    
    # Load Gateway
    df_gateway = pd.read_csv(os.path.join(DATA_DIR, "gateway_transactions.csv"))
    df_gateway['created_date'] = pd.to_datetime(df_gateway['created_at']).dt.date
    df_gateway['clean_ref'] = df_gateway['customer_ref'].apply(clean_text)
    df_gateway.to_sql("gateway", conn, index=False, if_exists="replace")
    
    # Load Bank
    df_bank = pd.read_csv(os.path.join(DATA_DIR, "bank_statement.csv"))
    df_bank['value_date'] = pd.to_datetime(df_bank['value_date']).dt.date
    df_bank['clean_narration'] = df_bank['narration'].apply(clean_text)
    df_bank.to_sql("bank", conn, index=False, if_exists="replace")
    
    # Load Ledger
    df_ledger = pd.read_csv(os.path.join(DATA_DIR, "ledger.csv"))
    df_ledger['entry_date'] = pd.to_datetime(df_ledger['entry_date']).dt.date
    df_ledger['clean_inv_ref'] = df_ledger['invoice_ref'].apply(clean_text)
    df_ledger.to_sql("ledger", conn, index=False, if_exists="replace")
    
    # Create Audit Log Table
    conn.execute('''
        CREATE TABLE audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            gateway_id TEXT,
            bank_id TEXT,
            ledger_id TEXT,
            status TEXT,
            reasoning TEXT,
            match_rule TEXT,
            confidence REAL
        )
    ''')
    
    conn.commit()
    conn.close()
    print("Data ingested successfully into SQLite DB.")

if __name__ == "__main__":
    ingest_data()
