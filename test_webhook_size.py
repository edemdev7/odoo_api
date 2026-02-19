#!/usr/bin/env python3
"""
Test de la taille des données du webhook sans compression
"""

import json

# Données du webhook
webhook_data = {
    "action": "COMPANY_RECHARGE",
    "companyExternalId": "4708",
    "amount": 5000.0
}

# Convertir en JSON minimisé
json_str = json.dumps(webhook_data, ensure_ascii=False, separators=(',', ':'))
json_bytes = json_str.encode('utf-8')

print(f"📊 Taille des données du webhook:")
print(f"   JSON: {json_str}")
print(f"   Taille: {len(json_bytes)} bytes")
print(f"   Limite RSA 2048 + OAEP SHA256: ~190 bytes")
print(f"   ✅ Compatible: {len(json_bytes) <= 190}")
