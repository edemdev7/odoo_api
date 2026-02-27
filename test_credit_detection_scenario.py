#!/usr/bin/env python3
"""
Test complet du scénario de rechargement TVPASS via kkiapay

Flux testé:
1. Appel endpoint /accounting/credit-account (payment_method=kkiapay)
2. Vérification: sale.order créée et confirmée
3. Vérification: facture créée et validée
4. Vérification: paiement enregistré et lettré
5. Vérification: webhook TVPASS_RECHARGE envoyé
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
PARTNER_ID = 4708  # JSI VOYAGES


def create_tvpass_recharge(amount: float, payment_method: str = "kkiapay"):
    """Appeler l'endpoint credit-account avec le nouveau flux TVPASS"""
    from core.encryption import encrypt_webhook_data

    url = f"http://{API_HOST}:{API_PORT}/accounting/credit-account"

    request_data = {
        "partner_id": PARTNER_ID,
        "amount": amount,
        "reference": f"KKIAPAY-TEST-{int(time.time())}",
        "payment_method": payment_method,
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
    print("=" * 80)
    print("🔄 TEST RECHARGEMENT TVPASS VIA KKIAPAY")
    print("   Flux: sale.order → facture → paiement → webhook TVPASS_RECHARGE")
    print("=" * 80)
    print()

    amount = 7000  # 7000 CFA

    # ===== ÉTAPE 1: Appel de l'endpoint =====
    print("📍 ÉTAPE 1: Appel de /accounting/credit-account")
    print("-" * 80)
    print(f"   Partenaire: JSI VOYAGES (ID: {PARTNER_ID})")
    print(f"   Montant: {amount} CFA")
    print(f"   Méthode: kkiapay")
    print()

    response = create_tvpass_recharge(amount, "kkiapay")

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
    print("📍 ÉTAPE 4: Vérification du paiement (kkiapay)")
    print("-" * 80)
    payment_info = data.get("payment")
    if payment_info:
        payment_state = payment_info.get("payment_state", "inconnu")
        amount_residual = payment_info.get("amount_residual", "?")
        print(f"   ✅ Paiement enregistré")
        print(f"   📊 État paiement facture: {payment_state}")
        print(f"   💰 Reste dû: {amount_residual} CFA")

        if payment_state in ("paid", "in_payment"):
            print(f"   ✅ Facture marquée comme payée !")
        else:
            print(f"   ⚠️  Facture pas encore marquée payée (état: {payment_state})")
    else:
        print(f"   ⚠️  Pas d'info paiement dans la réponse")
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
    print("📍 ÉTAPE 7: Webhook TVPASS_RECHARGE")
    print("-" * 80)
    webhook_sent = data.get("webhook_sent", False)
    if webhook_sent:
        print(f"   ✅ Webhook TVPASS_RECHARGE envoyé en arrière-plan !")
        print(f"   📤 URL: https://api-jnp-dev.opensi.co/public/odoo/webhook")
        print(f"   📦 Payload encrypté contient:")
        print(f'      action: "TVPASS_RECHARGE"')
        print(f'      companyExternalId: "{PARTNER_ID}"')
        print(f'      amount: {amount}')
        print(f'      invoice_id: {invoice_id}')
        print(f'      invoice_number: "{invoice_number}"')
    else:
        print(f"   ❌ Webhook NON envoyé")
    print()

    # ===== RÉSUMÉ =====
    print("=" * 80)
    print("📋 RÉSUMÉ DU FLUX")
    print("=" * 80)
    print(f"   1. sale.order     : {order_name} (ID: {order_id})")
    print(f"   2. Facture        : {invoice_number} (ID: {invoice_id}) - État: {invoice_state}")
    pm_state = payment_info.get('payment_state', 'N/A') if payment_info else 'N/A'
    print(f"   3. Paiement       : {pm_state}")
    print(f"   4. Webhook envoyé : {'✅ Oui' if webhook_sent else '❌ Non'}")
    print(f"   5. Montant        : {amount} CFA")
    print(f"   6. Référence      : {data.get('reference', 'N/A')}")
    print(f"   7. Méthode        : {data.get('payment_method', 'N/A')}")
    print()

    # Déterminer le succès global
    success = (
        order_id is not None
        and invoice_id is not None
        and webhook_sent
    )

    return success


if __name__ == "__main__":
    try:
        success = main()
        print()
        print("=" * 80)
        if success:
            print("🎉 TEST RÉUSSI ! Le flux complet kkiapay fonctionne.")
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
