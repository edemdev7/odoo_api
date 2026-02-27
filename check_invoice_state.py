#!/usr/bin/env python3
"""Vérifier l'état réel de la dernière facture"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.odoo_client import OdooClient
from core.config import settings

client = OdooClient(settings.ODOO_URL, settings.ODOO_DB, settings.ODOO_USERNAME, settings.ODOO_PASSWORD)
client.authenticate()

# Chercher les dernières factures JDV
invoices = client.execute_kw(
    'account.move', 'search_read',
    [[('name', 'like', 'JDV/2026/'), ('move_type', '=', 'out_invoice')]],
    {'fields': ['id', 'name', 'state', 'payment_state', 'amount_residual', 'amount_total', 'partner_id'],
     'order': 'id desc', 'limit': 5}
)

print("=" * 80)
print("DERNIÈRES FACTURES JDV")
print("=" * 80)
for inv in invoices:
    partner = inv['partner_id'][1] if isinstance(inv['partner_id'], list) else inv['partner_id']
    print(f"  {inv['name']} (ID:{inv['id']})")
    print(f"    state={inv['state']}, payment_state={inv['payment_state']}")
    print(f"    total={inv['amount_total']}, residual={inv['amount_residual']}")
    print(f"    partner={partner}")
    print()

# Vérifier les lignes de la dernière
if invoices:
    last = invoices[0]
    print(f"--- Lignes comptables de {last['name']} ---")
    lines = client.execute_kw(
        'account.move.line', 'search_read',
        [[('move_id', '=', last['id'])]],
        {'fields': ['id', 'account_id', 'debit', 'credit', 'reconciled', 'full_reconcile_id', 'amount_residual']}
    )
    for l in lines:
        acc = l['account_id'][1] if isinstance(l['account_id'], list) else l['account_id']
        rec = l['full_reconcile_id'][1] if isinstance(l['full_reconcile_id'], list) else l['full_reconcile_id']
        print(f"  Line {l['id']}: {acc} | D={l['debit']} C={l['credit']} | reconciled={l['reconciled']} | match={rec} | residual={l['amount_residual']}")

    # Chercher les paiements liés
    print(f"\n--- Paiements liés à {last['name']} ---")
    payments = client.execute_kw(
        'account.payment', 'search_read',
        [[('ref', 'like', last['name'])]],
        {'fields': ['id', 'name', 'state', 'amount', 'move_id', 'is_reconciled'],
         'order': 'id desc', 'limit': 5}
    )
    if not payments:
        # Essayer via reconciled_invoice_ids
        payments = client.execute_kw(
            'account.payment', 'search_read',
            [[('reconciled_invoice_ids', 'in', [last['id']])]],
            {'fields': ['id', 'name', 'state', 'amount', 'move_id', 'is_reconciled'],
             'order': 'id desc', 'limit': 5}
        )
    for p in payments:
        move = p['move_id'][1] if isinstance(p['move_id'], list) else p['move_id']
        print(f"  Payment {p['name']} (ID:{p['id']}): state={p['state']}, amount={p['amount']}, reconciled={p['is_reconciled']}, move={move}")

        # Lignes du paiement
        pmove_id = p['move_id'][0] if isinstance(p['move_id'], list) else p['move_id']
        plines = client.execute_kw(
            'account.move.line', 'search_read',
            [[('move_id', '=', pmove_id)]],
            {'fields': ['id', 'account_id', 'debit', 'credit', 'reconciled', 'full_reconcile_id', 'amount_residual']}
        )
        for l in plines:
            acc = l['account_id'][1] if isinstance(l['account_id'], list) else l['account_id']
            rec = l['full_reconcile_id'][1] if isinstance(l['full_reconcile_id'], list) else l['full_reconcile_id']
            print(f"    PLine {l['id']}: {acc} | D={l['debit']} C={l['credit']} | reconciled={l['reconciled']} | match={rec} | residual={l['amount_residual']}")

    # Chercher les relevés bancaires récents
    print(f"\n--- Relevés bancaires récents (JPASS) ---")
    stmts = client.execute_kw(
        'account.bank.statement.line', 'search_read',
        [[('journal_id', '=', 194)]],
        {'fields': ['id', 'payment_ref', 'amount', 'date', 'partner_id', 'move_id', 'is_reconciled'],
         'order': 'id desc', 'limit': 5}
    )
    for s in stmts:
        partner = s['partner_id'][1] if isinstance(s['partner_id'], list) else s['partner_id']
        move = s['move_id'][1] if isinstance(s['move_id'], list) else s['move_id']
        print(f"  StmtLine {s['id']}: ref={s['payment_ref']}, amount={s['amount']}, reconciled={s['is_reconciled']}, move={move}")
