#!/usr/bin/env python3
"""Test endpoint for transfers with location details - using urllib"""

import json
import sys
import subprocess
from datetime import datetime, timedelta
from urllib.request import urlopen, Request
from urllib.error import URLError

# Configuration
JWT_SECRET_KEY = "9ff474f4142fa5b28dfc3c6f8f10e4c5"
BASE_URL = "http://127.0.0.1:8002"
POS_ID = 4  # JO27 ALLADA

# Générer JWT token
print("🔑 Génération du JWT token...")
result = subprocess.run([
    sys.executable, "-c",
    f"""
import jwt
from datetime import datetime, timedelta
payload = {{"sub": "admin@jnpgroupe.com", "user_id": 2, "scopes": ["pos"], "db": "OMHI-TEST", "exp": int((datetime.utcnow() + timedelta(hours=1)).timestamp())}}
print(jwt.encode(payload, "{JWT_SECRET_KEY}", algorithm="HS256"))
"""
], capture_output=True, text=True)

if result.returncode != 0:
    print(f"❌ Erreur génération token: {result.stderr}")
    sys.exit(1)

token = result.stdout.strip()
print(f"✅ Token généré: {token[:50]}...")

# Appeler l'endpoint
url = f"{BASE_URL}/api/pos/{POS_ID}/inventory/transfers"
headers = {
    "Authorization": f"Bearer {token}",
    "Content-Type": "application/json"
}

print(f"\n📡 Appel: GET {url}")

try:
    req = Request(url, headers=headers)
    with urlopen(req, timeout=30) as response:
        print(f"✅ Status Code: {response.status}")
        
        data = json.loads(response.read().decode())
        print(f"\n📊 Résultats:")
        print(f"  - Total transferts: {data.get('count', 0)}")
        
        transfers = data.get('data', {}).get('transfers', [])
        print(f"  - Transferts retournés: {len(transfers)}")
        
        if transfers:
            print(f"\n🔍 Détails du premier transfert:")
            t = transfers[0]
            print(f"  ID: {t.get('id')}")
            print(f"  Nom: {t.get('name')}")
            print(f"  État: {t.get('state')}")
            print(f"  location_id (tuple): {t.get('location_id')}")
            print(f"  location_dest_id (tuple): {t.get('location_dest_id')}")
            
            # Vérifier les nouveaux champs
            source = t.get('location_source_details')
            dest = t.get('location_destination_details')
            
            print(f"\n✨ NOUVEAUX CHAMPS (location details):")
            if source:
                print(f"\n  📤 location_source_details (SOURCE):")
                print(f"    - id: {source.get('id')}")
                print(f"    - name: {source.get('name')}")
                print(f"    - complete_name: {source.get('complete_name')}")
                print(f"    - usage: {source.get('usage')}")
                print(f"    - partner_id: {source.get('partner_id')}")
                print(f"    - warehouse_id: {source.get('warehouse_id')}")
            else:
                print(f"  ❌ location_source_details: None ou absent")
            
            if dest:
                print(f"\n  📥 location_destination_details (DESTINATION):")
                print(f"    - id: {dest.get('id')}")
                print(f"    - name: {dest.get('name')}")
                print(f"    - complete_name: {dest.get('complete_name')}")
                print(f"    - usage: {dest.get('usage')}")
                print(f"    - partner_id: {dest.get('partner_id')}")
                print(f"    - warehouse_id: {dest.get('warehouse_id')}")
            else:
                print(f"  ❌ location_destination_details: None ou absent")
            
            # Test réussi si les deux champs sont présents
            if source and dest:
                print(f"\n✅ TEST RÉUSSI! Les deux localisations sont enrichies!")
                print(f"\nRésumé du transfert:")
                print(f"  De: {source.get('complete_name')} (ID: {source.get('id')})")
                print(f"  Vers: {dest.get('complete_name')} (ID: {dest.get('id')})")
            else:
                print(f"\n⚠️ TEST PARTIEL - Au moins un champ manque")
                print(f"  Source présent: {bool(source)}")
                print(f"  Destination présente: {bool(dest)}")

except URLError as e:
    print(f"\n❌ Erreur connexion: {e}")
    print(f"  Vérifiez que le serveur est lancé sur {BASE_URL}")
except json.JSONDecodeError as e:
    print(f"\n❌ Erreur parsing JSON: {e}")
except Exception as e:
    print(f"\n❌ Exception: {e}")
    import traceback
    traceback.print_exc()
