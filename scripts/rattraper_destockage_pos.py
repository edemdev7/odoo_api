#!/usr/bin/env python3
"""
Rattrape le destockage des ventes POS passees par l'API.

Jusqu'au correctif du 12/11/2026, l'API soldait les commandes sans jamais
creer leur transfert de stock. Le stock etant mis a jour « en temps reel »,
Odoo ne rattrape rien a la cloture : ces ventes sont toujours comptees en
stock. Le correctif dans api/pos.py vaut pour les ventes a venir ; ce script
reprend celles qui existent deja.

Il retient les ventes de l'API (reference « Order-<pdv>-... ») soldees :
  - sans aucun transfert, et portant au moins un produit stocke ;
  - ou dont le transfert existe mais n'a pas ete valide.
Il ecarte les sessions destockees a la cloture (mode « a la cloture » ou
transfert de session present) : leurs ventes sont deja sorties du stock.

Simulation par defaut : la liste est lue en stdlib seule, sans rien ecrire.
Avec --appliquer, chaque commande passe par _destocker_commande, la fonction
qu'utilise l'API au paiement. Il faut alors l'environnement Python du projet
(fastapi, dotenv...) : activer le virtualenv avant.

Les transferts sont dates du jour du rattrapage, pas de la vente.

Usage :
    cd ~/Documents/projects/odoo_api
    python scripts/rattraper_destockage_pos.py                      # tous les PDV
    python scripts/rattraper_destockage_pos.py --pos 32
    python scripts/rattraper_destockage_pos.py --pos 32 --depuis 2026-11-01
    python scripts/rattraper_destockage_pos.py --pos 32 --appliquer
    python scripts/rattraper_destockage_pos.py --appliquer --max 20
"""

import os
import sys
import time
import xmlrpc.client

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')
except AttributeError:
    pass

ICI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ICI)

from _odoo_direct import connexion  # noqa: E402

LARGEUR = 92
ETATS_SOLDES = ['paid', 'done', 'invoiced']
LOT = 200                      # commandes par requete
ESSAIS = 3                     # tentatives par lecture
LECTURES = ('search', 'search_read', 'search_count', 'read', 'fields_get')


def titre(t):
    print()
    print("=" * LARGEUR)
    print(t)
    print("=" * LARGEUR)


def m2o_id(v):
    return v[0] if isinstance(v, list) and v else (v or None)


def m2o_nom(v):
    return v[1] if isinstance(v, list) and len(v) > 1 else ('—' if not v else str(v))


def lire_args(argv):
    opts = {'pos': None, 'depuis': None, 'base': 'DB1', 'max': None, 'appliquer': False}
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == '--appliquer':
            opts['appliquer'] = True
            i += 1
            continue
        if a in ('-h', '--help'):
            print(__doc__)
            sys.exit(0)
        if not a.startswith('--'):
            raise SystemExit(f"Argument inattendu : {a}")
        cle, _, val = a[2:].partition('=')
        if cle not in ('pos', 'depuis', 'base', 'max'):
            raise SystemExit(f"Option inconnue : {a}")
        if not val:
            i += 1
            if i >= len(argv):
                raise SystemExit(f"Valeur manquante pour {a}")
            val = argv[i]
        opts[cle] = int(val) if cle in ('pos', 'max') else (
            val.upper() if cle == 'base' else val)
        i += 1
    return opts


def lectures_avec_relance(appel):
    """
    Relance une lecture quand Odoo.sh repond 502/503/504 (worker occupe ou
    endormi sur une base de staging). Les ecritures ne passent jamais par
    ici : rejouer une creation apres un 502 risquerait de la doubler, le
    serveur ayant pu l'enregistrer avant de couper.
    """
    def lire(modele, methode, args, kwargs=None):
        if methode not in LECTURES:
            raise ValueError(f"{methode} n'est pas une lecture")
        for essai in range(1, ESSAIS + 1):
            try:
                return appel(modele, methode, args, kwargs or {})
            except xmlrpc.client.ProtocolError as e:
                if e.errcode not in (502, 503, 504) or essai == ESSAIS:
                    raise
                attente = 5 * essai
                print(f"  Odoo a repondu {e.errcode} — nouvel essai dans {attente} s "
                      f"({essai}/{ESSAIS - 1})")
                time.sleep(attente)
    return lire


def sessions_destockees_a_la_cloture(lire, session_ids, cache):
    """
    Sessions dont les ventes sont deja sorties du stock a la cloture.
    `cache` garde la decision d'un lot a l'autre.
    """
    nouvelles = [s for s in session_ids if s and s not in cache]
    if nouvelles:
        for s in nouvelles:
            cache[s] = False
        try:
            for s in lire('pos.session', 'read', [nouvelles],
                          {'fields': ['update_stock_at_closing']}):
                if s.get('update_stock_at_closing'):
                    cache[s['id']] = True
        except Exception as e:
            print(f"  (mode de cloture des sessions illisible : {e})")
        for t in lire('stock.picking', 'search_read', [[
                ('pos_session_id', 'in', nouvelles),
                ('pos_order_id', '=', False),
                ('state', '!=', 'cancel')]], {'fields': ['pos_session_id']}):
            cache[m2o_id(t['pos_session_id'])] = True
    return {s for s in session_ids if cache.get(s)}


def recenser(lire, opts):
    # Seules les ventes de l'API sont concernees : la caisse Odoo cree ses
    # transferts elle-meme. L'API les reconnait a leur reference
    # « Order-<pdv>-<horodatage> » (avec un tiret, la ou la caisse ecrit
    # « Commande 30041-001-0008 »). Un remboursement fait dans Odoo reprend
    # la reference de la vente d'origine : il est donc inclus.
    domaine = [('state', 'in', ETATS_SOLDES), ('pos_reference', '=like', 'Order-%')]
    if opts['pos']:
        domaine.append(('session_id.config_id', '=', opts['pos']))
    if opts['depuis']:
        domaine.append(('date_order', '>=', f"{opts['depuis']} 00:00:00"))

    total = lire('pos.order', 'search_count', [domaine])
    print(f"  Ventes API soldees a examiner : {total}  (lots de {LOT})")

    a_traiter, quantites = [], {}
    cache_sessions, exclues_vues = {}, set()
    dernier_id, n_lot, vus = 0, 0, 0

    # Pagination par identifiant : chaque requete reste courte, quel que soit
    # le volume de la base.
    while True:
        commandes = lire('pos.order', 'search_read', [domaine + [('id', '>', dernier_id)]], {
            'fields': ['id', 'name', 'pos_reference', 'state', 'date_order',
                       'session_id', 'config_id', 'picking_ids'],
            'order': 'id', 'limit': LOT})
        if not commandes:
            break
        n_lot += 1
        vus += len(commandes)
        dernier_id = commandes[-1]['id']

        tr_ids = sorted({t for c in commandes for t in (c.get('picking_ids') or [])})
        etats_tr = {}
        if tr_ids:
            for t in lire('stock.picking', 'read', [tr_ids], {'fields': ['state']}):
                etats_tr[t['id']] = t['state']

        exclues = sessions_destockees_a_la_cloture(
            lire, {m2o_id(c['session_id']) for c in commandes}, cache_sessions)
        exclues_vues |= exclues

        sans_tr = [c for c in commandes
                   if m2o_id(c['session_id']) not in exclues
                   and all(etats_tr.get(t) == 'cancel' for t in (c.get('picking_ids') or []))]

        lignes_par_cmd = {}
        if sans_tr:
            for l in lire('pos.order.line', 'search_read', [[
                    ('order_id', 'in', [c['id'] for c in sans_tr]),
                    ('product_id.type', '!=', 'service'),
                    ('qty', '!=', 0)]], {'fields': ['order_id', 'product_id', 'qty']}):
                lignes_par_cmd.setdefault(m2o_id(l['order_id']), []).append(l)

        retenues = 0
        for c in sans_tr:
            lignes = lignes_par_cmd.get(c['id'])
            if not lignes:
                continue
            c['_motif'] = 'aucun transfert'
            a_traiter.append(c)
            retenues += 1
            pdv = m2o_nom(c.get('config_id'))
            for l in lignes:
                cle = (pdv, m2o_nom(l['product_id']))
                quantites[cle] = quantites.get(cle, 0.0) + float(l['qty'] or 0)
        print(f"  lot {n_lot:>3} : {vus}/{total} lues, {retenues} sans transfert")

    # Transferts existants mais jamais valides — peu nombreux, lus a part,
    # toutes origines confondues (caisse comprise).
    dom_tr = [('pos_order_id', '!=', False), ('state', 'not in', ('done', 'cancel'))]
    if opts['pos']:
        dom_tr.append(('pos_order_id.session_id.config_id', '=', opts['pos']))
    if opts['depuis']:
        dom_tr.append(('pos_order_id.date_order', '>=', f"{opts['depuis']} 00:00:00"))
    en_suspens = lire('stock.picking', 'search_read', [dom_tr],
                      {'fields': ['name', 'state', 'pos_order_id'], 'limit': 1000})
    deja = {c['id'] for c in a_traiter}
    par_cmd = {}
    for t in en_suspens:
        par_cmd.setdefault(m2o_id(t['pos_order_id']), []).append(t)
    if par_cmd:
        for c in lire('pos.order', 'read', [list(par_cmd)], {'fields': [
                'id', 'name', 'pos_reference', 'state', 'date_order', 'config_id']}):
            if c['id'] in deja or c['state'] not in ETATS_SOLDES:
                continue
            c['_motif'] = 'transfert non valide : ' + ', '.join(
                f"{t['name']} [{t['state']}]" for t in par_cmd[c['id']])
            a_traiter.append(c)

    titre(f"A RATTRAPER — {len(a_traiter)} commande(s)")
    if exclues_vues:
        print(f"  ({len(exclues_vues)} session(s) ecartee(s) : destockees a la cloture)")
    par_pdv = {}
    for c in a_traiter:
        par_pdv.setdefault(m2o_nom(c.get('config_id')), []).append(c)
    for pdv, liste in sorted(par_pdv.items()):
        print(f"\n  {pdv} — {len(liste)} commande(s)")
        for c in sorted(liste, key=lambda x: x.get('date_order') or ''):
            print(f"    {c['name']:<20} {(c.get('pos_reference') or '')[:26]:<26} "
                  f"{c['state']:<9} {(c.get('date_order') or '')[:16]}  {c['_motif']}")

    if quantites:
        titre("QUANTITES ENCORE COMPTEES EN STOCK (commandes sans transfert)")
        for (pdv, produit), q in sorted(quantites.items()):
            print(f"  {pdv[:20]:<20} {produit[:48]:<48} {q:>12,.3f}")
    return a_traiter


def appliquer(appel, a_traiter, maximum):
    # Import tardif : la simulation reste en stdlib seule.
    racine = os.path.dirname(ICI)
    sys.path.insert(0, racine)
    try:
        from api.pos import _destocker_commande
    except ImportError as e:
        raise SystemExit(
            f"Impossible de charger api/pos.py ({e}).\n"
            f"Activer le virtualenv du projet avant --appliquer, par exemple :\n"
            f"  source env/Scripts/activate")

    class Client:
        """Adapte la connexion stdlib a l'interface execute_kw de l'API."""
        def execute_kw(self, modele, methode, args, kwargs=None):
            return appel(modele, methode, args, kwargs or {})

    client = Client()
    lot = a_traiter[:maximum] if maximum else a_traiter
    titre(f"APPLICATION — {len(lot)} commande(s)")
    bilan = {}
    for c in lot:
        pos_id = m2o_id(c.get('config_id'))
        res = _destocker_commande(client, c['id'], pos_id)
        bilan[res['statut']] = bilan.get(res['statut'], 0) + 1
        transferts = ', '.join(f"{t['name']} [{t['state']}]" for t in res['transferts'])
        print(f"  {c['name']:<16} {res['statut']:<12} {transferts}"
              + (f"  — {res['message']}" if res.get('message') else ''))
    print(f"\n  Bilan : {bilan}")
    if maximum and len(a_traiter) > maximum:
        print(f"  Reste {len(a_traiter) - maximum} commande(s) : relancer la commande.")


def main():
    opts = lire_args(sys.argv[1:])
    appel = connexion(opts['base'])

    titre("RECENSEMENT" + (f" — PDV {opts['pos']}" if opts['pos'] else " — tous les PDV")
          + (f" depuis le {opts['depuis']}" if opts['depuis'] else ""))
    a_traiter = recenser(lectures_avec_relance(appel), opts)

    if not a_traiter:
        print("\n  Rien a rattraper.")
        return
    if not opts['appliquer']:
        print("\n  SIMULATION — rien n'a ete ecrit. Pour creer et valider les transferts :")
        print("    python scripts/rattraper_destockage_pos.py "
              + ' '.join(a for a in sys.argv[1:]) + " --appliquer")
        return
    appliquer(appel, a_traiter, opts['max'])


if __name__ == '__main__':
    main()
