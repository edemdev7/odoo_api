#!/usr/bin/env python3
"""
Script pour lister tous les points de vente (POS) disponibles dans chaque base Odoo
"""

from core.config import ODOO_DATABASES
from core.odoo_client import OdooClient

print("🏪 Liste des Points de Vente par Base de Données\n")
print("=" * 80)

for db_config in ODOO_DATABASES:
    print(f"\n📊 Base: {db_config['name']}")
    print(f"   URL: {db_config['url']}")
    print(f"   Type de transfert: {db_config.get('transfer_type_code', 'N/A')}")
    print("-" * 80)
    
    try:
        # Créer le client
        client = OdooClient(custom_config={
            'url': db_config['url'],
            'db': db_config['db'],
            'username': db_config['username'],
            'api_key': db_config['api_key']
        })
        
        # Rechercher tous les POS configs
        pos_configs = client.execute_kw(
            'pos.config',
            'search_read',
            [[]],
            {
                'fields': [
                    'id', 'name', 'company_id', 'warehouse_id', 
                    'picking_type_id', 'current_session_id', 'session_state'
                ],
                'order': 'id asc'
            }
        )
        
        if pos_configs:
            print(f"   ✅ {len(pos_configs)} Point(s) de Vente trouvé(s):\n")
            
            for pos in pos_configs:
                company = pos.get('company_id')
                company_name = company[1] if isinstance(company, list) else "N/A"
                
                warehouse = pos.get('warehouse_id')
                warehouse_name = warehouse[1] if isinstance(warehouse, list) else "N/A"
                
                session_state = pos.get('session_state', 'Aucune session')
                
                print(f"      🏪 ID: {pos['id']} | Nom: {pos['name']}")
                print(f"         └─ Société: {company_name}")
                print(f"         └─ Entrepôt: {warehouse_name}")
                print(f"         └─ État session: {session_state}")
                
                # Obtenir les types de picking associés
                if pos.get('picking_type_id'):
                    picking_type_id = pos['picking_type_id'][0] if isinstance(pos['picking_type_id'], list) else pos['picking_type_id']
                    
                    try:
                        picking_type = client.execute_kw(
                            'stock.picking.type',
                            'read',
                            [picking_type_id],
                            {'fields': ['code', 'name']}
                        )
                        
                        if picking_type:
                            print(f"         └─ Type opération: {picking_type[0].get('name')} ({picking_type[0].get('code')})")
                    except:
                        pass
                
                print()
        else:
            print("   ⚠️  Aucun Point de Vente trouvé dans cette base")
            
    except Exception as e:
        print(f"   ❌ Erreur lors de la connexion: {e}")

print("\n" + "=" * 80)
print("✅ Liste terminée\n")

print("\n💡 CONSEIL:")
print("   Pour utiliser un POS dans vos requêtes API, utilisez l'ID correspondant")
print("   à la base de données sur laquelle vous êtes authentifié.")
print("\n   Exemple:")
print("   - Authentifié sur 'franchise' → Utilisez un POS ID de la base Franchise")
print("   - Authentifié sur 'jnp_directe' → Utilisez un POS ID de la base JNP Directe\n")
