#!/usr/bin/env python3
"""
Pourquoi l'inventaire d'un camion ne bouge pas apres un transfert.

Montre quels emplacements l'ancienne resolution trouvait, lesquels la
nouvelle ajoute (comparaison sans espaces), et ce que chacun contient.
Un meme camion saisi `CAM/AX0042RB` d'un cote et `CAM/AX 0042 RB` de
l'autre voit son stock eclate : le chauffeur n'en voit qu'une moitie.

Affiche aussi la ligne « Stock transfere » du jour : les bouteilles vides
entrees dans le camion depuis une station.

Lecture seule.

Usage :
    cd ~/Documents/projects/odoo_api
    python3 scripts/diag_inventaire_camion.py AX0042RB
    python3 scripts/diag_inventaire_camion.py AX0042RB --jour 2026-10-14
"""

import sys
import os
from datetime import datetime

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

CATEG_BOUTEILLES_VIDES = [86]


def titre(t):
    print()
    print("=" * LARGEUR)
    print(t)
    print("=" * LARGEUR)


def normaliser(valeur):
    return ''.join(c for c in (valeur or '').upper() if c.isalnum())


def bouteilles_vides(client):
    ids = set()
    try:
        categories = list(CATEG_BOUTEILLES_VIDES)
        for cid in client.execute_kw(
            'product.category', 'search', [[('name', 'ilike', 'BOUTEILLES VIDES')]]
        ):
            if cid not in categories:
                categories.append(cid)
        ids.update(client.execute_kw(
            'product.product', 'search', [[('categ_id', 'in', categories)]]))
        ids.update(client.execute_kw(
            'product.product', 'search', [[('name', 'ilike', 'BOUTEILLE VIDE')]]))
    except Exception as e:
        print(f"  Produits « bouteille vide » illisibles: {e}")
    return ids


def main():
    argv = sys.argv[1:]
    if not argv or argv[0].startswith('--'):
        print(__doc__)
        sys.exit(1)

    camion = argv[0]
    jour = None
    i = 1
    while i < len(argv):
        a = argv[i]
        nom, valeur = (a.split('=', 1) if '=' in a
                       else (a, argv[i + 1] if i + 1 < len(argv) else None))
        if '=' not in a:
            i += 1
        if nom == '--jour':
            jour = valeur
        else:
            raise SystemExit(f"Option inconnue : {nom}")
        i += 1
    jour = jour or datetime.now().strftime('%Y-%m-%d')

    print("Connexion a Odoo...")
    client = OdooClient()

    titre(f"CAMION {camion} — journee du {jour}")

    # --- Passe 1 et 2 : ilike, comme avant ---
    anciens = []
    for champ in ('name', 'complete_name'):
        trouves = client.execute_kw(
            'stock.location', 'search',
            [[(champ, 'ilike', camion), ('usage', '=', 'internal')]]
        )
        if trouves:
            anciens = trouves
            print(f"  Recherche ilike sur « {champ} » : {len(trouves)} emplacement(s)")
            break
    if not anciens:
        print("  Recherche ilike : aucun emplacement.")

    # --- Passe 3 : comparaison sans espaces ---
    attendu = normaliser(camion)
    nouveaux = []
    if len(attendu) >= 4:
        candidats = client.execute_kw(
            'stock.location', 'search_read',
            [[('name', 'ilike', '%'.join(attendu)), ('usage', '=', 'internal')]],
            {'fields': ['id', 'name', 'complete_name']}
        )
        nouveaux = [c for c in candidats if normaliser(c.get('name')) == attendu]

    tous = list(anciens)
    ajoutes = []
    for c in nouveaux:
        if c['id'] not in tous:
            tous.append(c['id'])
            ajoutes.append(c)

    details = client.execute_kw(
        'stock.location', 'read', [tous], {'fields': ['id', 'complete_name']}
    ) if tous else []
    noms = {d['id']: d['complete_name'] for d in details}

    print(f"\n  Emplacements retenus ({len(tous)}) :")
    for lid in tous:
        marque = "   <- ajoute par la comparaison sans espaces" if lid in [
            c['id'] for c in ajoutes] else ""
        print(f"    {lid:>6}  {noms.get(lid, '?')}{marque}")

    if ajoutes:
        print("""
  Plusieurs emplacements portent cette plaque a l'espacement pres. Ils ne
  sont PAS fusionnes : l'un peut porter la marchandise et l'autre les pieces
  detachees du vehicule. Regarder leur contenu ci-dessous pour savoir lequel
  l'inventaire du chauffeur doit suivre.

  Seul le premier de la liste est retenu par l'API.""")

    if not tous:
        return

    # --- Contenu de chaque emplacement ---
    titre("CONTENU PAR EMPLACEMENT")
    for lid in tous:
        quants = client.execute_kw(
            'stock.quant', 'search_read',
            [[('location_id', 'child_of', [lid]), ('quantity', '!=', 0)]],
            {'fields': ['product_id', 'quantity'], 'limit': 40}
        )
        print(f"\n  {noms.get(lid, lid)} — {len(quants)} ligne(s)")
        for q in quants:
            prod = q.get('product_id')
            print(f"    {(prod[1] if isinstance(prod, list) else '?')[:50]:<50} "
                  f"{q.get('quantity'):>10}")
        if not quants:
            print("    (vide)")

    # --- Ligne « Stock transfere » du jour ---
    titre(f"STOCK TRANSFERE — bouteilles vides entrees le {jour}")
    vides = bouteilles_vides(client)
    if not vides:
        print("  Aucun produit « bouteille vide » identifie.")
        derniers_mouvements(client, camion, tous)
        return

    locaux = set(client.execute_kw(
        'stock.location', 'search', [[('id', 'child_of', tous)]]
    ))

    entrees = client.execute_kw(
        'stock.move.line', 'search_read',
        [[('state', '=', 'done'),
          ('date', '>=', f"{jour} 00:00:00"),
          ('date', '<=', f"{jour} 23:59:59"),
          ('product_id', 'in', list(vides)),
          ('location_dest_id', 'child_of', tous)]],
        {'fields': ['product_id', 'quantity', 'qty_done', 'date',
                    'location_id', 'location_dest_id'], 'order': 'date desc'}
    )

    if not entrees:
        print(f"  Aucune entree de bouteille vide le {jour}.")
        print("  stock_transfere vaudra 0 sur toutes les lignes.")
        # C'est justement le cas ou il faut regarder plus large : le
        # transfert existe peut-etre, un autre jour ou non valide.
        derniers_mouvements(client, camion, tous)
        return

    sources = {}
    a_lire = {(l['location_id'][0] if isinstance(l.get('location_id'), list)
               else l.get('location_id')) for l in entrees}
    a_lire = {s for s in a_lire if s and s not in locaux}
    if a_lire:
        for loc in client.execute_kw(
            'stock.location', 'read', [list(a_lire)],
            {'fields': ['usage', 'complete_name']}
        ):
            sources[loc['id']] = loc

    cumul, origines = {}, {}
    for l in entrees:
        prod = l.get('product_id')
        pid = prod[0] if isinstance(prod, list) else prod
        nom = prod[1] if isinstance(prod, list) else str(pid)
        src = l.get('location_id')
        src_id = src[0] if isinstance(src, list) else src
        qte = float(l.get('quantity') or 0) or float(l.get('qty_done') or 0)

        if src_id in locaux:
            motif = "deplacement interne au camion"
        else:
            source = sources.get(src_id) or {}
            if source.get('usage') != 'internal':
                motif = f"source usage « {source.get('usage') or '?'} »"
            else:
                motif = None
                cumul[nom] = cumul.get(nom, 0.0) + qte
                origines.setdefault(nom, set()).add(source.get('complete_name'))

        etat = "RETENU " if motif is None else "ECARTE "
        print(f"  {etat} {str(l.get('date'))[:16]}  {nom[:30]:<30} {qte:>7g}"
              + (f"   ({motif})" if motif else ""))

    print()
    if cumul:
        for nom in sorted(cumul):
            print(f"  {nom[:40]:<40} stock_transfere = {cumul[nom]:g}  "
                  f"depuis {', '.join(sorted(o for o in origines[nom] if o))}")
        print(f"\n  total_stock_transfere : {round(sum(cumul.values()), 3):g}")
    else:
        print("  stock_transfere = 0 : aucune entree ne vient d'une station.")

    derniers_mouvements(client, camion, tous)


def derniers_mouvements(client, camion, emplacements, jours=10):
    """
    Transferts de bouteilles vides touchant le camion, TOUS etats confondus.

    Un transfert reste invisible du chauffeur tant qu'il n'est pas valide :
    les quants ne bougent qu'a l'etat « done ». C'est la premiere chose a
    verifier quand la station s'est bien dechargee mais pas le camion.
    """
    from datetime import timedelta

    titre(f"TRANSFERTS DE BOUTEILLES VIDES — {jours} derniers jours, tous etats")

    depuis = (datetime.now() - timedelta(days=jours)).strftime('%Y-%m-%d 00:00:00')
    vides = bouteilles_vides(client)
    if not vides:
        return

    # On passe par stock.move : les move.line n'existent pas toujours avant
    # validation, alors qu'un transfert en brouillon a deja ses mouvements.
    moves = client.execute_kw(
        'stock.move', 'search_read',
        [['&', ('product_id', 'in', list(vides)),
          '&', ('date', '>=', depuis),
          '|', ('location_id', 'child_of', emplacements),
          ('location_dest_id', 'child_of', emplacements)]],
        {'fields': ['product_id', 'product_uom_qty', 'quantity', 'state',
                    'date', 'location_id', 'location_dest_id', 'reference',
                    'picking_id'],
         'order': 'date desc', 'limit': 60}
    )

    if not moves:
        print(f"  Aucun mouvement de bouteille vide depuis {depuis[:10]},")
        print("  ni valide ni en attente. Le transfert n'a pas touche ce camion.")
        return

    print(f"  {'Date':<17} {'Etat':<10} {'Produit':<28} {'Qte':>7}  Trajet")
    print("  " + "-" * (LARGEUR - 4))
    en_attente = 0
    for m in moves:
        prod = m.get('product_id')
        src = m.get('location_id')
        dst = m.get('location_dest_id')
        qte = m.get('quantity') or m.get('product_uom_qty') or 0
        etat = m.get('state')
        if etat != 'done':
            en_attente += 1
        print(f"  {str(m.get('date'))[:17]:<17} {etat:<10} "
              f"{(prod[1] if isinstance(prod, list) else '?')[:28]:<28} {qte:>7g}  "
              f"{(src[1] if isinstance(src, list) else '?')} -> "
              f"{(dst[1] if isinstance(dst, list) else '?')}")
        pick = m.get('picking_id')
        if pick:
            print(f"  {'':<17} {'':<10} transfert : "
                  f"{pick[1] if isinstance(pick, list) else pick}")

    if en_attente:
        print(f"""
  >>> {en_attente} mouvement(s) pas a l'etat « done ». Tant qu'un transfert
      n'est pas valide dans Odoo, les quantites ne bougent pas et le
      chauffeur ne voit rien — c'est le comportement attendu.""")
    else:
        print("""
  Tous les mouvements sont valides. Si le chauffeur ne les voit toujours
  pas, l'ecart vient de l'emplacement interroge, pas de l'etat.""")


if __name__ == '__main__':
    main()
