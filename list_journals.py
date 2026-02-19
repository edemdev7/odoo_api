#!/usr/bin/env python3
"""
Script pour lister les journaux comptables disponibles dans Odoo
"""

import sys
sys.path.insert(0, '/home/edem/Téléchargements/odoo_api')

from core.odoo_client import OdooClient

def list_journals():
    """Lister tous les journaux comptables"""
    
    print("=" * 70)
    print("📚 Liste des journaux comptables dans Odoo")
    print("=" * 70)
    print()
    
    try:
        # Connexion à Odoo
        client = OdooClient()
        print(f"✅ Connecté à Odoo")
        print()
        
        # Rechercher tous les journaux
        journals = client.execute_kw(
            'account.journal',
            'search_read',
            [[]],
            {
                'fields': ['id', 'name', 'code', 'type'],
                'order': 'id asc'
            }
        )
        
        if not journals:
            print("❌ Aucun journal trouvé")
            return
        
        print(f"📊 {len(journals)} journaux trouvés:")
        print()
        
        # Afficher les journaux
        print(f"{'ID':<6} {'Type':<12} {'Code':<10} {'Nom'}")
        print("-" * 70)
        
        for journal in journals:
            journal_id = journal['id']
            journal_type = journal.get('type', 'N/A')
            journal_code = journal.get('code', 'N/A')
            journal_name = journal.get('name', 'N/A')
            
            print(f"{journal_id:<6} {journal_type:<12} {journal_code:<10} {journal_name}")
        
        print()
        print("=" * 70)
        print("💡 Types de journaux:")
        print("   - sale: Ventes")
        print("   - purchase: Achats")
        print("   - cash: Caisse")
        print("   - bank: Banque")
        print("   - general: Opérations diverses")
        print()
        print("🔍 Pour les écritures de provision (compte 419101),")
        print("   utilisez un journal de type 'general' ou 'sale'")
        print("=" * 70)
        
    except Exception as e:
        print(f"❌ Erreur: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    list_journals()
