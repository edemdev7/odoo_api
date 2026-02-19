#!/usr/bin/env python3
"""
Test rapide de l'endpoint comptable /accounting/credit-account
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import requests
import json
from core.encryption import encrypt_webhook_data

# Configuration
API_HOST = "localhost"
API_PORT = 8002

def test_credit_account():
    """Test de création d'écriture comptable"""
    
    print("=" * 70)
    print("🧾 Test de l'endpoint /accounting/credit-account")
    print("=" * 70)
    print()
    
    # Paramètres du test
    partner_id = 4708
    amount = 10000
    reference = "TEST-ECRITURE-001"
    
    print(f"📋 Paramètres:")
    print(f"   Partner ID: {partner_id}")
    print(f"   Montant: {amount}")
    print(f"   Référence: {reference}")
    print()
    
    # Préparer les données
    request_data = {
        "partner_id": partner_id,
        "amount": amount,
        "reference": reference,
        "description": f"Test écriture comptable - Montant: {amount}"
    }
    
    print(f"📄 Données à envoyer:")
    print(json.dumps(request_data, indent=2))
    print()
    
    try:
        # Encrypter les données
        print("🔒 Encryption des données avec RSA...")
        encrypted_data = encrypt_webhook_data(request_data)
        print(f"✅ Données encryptées (longueur: {len(encrypted_data)} caractères)")
        print()
        
        # Préparer la requête
        url = f"http://{API_HOST}:{API_PORT}/accounting/credit-account"
        
        headers = {
            "Content-Type": "application/json",
            "x-encrypted-data": encrypted_data
        }
        
        print(f"🌐 Envoi de la requête POST à: {url}")
        print()
        
        # Envoyer la requête
        response = requests.post(
            url,
            headers=headers,
            json={},  # Body vide, données dans le header
            timeout=30
        )
        
        print(f"📥 Réponse reçue - Status: {response.status_code}")
        print()
        
        # Afficher la réponse
        if response.status_code == 200:
            result = response.json()
            print("✅ ✅ ✅ Écriture comptable créée avec succès!")
            print()
            print("📊 Détails de la réponse:")
            print(json.dumps(result, indent=2, ensure_ascii=False))
            print()
            
            if "data" in result:
                data = result["data"]
                print("=" * 70)
                print("📝 RÉSUMÉ DE L'ÉCRITURE")
                print("=" * 70)
                print(f"🆔 Move ID: {data.get('move_id')}")
                print(f"📄 Move Name: {data.get('move_name')}")
                print(f"✅ État: {data.get('move_state')}")
                print(f"👤 Partenaire: {data.get('partner_name')} (ID: {data.get('partner_id')})")
                print(f"💰 Montant: {data.get('amount')}")
                print(f"🔖 Référence: {data.get('reference')}")
                print(f"📅 Date: {data.get('date')}")
                
                if "account" in data:
                    print(f"📚 Compte crédité: {data['account']['credit']}")
                
                print()
                print(f"💳 Solde ancien: {data.get('old_balance')}")
                print(f"💳 Solde nouveau: {data.get('new_balance')}")
                print()
                
            return True
        else:
            print(f"❌ Erreur HTTP {response.status_code}")
            print(f"Réponse: {response.text}")
            return False
            
    except requests.exceptions.ConnectionError:
        print("❌ Erreur: Impossible de se connecter à l'API")
        print("   Assurez-vous que le serveur FastAPI est démarré:")
        print("   uvicorn main:app --reload")
        return False
    except Exception as e:
        print(f"❌ Erreur: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    print()
    success = test_credit_account()
    print()
    
    if success:
        print("✅ Test terminé avec succès!")
        exit(0)
    else:
        print("❌ Test échoué")
        exit(1)
