#!/usr/bin/env python3
"""
Test complet encryption/decryption avec les nouvelles clés
"""

import sys
sys.path.insert(0, '/home/edem/Téléchargements/odoo_api')

from core.encryption import encrypt_webhook_data, decrypt_webhook_data
import json

def test_full_cycle():
    """Test complet d'encryption/décryption"""
    
    print("=" * 70)
    print("🔄 Test complet Encryption/Decryption avec nouvelles clés")
    print("=" * 70)
    print()
    
    # Données de test (comme celles envoyées à l'API)
    test_data = {
        "partner_id": 4708,
        "amount": 10000,
        "reference": "TEST-ECRITURE-001",
        "description": "Test écriture comptable - Montant: 10000"
    }
    
    print("📄 Données originales:")
    print(json.dumps(test_data, indent=2, ensure_ascii=False))
    print()
    
    try:
        # 1. Encryption (ce que fait le client)
        print("🔒 ÉTAPE 1: Encryption des données...")
        encrypted = encrypt_webhook_data(test_data)
        print(f"✅ Encryption réussie")
        print(f"   Longueur: {len(encrypted)} caractères")
        print(f"   Aperçu: {encrypted[:80]}...")
        print()
        
        # 2. Décryption (ce que fait le serveur)
        print("🔓 ÉTAPE 2: Decryption des données...")
        decrypted = decrypt_webhook_data(encrypted)
        print(f"✅ Decryption réussie")
        print()
        
        print("📄 Données décryptées:")
        print(json.dumps(decrypted, indent=2, ensure_ascii=False))
        print()
        
        # 3. Vérification
        print("🔍 ÉTAPE 3: Vérification...")
        if decrypted == test_data:
            print("✅ ✅ ✅ SUCCÈS! Les données sont identiques!")
            print()
            print("=" * 70)
            print("💡 Conclusion:")
            print("   L'encryption/décryption fonctionne parfaitement!")
            print("   Le serveur DOIT être redémarré pour charger les nouvelles clés.")
            print("=" * 70)
            return True
        else:
            print("❌ ÉCHEC! Les données ne correspondent pas")
            print()
            print("Différences:")
            for key in test_data:
                if test_data[key] != decrypted.get(key):
                    print(f"  {key}: {test_data[key]} != {decrypted.get(key)}")
            return False
            
    except Exception as e:
        print(f"❌ Erreur: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = test_full_cycle()
    exit(0 if success else 1)
