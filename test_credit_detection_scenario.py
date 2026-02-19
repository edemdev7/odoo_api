#!/usr/bin/env python3
"""
Test complet du scénario de détection de changement de crédit
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

def get_token():
    """Obtenir un token d'authentification"""
    url = f"http://{API_HOST}:{API_PORT}/auth/pin-login"
    payload = {
        "pin_code": "0000",  # Changez selon votre PIN
        "database": "jnp_directe"
    }
    
    try:
        response = requests.post(url, json=payload, timeout=10)
        if response.status_code == 200:
            result = response.json()
            return result.get("data", {}).get("access_token")
    except:
        pass
    return None

def clear_cache(token):
    """Vider le cache pour un partenaire"""
    url = f"http://{API_HOST}:{API_PORT}/fuel-monitor/cache/clear"
    headers = {"Authorization": f"Bearer {token}"}
    params = {"partner_id": PARTNER_ID}
    
    response = requests.delete(url, headers=headers, params=params, timeout=10)
    return response.status_code == 200

def check_cache_status(token):
    """Vérifier le statut du cache"""
    url = f"http://{API_HOST}:{API_PORT}/fuel-monitor/cache/status"
    headers = {"Authorization": f"Bearer {token}"}
    
    response = requests.get(url, headers=headers, timeout=10)
    if response.status_code == 200:
        return response.json()
    return None

def capture_initial_credit(token):
    """Capturer le crédit initial"""
    url = f"http://{API_HOST}:{API_PORT}/fuel-monitor/check-credit-changes"
    headers = {"Authorization": f"Bearer {token}"}
    params = {"partner_id": PARTNER_ID}
    
    response = requests.get(url, headers=headers, params=params, timeout=10)
    if response.status_code == 200:
        return response.json()
    return None

def create_accounting_entry(amount):
    """Créer une écriture comptable"""
    from core.encryption import encrypt_webhook_data
    
    url = f"http://{API_HOST}:{API_PORT}/accounting/credit-account"
    
    request_data = {
        "partner_id": PARTNER_ID,
        "amount": amount,
        "reference": f"TEST-SCENARIO-{int(time.time())}",
        "description": f"Test scénario complet - Montant: {amount}"
    }
    
    encrypted_data = encrypt_webhook_data(request_data)
    
    headers = {
        "Content-Type": "application/json",
        "x-encrypted-data": encrypted_data
    }
    
    response = requests.post(url, headers=headers, json={}, timeout=30)
    return response.status_code == 200, response.json() if response.status_code == 200 else None

def detect_credit_change(token):
    """Détecter le changement de crédit"""
    url = f"http://{API_HOST}:{API_PORT}/fuel-monitor/check-credit-changes"
    headers = {"Authorization": f"Bearer {token}"}
    params = {"partner_id": PARTNER_ID}
    
    response = requests.get(url, headers=headers, params=params, timeout=10)
    if response.status_code == 200:
        return response.json()
    return None

def main():
    print("=" * 80)
    print("🔄 TEST COMPLET DU SCÉNARIO DE DÉTECTION DE CHANGEMENT DE CRÉDIT")
    print("=" * 80)
    print()
    
    # Étape 0: Authentification
    print("📍 ÉTAPE 0: Authentification")
    print("-" * 80)
    token = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJlbXBsb3llZV81MjMiLCJzY29wZXMiOlsicmVhZCIsInBvcyJdLCJpYXQiOjE3NzE1MDUzMTUsImVtcGxveWVlX2lkIjo1MjMsImVtcGxveWVlX25hbWUiOiJBS1BBTiBNYXJpZSBFbHZpcmUiLCJlbXBsb3llZV9tYXRyaWN1bGUiOiJKMDEyNTciLCJwYXJ0bmVyX2lkIjo5ODAyLCJvZG9vX2RiIjoiam5wX2RpcmVjdGUiLCJleHAiOjE3NzE1MzQxMTV9.5BhB8RRMdtPdRfrwXOq-XzknkxgLT2jLVTP4KqAlcVc"
    if not token:
        print("❌ Impossible d'obtenir un token. Test sans authentification...")
        token = None
    else:
        print("✅ Token obtenu")
    print()
    
    # Étape 1: Vider le cache
    print("📍 ÉTAPE 1: Vidage du cache")
    print("-" * 80)
    if token and clear_cache(token):
        print(f"✅ Cache vidé pour partner_id {PARTNER_ID}")
    else:
        print("⚠️  Impossible de vider le cache (ignoré)")
    print()
    
    # Étape 2: Capturer l'état initial
    print("📍 ÉTAPE 2: Capture de l'état initial du crédit")
    print("-" * 80)
    initial_result = capture_initial_credit(token) if token else None
    if initial_result:
        print(f"✅ État initial capturé")
        print(f"   Partenaires vérifiés: {initial_result.get('data', {}).get('total_partners_checked', 0)}")
        print(f"   Cache mis à jour: Oui")
    else:
        print("⚠️  Impossible de capturer l'état initial")
    print()
    
    # Vérifier le cache
    if token:
        cache_status = check_cache_status(token)
        if cache_status:
            entries = cache_status.get('data', {}).get('entries', [])
            for entry in entries:
                if entry['partner_id'] == PARTNER_ID:
                    print(f"📊 Cache actuel pour partner {PARTNER_ID}:")
                    print(f"   Crédit: {entry['credit']} CFA")
                    print()
    
    # Étape 3: Créer une écriture comptable
    print("📍 ÉTAPE 3: Création d'une écriture comptable")
    print("-" * 80)
    amount = 5000  # 5000 CFA
    print(f"   Montant: {amount} CFA")
    print(f"   Partenaire: JSI VOYAGES (ID: {PARTNER_ID})")
    print()
    
    success, result = create_accounting_entry(amount)
    if success:
        print("✅ Écriture comptable créée avec succès!")
        if result and result.get('data'):
            data = result['data']
            print(f"   Move ID: {data.get('move_id')}")
            print(f"   Move Name: {data.get('move_name')}")
            print(f"   Ancien solde: {data.get('old_balance')} CFA")
            print(f"   Nouveau solde: {data.get('new_balance')} CFA")
    else:
        print(f"❌ Erreur lors de la création de l'écriture")
        print(f"   Détails: {result}")
        return False
    print()
    
    # Étape 4: Attendre un instant
    print("⏳ Attente de 2 secondes...")
    time.sleep(2)
    print()
    
    # Étape 5: Détecter le changement
    print("📍 ÉTAPE 5: Détection du changement de crédit")
    print("-" * 80)
    detection_result = detect_credit_change(token) if token else None
    if detection_result:
        data = detection_result.get('data', {})
        changes = data.get('changes_detected', [])
        
        if len(changes) > 0:
            print(f"✅ ✅ ✅ CHANGEMENT DÉTECTÉ!")
            print()
            for change in changes:
                print(f"   Partenaire: {change.get('partner_name')}")
                print(f"   Crédit précédent: {change.get('previous_credit')} CFA")
                print(f"   Crédit actuel: {change.get('current_credit')} CFA")
                print(f"   Montant ajouté: +{change.get('amount_added')} CFA")
                print(f"   Détecté à: {change.get('detected_at')}")
            print()
            print("🎉 Le webhook devrait avoir été envoyé à:")
            print(f"   https://api-jnp-dev.opensi.co/public/odoo/webhook")
            print()
            return True
        else:
            print(f"❌ Aucun changement détecté")
            print(f"   Partenaires vérifiés: {data.get('total_partners_checked', 0)}")
            print(f"   Taille du cache: {data.get('cache_size', 0)}")
            print()
            print("💡 Cela peut arriver si:")
            print("   1. Le cache n'a pas été vidé avant")
            print("   2. L'authentification a échoué")
            return False
    else:
        print("❌ Erreur lors de la détection")
        return False

if __name__ == "__main__":
    try:
        success = main()
        print()
        print("=" * 80)
        if success:
            print("✅ TEST RÉUSSI!")
        else:
            print("❌ TEST ÉCHOUÉ")
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
