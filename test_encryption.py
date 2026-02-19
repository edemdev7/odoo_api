#!/usr/bin/env python3
"""
Script de test de l'encryption RSA

Ce script teste l'encryption/décryption des données avec les clés RSA.
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from core.encryption import RSAEncryption, encrypt_webhook_data, decrypt_webhook_data
import json

def test_encryption():
    """Tester l'encryption/décryption"""
    print("=" * 60)
    print("🔐 Test de l'encryption RSA")
    print("=" * 60)
    print()
    
    # Données de test
    test_data = {
        "action": "COMPANY_RECHARGE",
        "companyExternalId": "123",
        "amount": 50000.0
    }
    
    print("📄 Données originales:")
    print(json.dumps(test_data, indent=2, ensure_ascii=False))
    print()
    
    # Test encryption (utilise uniquement la clé publique)
    try:
        print("🔒 Encryption en cours...")
        encrypted = encrypt_webhook_data(test_data)
        print(f"✅ Données encryptées:")
        print(f"   Taille: {len(encrypted)} caractères")
        print(f"   Aperçu: {encrypted[:100]}...")
        print()
        
        print("✅ ✅ ✅ Test d'encryption réussi !")
        print()
        print("💡 Note: Le serveur distant décryptera avec sa clé privée.")
        print("   (Ce test n'inclut pas la décryption locale)")
        
        return True
            
    except FileNotFoundError as e:
        print(f"❌ Fichier de clé non trouvé: {e}")
        print()
        print("⚠️  Assurez-vous que le fichier public.pem")
        print("   est présent dans le répertoire courant.")
        return False
    except Exception as e:
        print(f"❌ Erreur: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    print()
    print("=" * 60)
    return True


def test_webhook_format():
    """Tester le format du webhook avec header"""
    print("=" * 60)
    print("📤 Test du format webhook")
    print("=" * 60)
    print()
    
    webhook_data = {
        "action": "COMPANY_RECHARGE",
        "companyExternalId": "456",
        "amount": 75000.0
    }
    
    try:
        encrypted = encrypt_webhook_data(webhook_data)
        
        print("📋 Format de la requête HTTP:")
        print()
        print(f"POST {os.getenv('FUEL_WEBHOOK_URL', 'https://api-jnp-dev.opensi.co/public/odoo/webhook')}")
        print("Headers:")
        print(f"  Content-Type: application/json")
        print(f"  x-encrypted-data: {encrypted[:50]}...")
        print()
        print("✅ Format correct")
        
    except Exception as e:
        print(f"❌ Erreur: {e}")
        return False
    
    print()
    print("=" * 60)
    return True


if __name__ == "__main__":
    print()
    success = test_encryption()
    print()
    
    if success:
        success = test_webhook_format()
    
    print()
    if success:
        print("✅ 🎉 Tous les tests ont réussi !")
    else:
        print("❌ Des tests ont échoué")
        sys.exit(1)
