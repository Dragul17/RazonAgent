"""Download UCI Online Retail II and build reconciliation input views.

The source is public transaction data. Gateway, bank, and ledger files are
derived views because the public dataset does not contain private bank or
payment-provider records for the same invoices.
"""

import os
import sys
import zipfile
from collections import defaultdict
from datetime import datetime
from urllib.request import urlopen

import openpyxl
import pandas as pd


BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
SOURCE_URL = "https://archive.ics.uci.edu/static/public/502/online+retail+ii.zip"
ARCHIVE_PATH = os.path.join(DATA_DIR, "online_retail_ii.zip")
SOURCE_XLSX = os.path.join(DATA_DIR, "online_retail_II.xlsx")
MAX_INVOICES = 5000


def download_source():
    if os.path.exists(SOURCE_XLSX):
        return

    print("Downloading UCI Online Retail II...")
    partial_path = ARCHIVE_PATH + ".part"
    with urlopen(SOURCE_URL) as response, open(partial_path, "wb") as output:
        while chunk := response.read(1024 * 1024):
            output.write(chunk)
    with zipfile.ZipFile(partial_path) as archive:
        archive.testzip()
    os.replace(partial_path, ARCHIVE_PATH)

    with zipfile.ZipFile(ARCHIVE_PATH) as archive:
        members = [name for name in archive.namelist() if name.lower().endswith(".xlsx")]
        if not members:
            raise RuntimeError("The UCI archive did not contain an Excel data file.")
        with archive.open(members[0]) as source, open(SOURCE_XLSX, "wb") as output:
            output.write(source.read())


def build_views():
    totals = defaultdict(float)
    invoice_details = {}
    workbook = openpyxl.load_workbook(SOURCE_XLSX, read_only=True, data_only=True)
    try:
        for sheet in workbook.worksheets:
            rows = sheet.iter_rows(values_only=True)
            headers = [str(value).strip() if value is not None else "" for value in next(rows)]
            positions = {name: headers.index(name) for name in ("Invoice", "InvoiceDate", "Quantity", "Price", "Customer ID", "Country")}
            for row in rows:
                invoice = str(row[positions["Invoice"]]).strip()
                invoice_date = row[positions["InvoiceDate"]]
                customer_id = row[positions["Customer ID"]]
                if invoice.upper().startswith("C") or not isinstance(invoice_date, datetime) or customer_id is None:
                    continue
                key = (invoice, invoice_date, str(int(customer_id)), row[positions["Country"]])
                totals[key] += float(row[positions["Quantity"]]) * float(row[positions["Price"]])
                invoice_details[key] = key
    finally:
        workbook.close()

    rows = [
        {"Invoice": key[0], "InvoiceDate": key[1], "Customer ID": key[2], "Country": key[3], "amount": round(amount, 2)}
        for key, amount in totals.items()
        if amount > 0
    ]
    invoices = pd.DataFrame(rows).sort_values("InvoiceDate").head(MAX_INVOICES).reset_index(drop=True)
    invoices["invoice_ref"] = "UCI-" + invoices["Invoice"]
    invoices["transaction_id"] = "uci_" + invoices["Invoice"]
    invoices["settlement_id"] = "setl_" + invoices["Invoice"]
    invoices["customer_ref"] = "customer_" + invoices["Customer ID"].astype(str)

    gateway = pd.DataFrame(
        {
            "txn_id": invoices["transaction_id"],
            "order_id": invoices["Invoice"],
            "amount": invoices["amount"],
            "currency": "GBP",
            "status": "captured",
            "method": "online_retail",
            "created_at": invoices["InvoiceDate"].dt.strftime("%Y-%m-%d %H:%M:%S"),
            "settlement_id": invoices["settlement_id"],
            "customer_ref": invoices["customer_ref"],
        }
    )
    bank = pd.DataFrame(
        {
            "bank_txn_id": "uci_bank_" + invoices["Invoice"],
            "value_date": invoices["InvoiceDate"].dt.strftime("%Y-%m-%d"),
            "narration": "UCI ONLINE RETAIL " + invoices["invoice_ref"],
            "debit": 0.0,
            "credit": invoices["amount"],
            "running_balance": invoices["amount"].cumsum().round(2),
            "utr_number": invoices["settlement_id"],
        }
    )
    ledger = pd.DataFrame(
        {
            "ledger_entry_id": "uci_ledger_" + invoices["Invoice"],
            "invoice_ref": invoices["invoice_ref"],
            "expected_amount": invoices["amount"],
            "customer_name": invoices["customer_ref"],
            "entry_date": invoices["InvoiceDate"].dt.strftime("%Y-%m-%d"),
            "status": "open",
        }
    )
    ground_truth = pd.DataFrame(
        {
            "gateway_id": invoices["transaction_id"],
            "bank_id": "uci_bank_" + invoices["Invoice"],
            "ledger_id": "uci_ledger_" + invoices["Invoice"],
            "match_type": "public_invoice",
            "expected_status": "MATCHED",
        }
    )

    gateway.to_csv(os.path.join(DATA_DIR, "gateway_transactions.csv"), index=False)
    bank.to_csv(os.path.join(DATA_DIR, "bank_statement.csv"), index=False)
    ledger.to_csv(os.path.join(DATA_DIR, "ledger.csv"), index=False)
    ground_truth.to_csv(os.path.join(DATA_DIR, "ground_truth.csv"), index=False)
    print(f"Created reconciliation views for {len(invoices)} public UCI invoices.")


def refresh_ground_truth():
    gateway = pd.read_csv(os.path.join(DATA_DIR, "gateway_transactions.csv"))
    ground_truth = pd.DataFrame(
        {
            "gateway_id": gateway["txn_id"],
            "bank_id": "uci_bank_" + gateway["order_id"].astype(str),
            "ledger_id": "uci_ledger_" + gateway["order_id"].astype(str),
            "match_type": "public_invoice",
            "expected_status": "MATCHED",
        }
    )
    ground_truth.to_csv(os.path.join(DATA_DIR, "ground_truth.csv"), index=False)
    print(f"Refreshed ground truth for {len(ground_truth)} public invoices.")


if __name__ == "__main__":
    if "--ground-truth-only" in sys.argv:
        refresh_ground_truth()
    else:
        download_source()
        build_views()