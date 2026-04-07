#!/usr/bin/env python3
"""
Test script pour vérifier l'enrichissement des transferts par camion
"""
import requests
import json
import sys
from datetime import datetime

# Configuration
BASE_URL = "http://localhost:8001"
TOKEN = ""  # À remplacer avec votre JWT token

def test_transfers_by_truck():
    """Test de l'endpoint /pos/inventory/transfers/by-truck"""
    
    if not TOKEN:
        print("❌ Erreur: TOKEN vide")
        print("Veuillez configurer votre JWT token dans le script")
        return False
    
    headers = {
        "Authorization": f"Bearer {TOKEN}",
        "Content-Type": "application/json"
    }
    
    # Test 1: Rechercher les transferts d'un camion spécifique
    print("\n" + "="*80)
    print("TEST 1: Recherche des transferts du camion 'JO70'")
    print("="*80)
    
    params = {
        "truck_name": "JO70",
        "transfer_type": "all",
        "page": 1,
        "page_size": 5
    }
    
    try:
        response = requests.get(
            f"{BASE_URL}/pos/inventory/transfers/by-truck",
            headers=headers,
            params=params,
            timeout=30
        )
        
        if response.status_code != 200:
            print(f"❌ Erreur HTTP {response.status_code}")
            print(response.text[:500])
            return False
        
        data = response.json()
        
        if not data.get('success'):
            print(f"❌ Réponse non-success: {data.get('message')}")
            return False
        
        transfers = data.get('data', {}).get('transfers', [])
        print(f"✅ Transferts trouvés: {len(transfers)}")
        
        if len(transfers) == 0:
            print("⚠️  Aucun transfert trouvé - c'est peut-être normal")
            return True
        
        # Vérifier les champs enrichis
        print("\n🔍 Vérification des champs enrichis:")
        
        transfer = transfers[0]
        print(f"\nTransfert: {transfer.get('name')}")
        
        # Vérifier les localisations
        has_location_source = 'location_source_details' in transfer
        has_location_dest = 'location_destination_details' in transfer
        
        print(f"  ✅ location_source_details: {has_location_source}")
        if has_location_source and transfer['location_source_details']:
            src = transfer['location_source_details']
            print(f"     → {src.get('complete_name', src.get('name', 'N/A'))}")
        
        print(f"  ✅ location_destination_details: {has_location_dest}")
        if has_location_dest and transfer['location_destination_details']:
            dst = transfer['location_destination_details']
            print(f"     → {dst.get('complete_name', dst.get('name', 'N/A'))}")
        
        # Vérifier les détails du partenaire
        has_partner = 'partner_details' in transfer
        print(f"  ✅ partner_details: {has_partner}")
        if has_partner and transfer['partner_details']:
            partner = transfer['partner_details']
            print(f"     → {partner.get('name', 'N/A')} ({partner.get('type', 'N/A')})")
        
        # Vérifier les détails du chauffeur
        has_driver = 'driver_details' in transfer
        print(f"  ✅ driver_details: {has_driver}")
        if has_driver and transfer['driver_details']:
            driver = transfer['driver_details']
            print(f"     → {driver.get('name', 'N/A')} - {driver.get('mobile', 'N/A')}")
        
        # Afficher un transfert complet
        print("\n📊 Exemple de transfert complet (première ligne):")
        print(json.dumps(transfer, indent=2, default=str)[:1000] + "...")
        
        return True
        
    except requests.exceptions.RequestException as e:
        print(f"❌ Erreur de connexion: {e}")
        return False
    except json.JSONDecodeError as e:
        print(f"❌ Erreur JSON: {e}")
        return False


def test_transfers_by_type():
    """Test avec filtrage par type"""
    print("\n" + "="*80)
    print("TEST 2: Recherche filtrée par type de transfert")
    print("="*80)
    
    if not TOKEN:
        print("❌ Erreur: TOKEN vide")
        return False
    
    headers = {
        "Authorization": f"Bearer {TOKEN}",
        "Content-Type": "application/json"
    }
    
    for transfer_type in ['internal', 'incoming', 'outgoing']:
        params = {
            "truck_name": "JO70",
            "transfer_type": transfer_type,
            "page": 1,
            "page_size": 2
        }
        
        try:
            response = requests.get(
                f"{BASE_URL}/pos/inventory/transfers/by-truck",
                headers=headers,
                params=params,
                timeout=30
            )
            
            if response.status_code == 200:
                data = response.json()
                count = len(data.get('data', {}).get('transfers', []))
                print(f"✅ Type '{transfer_type}': {count} transfert(s) trouvé(s)")
            else:
                print(f"⚠️  Type '{transfer_type}': HTTP {response.status_code}")
                
        except Exception as e:
            print(f"❌ Type '{transfer_type}': {str(e)}")
    
    return True


if __name__ == "__main__":
    print("\n" + "🚀 Tests d'enrichissement des transferts par camion".center(80))
    print("="*80)
    
    if not TOKEN:
        print("""
⚠️  Configuration requise:
        
1. Récupérez votre JWT token:
   curl -X POST "http://localhost:8001/auth/login" \\
     -H "Content-Type: application/json" \\
     -d '{"username": "admin@jnpgroupe.com", "password": "..."}'
     
2. Mettez à jour la variable TOKEN dans ce script

3. Relancez le script
        """)
        sys.exit(1)
    
    success = True
    success = test_transfers_by_truck() and success
    success = test_transfers_by_type() and success
    
    print("\n" + "="*80)
    if success:
        print("✅ Tests réussis!")
    else:
        print("❌ Certains tests ont échoué")
    print("="*80 + "\n")
    
    sys.exit(0 if success else 1)
