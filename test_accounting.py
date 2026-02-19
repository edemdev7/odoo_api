#!/usr/bin/env python3
"""
Script de test pour l'endpoint de crédit comptable

Ce script teste l'endpoint /accounting/credit-account avec encryption RSA.
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from core.encryption import encrypt_webhook_data
import requests
import json

# Configuration
API_URL = os.getenv("API_URL", "http://localhost:8001")

def test_credit_account(partner_id: int, amount: float, reference: str):
    """Tester l'endpoint de crédit comptable"""
    
    print("=" * 60)
    print("🧪 Test de l'endpoint de crédit comptable")
    print("=" * 60)
    print()
    
    # Préparer les données
    data = {
        "partner_id": partner_id,
        "amount": amount,
        "reference": reference,
        "description": "Test de recharge compte fuel"
    }
    
    print("📄 Données à envoyer:")
    print(json.dumps(data, indent=2, ensure_ascii=False))
    print()
    
    # Encrypter les données
    try:
        print("🔒 Encryption des données...")
        encrypted_data = encrypt_webhook_data(data)
        print(f"✅ Données encryptées ({len(encrypted_data)} chars)")
        print(f"   Aperçu: {encrypted_data[:60]}...")
        print()
    except Exception as e:
        print(f"❌ Erreur encryption: {e}")
        return False
    
    # Envoyer la requête
    print(f"📤 Envoi de la requête à {API_URL}/accounting/credit-account")
    print()
    
    try:
        response = requests.post(
            f"{API_URL}/accounting/credit-account",
            headers={
                "Content-Type": "application/json",
                "x-encrypted-data": encrypted_data
            },
            timeout=30
        )
        
        print(f"📥 Réponse reçue: Status {response.status_code}")
        print()
        
        if response.status_code == 200:
            result = response.json()
            print("✅ ✅ ✅ Succès !")
            print()
            print("📋 Résultat:")
            print(json.dumps(result, indent=2, ensure_ascii=False))
            print()
            
            if result.get('success'):
                data = result.get('data', {})
                print("📊 Résumé:")
                print(f"   Move ID: {data.get('move_id')}")
                print(f"   Move Name: {data.get('move_name')}")
                print(f"   État: {data.get('move_state')}")
                print(f"   Partenaire: {data.get('partner_name')}")
                print(f"   Montant: {data.get('amount')} CFA")
                print(f"   Référence: {data.get('reference')}")
                print(f"   Ancien solde: {data.get('old_balance')}")
                print(f"   Nouveau solde: {data.get('new_balance')}")
                print()
                
                accounts = data.get('accounts', {})
                print("💳 Comptes utilisés:")
                print(f"   Débit: {accounts.get('debit')}")
                print(f"   Crédit: {accounts.get('credit')}")
            
            return True
        else:
            print(f"❌ Erreur HTTP {response.status_code}")
            print(response.text)
            return False
            
    except requests.exceptions.Timeout:
        print("❌ Timeout de la requête")
        return False
    except Exception as e:
        print(f"❌ Erreur: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_get_account_info(account_code: str):
    """Tester la récupération d'informations de compte"""
    
    print("=" * 60)
    print(f"🔍 Test de récupération du compte {account_code}")
    print("=" * 60)
    print()
    
    # Encrypter une donnée vide pour l'authentification
    try:
        encrypted_data = encrypt_webhook_data({"check": "account"})
    except Exception as e:
        print(f"❌ Erreur encryption: {e}")
        return False
    
    try:
        response = requests.get(
            f"{API_URL}/accounting/accounts/{account_code}",
            headers={
                "x-encrypted-data": encrypted_data
            },
            timeout=10
        )
        
        print(f"📥 Réponse: Status {response.status_code}")
        print()
        
        if response.status_code == 200:
            result = response.json()
            print("✅ Compte trouvé:")
            print(json.dumps(result, indent=2, ensure_ascii=False))
            return True
        else:
            print(f"❌ Erreur: {response.text}")
            return False
            
    except Exception as e:
        print(f"❌ Erreur: {e}")
        return False


if __name__ == "__main__":
    print()
    print("🚀 Tests de l'endpoint accounting")
    print()
    
    # Vérifier que les clés RSA sont présentes
    if not os.path.exists("public.pem"):
        print("❌ Fichier public.pem non trouvé")
        sys.exit(1)
    
    print("✅ Clés RSA trouvées")
    print()
    
    # Test 1: Vérifier les comptes comptables
    print("📝 Test 1: Vérification des comptes")
    print()
    test_get_account_info("419101")
    print()
    
    # Test 2: Créer une écriture de crédit
    print("📝 Test 2: Créer une écriture de crédit")
    print()
    
    # Paramètres de test (À ADAPTER selon vos données Odoo)
    PARTNER_ID = int(input("Enter partner_id (ID de l'entreprise): ") or "1")
    AMOUNT = float(input("Enter amount (montant): ") or "50000")
    REFERENCE = input("Enter reference (ex: KKIAPAY-TEST-001): ") or "TEST-001"
    
    success = test_credit_account(PARTNER_ID, AMOUNT, REFERENCE)
    
    print()
    print("=" * 60)
    
    if success:
        print("✅ 🎉 Test réussi !")
        print()
        print("⚠️  Vérifiez dans Odoo:")
        print("   Comptabilité > Journal Items")
        print(f"   Recherchez la référence: {REFERENCE}")
    else:
        print("❌ Test échoué")
        sys.exit(1)
