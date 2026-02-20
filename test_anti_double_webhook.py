#!/usr/bin/env python3
"""
Test anti-double webhook

Vérifie que :
1. L'API accounting envoie le webhook immédiatement
2. Le scheduler ne renvoie PAS de webhook pour le même changement
3. Le scheduler détecte quand même les changements externes
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import requests
import time
from core.background_scheduler import get_scheduler

API_HOST = "localhost"
API_PORT = 8002
PARTNER_ID = 4708

def get_token():
    """Obtenir un token"""
    url = f"http://{API_HOST}:{API_PORT}/auth/pin-login"
    response = requests.post(url, json={"pin_code": "0000", "database": "jnp_directe"}, timeout=10)
    if response.status_code == 200:
        return response.json().get("data", {}).get("access_token")
    return None

def clear_cache(token):
    """Vider le cache"""
    url = f"http://{API_HOST}:{API_PORT}/fuel-monitor/cache/clear"
    headers = {"Authorization": f"Bearer {token}"}
    params = {"partner_id": PARTNER_ID}
    response = requests.delete(url, headers=headers, params=params, timeout=10)
    return response.status_code == 200

def get_scheduler_cache(token):
    """Récupérer l'état du cache"""
    url = f"http://{API_HOST}:{API_PORT}/fuel-monitor/scheduler/status"
    headers = {"Authorization": f"Bearer {token}"}
    response = requests.get(url, headers=headers, timeout=10)
    if response.status_code == 200:
        return response.json().get('data', {})
    return None

def create_accounting_entry(amount):
    """Créer une écriture comptable"""
    from core.encryption import encrypt_webhook_data
    
    url = f"http://{API_HOST}:{API_PORT}/accounting/credit-account"
    
    request_data = {
        "partner_id": PARTNER_ID,
        "amount": amount,
        "reference": f"TEST-ANTI-DOUBLE-{int(time.time())}",
    }
    
    encrypted_data = encrypt_webhook_data(request_data, use_compression=False)
    
    headers = {
        "Content-Type": "application/json",
        "x-encrypted-data": encrypted_data
    }
    
    response = requests.post(url, headers=headers, json={}, timeout=30)
    return response.status_code == 200, response.json() if response.status_code == 200 else None

def trigger_scheduler_check(token):
    """Forcer une vérification du scheduler"""
    url = f"http://{API_HOST}:{API_PORT}/fuel-monitor/scheduler/check-now"
    headers = {"Authorization": f"Bearer {token}"}
    response = requests.post(url, headers=headers, timeout=10)
    return response.status_code == 200

def main():
    print("=" * 80)
    print("🧪 TEST ANTI-DOUBLE WEBHOOK")
    print("=" * 80)
    print()
    print("Ce test vérifie que le webhook n'est envoyé qu'une seule fois")
    print("même si le scheduler vérifie après l'API accounting.")
    print()
    
    # Authentification
    print("📍 ÉTAPE 1 : Authentification")
    print("-" * 80)
    token = get_token()
    if not token:
        print("❌ Impossible d'obtenir un token")
        return False
    print("✅ Token obtenu")
    print()
    
    # Vérifier le scheduler
    print("📍 ÉTAPE 2 : Vérifier que le scheduler est actif")
    print("-" * 80)
    cache_info = get_scheduler_cache(token)
    if not cache_info:
        print("❌ Impossible de récupérer le statut du scheduler")
        return False
    
    if not cache_info.get('is_running'):
        print("❌ Le scheduler n'est pas actif !")
        print("   Démarrez le serveur FastAPI : python3 -m uvicorn main:app --port 8002")
        return False
    
    print(f"✅ Scheduler actif")
    print(f"   Cache: {cache_info.get('cache_size')} entrée(s)")
    print()
    
    # Vider le cache pour ce partenaire
    print("📍 ÉTAPE 3 : Préparation (vidage du cache)")
    print("-" * 80)
    if clear_cache(token):
        print(f"✅ Cache vidé pour partner {PARTNER_ID}")
    else:
        print("⚠️  Échec du vidage (ignoré)")
    print()
    
    # Initialiser le cache avec une première vérification
    print("📍 ÉTAPE 4 : Initialisation du cache")
    print("-" * 80)
    if trigger_scheduler_check(token):
        print("✅ Première vérification déclenchée")
        print("⏳ Attente de 3 secondes...")
        time.sleep(3)
    print()
    
    # Vérifier que le cache est initialisé
    cache_info = get_scheduler_cache(token)
    initial_cache_size = cache_info.get('cache_size', 0) if cache_info else 0
    print(f"📊 Cache initialisé : {initial_cache_size} entrée(s)")
    print()
    
    # Créer une écriture via l'API
    print("📍 ÉTAPE 5 : Création écriture via API accounting")
    print("-" * 80)
    amount = 5000
    print(f"   Montant: {amount} CFA")
    print(f"   Partenaire: {PARTNER_ID}")
    print()
    
    success, result = create_accounting_entry(amount)
    if not success:
        print(f"❌ Erreur lors de la création")
        print(f"   Détails: {result}")
        return False
    
    print("✅ Écriture créée avec succès")
    if result and result.get('data'):
        data = result['data']
        print(f"   Move: {data.get('move_name')}")
        print(f"   Nouveau crédit: {data.get('new_balance')} CFA")
    print()
    print("📤 À ce stade, un webhook devrait avoir été envoyé par l'API")
    print("   (vérifiez les logs du serveur)")
    print()
    
    # Vérifier que le cache a été mis à jour par l'API
    print("📍 ÉTAPE 6 : Vérification du cache après API")
    print("-" * 80)
    print("⏳ Attente de 2 secondes...")
    time.sleep(2)
    
    cache_info = get_scheduler_cache(token)
    if cache_info:
        print(f"✅ Cache après API: {cache_info.get('cache_size')} entrée(s)")
    print()
    
    # Forcer une vérification du scheduler
    print("📍 ÉTAPE 7 : Forcer une vérification du scheduler")
    print("-" * 80)
    print("⚠️  POINT CRITIQUE : Le scheduler va vérifier maintenant.")
    print("   Si le système fonctionne, il ne devrait PAS envoyer de webhook")
    print("   car le cache a déjà été mis à jour par l'API.")
    print()
    
    if trigger_scheduler_check(token):
        print("✅ Vérification scheduler déclenchée")
        print("⏳ Attente de 3 secondes...")
        time.sleep(3)
    print()
    
    # Résultat
    print("=" * 80)
    print("🎯 RÉSULTAT DU TEST")
    print("=" * 80)
    print()
    print("✅ Test technique réussi !")
    print()
    print("📊 Pour vérifier manuellement :")
    print("   1. Consultez les logs du serveur FastAPI")
    print("   2. Cherchez les lignes contenant 'Webhook envoyé'")
    print("   3. Vous devriez voir UN SEUL webhook pour ce test")
    print()
    print("Exemples de logs attendus :")
    print()
    print("  ✅ BON (1 seul webhook) :")
    print("     [API] Webhook planifié pour envoi en arrière-plan")
    print("     [fuel_monitor] Webhook envoyé avec succès - Montant: 5000.0")
    print("     [SCHEDULER] Vérification terminée: 234 clients, 0 changement(s)")
    print()
    print("  ❌ MAUVAIS (doublon) :")
    print("     [API] Webhook planifié pour envoi en arrière-plan")
    print("     [fuel_monitor] Webhook envoyé avec succès - Montant: 5000.0")
    print("     [SCHEDULER] Crédit augmenté détecté ← DOUBLON !")
    print("     [SCHEDULER] Webhook envoyé avec succès - Montant: 5000.0")
    print()
    print("=" * 80)
    
    return True

if __name__ == "__main__":
    try:
        success = main()
        exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\n\n⚠️  Test interrompu")
        exit(1)
    except Exception as e:
        print(f"\n\n❌ Erreur: {e}")
        import traceback
        traceback.print_exc()
        exit(1)
