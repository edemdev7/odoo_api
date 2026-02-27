#!/usr/bin/env python3
"""Script d'exploration Odoo pour le refactoring comptable"""
import sys
sys.path.insert(0, '/home/edem/Téléchargements/odoo_api')

from core.odoo_client import OdooClient

client = OdooClient()

# 1. Chercher le produit TVPASS_ESS
print("=" * 60)
print("1. PRODUIT TVPASS_ESS")
print("=" * 60)
products = client.execute_kw(
    'product.product',
    'search_read',
    [[('default_code', '=', 'TVPASS_ESS')]],
    {'fields': ['id', 'name', 'default_code', 'list_price', 'categ_id', 'type', 'uom_id', 'taxes_id']}
)
if products:
    for p in products:
        print(f"  ID: {p['id']}")
        print(f"  Nom: {p['name']}")
        print(f"  Code: {p['default_code']}")
        print(f"  Prix: {p['list_price']}")
        print(f"  Catégorie: {p['categ_id']}")
        print(f"  Type: {p['type']}")
        print(f"  UOM: {p['uom_id']}")
        print(f"  Taxes: {p['taxes_id']}")
else:
    print("  ❌ Produit TVPASS_ESS non trouvé !")
    # Chercher par nom partiel
    products_alt = client.execute_kw(
        'product.product',
        'search_read',
        [[('name', 'ilike', 'TVPASS')]],
        {'fields': ['id', 'name', 'default_code', 'list_price', 'categ_id'], 'limit': 10}
    )
    if products_alt:
        print("  Produits trouvés avec 'TVPASS' dans le nom:")
        for p in products_alt:
            print(f"    - {p['id']}: {p['name']} ({p['default_code']})")

# 2. Lister les journaux disponibles
print("\n" + "=" * 60)
print("2. JOURNAUX COMPTABLES")
print("=" * 60)
journals = client.execute_kw(
    'account.journal',
    'search_read',
    [[]],
    {'fields': ['id', 'name', 'code', 'type', 'company_id'], 'order': 'type, name'}
)
for j in journals:
    print(f"  [{j['type']:10s}] ID={j['id']:4d} | {j['code']:6s} | {j['name']} | Société: {j['company_id'][1] if j['company_id'] else 'N/A'}")

# 3. Méthodes de paiement
print("\n" + "=" * 60)
print("3. MÉTHODES DE PAIEMENT (account.payment.method)")
print("=" * 60)
payment_methods = client.execute_kw(
    'account.payment.method',
    'search_read',
    [[]],
    {'fields': ['id', 'name', 'code', 'payment_type']}
)
for pm in payment_methods:
    print(f"  ID={pm['id']:3d} | {pm['code']:15s} | {pm['name']:30s} | Type: {pm['payment_type']}")

# 4. Termes de paiement
print("\n" + "=" * 60)
print("4. TERMES DE PAIEMENT")
print("=" * 60)
payment_terms = client.execute_kw(
    'account.payment.term',
    'search_read',
    [[]],
    {'fields': ['id', 'name'], 'limit': 10}
)
for pt in payment_terms:
    print(f"  ID={pt['id']:3d} | {pt['name']}")

# 5. Comptes comptables clés
print("\n" + "=" * 60)
print("5. COMPTES COMPTABLES (411*, 419*, 512*)")
print("=" * 60)
accounts = client.execute_kw(
    'account.account',
    'search_read',
    [[('code', 'in', ['419101', '411100', '512000'])]],
    {'fields': ['id', 'name', 'code', 'account_type', 'company_id']}
)
for a in accounts:
    print(f"  {a['code']} | {a['name']} | Type: {a.get('account_type', 'N/A')} | ID: {a['id']}")

# 6. Vérifier structure sale.order
print("\n" + "=" * 60)
print("6. CHAMPS SALE.ORDER (extrait)")
print("=" * 60)
try:
    fields = client.execute_kw(
        'sale.order',
        'fields_get',
        [],
        {'attributes': ['string', 'type', 'required'], 'allfields': False}
    )
    important_fields = ['partner_id', 'payment_term_id', 'pricelist_id', 'order_line', 'state', 'company_id', 'currency_id', 'fiscal_position_id']
    for f in important_fields:
        if f in fields:
            info = fields[f]
            print(f"  {f}: {info.get('string', '')} (type={info.get('type', '')}, required={info.get('required', False)})")
except Exception as e:
    print(f"  Erreur: {e}")

print("\n✅ Exploration terminée")
