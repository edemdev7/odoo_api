#!/usr/bin/env python3
"""
Quelles taxes s'appliquent reellement a une vente, et sur quels comptes.

L'audit comptable a releve deux comptes de TVA au libelle identique,
4431 et 443100, et deux taxes « TVA 18 % » sur chaque produit. Deux
lectures sont possibles :

  - une seule taxe dont la repartition vise deux comptes : rien d'anormal ;
  - deux taxes distinctes appliquees ensemble : la TVA est comptee deux
    fois, et l'erreur ne se verra qu'a la declaration fiscale.

Ce script tranche en listant, produit par produit, chaque taxe avec son
taux, son mode de calcul et ses lignes de repartition.

AUCUNE DEPENDANCE : stdlib uniquement.

Usage :
    cd ~/Documents/projects/odoo_api
    python scripts/diag_tva.py
    python scripts/diag_tva.py 3014 2998
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _odoo_direct import connexion  # noqa: E402

LARGEUR = 96

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')
except AttributeError:
    pass

# Produits temoins : gasoil, essence, un lubrifiant.
PRODUITS_DEFAUT = [3014, 2998]


def titre(t):
    print()
    print("=" * LARGEUR)
    print(t)
    print("=" * LARGEUR)


def m2o(v, defaut='—'):
    return v[1] if isinstance(v, list) and v else defaut


def main():
    produits = [int(a) for a in sys.argv[1:] if a.isdigit()] or PRODUITS_DEFAUT
    appel = connexion()

    # ------------------------------------------------------------------
    # 1. Les comptes 4431*
    # ------------------------------------------------------------------
    titre("COMPTES DE TVA EXISTANTS (code commencant par 4431)")

    # La societe porteuse d'un compte se lit `company_id` en Odoo 17 et
    # `company_ids` a partir de la 18. Reclamer le mauvais fait echouer toute
    # la lecture : on demande donc celui que la base expose.
    champs = ['id', 'code', 'name', 'account_type']
    try:
        dispo = appel('account.account', 'fields_get', [], {'attributes': ['type']})
        for candidat in ('company_ids', 'company_id'):
            if candidat in dispo:
                champs.append(candidat)
                break
    except Exception as e:
        print(f"  (champs d'account.account illisibles : {e})")

    comptes = appel('account.account', 'search_read',
                    [[('code', '=like', '4431%')]],
                    {'fields': champs, 'order': 'code asc'})
    if not comptes:
        print("  Aucun compte dont le code commence par 4431.")
    for c in comptes:
        print(f"  id={c['id']:<6} {c['code']:<10} {c['name'][:44]:<44} {c.get('account_type')}")
    print(f"\n  {len(comptes)} compte(s). Deux comptes au meme libelle ne sont pas")
    print("  un doublon en soi : ils le deviennent si deux taxes les visent")
    print("  simultanement sur le meme produit.")

    # ------------------------------------------------------------------
    # 2. Les taxes de chaque produit
    # ------------------------------------------------------------------
    for pid in produits:
        lu = appel('product.product', 'read', [[pid]],
                   {'fields': ['display_name', 'taxes_id', 'list_price']})
        if not lu:
            titre(f"PRODUIT {pid} — INTROUVABLE")
            continue
        p = lu[0]

        titre(f"PRODUIT {pid} — {p['display_name']}  (prix {p.get('list_price')})")
        if not p.get('taxes_id'):
            print("  Aucune taxe de vente.")
            continue

        feuilles = []   # taxes reellement appliquees, groupes developpes

        def afficher(ids, retrait="  "):
            """
            Affiche des taxes, en descendant dans les groupes.

            Une taxe de type `group` ne prelve rien elle-meme : son montant
            vaut 0 et ce sont ses enfants qui s'appliquent. Les lister sans
            les developper laisse croire qu'un seul prelevement a lieu.
            """
            taxes = appel('account.tax', 'read', [ids],
                          {'fields': ['name', 'amount', 'amount_type', 'price_include',
                                      'include_base_amount', 'sequence', 'active',
                                      'invoice_repartition_line_ids', 'children_tax_ids']})
            taxes.sort(key=lambda t: t.get('sequence') or 0)
            for t in taxes:
                mode = t.get('amount_type')
                enfants = t.get('children_tax_ids') or []
                print(f"\n{retrait}[{t['id']}] {t['name']}"
                      + ("   (groupe)" if mode == 'group' else ""))
                print(f"{retrait}    seq {t.get('sequence')}   montant {t.get('amount')}   "
                      f"mode {mode}   TTC={t.get('price_include')}   "
                      f"base+={t.get('include_base_amount')}")

                if mode == 'group' and enfants:
                    afficher(enfants, retrait + "    ")
                    continue

                feuilles.append(t)
                lignes = appel('account.tax.repartition.line', 'read',
                               [t.get('invoice_repartition_line_ids') or []],
                               {'fields': ['repartition_type', 'factor_percent', 'account_id']})
                for l in lignes:
                    compte = m2o(l.get('account_id'), 'aucun compte (base)')
                    print(f"{retrait}    repartition {l.get('repartition_type'):<5} "
                          f"{l.get('factor_percent'):>6} %  ->  {compte}")

        afficher(p['taxes_id'])

        # Verdict : on compte les prelevements qui se disent « TVA », quel
        # que soit leur mode de calcul. Sur du carburant, la TVA est un
        # montant fixe par litre ; une TVA en pourcentage par-dessus serait
        # un second prelevement sur la meme assiette.
        tva = [t for t in feuilles if 'TVA' in (t['name'] or '').upper()]
        print()
        if len(tva) > 1:
            print(f"  >>> {len(tva)} prelevements de TVA s'appliquent a ce produit :")
            for t in tva:
                compte = '?'
                lignes = appel('account.tax.repartition.line', 'read',
                               [t.get('invoice_repartition_line_ids') or []],
                               {'fields': ['repartition_type', 'account_id']})
                for l in lignes:
                    if l.get('repartition_type') == 'tax' and l.get('account_id'):
                        compte = m2o(l['account_id'])
                unite = '%' if t.get('amount_type') == 'percent' else 'F (fixe)'
                print(f"        {t['name']:<30} {t.get('amount'):>9} {unite:<9} -> {compte}")
            print("""
      A FAIRE CONFIRMER PAR LA COMPTABILITE. Sur un carburant, la TVA
      est normalement un montant fixe par litre. Une TVA en pourcentage
      appliquee en plus porte sur la meme assiette : le client la paie
      deux fois, et l'ecart ne se verra qu'a la declaration.""")
        elif len(tva) == 1:
            print(f"  >>> Un seul prelevement de TVA : {tva[0]['name']} "
                  f"({tva[0].get('amount')}). Conforme.")
        else:
            print("  >>> Aucun prelevement nomme TVA sur ce produit.")

    titre("CE QU'IL FAUT RETENIR")
    print("""
  Une taxe peut legitimement viser deux comptes par sa repartition —
  par exemple une part deductible et une part non deductible. Ce qui
  pose probleme, c'est que DEUX taxes distinctes au meme taux soient
  appliquees au meme produit.

  Le verdict ci-dessus porte uniquement sur les taxes en pourcentage :
  les montants fixes (TS, ASAS, TVA specifique sur carburant) se
  cumulent normalement, c'est leur raison d'etre.
""")


if __name__ == '__main__':
    main()
