#!/usr/bin/env python3
"""
Diagnostic — points de vente sans emplacement au format attendu.

Le premier diagnostic a montré que 42 points de vente sur 140 ne trouvent pas
d'emplacement du type « JO19/Stock ». Avant de conclure qu'il faut les créer
dans Odoo, il faut vérifier s'ils existent sous un autre nom.

Pour chaque point de vente non résolu, ce script essaie plusieurs pistes :
  - un emplacement portant le nom complet du PDV
  - un emplacement portant l'un des mots significatifs du nom (TOGOUDO, ALLADA…)
  - l'entrepôt configuré sur le PDV, et son emplacement de stock

Il affiche aussi le volume stocké de chaque candidat : un emplacement vide n'est
sans doute pas le bon.

Usage :
    cd ~/odoo_api
    python3 scripts/diag_emplacements_manquants.py
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

LARGEUR = 88

# Mots trop génériques pour servir de critère de recherche
MOTS_IGNORES = {
    'BOUTIQUE', 'STATION', 'DEPOT', 'SIEGE', 'DIRECTION',
    'DE', 'DU', 'LA', 'LE', 'LES', 'ET',
}


def volume_emplacement(client, location_id):
    try:
        quants = client.execute_kw(
            'stock.quant', 'search_read',
            [[('location_id', 'child_of', location_id)]],
            {'fields': ['quantity']}
        )
        return sum(float(q.get('quantity') or 0) for q in quants)
    except Exception:
        return None


def chercher(client, motif):
    try:
        return client.execute_kw(
            'stock.location', 'search_read',
            [[('complete_name', 'ilike', motif), ('usage', '=', 'internal')]],
            {'fields': ['id', 'complete_name'], 'limit': 6}
        )
    except Exception:
        return []


def main():
    print("Connexion à Odoo...")
    client = OdooClient()

    pdvs = client.execute_kw(
        'pos.config', 'search_read',
        [[('active', '=', True)]],
        {'fields': ['id', 'name', 'warehouse_id'], 'order': 'name asc'}
    )

    non_resolus = []
    for pdv in pdvs:
        nom = pdv.get('name') or ''
        code = nom.split()[0] if nom.split() else None
        if not code:
            non_resolus.append(pdv)
            continue
        if not chercher(client, f'{code}/'):
            non_resolus.append(pdv)

    print()
    print("=" * LARGEUR)
    print(f"{len(non_resolus)} point(s) de vente sans emplacement au format attendu")
    print("=" * LARGEUR)

    pistes_trouvees, sans_piste = [], []

    for pdv in non_resolus:
        nom = pdv.get('name') or ''
        print(f"\nPDV {pdv['id']:>4}  {nom}")
        print("-" * LARGEUR)

        candidats = {}

        # Piste 1 : nom complet
        for c in chercher(client, nom):
            candidats[c['id']] = (c['complete_name'], 'nom complet')

        # Piste 2 : mots significatifs du nom
        for mot in nom.replace("'", ' ').split():
            mot = mot.strip().upper()
            if len(mot) < 4 or mot in MOTS_IGNORES:
                continue
            for c in chercher(client, mot):
                candidats.setdefault(c['id'], (c['complete_name'], f"mot « {mot} »"))

        # Piste 3 : entrepôt configuré
        entrepot_txt = "aucun"
        wh = pdv.get('warehouse_id')
        if wh:
            wh_id = wh[0] if isinstance(wh, list) else wh
            try:
                info = client.execute_kw(
                    'stock.warehouse', 'read', [[wh_id]],
                    {'fields': ['name', 'code', 'lot_stock_id']}
                )[0]
                entrepot_txt = (
                    f"{info['name']} ({info.get('code')}) "
                    f"-> {info['lot_stock_id'][1]}"
                )
            except Exception as e:
                entrepot_txt = f"illisible ({e})"
        print(f"  Entrepôt configuré : {entrepot_txt}")

        if candidats:
            print(f"  Emplacements candidats ({len(candidats)}) :")
            trouve_non_vide = False
            for loc_id, (nom_loc, origine) in sorted(
                candidats.items(), key=lambda x: x[1][0]
            ):
                vol = volume_emplacement(client, loc_id)
                marque = f"{vol:,.0f}" if vol is not None else "?"
                if vol and abs(vol) > 0.001:
                    trouve_non_vide = True
                print(f"    {marque:>12}  {nom_loc:<42} [{origine}]")
            if trouve_non_vide:
                pistes_trouvees.append(pdv)
            else:
                sans_piste.append(pdv)
        else:
            print("  Aucun emplacement candidat.")
            sans_piste.append(pdv)

    print()
    print("=" * LARGEUR)
    print("SYNTHÈSE")
    print("=" * LARGEUR)
    print(f"""
  {len(pistes_trouvees)} PDV ont un emplacement candidat contenant du stock.
      Leur emplacement existe sous un autre nom : il suffit d'ajouter une
      correspondance explicite plutôt que de créer quoi que ce soit.

  {len(sans_piste)} PDV n'ont aucune piste exploitable.
      Soit ils ne sont pas réellement exploités, soit leur emplacement reste
      à créer dans Odoo. À trancher avec l'équipe métier.
""")


if __name__ == '__main__':
    main()
