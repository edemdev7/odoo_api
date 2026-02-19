#!/usr/bin/env python3
"""Script pour remplacer les clés RSA"""

import shutil
import os

os.chdir('/home/edem/Téléchargements/odoo_api')

print("🔄 Remplacement des clés RSA...")
print()

# Sauvegarder les anciennes
if os.path.exists('public.pem'):
    shutil.copy('public.pem', 'public.pem.backup')
    print("✅ Sauvegarde: public.pem -> public.pem.backup")

if os.path.exists('private.pem'):
    shutil.copy('private.pem', 'private.pem.backup')
    print("✅ Sauvegarde: private.pem -> private.pem.backup")

print()

# Copier les nouvelles
if os.path.exists('public_new.pem'):
    shutil.copy('public_new.pem', 'public.pem')
    print("✅ Copie: public_new.pem -> public.pem")
else:
    print("❌ Fichier public_new.pem non trouvé!")

if os.path.exists('private_new.pem'):
    shutil.copy('private_new.pem', 'private.pem')
    print("✅ Copie: private_new.pem -> private.pem")
else:
    print("❌ Fichier private_new.pem non trouvé!")

print()
print("✅ ✅ ✅ Clés remplacées avec succès!")
print()
print("📋 Prochaines étapes:")
print("   1. Redémarrer le serveur FastAPI")
print("   2. Relancer le test: python3 test_accounting_quick.py")
