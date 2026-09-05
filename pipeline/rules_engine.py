import pandas as pd
import sqlite3
from rapidfuzz import fuzz
from datetime import timedelta
import logging
import os

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE_DIR, 'data', 'recon.db')

def apply_rules():
    conn = sqlite3.connect(DB_PATH)
    
    df_gateway = pd.read_sql("SELECT * FROM gateway WHERE status='captured'", conn)
    df_bank = pd.read_sql("SELECT * FROM bank", conn)
    df_ledger = pd.read_sql("SELECT * FROM ledger WHERE status='open'", conn)

    # Ledger entries that share the same invoice_ref (i.e. a duplicate
    # booking) are structurally ambiguous: any rule below matching purely on
    # invoice_ref/amount cannot tell which copy is the "real" one without
    # more context. Rather than let whichever rule processes them first make
    # a silent guess (which is how the earlier version of this pipeline
    # produced false-positive reconciliations on exactly this case), we
    # exclude all such entries from Stage 1 matching entirely and let
    # Stage 3's dedicated duplicate-detection logic handle them explicitly.
    # This does cost some recall (the genuinely valid entry among the
    # duplicates will show up as an exception instead of a match), but a
    # missed match that's flagged for review is far safer than a wrong one.
    dup_ref_counts = df_ledger['invoice_ref'].value_counts()
    ambiguous_refs = set(dup_ref_counts[dup_ref_counts > 1].index)
    if ambiguous_refs:
        logger.info(f"Excluding {len(ambiguous_refs)} ambiguous (duplicate) invoice_ref group(s) from Stage 1 matching.")
        df_ledger = df_ledger[~df_ledger['invoice_ref'].isin(ambiguous_refs)]
    
    # We will track which IDs are matched
    matched_gateway = set()
    matched_bank = set()
    matched_ledger = set()
    
    audit_logs = []

    def add_match(g_id, b_id, l_id, rule_name):
        audit_logs.append({
            'gateway_id': g_id,
            'bank_id': b_id,
            'ledger_id': l_id,
            'status': 'MATCHED',
            'reasoning': f"Matched by {rule_name}",
            'match_rule': rule_name,
            'confidence': 1.0
        })
        if g_id: matched_gateway.add(g_id)
        if b_id: matched_bank.add(b_id)
        if l_id: matched_ledger.add(l_id)

    # Convert date strings back to dates for logic
    df_gateway['created_date'] = pd.to_datetime(df_gateway['created_date'])
    df_bank['value_date'] = pd.to_datetime(df_bank['value_date'])
    df_ledger['entry_date'] = pd.to_datetime(df_ledger['entry_date'])

    # RULE 1: Exact Key Match
    # gateway.settlement_id == bank.utr_number and amounts exactly equal
    logger.info("Running Rule 1: Exact Key Match")
    for _, g in df_gateway.iterrows():
        if g['txn_id'] in matched_gateway: continue
        
        # Find matching bank
        b_matches = df_bank[
            (df_bank['utr_number'] == g['settlement_id']) & 
            (df_bank['credit'] == g['amount']) &
            (~df_bank['bank_txn_id'].isin(matched_bank))
        ]
        
        if not b_matches.empty:
            b = b_matches.iloc[0]
            # Now find ledger match (by expected amount and entry date approx)
            l_matches = df_ledger[
                (df_ledger['expected_amount'] == g['amount']) &
                (~df_ledger['ledger_entry_id'].isin(matched_ledger))
            ]
            
            # Refine ledger match by ref if possible
            if not l_matches.empty:
                # Try exact ref match first
                exact_l = l_matches[l_matches['clean_inv_ref'].apply(lambda x: x in str(g['clean_ref']) or x in str(b['clean_narration']))]
                candidates = exact_l if not exact_l.empty else l_matches

                # If more than one ledger entry shares the same invoice ref
                # and amount (e.g. a genuine duplicate ledger entry), do NOT
                # guess which one is correct — that is precisely how a real
                # duplicate slips through unflagged while an unrelated entry
                # gets wrongly matched. Skip so Stage 3's duplicate-entry
                # detection can handle both entries honestly instead.
                if len(candidates) == 1:
                    l = candidates.iloc[0]
                    add_match(g['txn_id'], b['bank_txn_id'], l['ledger_entry_id'], "Rule 1: Exact Key Match")

    # RULE 2: Amount + Date Window
    # amount ± 1, dates within ±5 days
    logger.info("Running Rule 2: Amount + Date Window")
    for _, g in df_gateway.iterrows():
        if g['txn_id'] in matched_gateway: continue
        
        b_matches = df_bank[
            (abs(df_bank['credit'] - g['amount']) <= 1.0) & 
            ((df_bank['value_date'] - g['created_date']).dt.days.abs() <= 5) &
            (~df_bank['bank_txn_id'].isin(matched_bank))
        ]
        
        # If more than one bank record falls inside the tolerance window, the
        # match is ambiguous (e.g. two similar-amount transactions on nearby
        # dates). Blindly taking the first candidate here is exactly how
        # false positives creep into a reconciliation system, so we skip it
        # and leave it for Stage 2 (LLM agent), which has more context (e.g.
        # invoice references) to disambiguate — or Stage 3, which will flag
        # it honestly as a low-confidence exception rather than guessing.
        if len(b_matches) == 1:
            b = b_matches.iloc[0]
            l_matches = df_ledger[
                (abs(df_ledger['expected_amount'] - g['amount']) <= 1.0) &
                ((df_ledger['entry_date'] - g['created_date']).dt.days.abs() <= 5) &
                (~df_ledger['ledger_entry_id'].isin(matched_ledger))
            ]
            if len(l_matches) == 1:
                l = l_matches.iloc[0]
                add_match(g['txn_id'], b['bank_txn_id'], l['ledger_entry_id'], "Rule 2: Amount + Date Window")

    # RULE 3: Normalized Reference Match
    # rapidfuzz token similarity >= 90
    logger.info("Running Rule 3: Normalized Reference Match")
    for _, l in df_ledger.iterrows():
        if l['ledger_entry_id'] in matched_ledger: continue
        
        l_ref = str(l['clean_inv_ref'])
        b_matches = df_bank[~df_bank['bank_txn_id'].isin(matched_bank)]
        
        best_b = None
        best_b_score = 0
        for _, b in b_matches.iterrows():
            score = fuzz.token_set_ratio(l_ref, str(b['clean_narration']))
            if score >= 90 and score > best_b_score:
                best_b_score = score
                best_b = b
                
        if best_b is not None:
            g_matches = df_gateway[~df_gateway['txn_id'].isin(matched_gateway)]
            best_g = None
            best_g_score = 0
            for _, g in g_matches.iterrows():
                score = fuzz.token_set_ratio(l_ref, str(g['clean_ref']))
                if score >= 90 and score > best_g_score:
                    best_g_score = score
                    best_g = g
                    
            if best_g is not None:
                add_match(best_g['txn_id'], best_b['bank_txn_id'], l['ledger_entry_id'], "Rule 3: Normalized Reference Match")

    # RULE 4: Many-to-One Aggregation
    logger.info("Running Rule 4: Many-to-One Aggregation")
    unmatched_g = df_gateway[~df_gateway['txn_id'].isin(matched_gateway)]
    grouped_g = unmatched_g.groupby('settlement_id')['amount'].sum().reset_index()
    
    for _, group in grouped_g.iterrows():
        if group['amount'] == 0: continue
        
        b_matches = df_bank[
            (df_bank['utr_number'] == group['settlement_id']) &
            (abs(df_bank['credit'] - group['amount']) <= 1.0) &
            (~df_bank['bank_txn_id'].isin(matched_bank))
        ]
        
        if not b_matches.empty:
            b = b_matches.iloc[0]
            # Find the individual gateway txns
            gtw_txns = unmatched_g[unmatched_g['settlement_id'] == group['settlement_id']]
            gtw_ids = gtw_txns['txn_id'].tolist()
            
            # Try to find corresponding ledger entries
            ldg_ids = []
            for _, g in gtw_txns.iterrows():
                l_matches = df_ledger[
                    (df_ledger['expected_amount'] == g['amount']) &
                    (~df_ledger['ledger_entry_id'].isin(matched_ledger)) &
                    (~df_ledger['ledger_entry_id'].isin(ldg_ids))
                ]
                if not l_matches.empty:
                    ldg_ids.append(l_matches.iloc[0]['ledger_entry_id'])
            
            if len(ldg_ids) > 0:
                add_match("|".join(gtw_ids), b['bank_txn_id'], "|".join(ldg_ids), "Rule 4: Many-to-One Aggregation")
                for g_id in gtw_ids: matched_gateway.add(g_id)
                for l_id in ldg_ids: matched_ledger.add(l_id)
                matched_bank.add(b['bank_txn_id'])

    # Write Audit Logs
    audit_df = pd.DataFrame(audit_logs)
    if not audit_df.empty:
        audit_df.to_sql("audit_log", conn, if_exists="append", index=False)
        
    conn.commit()
    conn.close()
    
    logger.info(f"Stage 1 completed. Generated {len(audit_df)} matches.")
    
if __name__ == "__main__":
    apply_rules()
