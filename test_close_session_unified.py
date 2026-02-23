#!/usr/bin/env python3
"""
Test de fermeture de session POS avec payload unifié (identique à l'ouverture)
"""

import requests
import json
from core.config import API_BASE_URL, EMPLOYEE_USERNAME, EMPLOYEE_PASSWORD

def get_auth_token():
    """Obtenir le token d'authentification"""
    response = requests.post(
        f"{API_BASE_URL}/auth/login",
        json={
            "username": EMPLOYEE_USERNAME,
            "password": EMPLOYEE_PASSWORD
        }
    )
    response.raise_for_status()
    return response.json()["access_token"]

def test_close_session_unified_payload():
    """Test de fermeture avec payload unifié"""
    
    print("=" * 80)
    print("TEST: Fermeture de session POS avec payload unifié")
    print("=" * 80)
    
    # 1. Authentification
    print("\n1. Authentification...")
    token = get_auth_token()
    print("✅ Token obtenu")
    
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    
    # 2. Test avec payload complet (station-service)
    print("\n2. Test fermeture station-service avec payload unifié...")
    
    # IMPORTANT: Remplacez par vos vraies valeurs
    pos_id = 1  # ID de votre POS
    
    # Payload unifié - identique au format d'ouverture
    close_payload = {
        "session_id": 123,  # Optionnel si session active détectée
        "starting_balance": 1000.00,  # Solde d'ouverture pour vérification
        "ending_balance": 5432.10,  # Solde de fermeture
        "pump_indexes": [
            {
                "id": "pump_001",
                "name": "J1_E1", 
                "stationId": "station_001",
                "type": "PETROL",
                "start_index": 1234.56,
                "end_index": 2345.67  # Index de fin pour fermeture
            },
            {
                "id": "pump_002",
                "name": "J1_E2",
                "stationId": "station_001",
                "type": "DIESEL",
                "start_index": 5678.90,
                "end_index": 6789.12
            }
        ],
        "closing_notes": "Fermeture normale - Test payload unifié"
    }
    
    print("\nPayload envoyé:")
    print(json.dumps(close_payload, indent=2, ensure_ascii=False))
    
    response = requests.post(
        f"{API_BASE_URL}/pos/{pos_id}/close-session",
        headers=headers,
        json=close_payload
    )
    
    print(f"\nStatus Code: {response.status_code}")
    print("\nRéponse:")
    print(json.dumps(response.json(), indent=2, ensure_ascii=False))
    
    if response.status_code == 200:
        print("\n✅ Fermeture réussie avec payload unifié!")
        result = response.json()
        print(f"\n📊 Résumé:")
        print(f"   - Session ID: {result.get('session_id')}")
        print(f"   - État: {result.get('state')}")
        print(f"   - Mode station: {result.get('is_station')}")
        print(f"   - Message: {result.get('message')}")
        if 'validation_summary' in result:
            print(f"   - Pompes validées: {result['validation_summary'].get('valid_pumps')}/{result['validation_summary'].get('total_pumps')}")
    else:
        print(f"\n❌ Erreur: {response.json().get('detail', 'Erreur inconnue')}")
    
    # 3. Test mode standard (sans pompes)
    print("\n" + "=" * 80)
    print("3. Test fermeture standard (sans pompes)...")
    
    standard_payload = {
        "starting_balance": 500.00,
        "ending_balance": 1234.56,
        "closing_notes": "Fermeture caisse standard"
    }
    
    print("\nPayload envoyé:")
    print(json.dumps(standard_payload, indent=2, ensure_ascii=False))
    
    response = requests.post(
        f"{API_BASE_URL}/pos/{pos_id}/close-session",
        headers=headers,
        json=standard_payload
    )
    
    print(f"\nStatus Code: {response.status_code}")
    print("\nRéponse:")
    print(json.dumps(response.json(), indent=2, ensure_ascii=False))
    
    if response.status_code == 200:
        print("\n✅ Fermeture standard réussie!")
    else:
        print(f"\n⚠️ Erreur (peut être normal si pas de session active): {response.json().get('detail')}")
    
    print("\n" + "=" * 80)
    print("Tests terminés!")
    print("=" * 80)

if __name__ == "__main__":
    try:
        test_close_session_unified_payload()
    except Exception as e:
        print(f"\n❌ Erreur lors du test: {e}")
        import traceback
        traceback.print_exc()
