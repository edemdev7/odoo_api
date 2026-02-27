#!/usr/bin/env python3
"""Check journal JPASS details and outstanding payment account"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from core.odoo_client import OdooClient

client = OdooClient()

# Journal JPASS
journal = client.execute_kw('account.journal', 'read', [194],
    {'fields': ['id', 'name', 'code', 'type', 'default_account_id', 
                'company_id']})
if journal:
    j = journal[0]
    print(f"Journal: {j['name']} (ID={j['id']}, type={j['type']})")
    print(f"  default_account_id: {j.get('default_account_id')}")

# Vérifier comment Odoo gère le passage in_payment → paid
# Lire la facture 44
inv = client.execute_kw('account.move', 'read', [163670],
    {'fields': ['id', 'name', 'payment_state', 'amount_residual',
                'amount_total', 'amount_residual_signed']})
print(f"\nFacture: {inv[0]['name']}")
print(f"  payment_state: {inv[0]['payment_state']}")
print(f"  amount_residual: {inv[0]['amount_residual']}")
print(f"  amount_total: {inv[0]['amount_total']}")

# Vérifier les outstanding lines du paiement 
# La ligne 521007 doit être rapprochée pour que la facture passe à paid
print(f"\nLigne outstanding (521007) du paiement:")
outstanding = client.execute_kw('account.move.line', 'search_read',
    [[('id', '=', 495297)]],
    {'fields': ['id', 'account_id', 'debit', 'credit', 'reconciled', 
                'amount_residual', 'statement_line_id', 'statement_id']})
if outstanding:
    o = outstanding[0]
    print(f"  account: {o['account_id']}")
    print(f"  debit={o['debit']}, credit={o['credit']}")
    print(f"  reconciled={o['reconciled']}")
    print(f"  statement_line_id={o.get('statement_line_id')}")
    print(f"  statement_id={o.get('statement_id')}")

print("\nDone.")
