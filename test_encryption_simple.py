#!/usr/bin/env python3
"""
Test simplifié de l'encryption RSA
"""

from core.encryption import encrypt_webhook_data
import json

def main():
    print("=" * 60)
    print("🔐 Test d'encryption RSA simplifié")
    print("=" * 60)
    
    # Données de test
    test_data = {
        "action": "COMPANY_RECHARGE",
        "companyExternalId": "123",
        "amount": 50000.0
    }
    
    print("\n📄 Données originales:")
    print(json.dumps(test_data, indent=2))
    
    try:
        # Test encryption (utilise uniquement la clé publique)
        print("\n🔒 Encryption en cours...")
        encrypted = encrypt_webhook_data(test_data)
        print(f"✅ Données encryptées (longueur: {len(encrypted)} caractères)")
        print(f"📦 Aperçu: {encrypted[:100]}...")
        
        print("\n✅ Test d'encryption réussi!")
        print("\n💡 Note: Pour décrypter, le serveur distant utilisera sa clé privée.")
        
        return True
        
    except Exception as e:
        print(f"\n❌ Erreur: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = main()
    exit(0 if success else 1)
