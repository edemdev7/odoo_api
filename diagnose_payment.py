#!/usr/bin/env python3
"""Diagnostic des lignes facture/paiement pour comprendre le lettrage"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.odoo_client import OdooClient

client = OdooClient()

# Dernière facture JDV/2026/00044
invoices = client.execute_kw('account.move', 'search_read',
    [[('name', '=', 'JDV/2026/00044')]],
    {'fields': ['id', 'name', 'state', 'payment_state', 'amount_residual', 'partner_id']})

if not invoices:
    print("Facture non trouvée")
    sys.exit(1)

inv = invoices[0]
inv_id = inv['id']
partner_id = inv['partner_id'][0]
print(f"FACTURE: {inv['name']} (ID={inv_id})")
print(f"  state={inv['state']}, payment_state={inv['payment_state']}, residual={inv['amount_residual']}")

# Lignes de la facture
lines = client.execute_kw('account.move.line', 'search_read',
    [[('move_id', '=', inv_id)]],
    {'fields': ['id', 'name', 'account_id', 'account_type', 'debit', 'credit', 
                'reconciled', 'amount_residual', 'matching_number']})
print(f"\nLIGNES FACTURE ({len(lines)}):")
for l in lines:
    acc = l['account_id'][1] if isinstance(l['account_id'], list) else l['account_id']
    print(f"  ID={l['id']:>8} | {acc:<40} | type={l['account_type']:<20} | D={l['debit']:>10} C={l['credit']:>10} | reconciled={l['reconciled']} | residual={l['amount_residual']} | match={l.get('matching_number')}")

# Paiements récents pour ce partner
payments = client.execute_kw('account.payment', 'search_read',
    [[('partner_id', '=', partner_id), ('ref', 'like', 'KKIAPAY-TEST')]],
    {'fields': ['id', 'name', 'state', 'amount', 'move_id', 'ref', 'is_reconciled'], 
     'order': 'id desc', 'limit': 3})
print(f"\nPAIEMENTS RÉCENTS ({len(payments)}):")
for p in payments:
    move_id_val = p['move_id'][0] if isinstance(p['move_id'], list) else p['move_id']
    print(f"  ID={p['id']} | {p.get('name','?')} | state={p['state']} | amount={p['amount']} | ref={p['ref']} | move_id={move_id_val} | is_reconciled={p.get('is_reconciled')}")
    
    if move_id_val:
        plines = client.execute_kw('account.move.line', 'search_read',
            [[('move_id', '=', move_id_val)]],
            {'fields': ['id', 'name', 'account_id', 'account_type', 'debit', 'credit', 
                        'reconciled', 'amount_residual', 'matching_number']})
        for pl in plines:
            acc = pl['account_id'][1] if isinstance(pl['account_id'], list) else pl['account_id']
            print(f"    line ID={pl['id']:>8} | {acc:<40} | type={pl['account_type']:<20} | D={pl['debit']:>10} C={pl['credit']:>10} | reconciled={pl['reconciled']} | residual={pl['amount_residual']} | match={pl.get('matching_number')}")

# Chercher TOUTES les lignes non réconciliées du partner sur les comptes receivable
print(f"\nLIGNES RECEIVABLE NON RÉCONCILIÉES (partner={partner_id}):")
unreconciled = client.execute_kw('account.move.line', 'search_read',
    [[('partner_id', '=', partner_id), ('account_type', '=', 'asset_receivable'), ('reconciled', '=', False)]],
    {'fields': ['id', 'move_id', 'account_id', 'debit', 'credit', 'amount_residual'], 'limit': 20, 'order': 'id desc'})
for u in unreconciled:
    acc = u['account_id'][1] if isinstance(u['account_id'], list) else u['account_id']
    move = u['move_id'][1] if isinstance(u['move_id'], list) else u['move_id']
    print(f"  ID={u['id']:>8} | move={move:<30} | {acc:<40} | D={u['debit']:>10} C={u['credit']:>10} | residual={u['amount_residual']}")

print("\nDone.")
