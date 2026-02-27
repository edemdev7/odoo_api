#!/usr/bin/env python3
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from core.odoo_client import OdooClient

c = OdooClient()
c._authenticate()

# Facture
inv = c.execute_kw('account.move', 'search_read',
    [[('name', '=', 'JDV/2026/00046')]],
    {'fields': ['id', 'state', 'payment_state', 'amount_residual']})
print("FACTURE:", inv)

if inv:
    inv_id = inv[0]['id']
    # Lignes de la facture
    lines = c.execute_kw('account.move.line', 'search_read',
        [[('move_id', '=', inv_id)]],
        {'fields': ['id', 'account_id', 'debit', 'credit', 'reconciled', 'full_reconcile_id', 'amount_residual']})
    print("\nLIGNES FACTURE:")
    for l in lines:
        acc = l['account_id'][1] if isinstance(l['account_id'], list) else l['account_id']
        rec = l['full_reconcile_id']
        print(f"  {l['id']}: {acc} D={l['debit']} C={l['credit']} reconciled={l['reconciled']} match={rec} residual={l['amount_residual']}")

    # Paiements liés
    pays = c.execute_kw('account.payment', 'search_read',
        [[('reconciled_invoice_ids', 'in', [inv_id])]],
        {'fields': ['id', 'name', 'state', 'amount', 'move_id', 'is_reconciled']})
    print("\nPAIEMENTS:", pays)

    if pays:
        pmove_id = pays[0]['move_id'][0] if isinstance(pays[0]['move_id'], list) else pays[0]['move_id']
        plines = c.execute_kw('account.move.line', 'search_read',
            [[('move_id', '=', pmove_id)]],
            {'fields': ['id', 'account_id', 'debit', 'credit', 'reconciled', 'full_reconcile_id', 'amount_residual']})
        print("\nLIGNES PAIEMENT:")
        for l in plines:
            acc = l['account_id'][1] if isinstance(l['account_id'], list) else l['account_id']
            rec = l['full_reconcile_id']
            print(f"  {l['id']}: {acc} D={l['debit']} C={l['credit']} reconciled={l['reconciled']} match={rec} residual={l['amount_residual']}")

    # Relevés bancaires récents
    stmts = c.execute_kw('account.bank.statement.line', 'search_read',
        [[('journal_id', '=', 194)]], 
        {'fields': ['id', 'payment_ref', 'amount', 'is_reconciled', 'move_id'], 'order': 'id desc', 'limit': 5})
    print("\nRELEVES BANCAIRES:")
    for s in stmts:
        print(f"  {s['id']}: ref={s['payment_ref']} amount={s['amount']} reconciled={s['is_reconciled']} move={s['move_id']}")
