#!/usr/bin/env python3
"""
Script simple pour vérifier quel POS existe dans quelle base
"""
import sys
sys.path.insert(0, '/home/edem/Téléchargements/odoo_api')

from core.config import ODOO_DATABASES
from core.odoo_client import OdooClient

print("\n🔍 Recherche du POS ID 5 dans les bases de données...\n")

for db_config in ODOO_DATABASES:
    print(f"📊 {db_config['name']} ({db_config['url']})")
    
    try:
        client = OdooClient(custom_config=db_config)
        
        # Chercher le POS ID 5
        pos_5 = client.execute_kw(
            'pos.config',
            'search_read',
            [[('id', '=', 5)]],
            {'fields': ['id', 'name', 'company_id'], 'limit': 1}
        )
        
        if pos_5:
            print(f"   ✅ POS ID 5 trouvé: {pos_5[0]['name']}")
        else:
            print(f"   ❌ POS ID 5 non trouvé")
            
        # Lister tous les POS
        all_pos = client.execute_kw(
            'pos.config',
            'search_read',
            [[]],
            {'fields': ['id', 'name'], 'limit': 10}
        )
        
        if all_pos:
            print(f"   📋 POS disponibles ({len(all_pos)}):")
            for pos in all_pos:
                print(f"      - ID {pos['id']}: {pos['name']}")
        else:
            print(f"   ⚠️  Aucun POS trouvé")
            
    except Exception as e:
        print(f"   ❌ Erreur: {e}")
    
    print()

print("✅ Recherche terminée\n")
