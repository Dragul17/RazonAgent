import pytest
import pandas as pd
import sqlite3
import os
import sys

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../pipeline')))
from llm_agent import run_agent


class MockFunctionCall:
    def __init__(self, name, args, id):
        self.name = name
        self.args = args
        self.id = id


class MockPart:
    def __init__(self, function_call=None, text=None):
        self.function_call = function_call
        self.text = text


class MockContent:
    def __init__(self, parts):
        self.parts = parts
        self.role = "model"


class MockCandidate:
    def __init__(self, content):
        self.content = content


class MockResponse:
    def __init__(self, candidates):
        self.candidates = candidates


class MockModels:
    """
    Simulates a two-turn Gemini conversation: first turn the model calls
    propose_match directly, second turn it responds with plain text (no
    more tool calls), which should stop the loop in run_agent().
    """
    def __init__(self):
        self.call_count = 0

    def generate_content(self, model, contents, config):
        self.call_count += 1
        if self.call_count == 1:
            fc = MockFunctionCall(
                name='propose_match',
                args={
                    'gateway_id': 'g1',
                    'bank_id': 'b1',
                    'ledger_id': 'l1',
                    'confidence': 0.95,
                    'reasoning': 'Mocked reasoning.'
                },
                id='mock_tool_id'
            )
            return MockResponse([MockCandidate(MockContent([MockPart(function_call=fc)]))])
        else:
            return MockResponse([MockCandidate(MockContent([MockPart(text="No further matches found.")]))])


class MockClient:
    def __init__(self, **kwargs):
        self.models = MockModels()


def test_llm_agent_mocked(tmp_path, monkeypatch):
    test_db = tmp_path / "test.db"
    monkeypatch.setattr('llm_agent.DB_PATH', str(test_db))
    monkeypatch.setenv("GEMINI_API_KEY", "mock_key")

    conn = sqlite3.connect(test_db)

    # Create tables
    pd.DataFrame([{'txn_id': 'g1', 'amount': 100}]).to_sql("gateway", conn, index=False)
    pd.DataFrame([{'bank_txn_id': 'b1', 'credit': 100}]).to_sql("bank", conn, index=False)
    pd.DataFrame([{'ledger_entry_id': 'l1', 'expected_amount': 100}]).to_sql("ledger", conn, index=False)

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

    monkeypatch.setattr('llm_agent.genai.Client', MockClient)

    run_agent()

    conn = sqlite3.connect(test_db)
    audit = pd.read_sql("SELECT * FROM audit_log", conn)
    conn.close()

    assert len(audit) == 1
    assert audit.iloc[0]['match_rule'] == 'Stage 2: LLM Agent'
    assert audit.iloc[0]['confidence'] == 0.95


def test_llm_agent_rejects_low_confidence_match(tmp_path, monkeypatch):
    """
    A match below MIN_CONFIDENCE must never reach the audit log, even if
    the model proposes it — this is enforced in code, not just prompted.
    """
    test_db = tmp_path / "test_lowconf.db"
    monkeypatch.setattr('llm_agent.DB_PATH', str(test_db))
    monkeypatch.setenv("GEMINI_API_KEY", "mock_key")

    conn = sqlite3.connect(test_db)
    pd.DataFrame([{'txn_id': 'g1', 'amount': 100}]).to_sql("gateway", conn, index=False)
    pd.DataFrame([{'bank_txn_id': 'b1', 'credit': 100}]).to_sql("bank", conn, index=False)
    pd.DataFrame([{'ledger_entry_id': 'l1', 'expected_amount': 100}]).to_sql("ledger", conn, index=False)
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

    class LowConfidenceModels(MockModels):
        def generate_content(self, model, contents, config):
            self.call_count += 1
            if self.call_count == 1:
                fc = MockFunctionCall(
                    name='propose_match',
                    args={
                        'gateway_id': 'g1', 'bank_id': 'b1', 'ledger_id': 'l1',
                        'confidence': 0.4, 'reasoning': 'Weak guess.'
                    },
                    id='mock_tool_id_2'
                )
                return MockResponse([MockCandidate(MockContent([MockPart(function_call=fc)]))])
            return MockResponse([MockCandidate(MockContent([MockPart(text="Stopping.")]))])

    class LowConfidenceClient:
        def __init__(self, **kwargs):
            self.models = LowConfidenceModels()

    monkeypatch.setattr('llm_agent.genai.Client', LowConfidenceClient)

    run_agent()

    conn = sqlite3.connect(test_db)
    audit = pd.read_sql("SELECT * FROM audit_log", conn)
    conn.close()

    assert len(audit) == 0
