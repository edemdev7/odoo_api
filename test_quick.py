#!/usr/bin/env python3
"""Test rapide de l'encryption"""

import sys
sys.path.insert(0, '/home/edem/Téléchargements/odoo_api')

from core.encryption import encrypt_webhook_data

# Test
data = {"action": "TEST", "amount": 100}
print("🔐 Test encryption...")
print(f"Données: {data}")

try:
    encrypted = encrypt_webhook_data(data)
    print(f"✅ Success! Longueur: {len(encrypted)}")
    print(f"Aperçu: {encrypted[:80]}...")
except Exception as e:
    print(f"❌ Erreur: {e}")
    import traceback
    traceback.print_exc()
