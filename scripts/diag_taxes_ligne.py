#!/usr/bin/env python3
"""
Deroule, etape par etape, le calcul de taxes d'une ligne de vente.

Rejoue la logique de `_taxes_ligne` (api/pos.py) en affichant chaque valeur
intermediaire : taxes du produit, filtrage par societe, position fiscale,
calcul Odoo, comparaison au montant paye. Sert a trouver a quelle etape les
taxes disparaissent quand une vente sort avec `tax_ids` vide.

AUCUNE DEPENDANCE : stdlib uniquement.

Usage :
    cd ~/Documents/projects/odoo_api
    python scripts/diag_taxes_ligne.py
    python scripts/diag_taxes_ligne.py --pos 32 --produit 2998 --prix 750 --qte 20
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _odoo_direct import connexion  # noqa: E402

LARGEUR = 92

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')
except AttributeError:
    pass

CAS_DEFAUT = [
    # pos, produit, prix unitaire, quantite  (les deux ventes du 27/11)
    (32, 3014, 765.0, 19.6078),
    (32, 2998, 750.0, 20.0),
]


def titre(t):
    print()
    print("=" * LARGEUR)
    print(t)
    print("=" * LARGEUR)


def m2o(v):
    return v[0] if isinstance(v, list) and v else (v or None)


def dérouler(appel, pos_id, product_id, prix, qte):
    montant_ttc = round(prix * qte, 0)
    titre(f"PDV {pos_id} · produit {product_id} · {qte} × {prix} = {montant_ttc:g}")

    # --- 1. Societe et position fiscale du point de vente ---
    cfg = appel('pos.config', 'read', [[pos_id]],
                {'fields': ['name', 'company_id', 'default_fiscal_position_id']})[0]
    societe_pdv = m2o(cfg.get('company_id'))
    position = m2o(cfg.get('default_fiscal_position_id'))
    print(f"  1. PDV « {cfg['name']} » — societe {societe_pdv}, "
          f"position fiscale {position or 'aucune'}")

    correspondances = {}
    if position:
        for l in appel('account.fiscal.position.tax', 'search_read',
                       [[('position_id', '=', position)]],
                       {'fields': ['tax_src_id', 'tax_dest_id']}):
            dest = m2o(l.get('tax_dest_id'))
            correspondances.setdefault(m2o(l.get('tax_src_id')), [])
            if dest:
                correspondances[m2o(l.get('tax_src_id'))].append(dest)
    print(f"     correspondances de taxe : {correspondances or 'aucune'}")

    # --- 2. Taxes portees par le produit ---
    produit = appel('product.product', 'read', [[product_id]],
                    {'fields': ['display_name', 'taxes_id']})
    if not produit:
        print("  2. PRODUIT INTROUVABLE — c'est la cause.")
        return
    brut = produit[0].get('taxes_id') or []
    print(f"\n  2. {produit[0]['display_name']}")
    print("     taxes_id brut : " + (str(brut) if brut else "AUCUNE — c'est la cause"))
    if not brut:
        return

    # --- 3. Filtrage par societe ---
    detail = appel('account.tax', 'read', [brut],
                   {'fields': ['name', 'company_id', 'active', 'amount', 'amount_type']})
    print("\n  3. Filtrage par societe du PDV")
    retenues = []
    for t in detail:
        soc = m2o(t.get('company_id'))
        garde = (soc == societe_pdv)
        if garde:
            retenues.append(t['id'])
        print(f"     [{t['id']:>4}] {t['name'][:34]:<34} societe {soc} "
              f"actif={t.get('active')}  -> {'RETENUE' if garde else 'ecartee'}")
    if not retenues:
        print("\n     >>> Aucune taxe retenue : la ligne partira SANS TAXE.")
        print("         Motif : « aucune taxe sur le produit pour la societe du PDV ».")
        return

    # --- 4. Application de la position fiscale ---
    appliquees = []
    for t in retenues:
        appliquees += correspondances.get(t, [t])
    appliquees = list(dict.fromkeys(appliquees))
    print(f"\n  4. Apres position fiscale : {appliquees}")
    if not appliquees:
        print("     >>> Vente exoneree par la position fiscale.")
        return

    # --- 5. Calcul par Odoo ---
    # Un groupe doit etre developpe : compute_all renvoie sinon le groupe
    # parent sous forme d'enregistrement, que XML-RPC ne sait pas serialiser.
    feuilles = []
    for t in appel('account.tax', 'read', [appliquees],
                   {'fields': ['amount_type', 'children_tax_ids', 'name']}):
        if t.get('amount_type') == 'group' and t.get('children_tax_ids'):
            print(f"     groupe [{t['id']}] {t['name']} developpe en "
                  f"{t['children_tax_ids']}")
            feuilles += t['children_tax_ids']
        else:
            feuilles.append(t['id'])
    calcul = appel('account.tax', 'compute_all', [feuilles, prix], {'quantity': qte})
    ttc = float(calcul.get('total_included') or 0)
    ht = float(calcul.get('total_excluded') or 0)
    print(f"\n  5. compute_all({appliquees}, prix={prix}, qte={qte})")
    print(f"     HT  {ht:12.2f}")
    for t in calcul.get('taxes') or []:
        print(f"     {t.get('name','')[:36]:<36} {t.get('amount'):10.2f}")
    print(f"     TTC {ttc:12.2f}   (montant paye : {montant_ttc:g})")

    # --- 6. Garde-fou ---
    ecart = abs(ttc - montant_ttc)
    print(f"\n  6. Ecart TTC recalcule / montant paye : {ecart:.4f}")
    if ecart > 1.000000001:
        print("     >>> GARDE-FOU : l'ecart depasse la tolerance, la ligne")
        print("         part SANS TAXE et l'anomalie est journalisee en erreur.")
    else:
        print(f"     >>> OK — la ligne porte {appliquees}, "
              f"HT {ht:.2f}, taxes {montant_ttc - ht:.2f}")


def main():
    argv = sys.argv[1:]
    opt = {}
    i = 0
    while i < len(argv):
        a = argv[i]
        cle, val = (a.split('=', 1) if '=' in a
                    else (a, argv[i + 1] if i + 1 < len(argv) else None))
        if '=' not in a:
            i += 1
        opt[cle.lstrip('-')] = val
        i += 1

    appel = connexion()

    if opt.get('produit'):
        cas = [(int(opt.get('pos', 32)), int(opt['produit']),
                float(opt.get('prix', 0)), float(opt.get('qte', 1)))]
    else:
        cas = CAS_DEFAUT

    for pos_id, product_id, prix, qte in cas:
        dérouler(appel, pos_id, product_id, prix, qte)

    titre("LECTURE")
    print("""
  L'etape qui affiche « c'est la cause » ou « SANS TAXE » designe l'endroit
  exact ou les taxes disparaissent. Les trois causes possibles :

    - le produit ne porte aucune taxe ;
    - aucune de ses taxes n'appartient a la societe du point de vente ;
    - le TTC recalcule ne retombe pas sur le montant paye, et le garde-fou
      retire les taxes pour ne pas changer le prix demande au client.
""")


if __name__ == '__main__':
    main()
