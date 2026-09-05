import sqlite3
import pandas as pd
import logging
import os

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE_DIR, 'data', 'recon.db')

def classify_exceptions():
    conn = sqlite3.connect(DB_PATH)
    
    audit = pd.read_sql("SELECT gateway_id, bank_id, ledger_id FROM audit_log", conn)
    
    g_ids = set()
    b_ids = set()
    l_ids = set()
    
    for _, row in audit.iterrows():
        if pd.notna(row['gateway_id']): g_ids.update(str(row['gateway_id']).split('|'))
        if pd.notna(row['bank_id']): b_ids.update(str(row['bank_id']).split('|'))
        if pd.notna(row['ledger_id']): l_ids.update(str(row['ledger_id']).split('|'))
        
    df_g = pd.read_sql("SELECT * FROM gateway", conn)
    df_b = pd.read_sql("SELECT * FROM bank", conn)
    df_l = pd.read_sql("SELECT * FROM ledger", conn)
    
    df_g_unmatched = df_g[~df_g['txn_id'].isin(g_ids)]
    df_b_unmatched = df_b[~df_b['bank_txn_id'].isin(b_ids)]
    df_l_unmatched = df_l[~df_l['ledger_entry_id'].isin(l_ids)]
    
    exceptions = []
    
    # 1. Gateway Only (usually Timing Lag)
    for _, g in df_g_unmatched.iterrows():
        exceptions.append({
            'gateway_id': g['txn_id'],
            'bank_id': None,
            'ledger_id': None,
            'status': 'EXCEPTION_TIMING_LAG',
            'reasoning': 'Gateway transaction captured but not yet settled in bank or booked in ledger.',
            'match_rule': 'Stage 3: Classifier',
            'confidence': 1.0
        })
        
    # 2. Bank Only (Bank Charge or genuine anomaly)
    for _, b in df_b_unmatched.iterrows():
        if b['debit'] > 0 and b['credit'] == 0:
            exceptions.append({
                'gateway_id': None,
                'bank_id': b['bank_txn_id'],
                'ledger_id': None,
                'status': 'EXCEPTION_GENUINE_ANOMALY',
                'reasoning': 'Bank debit/charge with no corresponding gateway or ledger entry.',
                'match_rule': 'Stage 3: Classifier',
                'confidence': 1.0
            })
        else:
            exceptions.append({
                'gateway_id': None,
                'bank_id': b['bank_txn_id'],
                'ledger_id': None,
                'status': 'EXCEPTION_LOW_CONFIDENCE_CANDIDATE',
                'reasoning': 'Unmatched bank credit without clear gateway counterpart.',
                'match_rule': 'Stage 3: Classifier',
                'confidence': 1.0
            })
            
    # 3. Ledger Only (Duplicate or missing payment)
    for _, l in df_l_unmatched.iterrows():
        # Heuristic: check if there's already a matched ledger entry with same invoice ref
        duplicate_check = pd.read_sql(
            '''
            SELECT * FROM ledger
            WHERE invoice_ref = ?
            AND ledger_entry_id != ?
            ''',
            conn,
            params=(l['invoice_ref'], l['ledger_entry_id'])
        )
        
        if not duplicate_check.empty:
            exceptions.append({
                'gateway_id': None,
                'bank_id': None,
                'ledger_id': l['ledger_entry_id'],
                'status': 'EXCEPTION_DUPLICATE_ENTRY',
                'reasoning': 'Duplicate ledger entry found for same invoice reference.',
                'match_rule': 'Stage 3: Classifier',
                'confidence': 1.0
            })
        else:
            exceptions.append({
                'gateway_id': None,
                'bank_id': None,
                'ledger_id': l['ledger_entry_id'],
                'status': 'EXCEPTION_LOW_CONFIDENCE_CANDIDATE',
                'reasoning': 'Open ledger entry with no matching payment found.',
                'match_rule': 'Stage 3: Classifier',
                'confidence': 1.0
            })

    if exceptions:
        exceptions_df = pd.DataFrame(exceptions)
        exceptions_df.to_sql("audit_log", conn, if_exists="append", index=False)
        logger.info(f"Stage 3 completed. Categorized {len(exceptions_df)} exceptions.")
    else:
        logger.info("Stage 3 completed. No exceptions to categorize.")

    conn.commit()
    conn.close()

if __name__ == "__main__":
    classify_exceptions()
