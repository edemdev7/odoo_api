#!/usr/bin/env python3
"""
Reprise des sessions POS fermées restées incohérentes.

La configuration vient de l'environnement, du .env ou de core/config.py —
plus de la tête du fichier. Elle y était codée en dur, avec le mot de passe
du compte Odoo en clair, et pointait vers une base de staging supprimée
depuis : le script ne résolvait même plus son nom de domaine.
"""

import os
import sys
import xmlrpc.client
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'scripts'))

from _odoo_direct import configuration  # noqa: E402

url, db, username, password = configuration('DB1')

print("Connexion à Odoo...")
common = xmlrpc.client.ServerProxy(f'{url}/xmlrpc/2/common')
uid = common.authenticate(db, username, password, {})
print(f"Authentifié - UID: {uid}\n")

models = xmlrpc.client.ServerProxy(f'{url}/xmlrpc/2/object')

print("Recherche des sessions POS fermées...")
sessions = models.execute_kw(
    db, uid, password,
    'pos.session',
    'search_read',
    [[('state', '=', 'closed')]],
    {'fields': ['id', 'name', 'config_id', 'stop_at', 'start_at', 'state'], 'order': 'id desc'}
)

print(f"Total sessions fermées: {len(sessions)}\n")

problematic = []
for s in sessions:
    if not s.get('stop_at') or s.get('stop_at') is False:
        problematic.append(s)
        print(f"Session {s['id']}: {s['name']} - stop_at = {s.get('stop_at')} (PROBLEME)")

if not problematic:
    print("\nAucune session problématique!")
else:
    print(f"\nTrouvé {len(problematic)} session(s) à corriger\n")
    fix = input("Corriger maintenant? (o/n): ")
    
    if fix.lower() == 'o':
        for s in problematic:
            stop_value = s.get('start_at') or datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            models.execute_kw(
                db, uid, password,
                'pos.session',
                'write',
                [[s['id']], {'stop_at': stop_value}]
            )
            print(f"✓ Session {s['id']} corrigée")
        print("\nTerminé!")
