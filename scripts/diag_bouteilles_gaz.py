#!/usr/bin/env python3
"""
Etat des lieux des bouteilles de gaz dans Odoo.

Objectif : savoir si la bouteille vide existe comme produit a part entiere
et si ses mouvements sont tracks, avant de decider comment calculer la
ligne « Stock transfere » demandee par JNP.

Trois issues possibles, et le script dit laquelle :

  A. un produit « bouteille vide » existe et bouge  -> la ligne se calcule
     depuis stock.move.line, rien d'autre a construire ;

  B. le produit existe mais ne bouge jamais         -> personne ne saisit
     les retours ; il faut un point d'entree ;

  C. aucun produit de ce genre                      -> la quantite est a
     declarer par le pompiste, ou a deduire des recharges vendues.

Lecture seule, aucune ecriture.

Usage :
    cd ~/Documents/projects/odoo_api
    python3 scripts/diag_bouteilles_gaz.py
    python3 scripts/diag_bouteilles_gaz.py --pos 4 --jours 60
"""

import sys
import os
from datetime import datetime, timedelta

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')
except AttributeError:
    pass

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from core.odoo_client import OdooClient  # noqa: E402

LARGEUR = 92

# Termes cherches dans les noms de produits et de categories.
TERMES = ['gaz', 'bouteille', 'vide', 'consign', 'emballage', 'btl']

# Ce qui, dans un nom, denonce une bouteille vide plutot qu'un plein.
TERMES_VIDE = ['vide', 'consign', 'retour', 'emballage']


def titre(t):
    print()
    print("=" * LARGEUR)
    print(t)
    print("=" * LARGEUR)


def option(argv, nom, defaut=None):
    for i, a in enumerate(argv):
        if a == nom and i + 1 < len(argv):
            return argv[i + 1]
        if a.startswith(nom + '='):
            return a.split('=', 1)[1]
    return defaut


def main():
    argv = sys.argv[1:]
    jours = int(option(argv, '--jours', '30'))
    pos_id = option(argv, '--pos')

    print("Connexion a Odoo...")
    client = OdooClient()

    # ------------------------------------------------------------------
    # 1. Categories concernees
    # ------------------------------------------------------------------
    titre("CATEGORIES LIEES AU GAZ")

    domaine_cat = ['|'] * (len(TERMES) - 1) + [('name', 'ilike', t) for t in TERMES]
    categories = client.execute_kw(
        'product.category', 'search_read', [domaine_cat],
        {'fields': ['id', 'name', 'complete_name'], 'order': 'complete_name asc'}
    )
    if categories:
        for c in categories:
            print(f"  {c['id']:>5}  {c.get('complete_name') or c['name']}")
    else:
        print("  Aucune categorie ne mentionne le gaz ou la bouteille.")

    ids_categories = [c['id'] for c in categories]

    # ------------------------------------------------------------------
    # 2. Produits concernes
    # ------------------------------------------------------------------
    titre("PRODUITS")

    domaine_nom = ['|'] * (len(TERMES) - 1) + [('name', 'ilike', t) for t in TERMES]
    trouves = {}

    for libelle, domaine in (
        ("nom", domaine_nom),
        ("categorie", [('categ_id', 'in', ids_categories)] if ids_categories else None),
    ):
        if domaine is None:
            continue
        try:
            produits = client.execute_kw(
                'product.product', 'search_read', [domaine],
                {'fields': ['id', 'name', 'default_code', 'type', 'categ_id',
                            'uom_id', 'available_in_pos', 'list_price',
                            'qty_available', 'active'],
                 'order': 'name asc', 'limit': 200}
            )
            for p in produits:
                trouves.setdefault(p['id'], p)
        except Exception as e:
            print(f"  Recherche par {libelle} echouee: {e}")

    if not trouves:
        print("  Aucun produit trouve. >>> Cas C.")
        return

    print(f"  {len(trouves)} produit(s). Colonne V = nom evoquant une bouteille vide.\n")
    print(f"  {'ID':>6}  {'V':<2} {'Nom':<40} {'Type':<10} {'UdM':<8} {'PdV':<4} {'Stock':>10}")
    print("  " + "-" * (LARGEUR - 4))

    produits_vides = []
    produits_pleins = []

    for p in sorted(trouves.values(), key=lambda x: x['name']):
        nom_bas = (p['name'] or '').lower()
        est_vide = any(t in nom_bas for t in TERMES_VIDE)
        if est_vide:
            produits_vides.append(p)
        elif 'gaz' in nom_bas or 'bouteille' in nom_bas:
            produits_pleins.append(p)

        print(f"  {p['id']:>6}  {'x' if est_vide else ' ':<2} "
              f"{(p['name'] or '')[:40]:<40} "
              f"{str(p.get('type'))[:10]:<10} "
              f"{(p.get('uom_id') or [None, ''])[1][:8]:<8} "
              f"{'oui' if p.get('available_in_pos') else '—':<4} "
              f"{p.get('qty_available'):>10}")

    # ------------------------------------------------------------------
    # 3. Les produits « vides » bougent-ils reellement ?
    # ------------------------------------------------------------------
    titre(f"MOUVEMENTS DES PRODUITS « VIDE » SUR {jours} JOUR(S)")

    if not produits_vides:
        print("""  Aucun produit ne porte un nom de bouteille vide.

  >>> Cas C : la quantite de vides recuperes n'est pas tracee dans Odoo.
      Elle devra etre declaree par le pompiste, ou deduite du nombre de
      recharges vendues — ce qui suppose qu'une recharge equivaut
      toujours a un vide rendu.""")
    else:
        depuis = (datetime.now() - timedelta(days=jours)).strftime('%Y-%m-%d 00:00:00')
        ids_vides = [p['id'] for p in produits_vides]

        domaine_mvt = [('product_id', 'in', ids_vides),
                       ('state', '=', 'done'),
                       ('date', '>=', depuis)]

        lignes = client.execute_kw(
            'stock.move.line', 'search_read', [domaine_mvt],
            {'fields': ['product_id', 'quantity', 'date',
                        'location_id', 'location_dest_id', 'reference'],
             'order': 'date desc', 'limit': 60}
        )

        if not lignes:
            print(f"""  Aucun mouvement depuis {depuis[:10]}.

  >>> Cas B : le produit existe mais personne ne saisit les retours.
      Un point d'entree est necessaire — soit une saisie dans l'appli a
      la fermeture de session, soit un transfert cree par la passerelle.""")
        else:
            print(f"  {len(lignes)} mouvement(s), les plus recents d'abord :\n")
            print(f"  {'Date':<17} {'Produit':<28} {'Qte':>8}  Trajet")
            print("  " + "-" * (LARGEUR - 4))
            for l in lignes[:30]:
                prod = l.get('product_id')
                src = l.get('location_id')
                dst = l.get('location_dest_id')
                print(f"  {str(l.get('date'))[:17]:<17} "
                      f"{(prod[1] if isinstance(prod, list) else '')[:28]:<28} "
                      f"{l.get('quantity'):>8}  "
                      f"{(src[1] if isinstance(src, list) else '?')} -> "
                      f"{(dst[1] if isinstance(dst, list) else '?')}")
            print("""
  >>> Cas A : les vides bougent dans Odoo. La ligne « Stock transfere »
      peut se calculer depuis stock.move.line, sans nouvelle saisie.""")

    # ------------------------------------------------------------------
    # 4. Recharges vendues sur la station, pour comparaison
    # ------------------------------------------------------------------
    if pos_id and produits_pleins:
        titre(f"RECHARGES VENDUES — PDV {pos_id}, {jours} JOUR(S)")
        depuis = (datetime.now() - timedelta(days=jours)).strftime('%Y-%m-%d 00:00:00')
        try:
            ventes = client.execute_kw(
                'pos.order.line', 'search_read',
                [[('product_id', 'in', [p['id'] for p in produits_pleins]),
                  ('order_id.session_id.config_id', '=', int(pos_id)),
                  ('order_id.date_order', '>=', depuis)]],
                {'fields': ['product_id', 'qty'], 'limit': 500}
            )
            cumul = {}
            for v in ventes:
                prod = v.get('product_id')
                nom = prod[1] if isinstance(prod, list) else str(prod)
                cumul[nom] = cumul.get(nom, 0.0) + float(v.get('qty') or 0)
            if cumul:
                for nom, qte in sorted(cumul.items()):
                    print(f"  {nom[:50]:<50} {qte:>10g}")
                print("""
  A rapprocher des mouvements de vides ci-dessus : si les deux series
  collent, deduire les vides des recharges est defendable. Sinon, c'est
  qu'une partie des bouteilles part en consignation sans retour.""")
            else:
                print("  Aucune recharge vendue sur la periode.")
        except Exception as e:
            print(f"  Lecture des ventes echouee: {e}")

    titre("RAPPEL")
    print("""
  Lancer avec --pos pour comparer aux recharges vendues :

      python3 scripts/diag_bouteilles_gaz.py --pos 4 --jours 60
""")


if __name__ == '__main__':
    main()
