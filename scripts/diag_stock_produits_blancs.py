#!/usr/bin/env python3
"""
Diagnostic — remontée des stocks « produits blancs » (carburants) en station.

Objectif : comprendre pourquoi le stock affiché par l'API ne correspond pas aux
quantités réellement approvisionnées en station.

L'API interroge l'emplacement `lot_stock_id` de l'entrepôt rattaché au point de
vente, ainsi que ses sous-emplacements. Si les cuves sont rangées ailleurs dans
l'arborescence — sous un autre entrepôt, ou hors de cet emplacement — les
quantités n'apparaissent pas, alors qu'elles existent bien dans Odoo.

Ce script affiche, pour chaque carburant :
  - l'emplacement interrogé par l'API et ce qu'il contient
  - TOUS les emplacements où le produit a du stock
  - lesquels sont hors du périmètre interrogé

Usage :
    cd ~/odoo_api
    python3 scripts/diag_stock_produits_blancs.py            # PDV 32 par défaut
    python3 scripts/diag_stock_produits_blancs.py 32 19 27   # plusieurs PDV
"""

import sys
import os

# La console Windows utilise cp1252, incapable d'encoder les caractères
# accentués et typographiques de ce script. On force l'UTF-8 en sortie.
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')
except AttributeError:
    pass

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from core.odoo_client import OdooClient  # noqa: E402

# Catégories des carburants pompés, alignées sur api/pos.py
CATEG_PRODUITS_BLANC = [23, 93, 95, 98]

LARGEUR = 78


def titre(texte):
    print()
    print("=" * LARGEUR)
    print(texte)
    print("=" * LARGEUR)


def sous_titre(texte):
    print()
    print(texte)
    print("-" * LARGEUR)


def diagnostiquer_pdv(client, pos_id):
    titre(f"POINT DE VENTE {pos_id}")

    pos = client.execute_kw(
        'pos.config', 'search_read',
        [[('id', '=', pos_id)]],
        {'fields': ['id', 'name', 'warehouse_id'], 'limit': 1}
    )
    if not pos:
        print(f"  Point de vente {pos_id} introuvable.")
        return
    pos = pos[0]
    print(f"  Nom       : {pos['name']}")

    entrepot = pos.get('warehouse_id')
    if not entrepot:
        print("  Entrepôt  : AUCUN — l'API se rabat sur le premier emplacement interne,")
        print("              ce qui est très probablement la cause du problème.")
        return

    wh_id = entrepot[0] if isinstance(entrepot, list) else entrepot
    wh = client.execute_kw(
        'stock.warehouse', 'read', [[wh_id]],
        {'fields': ['id', 'name', 'code', 'lot_stock_id']}
    )[0]
    loc_id = wh['lot_stock_id'][0]
    loc_nom = wh['lot_stock_id'][1]

    print(f"  Entrepôt  : {wh['name']} ({wh.get('code')})")
    print(f"  Emplacement interrogé par l'API : {loc_nom} (ID {loc_id})")

    # Périmètre réellement couvert par l'API
    perimetre = client.execute_kw(
        'stock.location', 'search', [[('id', 'child_of', loc_id)]]
    )
    print(f"  Périmètre : {len(perimetre)} emplacement(s) avec les sous-niveaux")

    produits = client.execute_kw(
        'product.product', 'search_read',
        [[('categ_id', 'in', CATEG_PRODUITS_BLANC), ('active', '=', True)]],
        {'fields': ['id', 'name', 'default_code', 'available_in_pos', 'uom_id']}
    )
    if not produits:
        print("\n  Aucun produit blanc trouvé dans les catégories configurées.")
        return

    for p in produits:
        sous_titre(f"{p['name']}  [{p.get('default_code') or 'sans code'}]")
        print(f"  Disponible en PdV : {'oui' if p.get('available_in_pos') else 'NON'}")

        quants = client.execute_kw(
            'stock.quant', 'search_read',
            [[('product_id', '=', p['id']),
              ('location_id.usage', '=', 'internal')]],
            {'fields': ['location_id', 'quantity', 'reserved_quantity']}
        )
        if not quants:
            print("  Aucun stock sur aucun emplacement interne.")
            continue

        dedans, dehors = [], []
        for q in quants:
            loc = q['location_id']
            entree = {
                'id': loc[0],
                'nom': loc[1],
                'qte': float(q.get('quantity') or 0),
                'res': float(q.get('reserved_quantity') or 0),
            }
            (dedans if loc[0] in perimetre else dehors).append(entree)

        total_dedans = sum(e['qte'] for e in dedans)
        total_dehors = sum(e['qte'] for e in dehors)

        print(f"\n  VU PAR L'API ({len(dedans)} emplacement(s)) — total {total_dedans:,.3f}")
        for e in sorted(dedans, key=lambda x: -abs(x['qte']))[:10]:
            print(f"    {e['qte']:>18,.3f}  (réservé {e['res']:>12,.3f})  {e['nom']}")
        if not dedans:
            print("    (rien)")

        if dehors:
            print(f"\n  HORS PÉRIMÈTRE ({len(dehors)} emplacement(s)) — total {total_dehors:,.3f}")
            print("  Ce stock existe dans Odoo mais l'API ne le voit pas :")
            for e in sorted(dehors, key=lambda x: -abs(x['qte']))[:15]:
                print(f"    {e['qte']:>18,.3f}  (réservé {e['res']:>12,.3f})  {e['nom']}")

            if abs(total_dehors) > abs(total_dedans):
                print("\n  >>> L'essentiel du stock est hors du périmètre interrogé.")
                print("      C'est l'explication de la remontée erronée.")
        else:
            print("\n  Aucun stock hors périmètre : la remontée devrait être correcte.")


def main():
    pos_ids = [int(a) for a in sys.argv[1:]] or [32]

    print("Connexion à Odoo...")
    client = OdooClient()

    for pos_id in pos_ids:
        try:
            diagnostiquer_pdv(client, pos_id)
        except Exception as e:
            print(f"\n  Erreur sur le PDV {pos_id} : {e}")

    titre("FIN DU DIAGNOSTIC")
    print("""
Lecture des résultats :

  Stock important « HORS PÉRIMÈTRE »
      Les cuves ne sont pas rattachées à l'emplacement de l'entrepôt du PDV.
      Deux corrections possibles : les déplacer dans l'arborescence côté Odoo,
      ou élargir le périmètre interrogé par l'API.

  Tout dans « VU PAR L'API », mais les chiffres restent faux
      Le problème vient alors des mouvements d'approvisionnement eux-mêmes,
      pas de l'emplacement interrogé.

  « Disponible en PdV : NON »
      Le produit est exclu de la remontée quelle que soit sa quantité.
""")


if __name__ == '__main__':
    main()
