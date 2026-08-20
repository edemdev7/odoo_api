#!/usr/bin/env python3
"""
Diagnostic — correspondance entre points de vente et emplacements de stock.

La résolution d'emplacement de l'API dérive le code du PDV depuis son nom
(« JO19 COVE » → « JO19/ ») et cherche l'emplacement interne correspondant.
Quand aucun ne correspond, elle se rabat sur l'entrepôt du pos.config, qui
pointe vers le siège et ne reflète pas les cuves de la station.

Ce script vérifie, pour chaque point de vente, si un emplacement existe. Il
répond donc à la seule question qui compte avant la mise en production :
combien de stations seront correctement servies, et lesquelles resteront
sur le repli.

Usage :
    cd ~/odoo_api
    python3 scripts/diag_emplacements_pdv.py           # tous les PDV actifs
    python3 scripts/diag_emplacements_pdv.py 32 17 14  # une sélection
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

LARGEUR = 92


def code_station(nom_pdv):
    """« JO19 COVE » → « JO19 ». Même dérivation que l'API."""
    parties = (nom_pdv or '').split()
    return parties[0] if parties else None


def main():
    ids_demandes = [int(a) for a in sys.argv[1:]]

    print("Connexion à Odoo...")
    client = OdooClient()

    domaine = [('id', 'in', ids_demandes)] if ids_demandes else [('active', '=', True)]
    pdvs = client.execute_kw(
        'pos.config', 'search_read', [domaine],
        {'fields': ['id', 'name', 'warehouse_id'], 'order': 'name asc'}
    )
    if not pdvs:
        print("Aucun point de vente trouvé.")
        return

    print()
    print("=" * LARGEUR)
    print(f"{'PDV':>5}  {'NOM':<22} {'CODE':<8} {'EMPLACEMENT TROUVÉ':<32} {'STOCK':>10}")
    print("=" * LARGEUR)

    resolus, replis = [], []

    for pdv in pdvs:
        nom = pdv.get('name') or ''
        code = code_station(nom)
        emplacement, total = None, None

        if code:
            try:
                candidats = client.execute_kw(
                    'stock.location', 'search_read',
                    [[('complete_name', '=like', f'{code}/%'),
                      ('usage', '=', 'internal')]],
                    {'fields': ['id', 'complete_name']}
                )
                if candidats:
                    emplacement = min(
                        candidats, key=lambda c: len(c.get('complete_name') or '')
                    )
            except Exception as e:
                print(f"  Erreur sur le PDV {pdv['id']} : {e}")

        if emplacement:
            # Volume total stocké, pour distinguer un emplacement réel d'une coquille vide
            try:
                quants = client.execute_kw(
                    'stock.quant', 'search_read',
                    [[('location_id', 'child_of', emplacement['id'])]],
                    {'fields': ['quantity']}
                )
                total = sum(float(q.get('quantity') or 0) for q in quants)
            except Exception:
                total = None
            resolus.append((pdv, emplacement, total))
            marque = emplacement['complete_name']
            volume = f"{total:,.0f}" if total is not None else "?"
        else:
            replis.append(pdv)
            marque = ">>> AUCUN — repli sur l'entrepôt"
            volume = "-"

        print(f"{pdv['id']:>5}  {nom[:22]:<22} {str(code)[:8]:<8} {marque[:32]:<32} {volume:>10}")

    print("=" * LARGEUR)
    total_pdv = len(pdvs)
    print(f"\n{len(resolus)}/{total_pdv} point(s) de vente correctement résolu(s).")

    vides = [(p, e) for p, e, t in resolus if t is not None and abs(t) < 0.001]
    if vides:
        print(f"\nEmplacement trouvé mais vide ({len(vides)}) — à vérifier :")
        for p, e in vides:
            print(f"    {p['name']} → {e['complete_name']}")

    if replis:
        print(f"\nAucun emplacement pour {len(replis)} point(s) de vente :")
        for p in replis:
            print(f"    PDV {p['id']:>4}  {p['name']}")
        print("""
    Ces stations resteront sur le repli entrepôt et continueront d'afficher
    des stocks erronés. Deux options : créer l'emplacement correspondant dans
    Odoo, ou rattacher explicitement le PDV à son emplacement réel.""")
    else:
        print("\nTous les points de vente disposent d'un emplacement dédié.")


if __name__ == '__main__':
    main()
