import pytest
import pandas as pd
import sqlite3
import os
import sys

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../pipeline')))
from scorer import generate_report

def test_generate_report(tmp_path, monkeypatch):
    test_db = tmp_path / "test.db"
    test_gt = tmp_path / "ground_truth.csv"
    test_report = tmp_path / "metrics_report.md"
    
    monkeypatch.setattr('scorer.DB_PATH', str(test_db))
    monkeypatch.setattr('scorer.GT_PATH', str(test_gt))
    monkeypatch.setattr('scorer.REPORT_PATH', str(test_report))
    
    # Ground truth
    gt_data = [
        {'gateway_id': 'g1', 'bank_id': 'b1', 'ledger_id': 'l1', 'expected_status': 'MATCHED'},
        {'gateway_id': 'g2', 'bank_id': 'b2', 'ledger_id': 'l2', 'expected_status': 'EXCEPTION_TIMING_LAG'}
    ]
    pd.DataFrame(gt_data).to_csv(test_gt, index=False)
    
    conn = sqlite3.connect(test_db)
    # Audit log (perfect match)
    audit_data = [
        {'id': 1, 'gateway_id': 'g1', 'bank_id': 'b1', 'ledger_id': 'l1', 'status': 'MATCHED', 'match_rule': 'Stage 1'},
        {'id': 2, 'gateway_id': 'g2', 'bank_id': 'b2', 'ledger_id': 'l2', 'status': 'EXCEPTION_TIMING_LAG', 'match_rule': 'Stage 3'}
    ]
    pd.DataFrame(audit_data).to_sql("audit_log", conn, index=False)
    conn.close()
    
    # Needs to handle os.makedirs
    monkeypatch.setattr('os.makedirs', lambda *args, **kwargs: None)
    
    generate_report()
    
    assert os.path.exists(test_report)
    with open(test_report, 'r') as f:
        content = f.read()
        assert "Total Ground Truth Records**: 2" in content
        assert "TP**: 1" in content
        assert "TN**: 1" in content
        assert "FP**: 0" in content
        assert "FN**: 0" in content
