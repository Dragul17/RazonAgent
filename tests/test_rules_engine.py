import pytest
import pandas as pd
import sqlite3
import os
import sys

# Add pipeline directory to path so we can import modules
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../pipeline')))
from ingestion import ingest_data
from rules_engine import apply_rules

def test_exact_key_match(tmp_path, monkeypatch):
    # We will mock the DB_PATH to use a temp db
    test_db = tmp_path / "test.db"
    monkeypatch.setattr('ingestion.DB_PATH', str(test_db))
    monkeypatch.setattr('rules_engine.DB_PATH', str(test_db))
    monkeypatch.setattr('ingestion.DATA_DIR', str(tmp_path))
    
    # Create mock data
    g_data = [{'txn_id': 'g1', 'order_id': 'o1', 'amount': 100, 'customer_ref': 'C1', 'created_at': '2023-01-01 10:00:00', 'settlement_id': 'S1', 'status': 'captured'}]
    b_data = [{'bank_txn_id': 'b1', 'value_date': '2023-01-02', 'narration': 'SETL-S1', 'credit': 100, 'utr_number': 'S1'}]
    l_data = [{'ledger_entry_id': 'l1', 'invoice_ref': 'INV1', 'expected_amount': 100, 'entry_date': '2023-01-01', 'status': 'open'}]
    
    pd.DataFrame(g_data).to_csv(tmp_path / "gateway_transactions.csv", index=False)
    pd.DataFrame(b_data).to_csv(tmp_path / "bank_statement.csv", index=False)
    pd.DataFrame(l_data).to_csv(tmp_path / "ledger.csv", index=False)
    
    # Mock file paths
    monkeypatch.setattr('builtins.open', lambda f, *args, **kwargs: open(tmp_path / f.split('/')[-1], *args, **kwargs))
    # Wait, simple way is to temporarily chdir to tmp_path or just patch the string in ingest_data
    # Actually ingest_data hardcodes 'data/gateway_transactions.csv'
    # For a unit test, it's easier to just create the sqlite db directly
    
    conn = sqlite3.connect(test_db)
    df_g = pd.DataFrame(g_data)
    df_g['created_date'] = pd.to_datetime(df_g['created_at']).dt.date
    df_g['clean_ref'] = 'C1'
    df_g.to_sql("gateway", conn, index=False)
    
    df_b = pd.DataFrame(b_data)
    df_b['value_date'] = pd.to_datetime(df_b['value_date']).dt.date
    df_b['clean_narration'] = 'SETLS1'
    df_b.to_sql("bank", conn, index=False)
    
    df_l = pd.DataFrame(l_data)
    df_l['entry_date'] = pd.to_datetime(df_l['entry_date']).dt.date
    df_l['clean_inv_ref'] = 'INV1'
    df_l.to_sql("ledger", conn, index=False)
    
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
    conn.close()
    
    apply_rules()
    
    conn = sqlite3.connect(test_db)
    audit = pd.read_sql("SELECT * FROM audit_log", conn)
    conn.close()
    
    assert len(audit) == 1
    assert audit.iloc[0]['match_rule'] == 'Rule 1: Exact Key Match'
    assert audit.iloc[0]['gateway_id'] == 'g1'


def test_duplicate_invoice_ref_is_never_auto_matched(tmp_path, monkeypatch):
    """
    Regression test for the false-positive bug: two ledger entries sharing
    the same invoice_ref (a duplicate booking) must NOT be silently matched
    by Stage 1, since there is no way to know which one is genuine without
    more context. Both must be left for Stage 3 to flag explicitly.
    """
    test_db = tmp_path / "test_dup.db"
    monkeypatch.setattr('rules_engine.DB_PATH', str(test_db))

    conn = sqlite3.connect(test_db)

    g_data = [{'txn_id': 'g1', 'order_id': 'o1', 'amount': 500, 'customer_ref': 'CustDup',
               'created_at': '2023-01-01 10:00:00', 'settlement_id': 'S1', 'status': 'captured'}]
    b_data = [{'bank_txn_id': 'b1', 'value_date': '2023-01-02', 'narration': 'SETL-S1-INV1',
               'credit': 500, 'utr_number': 'S1'}]
    # Two ledger entries with the SAME invoice_ref/amount — a duplicate booking.
    l_data = [
        {'ledger_entry_id': 'l1', 'invoice_ref': 'INV1', 'expected_amount': 500,
         'entry_date': '2023-01-01', 'status': 'open'},
        {'ledger_entry_id': 'l2', 'invoice_ref': 'INV1', 'expected_amount': 500,
         'entry_date': '2023-01-01', 'status': 'open'},
    ]

    df_g = pd.DataFrame(g_data)
    df_g['created_date'] = pd.to_datetime(df_g['created_at']).dt.date
    df_g['clean_ref'] = 'CUSTDUP'
    df_g.to_sql("gateway", conn, index=False)

    df_b = pd.DataFrame(b_data)
    df_b['value_date'] = pd.to_datetime(df_b['value_date']).dt.date
    df_b['clean_narration'] = 'SETLS1INV1'
    df_b.to_sql("bank", conn, index=False)

    df_l = pd.DataFrame(l_data)
    df_l['entry_date'] = pd.to_datetime(df_l['entry_date']).dt.date
    df_l['clean_inv_ref'] = 'INV1'
    df_l.to_sql("ledger", conn, index=False)

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
    conn.close()

    apply_rules()

    conn = sqlite3.connect(test_db)
    audit = pd.read_sql("SELECT * FROM audit_log", conn)
    conn.close()

    # No rule should have guessed between l1 and l2 — Stage 1 must produce
    # zero matches here, leaving both ledger entries for Stage 3.
    assert len(audit) == 0
