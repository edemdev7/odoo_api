#!/usr/bin/env python3
"""
Test du chargement des clés RSA
"""

import sys
sys.path.insert(0, '/home/edem/Téléchargements/odoo_api')

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend

def test_key_loading(public_file, private_file):
    """Tester le chargement des clés"""
    
    print("=" * 60)
    print(f"🔑 Test de chargement des clés RSA")
    print("=" * 60)
    print()
    
    # Test clé publique
    print(f"📄 Chargement de la clé publique: {public_file}")
    try:
        with open(public_file, 'rb') as f:
            public_key = serialization.load_pem_public_key(
                f.read(),
                backend=default_backend()
            )
        print(f"✅ Clé publique chargée avec succès")
        print(f"   Taille: {public_key.key_size} bits")
        print()
    except Exception as e:
        print(f"❌ Erreur clé publique: {e}")
        return False
    
    # Test clé privée
    print(f"🔐 Chargement de la clé privée: {private_file}")
    try:
        with open(private_file, 'rb') as f:
            private_key = serialization.load_pem_private_key(
                f.read(),
                password=None,
                backend=default_backend()
            )
        print(f"✅ Clé privée chargée avec succès")
        print(f"   Taille: {private_key.key_size} bits")
        print()
    except Exception as e:
        print(f"❌ Erreur clé privée: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    # Test encrypt/decrypt simple
    print("🔄 Test encryption/decryption...")
    try:
        from cryptography.hazmat.primitives.asymmetric import padding
        from cryptography.hazmat.primitives import hashes
        
        test_data = b"Hello World Test"
        
        # Encrypt
        encrypted = public_key.encrypt(
            test_data,
            padding.OAEP(
                mgf=padding.MGF1(algorithm=hashes.SHA256()),
                algorithm=hashes.SHA256(),
                label=None
            )
        )
        print(f"✅ Encryption réussie (longueur: {len(encrypted)} bytes)")
        
        # Decrypt
        decrypted = private_key.decrypt(
            encrypted,
            padding.OAEP(
                mgf=padding.MGF1(algorithm=hashes.SHA256()),
                algorithm=hashes.SHA256(),
                label=None
            )
        )
        print(f"✅ Decryption réussie")
        
        if decrypted == test_data:
            print(f"✅ ✅ ✅ Les données correspondent!")
            return True
        else:
            print(f"❌ Les données ne correspondent pas")
            return False
            
    except Exception as e:
        print(f"❌ Erreur: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    import os
    
    # Tester les anciennes clés
    print("\n### Test des clés actuelles ###\n")
    if os.path.exists("public.pem") and os.path.exists("private.pem"):
        result1 = test_key_loading("public.pem", "private.pem")
    else:
        print("❌ Fichiers public.pem ou private.pem non trouvés")
        result1 = False
    
    print("\n" + "=" * 60)
    
    # Tester les nouvelles clés si elles existent
    if os.path.exists("public_new.pem") and os.path.exists("private_new.pem"):
        print("\n### Test des nouvelles clés ###\n")
        result2 = test_key_loading("public_new.pem", "private_new.pem")
        
        if result2 and not result1:
            print("\n" + "=" * 60)
            print("💡 Les nouvelles clés fonctionnent!")
            print("   Remplacez les anciennes clés:")
            print("   mv public_new.pem public.pem")
            print("   mv private_new.pem private.pem")
            print("=" * 60)
    
    exit(0 if result1 else 1)
