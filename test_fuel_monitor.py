#!/usr/bin/env python3
"""
Test du fuel monitor - Détection de changement de crédit et envoi de webhook
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import requests
import json
from datetime import datetime

# Configuration
API_HOST = "localhost"
API_PORT = 8002

def test_credit_change_detection():
    """Test de la détection de changement de crédit"""
    
    print("=" * 70)
    print("⛽ Test du Fuel Monitor - Détection de changement de crédit")
    print("=" * 70)
    print()
    
    # ID de l'entreprise à surveiller (JSI VOYAGES)
    partner_id = 4708
    
    print(f"📋 Configuration:")
    print(f"   Partner ID: {partner_id}")
    print(f"   Endpoint: http://{API_HOST}:{API_PORT}/fuel-monitor/check-credit-changes")
    print()
    
    try:
        # 1. Vérifier l'état actuel du crédit
        print("🔍 ÉTAPE 1: Vérification de l'état actuel du crédit...")
        url = f"http://{API_HOST}:{API_PORT}/fuel-monitor/check-credit-changes"
        
        params = {"partner_id": partner_id}
        
        response = requests.get(url, params=params, timeout=30)
        
        if response.status_code == 200:
            result = response.json()
            print(f"✅ Réponse reçue")
            print()
            print(json.dumps(result, indent=2, ensure_ascii=False))
            print()
            
            # Analyser les changements détectés
            if result.get("success") and result.get("data"):
                data = result["data"]
                changes_detected = data.get("changes_detected", 0)
                partners_checked = data.get("partners_checked", 0)
                
                print("=" * 70)
                print("📊 RÉSUMÉ")
                print("=" * 70)
                print(f"✅ Partenaires vérifiés: {partners_checked}")
                print(f"🔔 Changements détectés: {changes_detected}")
                print()
                
                if changes_detected > 0 and data.get("changes"):
                    print("💡 Changements de crédit détectés:")
                    for change in data["changes"]:
                        print(f"   - {change.get('partner_name', 'N/A')} (ID: {change.get('partner_id')})")
                        print(f"     Ancien: {change.get('old_credit', 0)} CFA")
                        print(f"     Nouveau: {change.get('new_credit', 0)} CFA")
                        print(f"     Différence: +{change.get('difference', 0)} CFA")
                        print(f"     Webhook envoyé: {'✅' if change.get('webhook_sent') else '❌'}")
                        print()
                else:
                    print("ℹ️  Aucun changement détecté (c'est normal pour le premier appel)")
                    print("   Le système a mis en cache la valeur actuelle.")
                    print()
                    print("💡 Pour tester la détection de changement:")
                    print("   1. Créez une écriture comptable avec test_accounting_quick.py")
                    print("   2. Relancez ce test pour voir le changement détecté")
                
                return True
        else:
            print(f"❌ Erreur HTTP {response.status_code}")
            print(f"Réponse: {response.text}")
            return False
            
    except requests.exceptions.ConnectionError:
        print("❌ Erreur: Impossible de se connecter à l'API")
        print("   Assurez-vous que le serveur FastAPI est démarré:")
        print(f"   uvicorn main:app --host 0.0.0.0 --port {API_PORT} --reload")
        return False
    except Exception as e:
        print(f"❌ Erreur: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_full_scenario():
    """Test du scénario complet: écriture comptable + détection changement"""
    
    print("\n\n")
    print("=" * 70)
    print("🔄 Test du scénario complet")
    print("=" * 70)
    print()
    
    partner_id = 4708
    
    print("Ce test va:")
    print("1. Vérifier l'état initial du crédit")
    print("2. Créer une écriture comptable de 1000 CFA")
    print("3. Re-vérifier le crédit pour détecter le changement")
    print()
    
    # Étape 1: État initial
    print("📍 ÉTAPE 1: État initial")
    print("-" * 70)
    url = f"http://{API_HOST}:{API_PORT}/fuel-monitor/check-credit-changes"
    response = requests.get(url, params={"partner_id": partner_id}, timeout=30)
    
    if response.status_code == 200:
        result = response.json()
        initial_credit = None
        if result.get("data", {}).get("cache_updated"):
            for update in result["data"]["cache_updated"]:
                if update.get("partner_id") == partner_id:
                    initial_credit = update.get("current_credit")
        print(f"✅ Crédit initial capturé: {initial_credit} CFA")
    else:
        print(f"❌ Erreur: {response.status_code}")
        return False
    
    print()
    input("⏸️  Appuyez sur Entrée après avoir créé une écriture comptable...")
    print()
    
    # Étape 2: Détection du changement
    print("📍 ÉTAPE 2: Détection du changement")
    print("-" * 70)
    response = requests.get(url, params={"partner_id": partner_id}, timeout=30)
    
    if response.status_code == 200:
        result = response.json()
        if result.get("data", {}).get("changes_detected", 0) > 0:
            print("✅ ✅ ✅ Changement détecté!")
            changes = result["data"].get("changes", [])
            for change in changes:
                print(f"   Partenaire: {change.get('partner_name')}")
                print(f"   Ancien crédit: {change.get('old_credit')} CFA")
                print(f"   Nouveau crédit: {change.get('new_credit')} CFA")
                print(f"   Différence: +{change.get('difference')} CFA")
                print(f"   Webhook envoyé: {'✅' if change.get('webhook_sent') else '❌'}")
            return True
        else:
            print("ℹ️  Aucun changement détecté")
            return False
    else:
        print(f"❌ Erreur: {response.status_code}")
        return False

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Test du fuel monitor")
    parser.add_argument("--full", action="store_true", help="Test du scénario complet avec pause")
    args = parser.parse_args()
    
    if args.full:
        success = test_full_scenario()
    else:
        success = test_credit_change_detection()
    
    print()
    exit(0 if success else 1)
