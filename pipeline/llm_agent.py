import os
import sqlite3
import pandas as pd
import json
import logging
from rapidfuzz import fuzz
from dotenv import load_dotenv
from google import genai
from google.genai import types

# Load GEMINI_API_KEY (and any other vars) from a .env file if present.
# Without this, os.environ.get("GEMINI_API_KEY") below would never see a
# key placed in .env, and Stage 2 would silently no-op on every run.
load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Minimum confidence the agent must report before a match is written to the
# audit log. This is enforced in code, not just requested in the prompt —
# we never trust the model's own compliance with instructions for something
# that touches financial records.
MIN_CONFIDENCE = 0.8

# Hard cap on tool-calling turns per transaction, so a confused model can
# never loop indefinitely and run up cost/latency on a single record.
MAX_TURNS = 4

MODEL_NAME = "gemini-2.5-flash"

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE_DIR, 'data', 'recon.db')


def get_unmatched_records(conn):
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

    df_g = df_g[~df_g['txn_id'].isin(g_ids)].where(pd.notnull(df_g), None)
    df_b = df_b[~df_b['bank_txn_id'].isin(b_ids)].where(pd.notnull(df_b), None)
    df_l = df_l[~df_l['ledger_entry_id'].isin(l_ids)].where(pd.notnull(df_l), None)

    return df_g, df_b, df_l


def search_ledger_by_fuzzy_ref(text, df_l):
    if pd.isna(text):
        return "[]"
    text = str(text)
    candidates = []
    for _, l in df_l.iterrows():
        score = fuzz.token_set_ratio(text, str(l['clean_inv_ref']))
        if score > 70:
            candidates.append(l.to_dict())
    return json.dumps(candidates[:3])  # Top 3


def get_candidate_matches(txn, df_b, df_l):
    # Simple logic to find records with similar amount/date
    amount = txn.get('amount', 0)
    candidates = {}

    # Bank candidates
    b_cands = df_b[
        (abs(df_b['credit'] - amount) <= amount * 0.05)  # 5% tolerance
    ]
    candidates['bank_candidates'] = b_cands.head(3).to_dict(orient='records')

    # Ledger candidates
    l_cands = df_l[
        (abs(df_l['expected_amount'] - amount) <= amount * 0.05)
    ]
    candidates['ledger_candidates'] = l_cands.head(3).to_dict(orient='records')

    return json.dumps(candidates)


def _record_proposed_match(audit_logs, match_input):
    """
    Validate and record a proposed match. This is the single enforcement
    point for MIN_CONFIDENCE — the agent's own compliance with the system
    prompt is never trusted on its own for a financial write.
    """
    confidence = match_input.get('confidence')
    try:
        confidence = float(confidence)
    except (TypeError, ValueError):
        logger.warning(f"Rejected proposed match with non-numeric confidence: {match_input}")
        return "REJECTED: confidence must be a number."

    if confidence < MIN_CONFIDENCE:
        logger.info(
            f"Rejected low-confidence match ({confidence:.2f} < {MIN_CONFIDENCE}) "
            f"for gateway_id={match_input.get('gateway_id')}"
        )
        return f"REJECTED: confidence {confidence:.2f} is below the required minimum of {MIN_CONFIDENCE}."

    audit_logs.append({
        'gateway_id': match_input.get('gateway_id'),
        'bank_id': match_input.get('bank_id'),
        'ledger_id': match_input.get('ledger_id'),
        'status': 'MATCHED',
        'reasoning': match_input.get('reasoning'),
        'match_rule': 'Stage 2: LLM Agent',
        'confidence': confidence
    })
    return "RECORDED: match written to the audit log."


# --- Gemini function declarations (OpenAPI-subset schema dicts) ---

SEARCH_LEDGER_DECLARATION = {
    "name": "search_ledger_by_fuzzy_ref",
    "description": "Search the ledger for candidate invoices by fuzzy reference string.",
    "parameters": {
        "type": "object",
        "properties": {
            "text": {"type": "string", "description": "Reference string to search"}
        },
        "required": ["text"]
    }
}

GET_CANDIDATE_MATCHES_DECLARATION = {
    "name": "get_candidate_matches",
    "description": "Get potential bank and ledger matches based on amount/date proximity for a given transaction.",
    "parameters": {
        "type": "object",
        "properties": {
            "txn_json": {"type": "string", "description": "JSON string of the transaction"}
        },
        "required": ["txn_json"]
    }
}

PROPOSE_MATCH_DECLARATION = {
    "name": "propose_match",
    "description": "Propose a match between a gateway transaction, bank transaction, and ledger entry. Only call this once you are confident; it does not modify any records directly, it only logs a proposal for audit.",
    "parameters": {
        "type": "object",
        "properties": {
            "gateway_id": {"type": "string"},
            "bank_id": {"type": "string"},
            "ledger_id": {"type": "string"},
            "confidence": {"type": "number", "description": "Confidence score 0.0-1.0"},
            "reasoning": {"type": "string", "description": "One sentence reasoning"}
        },
        "required": ["gateway_id", "confidence", "reasoning"]
    }
}

SYSTEM_PROMPT = """You are an AI financial reconciliation agent.
Your job is to evaluate unmatched payment gateway transactions and find corresponding bank statements and ledger entries.
Use the provided tools to search for candidates.
Rules:
- Only propose a match when justified.
- If you cannot find a confident match, simply stop calling tools and explain briefly in text — do not force a guess.
- Explicitly flag suspected split/partial payments in your reasoning.
- Never invent data that wasn't returned by a tool.
- Never propose a match below 0.8 confidence; propose_match will reject it anyway, so don't waste a turn on it.
"""


def _dispatch_tool_call(name, args, df_l, df_b, audit_logs):
    """Execute a single tool call and return its string result for the model."""
    if name == "search_ledger_by_fuzzy_ref":
        return search_ledger_by_fuzzy_ref(args.get('text', ''), df_l)
    elif name == "get_candidate_matches":
        txn_json_str = args.get('txn_json', '{}')
        try:
            txn_data = json.loads(txn_json_str)
        except (TypeError, json.JSONDecodeError):
            txn_data = {}
        return get_candidate_matches(txn_data, df_b, df_l)
    elif name == "propose_match":
        return _record_proposed_match(audit_logs, args)
    else:
        return f"ERROR: unknown tool '{name}'"


def run_agent():
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        logger.warning("No GEMINI_API_KEY found. Skipping Stage 2 (LLM Agent).")
        return

    client = genai.Client(api_key=api_key)
    conn = sqlite3.connect(DB_PATH)

    df_g, df_b, df_l = get_unmatched_records(conn)
    if df_g.empty:
        logger.info("No unmatched gateway records for LLM.")
        conn.close()
        return

    audit_logs = []

    tools = [types.Tool(function_declarations=[
        SEARCH_LEDGER_DECLARATION,
        GET_CANDIDATE_MATCHES_DECLARATION,
        PROPOSE_MATCH_DECLARATION,
    ])]
    # We handle each tool call ourselves (rather than the SDK's automatic
    # function calling) so MIN_CONFIDENCE and the audit log stay under our
    # explicit control.
    config = types.GenerateContentConfig(
        system_instruction=SYSTEM_PROMPT,
        tools=tools,
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        temperature=0,
    )

    for _, txn in df_g.iterrows():
        txn_dict = txn.to_dict()
        prompt = f"Find matches for this transaction: {json.dumps(txn_dict)}"
        contents = [types.Content(role="user", parts=[types.Part(text=prompt)])]

        try:
            for _turn in range(MAX_TURNS):
                response = client.models.generate_content(
                    model=MODEL_NAME,
                    contents=contents,
                    config=config,
                )

                candidate = response.candidates[0] if response.candidates else None
                if candidate is None or not candidate.content or not candidate.content.parts:
                    break

                function_calls = [p.function_call for p in candidate.content.parts if p.function_call]

                if not function_calls:
                    # Model responded with plain text (e.g. "no confident
                    # match found") instead of calling a tool — nothing more
                    # to do for this transaction.
                    break

                # Echo the model's turn back into the conversation, then
                # append one function_response per function_call it made
                # (handles both a single call and parallel calls in one turn).
                contents.append(candidate.content)
                response_parts = []
                for fc in function_calls:
                    result = _dispatch_tool_call(fc.name, dict(fc.args or {}), df_l, df_b, audit_logs)
                    response_parts.append(
                        types.Part.from_function_response(
                            name=fc.name,
                            response={"result": result},
                            id=fc.id,
                        )
                    )
                contents.append(types.Content(role="user", parts=response_parts))
        except Exception as e:
            logger.error(f"LLM Error on txn {txn_dict.get('txn_id')}: {e}")

    if audit_logs:
        audit_df = pd.DataFrame(audit_logs)
        audit_df.to_sql("audit_log", conn, if_exists="append", index=False)
        logger.info(f"Stage 2 completed. LLM generated {len(audit_df)} matches.")
    else:
        logger.info("Stage 2 completed. LLM generated 0 matches.")

    conn.commit()
    conn.close()


if __name__ == "__main__":
    run_agent()
