#!/usr/bin/env python3
"""
Controle de la ligne « Stock transfere » avant deploiement.

Rejoue, hors API, le calcul ajoute a /pos/sessions/{id}/stock-evolution :
les bouteilles vides reparties de la station vers un camion ou un magasin
depuis l'ouverture de la session.

Le script affiche aussi les sorties ecartees — ventes a des clients,
deplacements internes — pour qu'on voie ce que le filtre retient et ce
qu'il laisse de cote.

Lecture seule.

Attention : le code d'une station et l'identifiant de son point de vente ne
coincident pas — le PDV 29 est JO16. `--station` prend le code lu dans les
mouvements de stock, `--pos` l'identifiant du pos.config.

Usage :
    cd ~/Documents/projects/odoo_api
    python3 scripts/diag_transfert_bouteilles.py 26761        # une session
    python3 scripts/diag_transfert_bouteilles.py --station JO29 --jours 30
    python3 scripts/diag_transfert_bouteilles.py --pos 29 --jours 7
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

# Les deux resolutions ci-dessous existent deja dans api/pos.py, mais importer
# ce module tirerait FastAPI, passlib et tout le reste : un poste de dev n'a pas
# forcement les dependances du serveur. Elles sont donc redites ici, a
# l'identique. Si la regle change dans pos.py, elle doit changer ici aussi —
# c'est le prix d'un script qui tourne partout.

MOTIF_BOUTEILLE_VIDE = 'BOUTEILLE VIDE'
MOTIFS_HORS_PERIMETRE = ('HORS USAGE', 'REBUT', 'FERRAILLE')


def bouteilles_vides(client):
    """
    Bouteilles consignees, hors rebut.

    Le nom fait foi : la categorie 86 s'appelle « BOUTEILLES VIDES DE GAZ »
    mais ne contient que des bouteilles hors usage, tandis que les vraies
    consignees sont rangees en categorie 85.
    """
    ids = set()
    try:
        for p in client.execute_kw(
            'product.product', 'search_read',
            [[('name', 'ilike', MOTIF_BOUTEILLE_VIDE)]], {'fields': ['id', 'name']}
        ):
            nom = (p.get('name') or '').upper()
            if any(m in nom for m in MOTIFS_HORS_PERIMETRE):
                continue
            ids.add(p['id'])
    except Exception as e:
        print(f"  Produits « bouteille vide » illisibles: {e}")
    return ids


def resoudre_emplacement_station(client, code: str) -> tuple:
    """
    (location_id, nom, fiable) depuis le code d'une station — « JO29 ».

    Raccourci de diagnostic : le code station ne coincide pas avec l'ID du
    point de vente (le PDV 29 est JO16), et c'est le code qu'on lit dans les
    mouvements de stock.
    """
    code = code.strip().rstrip('/')
    candidats = client.execute_kw(
        'stock.location', 'search_read',
        [[('complete_name', '=like', f'{code}/%'), ('usage', '=', 'internal')]],
        {'fields': ['id', 'complete_name']}
    )
    if not candidats:
        raise SystemExit(f"Aucun emplacement interne « {code}/… » dans Odoo.")
    racine = min(candidats, key=lambda c: len(c.get('complete_name') or ''))
    return racine['id'], racine['complete_name'], True


def resoudre_emplacement_pdv(client, pos_id: int) -> tuple:
    """
    (location_id, nom, fiable) — emplacement de stock d'un point de vente.

    Derive du code de la station (« JO29 ALLADA » -> « JO29/ »). L'entrepot
    du pos.config pointe vers le siege et ne reflete pas la station : il ne
    sert qu'en dernier recours, et `fiable` vaut alors False.
    """
    config = client.execute_kw(
        'pos.config', 'search_read', [[('id', '=', pos_id)]],
        {'fields': ['id', 'name', 'warehouse_id'], 'limit': 1}
    )
    if not config:
        raise SystemExit(f"Point de vente {pos_id} introuvable.")

    nom_pdv = config[0].get('name') or ''
    code = nom_pdv.split()[0] if nom_pdv.split() else None

    if code:
        try:
            candidats = client.execute_kw(
                'stock.location', 'search_read',
                [[('complete_name', '=like', f'{code}/%'),
                  ('usage', '=', 'internal')]],
                {'fields': ['id', 'complete_name']}
            )
            if candidats:
                racine = min(candidats, key=lambda c: len(c.get('complete_name') or ''))
                return racine['id'], racine['complete_name'], True
        except Exception as e:
            print(f"  Recherche de l'emplacement « {code} » echouee: {e}")

    entrepot = config[0].get('warehouse_id')
    if entrepot:
        wh_id = entrepot[0] if isinstance(entrepot, list) else entrepot
        wh = client.execute_kw(
            'stock.warehouse', 'read', [[wh_id]], {'fields': ['lot_stock_id', 'name']}
        )
        if wh:
            return wh[0]['lot_stock_id'][0], f"Stock {wh[0]['name']}", False

    raise SystemExit(f"Aucun emplacement de stock pour le PDV {pos_id}.")


def titre(t):
    print()
    print("=" * LARGEUR)
    print(t)
    print("=" * LARGEUR)


def lire_arguments(argv) -> tuple:
    """
    (sessions, pos_id, jours) depuis la ligne de commande.

    Les valeurs d'options sont consommees au passage : sans cela, le `7` de
    `--jours 7` se faisait prendre pour un identifiant de session, et le
    script analysait tout autre chose que ce qu'on lui demandait.
    """
    sessions, pos_id, station, jours = [], None, None, None
    i = 0
    while i < len(argv):
        a = argv[i]
        if a.startswith('--'):
            if '=' in a:
                nom, valeur = a.split('=', 1)
            else:
                nom, valeur = a, (argv[i + 1] if i + 1 < len(argv) else None)
                i += 1
            if nom == '--pos':
                pos_id = valeur
            elif nom == '--station':
                station = valeur
            elif nom == '--jours':
                jours = valeur
            else:
                raise SystemExit(f"Option inconnue : {nom}")
        elif a.isdigit():
            sessions.append(int(a))
        else:
            raise SystemExit(f"Argument inattendu : {a}")
        i += 1
    return sessions, pos_id, station, jours


def analyser(client, emplacement, depuis, libelle_periode, entete=''):
    emplacement_id, nom_emplacement, fiable = emplacement

    titre(" — ".join(p for p in (entete, nom_emplacement, libelle_periode) if p))
    if not fiable:
        print("  ATTENTION : emplacement resolu par repli sur l'entrepot du siege.")
        print("  Les quantites ci-dessous ne refletent pas cette station.\n")

    bouteilles = bouteilles_vides(client)
    if not bouteilles:
        print("  Aucun produit « bouteille vide » identifie. Rien a calculer.")
        return

    locaux = set(client.execute_kw(
        'stock.location', 'search', [[('id', 'child_of', emplacement_id)]]
    ))

    lignes = client.execute_kw(
        'stock.move.line', 'search_read',
        [[('state', '=', 'done'),
          ('date', '>=', depuis),
          ('product_id', 'in', list(bouteilles)),
          ('location_id', 'child_of', emplacement_id)]],
        {'fields': ['product_id', 'quantity', 'qty_done', 'date',
                    'location_id', 'location_dest_id', 'reference'],
         'order': 'date desc'}
    )

    if not lignes:
        print(f"  Aucune sortie de bouteille vide depuis {depuis}.")
        print("  La ligne « Stock transfere » vaudra 0 sur cette session.")
        return

    # Usage des destinations : seul un emplacement interne vaut reprise.
    dst_ids = set()
    for l in lignes:
        d = l.get('location_dest_id')
        did = d[0] if isinstance(d, list) else d
        if did and did not in locaux:
            dst_ids.add(did)

    usages = {}
    if dst_ids:
        for loc in client.execute_kw(
            'stock.location', 'read', [list(dst_ids)],
            {'fields': ['usage', 'complete_name']}
        ):
            usages[loc['id']] = loc

    retenues, ecartees = [], []
    cumul: dict = {}
    destinations: dict = {}

    for l in lignes:
        prod = l.get('product_id')
        pid = prod[0] if isinstance(prod, list) else prod
        nom = prod[1] if isinstance(prod, list) else str(pid)
        qte = float(l.get('quantity') or 0) or float(l.get('qty_done') or 0)
        if qte <= 0:
            continue

        d = l.get('location_dest_id')
        did = d[0] if isinstance(d, list) else d
        dest = usages.get(did) or {}
        nom_dest = dest.get('complete_name') or (d[1] if isinstance(d, list) else '?')

        if did in locaux:
            ecartees.append((l, nom, qte, nom_dest, "deplacement interne au PDV"))
        elif dest.get('usage') == 'internal':
            retenues.append((l, nom, qte, nom_dest, ""))
            cumul[nom] = cumul.get(nom, 0.0) + qte
            destinations.setdefault(nom, set()).add(nom_dest)
        else:
            ecartees.append((l, nom, qte, nom_dest,
                             f"usage « {dest.get('usage') or '?'} » — vente ou perte"))

    print(f"  RETENU — {len(retenues)} mouvement(s) comptes comme reprise\n")
    for l, nom, qte, nom_dest, _ in retenues:
        print(f"    {str(l.get('date'))[:16]}  {nom[:30]:<30} {qte:>7g}  -> {nom_dest}")

    if ecartees:
        print(f"\n  ECARTE — {len(ecartees)} mouvement(s)\n")
        for l, nom, qte, nom_dest, motif in ecartees:
            print(f"    {str(l.get('date'))[:16]}  {nom[:30]:<30} {qte:>7g}  "
                  f"-> {nom_dest}")
            print(f"    {'':<16}  {motif}")

    titre("CE QUE L'API RENVERRA")
    if cumul:
        print(f"  {'Produit':<34} {'stock_transfere':>16}  destinations")
        print("  " + "-" * (LARGEUR - 4))
        for nom in sorted(cumul):
            print(f"  {nom[:34]:<34} {cumul[nom]:>16g}  "
                  f"{', '.join(sorted(destinations[nom]))}")
        print(f"\n  total_stock_transfere : {round(sum(cumul.values()), 3):g}")
    else:
        print("  stock_transfere = 0 pour tous les formats.")
    print("\n  Rappel : null sur tout produit qui n'est pas une bouteille vide.")


def main():
    sessions, pos_id, station, jours = lire_arguments(sys.argv[1:])

    if not sessions and not pos_id and not station:
        print(__doc__)
        sys.exit(1)

    print("Connexion a Odoo...")
    client = OdooClient()

    for sid in sessions:
        # Toutes les sessions ne sont pas lisibles : l'utilisateur API n'a pas
        # acces aux societes auxquelles il n'est pas rattache. On le dit et on
        # passe a la suivante plutot que d'interrompre le diagnostic.
        try:
            session = client.execute_kw(
                'pos.session', 'read', [sid],
                {'fields': ['name', 'state', 'start_at', 'stop_at', 'config_id']}
            )
        except Exception as e:
            titre(f"SESSION {sid} — ILLISIBLE")
            print(f"  {e}")
            print("\n  Session hors du perimetre de l'utilisateur API, ou inexistante.")
            continue

        if not session:
            titre(f"SESSION {sid} — INTROUVABLE")
            continue

        s = session[0]
        cfg = s.get('config_id')
        pid = cfg[0] if isinstance(cfg, list) else cfg
        analyser(
            client,
            resoudre_emplacement_pdv(client, pid),
            s['start_at'],
            f"session {s['name']} ouverte le {s['start_at']} ({s['state']})",
            entete=f"PDV {pid}"
        )

    nb = int(jours or 7)
    depuis = (datetime.now() - timedelta(days=nb)).strftime('%Y-%m-%d 00:00:00')
    periode = f"{nb} dernier(s) jour(s), depuis le {depuis[:10]}"

    if pos_id:
        analyser(client, resoudre_emplacement_pdv(client, int(pos_id)),
                 depuis, periode, entete=f"PDV {pos_id}")

    if station:
        analyser(client, resoudre_emplacement_station(client, station),
                 depuis, periode, entete=f"Station {station.upper()}")


if __name__ == '__main__':
    main()
