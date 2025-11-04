#!/usr/bin/env python3
"""
Script de diagnostic pour tester la connexion aux bases Odoo
"""

from core.config import ODOO_DATABASES, logger
from core.odoo_client import OdooClient

print("🔍 Diagnostic de connexion aux bases Odoo\n")
print("=" * 60)

for db_config in ODOO_DATABASES:
    print(f"\n📊 Test de {db_config['name']}")
    print(f"   URL: {db_config['url']}")
    print(f"   DB: {db_config['db']}")
    print(f"   User: {db_config['username']}")
    print(f"   Type: {db_config.get('transfer_type_code', 'N/A')}")
    
    try:
        # Créer le client avec custom_config
        client = OdooClient(custom_config={
            'url': db_config['url'],
            'db': db_config['db'],
            'username': db_config['username'],
            'api_key': db_config['api_key']
        })
        
        # Test simple : rechercher un partenaire
        partners = client.execute_kw('res.partner', 'search', [[]], {'limit': 1})
        
        if partners:
            print(f"   ✅ Connexion réussie ! (UID: {client.uid})")
            
            # Tester la recherche d'employés
            employees = client.execute_kw(
                'hr.employee',
                'search_read',
                [[('active', '=', True)]],
                {'fields': ['id', 'name', 'x_studio_matricule'], 'limit': 3}
            )
            
            if employees:
                print(f"   👥 {len(employees)} employé(s) trouvé(s) (exemple):")
                for emp in employees[:3]:
                    matricule = emp.get('x_studio_matricule', 'N/A')
                    print(f"      - {emp['name']} (Matricule: {matricule})")
            else:
                print(f"   ⚠️  Aucun employé actif trouvé")
        else:
            print(f"   ⚠️  Connexion OK mais aucun partenaire trouvé")
            
    except Exception as e:
        print(f"   ❌ Erreur: {e}")

print("\n" + "=" * 60)
print("✅ Diagnostic terminé\n")
