#!/usr/bin/env python3
"""
Pourquoi un bon de livraison n'apparait pas dans /pos/inventory/transfers/by-truck.

Compare l'ancienne recherche (strategies en cascade, la premiere qui donne
un resultat l'emporte) a la nouvelle (strategies reunies par OU), et dit
pour chaque transfert attendu quelle strategie le trouve.

Lecture seule.

Usage :
    cd ~/Documents/projects/odoo_api
    python3 scripts/diag_transferts_camion.py AX0042RB
    python3 scripts/diag_transferts_camion.py AX0042RB --attendus 737244,737245,737246
    python3 scripts/diag_transferts_camion.py AX0042RB --etat done
"""

import sys
import os

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
TYPES = ['internal', 'incoming', 'outgoing']


def titre(t):
    print()
    print("=" * LARGEUR)
    print(t)
    print("=" * LARGEUR)


def equilibrer(sous_domaine):
    feuilles = sum(1 for c in sous_domaine
                   if isinstance(c, (list, tuple)) and len(c) == 3)
    operateurs = sum(1 for c in sous_domaine if c in ('&', '|'))
    return ['&'] * max(feuilles - 1 - operateurs, 0) + list(sous_domaine)


def ou_domaines(sous_domaines):
    valides = [equilibrer(d) for d in sous_domaines if d]
    if not valides:
        return []
    if len(valides) == 1:
        return valides[0]
    combine = ['|'] * (len(valides) - 1)
    for d in valides:
        combine.extend(d)
    return combine


def construire_strategies(client, camion):
    """[(nom, sous-domaine)] — mêmes stratégies que l'endpoint."""
    strategies = []

    partenaires = client.execute_kw(
        'res.partner', 'search', [[('name', 'ilike', camion)]]
    )
    if partenaires:
        print(f"  Partenaire(s) nomme(s) « {camion} » : {partenaires}")
        try:
            champs = client.execute_kw('stock.picking', 'fields_get', [],
                                       {'attributes': ['type']})
            if 'x_studio_camion' in champs:
                strategies.append(('x_studio_camion',
                                   [('x_studio_camion', 'in', partenaires)]))
            else:
                print("  Champ x_studio_camion : absent de stock.picking")
        except Exception as e:
            print(f"  fields_get echoue: {e}")
        strategies.append(('partner_id', [('partner_id', 'in', partenaires)]))
    else:
        print(f"  Aucun partenaire nomme « {camion} »")

    emplacements = client.execute_kw(
        'stock.location', 'search', [[('name', 'ilike', camion)]]
    )
    if emplacements:
        details = client.execute_kw(
            'stock.location', 'read', [emplacements], {'fields': ['complete_name']}
        )
        print(f"  Emplacement(s) : "
              f"{', '.join(d['complete_name'] for d in details)}")
        strategies.append(('location', [
            '|',
            ('location_id', 'child_of', emplacements),
            ('location_dest_id', 'child_of', emplacements),
        ]))
    else:
        print(f"  Aucun emplacement nomme « {camion} »")

    strategies.append(('origin', [('origin', 'ilike', camion)]))
    strategies.append(('name', [('name', 'ilike', camion)]))
    return strategies


def filtres(etat):
    return [('state', '=', etat)] if etat else []


def main():
    argv = sys.argv[1:]
    if not argv or argv[0].startswith('--'):
        print(__doc__)
        sys.exit(1)

    camion = argv[0]
    etat, attendus = None, []
    i = 1
    while i < len(argv):
        a = argv[i]
        nom, valeur = (a.split('=', 1) if '=' in a
                       else (a, argv[i + 1] if i + 1 < len(argv) else None))
        if '=' not in a:
            i += 1
        if nom == '--etat':
            etat = valeur
        elif nom == '--attendus':
            attendus = [int(x) for x in (valeur or '').split(',') if x.strip()]
        else:
            raise SystemExit(f"Option inconnue : {nom}")
        i += 1

    print("Connexion a Odoo...")
    client = OdooClient()

    titre(f"CAMION {camion}")
    strategies = construire_strategies(client, camion)

    base = [('picking_type_code', 'in', TYPES)]

    # ------------------------------------------------------------------
    # Ancien comportement : cascade
    # ------------------------------------------------------------------
    titre("ANCIEN COMPORTEMENT — strategies en cascade")
    gagnante, ids_cascade = None, []
    for nom, conditions in strategies:
        domaine = base + conditions + filtres(etat)
        try:
            ids = client.execute_kw('stock.picking', 'search', [domaine])
        except Exception as e:
            print(f"  {nom:<18} erreur : {e}")
            continue
        marque = ''
        if ids and gagnante is None:
            gagnante, ids_cascade = nom, ids
            marque = '   <- retenue, les suivantes ne sont jamais evaluees'
        print(f"  {nom:<18} {len(ids):>5} transfert(s){marque}")

    print(f"\n  Strategie retenue : {gagnante or 'aucune'} "
          f"-> {len(ids_cascade)} transfert(s) renvoyes")

    # ------------------------------------------------------------------
    # Nouveau comportement : union
    # ------------------------------------------------------------------
    titre("NOUVEAU COMPORTEMENT — strategies reunies par OU")
    domaine_union = base + ou_domaines([c for _, c in strategies]) + filtres(etat)
    ids_union = client.execute_kw('stock.picking', 'search', [domaine_union])
    print(f"  {len(ids_union)} transfert(s) renvoyes")

    gagnes = sorted(set(ids_union) - set(ids_cascade))
    if gagnes:
        print(f"\n  {len(gagnes)} transfert(s) que l'ancienne recherche manquait :\n")
        details = client.execute_kw(
            'stock.picking', 'read', [gagnes[:40]],
            {'fields': ['name', 'state', 'partner_id', 'location_id',
                        'location_dest_id', 'picking_type_code', 'date']}
        )
        for d in sorted(details, key=lambda x: str(x.get('date')), reverse=True):
            part = d.get('partner_id')
            src = d.get('location_id')
            dst = d.get('location_dest_id')
            print(f"    {d['id']:>7}  {d['name']:<20} {d['state']:<6} "
                  f"{d['picking_type_code']:<9} {str(d.get('date'))[:16]}")
            print(f"    {'':>7}  {src[1] if isinstance(src, list) else '?'} -> "
                  f"{dst[1] if isinstance(dst, list) else '?'}")
            print(f"    {'':>7}  partenaire : "
                  f"{part[1] if isinstance(part, list) else '—'}")
        if len(gagnes) > 40:
            print(f"    ... et {len(gagnes) - 40} autre(s)")
    else:
        print("\n  Aucun ecart : les deux recherches renvoient la meme chose.")

    # ------------------------------------------------------------------
    # Transferts nommement attendus
    # ------------------------------------------------------------------
    if attendus:
        titre("TRANSFERTS ATTENDUS")
        for pid in attendus:
            try:
                p = client.execute_kw(
                    'stock.picking', 'read', [pid],
                    {'fields': ['name', 'state', 'partner_id', 'location_id',
                                'location_dest_id', 'picking_type_code', 'date']}
                )[0]
            except Exception as e:
                print(f"\n  {pid} : illisible — {e}")
                continue

            src = p.get('location_id')
            part = p.get('partner_id')
            print(f"\n  {pid}  {p['name']}  ({p['state']}, {p['picking_type_code']})")
            print(f"    source     : {src[1] if isinstance(src, list) else '?'}")
            print(f"    partenaire : {part[1] if isinstance(part, list) else '—'}")
            print(f"    ancienne recherche : "
                  f"{'TROUVE' if pid in ids_cascade else 'MANQUE'}")
            print(f"    nouvelle recherche : "
                  f"{'TROUVE' if pid in ids_union else 'MANQUE'}")

            # Quelle strategie le ramene, une par une
            porteuses = []
            for nom, conditions in strategies:
                try:
                    if client.execute_kw(
                        'stock.picking', 'search_count',
                        [[('id', '=', pid)] + conditions]
                    ):
                        porteuses.append(nom)
                except Exception:
                    pass
            print(f"    trouve par : {', '.join(porteuses) or 'aucune strategie'}")


if __name__ == '__main__':
    main()
