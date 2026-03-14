#!/usr/bin/env python3
"""
Test complet du scénario de rechargement TVPASS (COMPANY_SUPPLY_VALIDATION)

Flux testé (mode kkiapay):
1. Appel endpoint /accounting/credit-account (payment_method=kkiapay)
2. Vérification: sale.order créée et confirmée
3. Vérification: facture créée et validée
4. Vérification: paiement enregistré et lettré → payment_state=paid
5. Vérification: webhook COMPANY_SUPPLY_VALIDATION envoyé (supplyId + invoiceId)

Flux testé (mode bank):
1. Appel endpoint /accounting/credit-account (payment_method=bank)
2. Vérification: sale.order créée et confirmée
3. Vérification: facture créée et validée
4. Vérification: paiement enregistré → payment_state=in_payment
5. Webhook NON envoyé (sera envoyé par le scheduler quand admin valide)
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import requests
import json
import time

# Configuration
API_HOST = "localhost"
API_PORT = 8002
PARTNER_ID = 11954  # Open SI test


def create_tvpass_recharge(amount: float, payment_method: str = "kkiapay", supply_id: str = None):
    """Appeler l'endpoint credit-account avec le nouveau flux TVPASS"""
    from core.encryption import encrypt_webhook_data

    url = f"http://{API_HOST}:{API_PORT}/accounting/credit-account"

    if supply_id is None:
        supply_id = f"SUPPLY-TEST-{int(time.time())}"

    request_data = {
        "partner_id": PARTNER_ID,
        "amount": amount,
        "reference": f"KKIAPAY-TEST-{int(time.time())}",
        "payment_method": payment_method,
        "supply_id": supply_id,
        "description": f"Test rechargement TVPASS {payment_method} - {amount} CFA"
    }

    print(f"   📦 Payload envoyé:")
    for k, v in request_data.items():
        print(f"      {k}: {v}")
    print()

    encrypted_data = encrypt_webhook_data(request_data)

    headers = {
        "Content-Type": "application/json",
        "x-encrypted-data": encrypted_data
    }

    response = requests.post(url, headers=headers, json={}, timeout=60)
    return response


def main():
    # Mode par défaut: kkiapay, sinon passer "bank" en argument
    mode = sys.argv[1] if len(sys.argv) > 1 else "kkiapay"
    if mode not in ("kkiapay", "bank"):
        print(f"❌ Mode inconnu: {mode}. Utiliser 'kkiapay' ou 'bank'.")
        return False

    print("=" * 80)
    print(f"🔄 TEST RECHARGEMENT TVPASS VIA {mode.upper()}")
    if mode == "kkiapay":
        print("   Flux: sale.order → facture → paiement kkiapay → paid → webhook")
    else:
        print("   Flux: sale.order → facture → en attente paiement admin")
    print("=" * 80)
    print()

    amount = 150000  # 150 000 CFA
    supply_id = f"SUPPLY-TEST-{int(time.time())}"

    # ===== ÉTAPE 1: Appel de l'endpoint =====
    print(f"📍 ÉTAPE 1: Appel de /accounting/credit-account (mode {mode})")
    print("-" * 80)
    print(f"   Partenaire: Open SI test (ID: {PARTNER_ID})")
    print(f"   Montant: {amount} CFA")
    print(f"   Méthode: {mode}")
    print(f"   Supply ID: {supply_id}")
    print()

    response = create_tvpass_recharge(amount, mode, supply_id)

    print(f"   ⏱️  Status HTTP: {response.status_code}")
    print()

    if response.status_code != 200:
        print(f"❌ ERREUR HTTP {response.status_code}")
        try:
            error = response.json()
            print(f"   Détail: {json.dumps(error, indent=2, ensure_ascii=False)}")
        except Exception:
            print(f"   Body: {response.text[:500]}")
        return False

    result = response.json()
    data = result.get("data", {})
    message = result.get("message", "")
    payment_method_used = data.get("payment_method", "bank")

    print(f"   ✅ Message: {message}")
    print()

    # ===== ÉTAPE 2: Vérification commande de vente =====
    print("📍 ÉTAPE 2: Vérification de la commande de vente") 
    print("-" * 80)
    order_id = data.get("order_id")
    order_name = data.get("order_name")
    if order_id:
        print(f"   ✅ Commande créée: {order_name} (ID: {order_id})")
    else:
        print(f"   ❌ Pas de commande dans la réponse")
        return False
    print()

    # ===== ÉTAPE 3: Vérification facture =====
    print("📍 ÉTAPE 3: Vérification de la facture")
    print("-" * 80)
    invoice_id = data.get("invoice_id")
    invoice_number = data.get("invoice_number")
    invoice_state = data.get("invoice_state")
    if invoice_id:
        print(f"   ✅ Facture créée: {invoice_number} (ID: {invoice_id})")
        print(f"   📊 État: {invoice_state}")
    else:
        print(f"   ❌ Pas de facture dans la réponse")
        return False
    print()

    # ===== ÉTAPE 4: Vérification paiement =====
    print("📍 ÉTAPE 4: Vérification du paiement (bank)")
    print("-" * 80)
    payment_info = data.get("payment")
    note = data.get("note", "")
    if payment_info:
        payment_state = payment_info.get("payment_state", "inconnu")
        amount_residual = payment_info.get("amount_residual", "?")
        print(f"   ✅ Paiement enregistré (sans rapprochement bancaire)")
        print(f"   📊 État paiement facture: {payment_state}")
        print(f"   💰 Reste dû: {amount_residual} CFA")
        if payment_state == "in_payment":
            print(f"   ✅ Facture en paiement (en attente rapprochement bancaire par l'admin)")
        elif payment_state == "paid":
            print(f"   ⚠️  Facture déjà payée (le rapprochement a été fait automatiquement)")
        else:
            print(f"   ⚠️  État inattendu: {payment_state}")
    else:
        print(f"   ❌ Pas de paiement dans la réponse")
        if note:
            print(f"   📝 Note: {note}")
    print()

    # ===== ÉTAPE 5: Vérification produit =====
    print("📍 ÉTAPE 5: Détails du produit utilisé")
    print("-" * 80)
    product = data.get("product", {})
    print(f"   Produit: {product.get('name', 'N/A')}")
    print(f"   Code: {product.get('code', 'N/A')}")
    print(f"   ID: {product.get('id', 'N/A')}")
    print()

    # ===== ÉTAPE 6: Vérification soldes =====
    print("📍 ÉTAPE 6: Évolution du solde client")
    print("-" * 80)
    old_balance = data.get("old_balance", "?")
    new_balance = data.get("new_balance", "?")
    print(f"   Ancien solde: {old_balance} CFA")
    print(f"   Nouveau solde: {new_balance} CFA")
    if isinstance(old_balance, (int, float)) and isinstance(new_balance, (int, float)):
        diff = new_balance - old_balance
        print(f"   Différence: {'+' if diff >= 0 else ''}{diff} CFA")
    print()

    # ===== ÉTAPE 7: Vérification webhook =====
    print("📍 ÉTAPE 7: Webhook COMPANY_SUPPLY_VALIDATION")
    print("-" * 80)
    webhook_sent = data.get("webhook_sent", False)
    supply_id_resp = data.get("supply_id", "N/A")
    if webhook_sent:
        if payment_method_used == "kkiapay":
            print(f"   ✅ Webhook COMPANY_SUPPLY_VALIDATION envoyé")
            print(f"   📦 supplyId: {supply_id_resp}")
            print(f"   📦 invoiceId: {invoice_id}")
        else:
            print(f"   ⚠️  Webhook envoyé immédiatement (ne devrait pas en mode bank)")
    else:
        if payment_method_used == "bank":
            print(f"   ✅ Webhook NON envoyé (normal en mode bank)")
            print(f"   📝 Le webhook sera envoyé par le scheduler quand l'admin validera le paiement")
        else:
            print(f"   ❌ Webhook NON envoyé (devrait l'être en mode kkiapay)")
    print()

    # ===== ÉTAPE 8: Vérification factures en attente =====
    print("📍 ÉTAPE 8: Vérification des factures en attente")
    print("-" * 80)
    try:
        pending_url = f"http://{API_HOST}:{API_PORT}/accounting/pending-invoices"
        pending_response = requests.get(pending_url, timeout=30)
        if pending_response.status_code == 200:
            pending_data = pending_response.json().get("data", {})
            count = pending_data.get("count", 0)
            invoices = pending_data.get("invoices", {})
            print(f"   � {count} facture(s) en attente de paiement")
            for inv_id, inv_info in invoices.items():
                print(f"      - Facture ID {inv_id}: {inv_info.get('invoice_number', 'N/A')} | "
                      f"Montant: {inv_info.get('amount', 'N/A')} CFA | "
                      f"Ref: {inv_info.get('reference', 'N/A')}")
            if str(invoice_id) in invoices or invoice_id in invoices:
                print(f"   ✅ La facture {invoice_number} est bien dans la liste d'attente !")
            else:
                # Vérifier avec int key
                found = any(str(k) == str(invoice_id) for k in invoices.keys())
                if found:
                    print(f"   ✅ La facture {invoice_number} est bien dans la liste d'attente !")
                else:
                    print(f"   ⚠️  La facture {invoice_number} n'est pas trouvée dans pending (keys: {list(invoices.keys())})")
        else:
            print(f"   ❌ Erreur HTTP {pending_response.status_code} sur /pending-invoices")
    except Exception as e:
        print(f"   ❌ Erreur lors de la vérification: {e}")
    print()

    # ===== ÉTAPE 9: Diagnostic Odoo pour lettrage (mode bank) =====
    if payment_method_used == "bank" and invoice_id:
        print("📍 ÉTAPE 9: Diagnostic Odoo - Infos pour le lettrage manuel")
        print("-" * 80)
        try:
            from core.odoo_client import OdooClient
            odoo = OdooClient()

            # Lire la facture dans Odoo
            inv_data = odoo.execute_kw('account.move', 'read', [invoice_id],
                {'fields': ['name', 'payment_state', 'amount_residual', 'ref']})
            if inv_data:
                inv_info = inv_data[0]
                print(f"   📄 Facture Odoo: {inv_info['name']} (ID: {invoice_id})")
                print(f"   📊 payment_state: {inv_info['payment_state']}")
                print(f"   💰 amount_residual: {inv_info['amount_residual']}")
                print(f"   🔗 Référence: {inv_info.get('ref', 'N/A')}")

            # Trouver le paiement lié
            pay_moves = odoo.execute_kw('account.payment', 'search_read',
                [[('ref', 'ilike', data.get('reference', 'XXXX'))]],
                {'fields': ['id', 'name', 'move_id', 'amount', 'state'], 'limit': 1})
            if not pay_moves:
                # Chercher par move_id associé à la facture
                pay_moves = odoo.execute_kw('account.payment', 'search_read',
                    [[('partner_id', '=', PARTNER_ID), ('amount', '=', amount)]],
                    {'fields': ['id', 'name', 'move_id', 'amount', 'state'],
                     'order': 'id desc', 'limit': 1})

            if pay_moves:
                pay = pay_moves[0]
                pay_move_id = pay['move_id'][0] if isinstance(pay['move_id'], list) else pay['move_id']
                pay_move_name = pay['move_id'][1] if isinstance(pay['move_id'], list) else pay['move_id']
                print(f"\n   💳 Paiement: {pay['name']} (ID: {pay['id']})")
                print(f"   📝 Move: {pay_move_name} (ID: {pay_move_id})")

                # Trouver la ligne 521007 outstanding
                pay_lines = odoo.execute_kw('account.move.line', 'search_read',
                    [[('move_id', '=', pay_move_id)]],
                    {'fields': ['id', 'account_id', 'debit', 'credit', 'reconciled', 'amount_residual']})

                outstanding_line = None
                for pl in pay_lines:
                    acc_name = pl['account_id'][1] if isinstance(pl['account_id'], list) else pl['account_id']
                    status = "✅ lettré" if pl['reconciled'] else "❌ NON lettré"
                    print(f"      Line {pl['id']}: {acc_name} D={pl['debit']} C={pl['credit']} {status} res={pl['amount_residual']}")
                    if '521007' in str(acc_name) and not pl['reconciled']:
                        outstanding_line = pl

                if outstanding_line:
                    print(f"\n   🎯 LIGNE À LETTRER: ID={outstanding_line['id']} (521007 D={outstanding_line['debit']})")
                    print()
                    print("   " + "=" * 60)
                    print("   📋 INSTRUCTIONS POUR LE LETTRAGE MANUEL:")
                    print("   " + "=" * 60)
                    print(f"   Option 1 - Via script fix_reconcile_521007.py:")
                    print(f"      Modifier les constantes dans le script:")
                    print(f"        INVOICE_ID = {invoice_id}")
                    print(f"        PAYMENT_MOVE_ID = {pay_move_id}")
                    print(f"        OUTSTANDING_LINE_ID = {outstanding_line['id']}")
                    print(f"        PARTNER_ID = {PARTNER_ID}")
                    print(f"        REFERENCE = \"{inv_info.get('ref', data.get('reference', 'N/A'))}\"")
                    print(f"        AMOUNT = {amount}.0")
                    print(f"      Puis: python3 fix_reconcile_521007.py")
                    print()
                    print(f"   Option 2 - Via Odoo UI:")
                    print(f"      1. Aller dans Comptabilité → Journal PASS GD")
                    print(f"      2. Rapprochement bancaire")
                    print(f"      3. Créer un relevé bancaire de {amount} CFA")
                    print(f"      4. Matcher avec le paiement outstanding {pay_move_name}")
                    print(f"      5. Valider le rapprochement")
                    print("   " + "=" * 60)
                else:
                    print("\n   ✅ Toutes les lignes 521007 sont déjà lettrées")
            else:
                print("\n   ⚠️  Paiement non trouvé dans Odoo")

        except Exception as e:
            print(f"   ❌ Erreur diagnostic Odoo: {e}")
        print()

    # ===== RÉSUMÉ =====
    print("=" * 80)
    print(f"📋 RÉSUMÉ DU FLUX (MODE {payment_method_used.upper()})")
    print("=" * 80)
    print(f"   1. sale.order     : {order_name} (ID: {order_id})")
    print(f"   2. Facture        : {invoice_number} (ID: {invoice_id}) - État: {invoice_state}")
    pm_state = payment_info.get('payment_state', 'N/A') if payment_info else 'Aucun (attente admin)'
    print(f"   3. Paiement       : {pm_state}")
    print(f"   4. Webhook envoyé : {'✅ Oui' if webhook_sent else '❌ Non'}")
    print(f"   5. Montant        : {amount} CFA")
    print(f"   6. Référence      : {data.get('reference', 'N/A')}")
    print(f"   7. Supply ID      : {data.get('supply_id', 'N/A')}")
    print(f"   8. Méthode        : {payment_method_used}")
    print()

    # Déterminer le succès global
    pm_state_check = payment_info.get('payment_state', '') if payment_info else ''

    if payment_method_used == "kkiapay":
        success = (
            order_id is not None
            and invoice_id is not None
            and invoice_state == 'posted'
            and pm_state_check == 'paid'
            and webhook_sent  # Le webhook DOIT être envoyé en mode kkiapay
        )
    else:  # bank
        success = (
            order_id is not None
            and invoice_id is not None
            and invoice_state == 'posted'
            and pm_state_check == 'in_payment'  # Doit être en_paiement
            and not webhook_sent  # Le webhook NE DOIT PAS être envoyé en mode bank
        )

    return success


if __name__ == "__main__":
    try:
        success = main()
        print()
        print("=" * 80)
        if success:
            mode = sys.argv[1] if len(sys.argv) > 1 else "kkiapay"
            if mode == "kkiapay":
                print("🎉 TEST RÉUSSI ! Flux kkiapay OK (facture paid + webhook COMPANY_SUPPLY_VALIDATION envoyé).")
            else:
                print("🎉 TEST RÉUSSI ! Flux bank OK (facture in_payment, en attente admin).")
                print("   📝 Suivez les instructions de l'étape 9 pour faire le lettrage.")
                print("   📝 Après lettrage → payment_state=paid → scheduler envoie le webhook.")
        else:
            print("❌ TEST ÉCHOUÉ - Vérifiez les logs du serveur pour plus de détails")
        print("=" * 80)
        exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\n\n⚠️  Test interrompu par l'utilisateur")
        exit(1)
    except Exception as e:
        print(f"\n\n❌ Erreur inattendue: {e}")
        import traceback
        traceback.print_exc()
        exit(1)
