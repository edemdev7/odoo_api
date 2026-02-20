#!/usr/bin/env python3
"""
Test du système de surveillance automatique des crédits
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import requests
import time

API_HOST = "localhost"
API_PORT = 8002

def get_token():
    """Obtenir un token d'authentification"""
    url = f"http://{API_HOST}:{API_PORT}/auth/pin-login"
    payload = {
        "pin_code": "0000",
        "database": "jnp_directe"
    }
    
    response = requests.post(url, json=payload, timeout=10)
    if response.status_code == 200:
        result = response.json()
        return result.get("data", {}).get("access_token")
    return None

def check_scheduler_status(token):
    """Vérifier le statut du scheduler"""
    url = f"http://{API_HOST}:{API_PORT}/fuel-monitor/scheduler/status"
    headers = {"Authorization": f"Bearer {token}"}
    
    response = requests.get(url, headers=headers, timeout=10)
    if response.status_code == 200:
        return response.json()
    return None

def trigger_check_now(token):
    """Forcer une vérification immédiate"""
    url = f"http://{API_HOST}:{API_PORT}/fuel-monitor/scheduler/check-now"
    headers = {"Authorization": f"Bearer {token}"}
    
    response = requests.post(url, headers=headers, timeout=10)
    return response.status_code == 200

def clear_cache(token):
    """Vider le cache"""
    url = f"http://{API_HOST}:{API_PORT}/fuel-monitor/cache/clear"
    headers = {"Authorization": f"Bearer {token}"}
    
    response = requests.delete(url, headers=headers, timeout=10)
    return response.status_code == 200

def main():
    print("=" * 80)
    print("🔄 TEST DU SYSTÈME DE SURVEILLANCE AUTOMATIQUE")
    print("=" * 80)
    print()
    
    # Authentification
    print("📍 Authentification...")
    token = get_token()
    if not token:
        print("❌ Impossible d'obtenir un token")
        return False
    print("✅ Token obtenu")
    print()
    
    # Vérifier le statut du scheduler
    print("📍 Vérification du statut du scheduler...")
    print("-" * 80)
    status = check_scheduler_status(token)
    if status:
        data = status.get('data', {})
        print(f"✅ Scheduler: {'ACTIF' if data.get('is_running') else 'INACTIF'}")
        print(f"   Cache: {data.get('cache_size')} entrée(s)")
        print(f"   Webhook URL: {data.get('webhook_url')}")
        print(f"   Intervalle: {data.get('check_interval_seconds')} secondes")
        print()
        
        if not data.get('is_running'):
            print("⚠️  Le scheduler n'est pas actif !")
            print("   Le serveur FastAPI doit être démarré pour que le scheduler fonctionne.")
            return False
    else:
        print("❌ Impossible de récupérer le statut")
        return False
    
    # Vider le cache pour préparer le test
    print("📍 Préparation du test (vidage du cache)...")
    print("-" * 80)
    if clear_cache(token):
        print("✅ Cache vidé")
    else:
        print("⚠️  Échec du vidage du cache (ignoré)")
    print()
    
    # Forcer une vérification pour initialiser le cache
    print("📍 Initialisation du cache...")
    print("-" * 80)
    if trigger_check_now(token):
        print("✅ Vérification déclenchée")
        print("⏳ Attente de 3 secondes...")
        time.sleep(3)
    print()
    
    # Vérifier le cache après initialisation
    status = check_scheduler_status(token)
    if status:
        cache_size = status.get('data', {}).get('cache_size', 0)
        print(f"📊 Cache après initialisation: {cache_size} entrée(s)")
        print()
    
    # Instructions pour la suite du test
    print("=" * 80)
    print("✅ SYSTÈME PRÊT POUR LE TEST")
    print("=" * 80)
    print()
    print("🎯 Pour tester la détection automatique:")
    print()
    print("1. Créez une écriture comptable:")
    print("   python3 test_accounting_quick.py")
    print()
    print("2. Le scheduler détectera automatiquement le changement dans les 60 secondes")
    print("   (ou utilisez le test de scénario complet)")
    print()
    print("3. Surveillez les logs du serveur FastAPI:")
    print("   grep 'SCHEDULER' dans les logs")
    print()
    print("4. Vous devriez voir:")
    print("   - [SCHEDULER] Crédit augmenté détecté")
    print("   - [SCHEDULER] Webhook envoyé avec succès")
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
