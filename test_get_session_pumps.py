#!/usr/bin/env python3
"""
Test de récupération des pompes d'une session POS
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

def test_get_session_pumps():
    """Test de récupération des pompes d'une session"""
    
    print("=" * 80)
    print("TEST: Récupération des pompes d'une session POS")
    print("=" * 80)
    
    # 1. Authentification
    print("\n1. Authentification...")
    token = get_auth_token()
    print("✅ Token obtenu")
    
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    
    # 2. Configuration du test (MODIFIER CES VALEURS)
    pos_id = 1  # ID de votre point de vente
    session_id = 123  # ID de la session dont vous voulez récupérer les pompes
    
    print(f"\n2. Récupération des pompes pour la session {session_id}...")
    
    # 3. Appeler la route GET
    response = requests.get(
        f"{API_BASE_URL}/pos/{pos_id}/session/{session_id}/pumps",
        headers=headers
    )
    
    print(f"\nStatus Code: {response.status_code}")
    
    if response.status_code == 200:
        result = response.json()
        
        print("\n✅ Pompes récupérées avec succès!")
        print(f"\nNombre de pompes: {result.get('count', 0)}")
        print(f"Message: {result.get('message', '')}")
        
        print("\n📊 Détail des pompes:\n")
        print("-" * 80)
        
        pumps = result.get('data', [])
        
        if not pumps:
            print("⚠️ Aucune pompe trouvée pour cette session")
            print("\nRaisons possibles:")
            print("  - La session n'a pas été ouverte avec des pompes")
            print("  - Le session_id est incorrect")
            print("  - Les pompes n'ont pas été sauvegardées lors de l'ouverture")
        else:
            for i, pump in enumerate(pumps, 1):
                print(f"\n🔹 Pompe #{i}: {pump.get('name', 'N/A')}")
                print(f"   ID: {pump.get('id')}")
                print(f"   Type: {pump.get('type')}")
                print(f"   Station: {pump.get('stationId')}")
                print(f"   Produit: {pump.get('product_name', 'N/A')} (ID: {pump.get('product_id', 'N/A')})")
                print(f"   Index départ: {pump.get('start_index', 0):.2f} L")
                print(f"   Index actuel: {pump.get('current_index', 0):.2f} L")
                print(f"   Quantité vendue: {pump.get('quantity_available', 0):.2f} L")
                print(f"   Disponible: {'✅ Oui' if pump.get('available') else '❌ Non'}")
                print("-" * 80)
        
        # 4. Afficher le JSON brut pour référence
        print("\n📄 JSON brut de la réponse:")
        print(json.dumps(result, indent=2, ensure_ascii=False))
        
    elif response.status_code == 404:
        print(f"\n❌ Erreur 404: {response.json().get('detail', 'Session non trouvée')}")
        print("\nVérifiez que:")
        print(f"  - Le POS ID {pos_id} existe")
        print(f"  - La session ID {session_id} existe et appartient à ce POS")
    elif response.status_code == 401:
        print("\n❌ Erreur 401: Authentification invalide")
    else:
        print(f"\n❌ Erreur {response.status_code}:")
        print(json.dumps(response.json(), indent=2, ensure_ascii=False))
    
    print("\n" + "=" * 80)
    print("Test terminé!")
    print("=" * 80)

def test_get_session_status_first():
    """
    Test alternatif: Récupérer d'abord le statut de la session active
    puis récupérer les pompes
    """
    print("\n" + "=" * 80)
    print("TEST ALTERNATIF: Récupération via statut de session")
    print("=" * 80)
    
    token = get_auth_token()
    headers = {"Authorization": f"Bearer {token}"}
    
    pos_id = 1  # Modifier selon votre POS
    
    # 1. Récupérer le statut de la session active
    print(f"\n1. Récupération du statut de session pour POS {pos_id}...")
    response = requests.get(
        f"{API_BASE_URL}/pos/{pos_id}/session-status",
        headers=headers
    )
    
    if response.status_code == 200:
        status = response.json()
        
        if status.get('has_active_session'):
            session_id = status.get('session_id')
            print(f"✅ Session active trouvée: {session_id}")
            print(f"   État: {status.get('session_state')}")
            
            # 2. Récupérer les pompes de cette session
            print(f"\n2. Récupération des pompes de la session {session_id}...")
            response = requests.get(
                f"{API_BASE_URL}/pos/{pos_id}/session/{session_id}/pumps",
                headers=headers
            )
            
            if response.status_code == 200:
                result = response.json()
                pumps = result.get('data', [])
                
                print(f"✅ {len(pumps)} pompe(s) récupérée(s)")
                
                for pump in pumps:
                    print(f"\n   🔹 {pump.get('name')}")
                    print(f"      Index: {pump.get('start_index')} → {pump.get('current_index')}")
                    print(f"      Vendu: {pump.get('quantity_available')} L")
            else:
                print(f"❌ Erreur lors de la récupération des pompes: {response.status_code}")
        else:
            print("⚠️ Aucune session active pour ce POS")
    else:
        print(f"❌ Erreur lors de la récupération du statut: {response.status_code}")

if __name__ == "__main__":
    try:
        # Test principal
        test_get_session_pumps()
        
        # Test alternatif
        print("\n\n")
        test_get_session_status_first()
        
    except Exception as e:
        print(f"\n❌ Erreur lors du test: {e}")
        import traceback
        traceback.print_exc()
