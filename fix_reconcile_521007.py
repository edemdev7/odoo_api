"""Fix: Lettrer la ligne outstanding 521007 de la facture JDV/2026/00060 (ID=163727)
pour faire passer payment_state de 'in_payment' à 'paid'
"""
from core.odoo_client import OdooClient

client = OdooClient()

# IDs connus
INVOICE_ID = 163727
PAYMENT_MOVE_ID = 163728
OUTSTANDING_LINE_ID = 495473  # 521007 D=150000, non reconcilié
PARTNER_ID = 11954
REFERENCE = "7b-KSy"
AMOUNT = 150000.0
DATE = "2026-03-12"
JOURNAL_OD_ID = 128  # JOURNAL DES OD (misc)

# Étape 1: Vérifier les comptes
print("1. Vérification des comptes...")
acc_521007 = client.execute_kw('account.account', 'search_read',
    [[('code', '=', '521007')]], {'fields': ['id', 'code', 'name']})
acc_471130 = client.execute_kw('account.account', 'search_read',
    [[('code', '=', '471130')]], {'fields': ['id', 'code', 'name']})

print(f"   521007: ID={acc_521007[0]['id']} - {acc_521007[0]['name']}")
print(f"   471130: ID={acc_471130[0]['id']} - {acc_471130[0]['name']}")

acc_521007_id = acc_521007[0]['id']
acc_471130_id = acc_471130[0]['id']

# Étape 2: Vérifier que la ligne outstanding existe toujours
print("\n2. Vérification ligne outstanding 495473...")
line = client.execute_kw('account.move.line', 'read', [OUTSTANDING_LINE_ID],
    {'fields': ['id', 'account_id', 'debit', 'credit', 'reconciled', 'amount_residual']})
if line:
    l = line[0]
    acc_name = l['account_id'][1] if isinstance(l['account_id'], list) else l['account_id']
    print(f"   Line {l['id']}: {acc_name} D={l['debit']} C={l['credit']} rec={l['reconciled']} res={l['amount_residual']}")
    if l['reconciled']:
        print("   DEJA RECONCILIE - rien a faire")
        exit(0)
else:
    print("   LIGNE INTROUVABLE")
    exit(1)

# Étape 3: Créer écriture de transfert (Débit 471130 / Crédit 521007)
print("\n3. Création écriture de transfert sur journal OD...")
transfer_id = client.execute_kw('account.move', 'create', [{
    'journal_id': JOURNAL_OD_ID,
    'date': DATE,
    'ref': f'Rapprochement {REFERENCE} - TVPASS',
    'line_ids': [
        (0, 0, {
            'account_id': acc_471130_id,
            'debit': AMOUNT,
            'credit': 0,
            'name': f'Transfer {REFERENCE}',
            'partner_id': PARTNER_ID,
        }),
        (0, 0, {
            'account_id': acc_521007_id,
            'debit': 0,
            'credit': AMOUNT,
            'name': f'Transfer {REFERENCE}',
            'partner_id': PARTNER_ID,
        }),
    ]
}])
print(f"   Créé: ID={transfer_id}")

print("   Validation...")
client.execute_kw('account.move', 'action_post', [[transfer_id]])
print("   Validé OK")

# Étape 4: Trouver la ligne crédit 521007 du transfer
print("\n4. Lignes du transfer...")
tlines = client.execute_kw('account.move.line', 'search_read',
    [[('move_id', '=', transfer_id)]],
    {'fields': ['id', 'account_id', 'debit', 'credit', 'reconciled']})

transfer_credit_521007 = None
for tl in tlines:
    acc_name = tl['account_id'][1] if isinstance(tl['account_id'], list) else tl['account_id']
    print(f"   Line {tl['id']}: {acc_name} D={tl['debit']} C={tl['credit']} rec={tl['reconciled']}")
    if tl['credit'] > 0 and '521007' in str(acc_name):
        transfer_credit_521007 = tl['id']

# Étape 5: Lettrer 521007
if transfer_credit_521007:
    print(f"\n5. Lettrage 521007: outstanding={OUTSTANDING_LINE_ID} (D=150000) + transfer={transfer_credit_521007} (C=150000)")
    client.execute_kw('account.move.line', 'reconcile', [[OUTSTANDING_LINE_ID, transfer_credit_521007]])
    print("   Lettrage OK")
else:
    print("\n5. ERREUR: ligne credit 521007 non trouvee dans le transfer")
    exit(1)

# Étape 6: Vérifier le résultat
print("\n6. Vérification finale...")
inv = client.execute_kw('account.move', 'read', [INVOICE_ID],
    {'fields': ['payment_state', 'amount_residual', 'name']})
result = inv[0]
print(f"   Facture: {result['name']}")
print(f"   payment_state = {result['payment_state']}")
print(f"   amount_residual = {result['amount_residual']}")

if result['payment_state'] == 'paid':
    print("\n=== SUCCES: La facture est maintenant PAID ===")
else:
    print(f"\n=== ATTENTION: payment_state = {result['payment_state']} (attendu: paid) ===")
