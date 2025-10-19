#!/usr/bin/env python3
"""
Test de l'endpoint de changement d'état des transferts corrigé
"""

import requests
import json

def test_transfer_state_change():
    # Configuration
    base_url = "http://127.0.0.1:8000"
    
    # Données d'authentification
    auth_data = {
        'username': 'edem.senatsi@eduplus.edu',
        'password': 'Eduplus@2024'
    }
    
    try:
        # 1. Authentification
        print("🔐 Authentification...")
        auth_response = requests.post(f'{base_url}/auth/login', json=auth_data)
        print(f"Auth Status: {auth_response.status_code}")
        
        if auth_response.status_code != 200:
            print(f"❌ Erreur auth: {auth_response.text}")
            return
            
        token = auth_response.json()['access_token']
        headers = {'Authorization': f'Bearer {token}'}
        print("✅ Authentification réussie")
        
        # 2. Vérifier l'état actuel du transfert 76
        print(f"\n📋 Vérification état actuel transfert 76...")
        response = requests.get(f'{base_url}/pos/3/inventory/transfers?state=assigned&limit=10', headers=headers)
        
        if response.status_code == 200:
            data = response.json()
            transfer_76 = None
            for t in data['data']['transfers']:
                if t['id'] == 76:
                    transfer_76 = t
                    break
            
            if transfer_76:
                print(f"✅ Transfert trouvé: {transfer_76['name']}")
                print(f"   État actuel: {transfer_76['state']}")
                print(f"   Disponibilité: {transfer_76.get('products_availability', 'N/A')}")
                
                # Afficher les move_line_details
                if transfer_76.get('move_line_details'):
                    print(f"   Opérations détaillées:")
                    for line in transfer_76['move_line_details'][:2]:
                        print(f"     - ID {line['id']}: Qté={line['quantity']}, Réalisé={line['qty_done']}")
            else:
                print("⚠️ Transfert 76 non trouvé dans les transferts assigned")
                return
        
        # 3. Changer l'état vers 'done' avec force=true
        print(f"\n🔄 Changement d'état vers 'done' avec force=true...")
        
        update_data = {
            'picking_ids': [76],
            'action': 'done',
            'force': True
        }
        
        update_response = requests.put(
            f'{base_url}/pos/3/inventory/transfers/update-state',
            json=update_data,
            headers=headers
        )
        
        print(f"Update Status: {update_response.status_code}")
        
        if update_response.status_code == 200:
            result = update_response.json()
            print("✅ Réponse de l'update:")
            print(f"   Succès: {result['success']}")
            print(f"   Message: {result['message']}")
            
            if result['data']['results']:
                for res in result['data']['results']:
                    print(f"   - ID {res['id']}: {res['previous_state']} → {res['new_state']} (success: {res['success']})")
            
            if result['data'].get('errors'):
                print(f"   Erreurs: {result['data']['errors']}")
        else:
            print(f"❌ Erreur update: {update_response.text}")
            return
            
        # 4. Vérifier l'état après changement
        print(f"\n🔍 Vérification état après changement...")
        # Attendre un peu pour que la base soit mise à jour
        import time
        time.sleep(2)
        
        # Chercher dans tous les états maintenant
        response = requests.get(f'{base_url}/pos/3/inventory/transfers?limit=50', headers=headers)
        
        if response.status_code == 200:
            data = response.json()
            transfer_76_after = None
            for t in data['data']['transfers']:
                if t['id'] == 76:
                    transfer_76_after = t
                    break
            
            if transfer_76_after:
                print(f"✅ Transfert après changement:")
                print(f"   État: {transfer_76_after['state']}")
                print(f"   Date réalisation: {transfer_76_after.get('date_done', 'N/A')}")
                print(f"   Disponibilité: {transfer_76_after.get('products_availability', 'N/A')}")
                
                # Vérifier les move_lines après
                if transfer_76_after.get('move_line_details'):
                    print(f"   Opérations après changement:")
                    for line in transfer_76_after['move_line_details'][:2]:
                        print(f"     - ID {line['id']}: Qté={line['quantity']}, Réalisé={line['qty_done']}, État={line.get('state', 'N/A')}")
            else:
                print("⚠️ Transfert 76 non trouvé après changement")
        else:
            print(f"❌ Erreur vérification: {response.text}")
            
    except Exception as e:
        print(f"❌ Erreur lors du test: {e}")

if __name__ == "__main__":
    test_transfer_state_change()
