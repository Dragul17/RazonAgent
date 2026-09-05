import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import random
import uuid
import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, 'data')

def generate_id(prefix):
    return f"{prefix}_{uuid.uuid4().hex[:8]}"

def random_date(start, end):
    return start + timedelta(seconds=random.randint(0, int((end - start).total_seconds())))

def add_business_days(from_date, add_days):
    business_days_to_add = add_days
    current_date = from_date
    while business_days_to_add > 0:
        current_date += timedelta(days=1)
        if current_date.weekday() < 5: # Monday-Friday
            business_days_to_add -= 1
    return current_date

def generate_data(num_base_records=300):
    gateway_data = []
    bank_data = []
    ledger_data = []
    ground_truth = []
    
    start_date = datetime(2023, 1, 1)
    end_date = datetime(2023, 12, 1)
    
    # 50% exact, 10% amount, 10% timing, 10% many-to-one, 5% one-to-many, 10% ref, 5% anomalies
    dist = {
        'exact': int(num_base_records * 0.50),
        'amount_mismatch': int(num_base_records * 0.10),
        'timing_mismatch': int(num_base_records * 0.10),
        'many_to_one': int(num_base_records * 0.10),
        'one_to_many': int(num_base_records * 0.05),
        'ref_mismatch': int(num_base_records * 0.10),
        'anomalies': int(num_base_records * 0.05)
    }
    
    running_balance = 100000.0
    
    for _ in range(dist['exact']):
        amount = round(random.uniform(100, 5000), 2)
        txn_date = random_date(start_date, end_date)
        bank_date = add_business_days(txn_date, 1)
        
        gtw_id = generate_id('gtw')
        bank_id = generate_id('bnk')
        ldg_id = generate_id('ldg')
        order_id = generate_id('ord')
        settlement_id = generate_id('setl')
        inv_ref = f"INV{random.randint(10000, 99999)}"
        cust = f"Cust_{random.randint(1, 1000)}"
        
        gateway_data.append({
            'txn_id': gtw_id, 'order_id': order_id, 'amount': amount, 'currency': 'INR',
            'status': 'captured', 'method': 'card', 'created_at': txn_date.strftime('%Y-%m-%d %H:%M:%S'),
            'settlement_id': settlement_id, 'customer_ref': cust
        })
        
        narration = f"NEFT-RAZORP-SETL-{settlement_id}-{inv_ref}"
        running_balance += amount
        bank_data.append({
            'bank_txn_id': bank_id, 'value_date': bank_date.strftime('%Y-%m-%d'),
            'narration': narration, 'debit': 0.0, 'credit': amount, 'running_balance': running_balance,
            'utr_number': settlement_id
        })
        
        ledger_data.append({
            'ledger_entry_id': ldg_id, 'invoice_ref': inv_ref, 'expected_amount': amount,
            'customer_name': cust, 'entry_date': txn_date.strftime('%Y-%m-%d'), 'status': 'open'
        })
        
        ground_truth.append({
            'gateway_id': gtw_id, 'bank_id': bank_id, 'ledger_id': ldg_id,
            'match_type': 'exact', 'expected_status': 'MATCHED'
        })

    for _ in range(dist['amount_mismatch']):
        amount = round(random.uniform(100, 5000), 2)
        # Bank amount has fee deducted (e.g. 1%)
        bank_amount = round(amount * 0.99, 2)
        txn_date = random_date(start_date, end_date)
        bank_date = add_business_days(txn_date, 1)
        
        gtw_id = generate_id('gtw')
        bank_id = generate_id('bnk')
        ldg_id = generate_id('ldg')
        settlement_id = generate_id('setl')
        inv_ref = f"INV{random.randint(10000, 99999)}"
        cust = f"Cust_{random.randint(1, 1000)}"
        
        gateway_data.append({
            'txn_id': gtw_id, 'order_id': generate_id('ord'), 'amount': amount, 'currency': 'INR',
            'status': 'captured', 'method': 'upi', 'created_at': txn_date.strftime('%Y-%m-%d %H:%M:%S'),
            'settlement_id': settlement_id, 'customer_ref': cust
        })
        
        running_balance += bank_amount
        bank_data.append({
            'bank_txn_id': bank_id, 'value_date': bank_date.strftime('%Y-%m-%d'),
            'narration': f"IMPS-RAZORP-SETL-{settlement_id}-{inv_ref}", 'debit': 0.0, 'credit': bank_amount,
            'running_balance': running_balance, 'utr_number': settlement_id
        })
        
        ledger_data.append({
            'ledger_entry_id': ldg_id, 'invoice_ref': inv_ref, 'expected_amount': amount,
            'customer_name': cust, 'entry_date': txn_date.strftime('%Y-%m-%d'), 'status': 'open'
        })
        
        ground_truth.append({
            'gateway_id': gtw_id, 'bank_id': bank_id, 'ledger_id': ldg_id,
            'match_type': 'amount_mismatch', 'expected_status': 'MATCHED'
        })

    for _ in range(dist['timing_mismatch']):
        amount = round(random.uniform(100, 5000), 2)
        txn_date = random_date(start_date, end_date)
        bank_date = add_business_days(txn_date, random.randint(3, 6)) # T+3 to T+6
        
        gtw_id = generate_id('gtw')
        bank_id = generate_id('bnk')
        ldg_id = generate_id('ldg')
        settlement_id = generate_id('setl')
        inv_ref = f"INV{random.randint(10000, 99999)}"
        cust = f"Cust_{random.randint(1, 1000)}"
        
        gateway_data.append({
            'txn_id': gtw_id, 'order_id': generate_id('ord'), 'amount': amount, 'currency': 'INR',
            'status': 'captured', 'method': 'netbanking', 'created_at': txn_date.strftime('%Y-%m-%d %H:%M:%S'),
            'settlement_id': settlement_id, 'customer_ref': cust
        })
        
        running_balance += amount
        bank_data.append({
            'bank_txn_id': bank_id, 'value_date': bank_date.strftime('%Y-%m-%d'),
            'narration': f"RTGS-RAZORP-{settlement_id}-{inv_ref}", 'debit': 0.0, 'credit': amount,
            'running_balance': running_balance, 'utr_number': settlement_id
        })
        
        ledger_data.append({
            'ledger_entry_id': ldg_id, 'invoice_ref': inv_ref, 'expected_amount': amount,
            'customer_name': cust, 'entry_date': txn_date.strftime('%Y-%m-%d'), 'status': 'open'
        })
        
        ground_truth.append({
            'gateway_id': gtw_id, 'bank_id': bank_id, 'ledger_id': ldg_id,
            'match_type': 'timing_mismatch', 'expected_status': 'MATCHED'
        })

    for _ in range(dist['many_to_one']):
        num_txns = random.randint(2, 5)
        amounts = [round(random.uniform(50, 1000), 2) for _ in range(num_txns)]
        total_amount = round(sum(amounts), 2)
        txn_date = random_date(start_date, end_date)
        bank_date = add_business_days(txn_date, 1)
        
        settlement_id = generate_id('setl')
        bank_id = generate_id('bnk')
        
        gtw_ids = []
        ldg_ids = []
        
        for amt in amounts:
            gtw_id = generate_id('gtw')
            ldg_id = generate_id('ldg')
            inv_ref = f"INV{random.randint(10000, 99999)}"
            cust = f"Cust_{random.randint(1, 1000)}"
            
            gateway_data.append({
                'txn_id': gtw_id, 'order_id': generate_id('ord'), 'amount': amt, 'currency': 'INR',
                'status': 'captured', 'method': 'card', 'created_at': txn_date.strftime('%Y-%m-%d %H:%M:%S'),
                'settlement_id': settlement_id, 'customer_ref': cust
            })
            
            ledger_data.append({
                'ledger_entry_id': ldg_id, 'invoice_ref': inv_ref, 'expected_amount': amt,
                'customer_name': cust, 'entry_date': txn_date.strftime('%Y-%m-%d'), 'status': 'open'
            })
            gtw_ids.append(gtw_id)
            ldg_ids.append(ldg_id)
            
        running_balance += total_amount
        bank_data.append({
            'bank_txn_id': bank_id, 'value_date': bank_date.strftime('%Y-%m-%d'),
            'narration': f"BULK-SETL-{settlement_id}", 'debit': 0.0, 'credit': total_amount,
            'running_balance': running_balance, 'utr_number': settlement_id
        })
        
        ground_truth.append({
            'gateway_id': "|".join(gtw_ids), 'bank_id': bank_id, 'ledger_id': "|".join(ldg_ids),
            'match_type': 'many_to_one', 'expected_status': 'MATCHED'
        })
        
    for _ in range(dist['one_to_many']):
        num_txns = random.randint(2, 3)
        total_amount = round(random.uniform(1000, 5000), 2)
        amounts = [round(total_amount / num_txns, 2)] * num_txns
        amounts[-1] = round(total_amount - sum(amounts[:-1]), 2)
        
        txn_date = random_date(start_date, end_date)
        ldg_id = generate_id('ldg')
        inv_ref = f"INV{random.randint(10000, 99999)}"
        cust = f"Cust_{random.randint(1, 1000)}"
        
        ledger_data.append({
            'ledger_entry_id': ldg_id, 'invoice_ref': inv_ref, 'expected_amount': total_amount,
            'customer_name': cust, 'entry_date': txn_date.strftime('%Y-%m-%d'), 'status': 'open'
        })
        
        gtw_ids = []
        bank_ids = []
        
        for amt in amounts:
            gtw_id = generate_id('gtw')
            bank_id = generate_id('bnk')
            settlement_id = generate_id('setl')
            bank_date = add_business_days(txn_date, random.randint(1, 3))
            
            gateway_data.append({
                'txn_id': gtw_id, 'order_id': generate_id('ord'), 'amount': amt, 'currency': 'INR',
                'status': 'captured', 'method': 'card', 'created_at': txn_date.strftime('%Y-%m-%d %H:%M:%S'),
                'settlement_id': settlement_id, 'customer_ref': cust
            })
            
            running_balance += amt
            bank_data.append({
                'bank_txn_id': bank_id, 'value_date': bank_date.strftime('%Y-%m-%d'),
                'narration': f"PART-PAY-{settlement_id}-{inv_ref}", 'debit': 0.0, 'credit': amt,
                'running_balance': running_balance, 'utr_number': settlement_id
            })
            gtw_ids.append(gtw_id)
            bank_ids.append(bank_id)
            
        ground_truth.append({
            'gateway_id': "|".join(gtw_ids), 'bank_id': "|".join(bank_ids), 'ledger_id': ldg_id,
            'match_type': 'one_to_many', 'expected_status': 'MATCHED'
        })

    for _ in range(dist['ref_mismatch']):
        amount = round(random.uniform(100, 5000), 2)
        txn_date = random_date(start_date, end_date)
        bank_date = add_business_days(txn_date, 1)
        
        gtw_id = generate_id('gtw')
        bank_id = generate_id('bnk')
        ldg_id = generate_id('ldg')
        settlement_id = generate_id('setl')
        inv_base = random.randint(10000, 99999)
        inv_ref = f"INV{inv_base}"
        
        # Variations
        variations = [f"Invoice #{inv_base}", f"{inv_base}", f"inv {inv_base}", f"REF:INV-{inv_base}"]
        messy_ref = random.choice(variations)
        cust = f"Cust_{random.randint(1, 1000)}"
        
        gateway_data.append({
            'txn_id': gtw_id, 'order_id': generate_id('ord'), 'amount': amount, 'currency': 'INR',
            'status': 'captured', 'method': 'upi', 'created_at': txn_date.strftime('%Y-%m-%d %H:%M:%S'),
            'settlement_id': settlement_id, 'customer_ref': cust
        })
        
        running_balance += amount
        bank_data.append({
            'bank_txn_id': bank_id, 'value_date': bank_date.strftime('%Y-%m-%d'),
            'narration': f"PAYMENT {messy_ref} {settlement_id}", 'debit': 0.0, 'credit': amount,
            'running_balance': running_balance, 'utr_number': settlement_id
        })
        
        ledger_data.append({
            'ledger_entry_id': ldg_id, 'invoice_ref': inv_ref, 'expected_amount': amount,
            'customer_name': cust, 'entry_date': txn_date.strftime('%Y-%m-%d'), 'status': 'open'
        })
        
        ground_truth.append({
            'gateway_id': gtw_id, 'bank_id': bank_id, 'ledger_id': ldg_id,
            'match_type': 'ref_mismatch', 'expected_status': 'MATCHED'
        })

    # Anomalies
    for _ in range(dist['anomalies']):
        anomaly_type = random.choice(['bank_charge', 'gateway_only', 'duplicate_ledger'])
        txn_date = random_date(start_date, end_date)
        
        if anomaly_type == 'bank_charge':
            amount = round(random.uniform(5, 50), 2)
            bank_id = generate_id('bnk')
            running_balance -= amount
            bank_data.append({
                'bank_txn_id': bank_id, 'value_date': txn_date.strftime('%Y-%m-%d'),
                'narration': "MONTHLY MAINTENANCE CHARGE", 'debit': amount, 'credit': 0.0,
                'running_balance': running_balance, 'utr_number': None
            })
            ground_truth.append({
                'gateway_id': None, 'bank_id': bank_id, 'ledger_id': None,
                'match_type': 'bank_charge', 'expected_status': 'EXCEPTION_GENUINE_ANOMALY'
            })
            
        elif anomaly_type == 'gateway_only':
            amount = round(random.uniform(100, 5000), 2)
            gtw_id = generate_id('gtw')
            settlement_id = generate_id('setl')
            gateway_data.append({
                'txn_id': gtw_id, 'order_id': generate_id('ord'), 'amount': amount, 'currency': 'INR',
                'status': 'captured', 'method': 'card', 'created_at': txn_date.strftime('%Y-%m-%d %H:%M:%S'),
                'settlement_id': settlement_id, 'customer_ref': "Unknown"
            })
            ground_truth.append({
                'gateway_id': gtw_id, 'bank_id': None, 'ledger_id': None,
                'match_type': 'gateway_only', 'expected_status': 'EXCEPTION_TIMING_LAG'
            })
            
        elif anomaly_type == 'duplicate_ledger':
            amount = round(random.uniform(100, 5000), 2)
            ldg_id = generate_id('ldg')
            inv_ref = f"INV{random.randint(10000, 99999)}"
            ledger_data.append({
                'ledger_entry_id': ldg_id, 'invoice_ref': inv_ref, 'expected_amount': amount,
                'customer_name': "Cust_Dup", 'entry_date': txn_date.strftime('%Y-%m-%d'), 'status': 'open'
            })
            ldg_id_2 = generate_id('ldg')
            ledger_data.append({
                'ledger_entry_id': ldg_id_2, 'invoice_ref': inv_ref, 'expected_amount': amount,
                'customer_name': "Cust_Dup", 'entry_date': txn_date.strftime('%Y-%m-%d'), 'status': 'open'
            })
            # Also insert matching bank/gateway for ONE of them
            gtw_id = generate_id('gtw')
            bank_id = generate_id('bnk')
            settlement_id = generate_id('setl')
            gateway_data.append({
                'txn_id': gtw_id, 'order_id': generate_id('ord'), 'amount': amount, 'currency': 'INR',
                'status': 'captured', 'method': 'card', 'created_at': txn_date.strftime('%Y-%m-%d %H:%M:%S'),
                'settlement_id': settlement_id, 'customer_ref': "Cust_Dup"
            })
            running_balance += amount
            bank_data.append({
                'bank_txn_id': bank_id, 'value_date': (txn_date + timedelta(days=1)).strftime('%Y-%m-%d'),
                'narration': f"SETL-{settlement_id}-{inv_ref}", 'debit': 0.0, 'credit': amount,
                'running_balance': running_balance, 'utr_number': settlement_id
            })
            
            ground_truth.append({
                'gateway_id': gtw_id, 'bank_id': bank_id, 'ledger_id': ldg_id,
                'match_type': 'duplicate_ledger_valid', 'expected_status': 'MATCHED'
            })
            ground_truth.append({
                'gateway_id': None, 'bank_id': None, 'ledger_id': ldg_id_2,
                'match_type': 'duplicate_ledger_invalid', 'expected_status': 'EXCEPTION_DUPLICATE_ENTRY'
            })

    # Shuffle lists
    random.shuffle(gateway_data)
    random.shuffle(bank_data)
    random.shuffle(ledger_data)
    random.shuffle(ground_truth)

    os.makedirs(DATA_DIR, exist_ok=True)
    pd.DataFrame(gateway_data).to_csv(os.path.join(DATA_DIR, 'gateway_transactions.csv'), index=False)
    pd.DataFrame(bank_data).to_csv(os.path.join(DATA_DIR, 'bank_statement.csv'), index=False)
    pd.DataFrame(ledger_data).to_csv(os.path.join(DATA_DIR, 'ledger.csv'), index=False)
    pd.DataFrame(ground_truth).to_csv(os.path.join(DATA_DIR, 'ground_truth.csv'), index=False)
    
    print(f"Generated {len(gateway_data)} Gateway txns")
    print(f"Generated {len(bank_data)} Bank statement records")
    print(f"Generated {len(ledger_data)} Ledger entries")
    print(f"Generated {len(ground_truth)} Ground Truth records")

if __name__ == "__main__":
    generate_data()
