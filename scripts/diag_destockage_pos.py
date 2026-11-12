#!/usr/bin/env python3
"""
Verifie comment les ventes passees par l'API sont destockees dans Odoo.

Contexte : POST /pos/{pos_id}/orders/{order_id}/payments renvoie 502 quand
aucun transfert n'est rattache a la commande apres action_pos_order_paid.
Or en Odoo 17 cette action ne cree pas de transfert. Selon le reglage de la
societe, le stock est mis a jour :
  - a la cloture de session : transferts groupes, rattaches a la session ;
  - en temps reel : un transfert par commande, cree uniquement par le
    circuit de la caisse Odoo (create_from_ui) — jamais par l'API.

Le script repond a trois questions :
  1. Quel est le mode de mise a jour du stock (societe, sessions) ?
  2. Les sessions cloturees ont-elles des transferts, et ces transferts
     couvrent-ils les quantites vendues ?
  3. (option --commande) Que voit Odoo sur une commande precise ?
  4. (option --origine) Qui a cree les transferts existants, et quand ?
     Liste aussi les automatisations Odoo qui touchent pos.order /
     pos.session / stock.picking (bouton NORMALISER, actions, crons...).

Lecture seule.

Usage :
    cd ~/Documents/projects/odoo_api
    python3 scripts/diag_destockage_pos.py 32
    python3 scripts/diag_destockage_pos.py 32 --commande 785505
    python3 scripts/diag_destockage_pos.py 32 --limite 8 --base DB2
    python3 scripts/diag_destockage_pos.py 32 --origine
"""

import os
import re
import sys
import xmlrpc.client

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')
except AttributeError:
    pass

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _odoo_direct import connexion, configuration  # noqa: E402

LARGEUR = 92
ETATS_VENDUS = ['paid', 'done', 'invoiced']


# ---------------------------------------------------------------- utilitaires

def titre(t):
    print()
    print("=" * LARGEUR)
    print(t)
    print("=" * LARGEUR)


def m2o_id(v):
    return v[0] if isinstance(v, list) and v else (v or None)


def m2o_nom(v):
    if isinstance(v, list) and len(v) > 1:
        return v[1]
    return '—' if not v else str(v)


def champs(appel, modele, voulus):
    """Garde les champs qui existent sur le modele (17 et 19 different)."""
    try:
        dispo = appel(modele, 'fields_get', [], {'attributes': ['type']})
    except Exception:
        return list(voulus)
    return [c for c in voulus if c in dispo]


def version_odoo(base):
    url = configuration(base)[0]
    try:
        return xmlrpc.client.ServerProxy(f"{url}/xmlrpc/2/common").version().get(
            'server_version', '?')
    except Exception as e:
        return f"illisible ({e})"


def lire_args(argv):
    if not argv or not argv[0].isdigit():
        print(__doc__)
        sys.exit(1)
    opts = {'pos_id': int(argv[0]), 'commande': None, 'limite': 5, 'base': 'DB1',
            'origine': False}
    i = 1
    while i < len(argv):
        a = argv[i]
        if a == '--origine':
            opts['origine'] = True
            i += 1
            continue
        if not a.startswith('--'):
            raise SystemExit(f"Argument inattendu : {a}")
        cle, _, val = a[2:].partition('=')
        if cle not in ('commande', 'limite', 'base'):
            raise SystemExit(f"Option inconnue : {a}")
        if not val:
            i += 1
            if i >= len(argv):
                raise SystemExit(f"Valeur manquante pour {a}")
            val = argv[i]
        opts[cle] = val.upper() if cle == 'base' else int(val)
        i += 1
    return opts


# ------------------------------------------------------- 1. mode de mise a jour

def section_configuration(appel, pos_id):
    titre("1. CONFIGURATION — mode de mise a jour du stock")

    cfg = appel('pos.config', 'read', [[pos_id]], {'fields': champs(
        appel, 'pos.config',
        ['name', 'company_id', 'picking_type_id', 'current_session_id'])})
    if not cfg:
        raise SystemExit(f"Point de vente {pos_id} introuvable.")
    cfg = cfg[0]

    print(f"  PDV                    : {pos_id} — {cfg.get('name')}")
    print(f"  Societe                : {m2o_nom(cfg.get('company_id'))}")
    print(f"  Session en cours       : {m2o_nom(cfg.get('current_session_id'))}")

    mode_societe = None
    company_id = m2o_id(cfg.get('company_id'))
    if company_id:
        try:
            soc = appel('res.company', 'read', [[company_id]], {'fields': champs(
                appel, 'res.company',
                ['point_of_sale_update_stock_quantities', 'anglo_saxon_accounting'])})[0]
            mode_societe = soc.get('point_of_sale_update_stock_quantities')
            libelle = {'closing': "a la cloture de la session",
                       'real': "en temps reel"}.get(mode_societe, repr(mode_societe))
            print(f"  Mise a jour du stock   : {libelle}  (reglage societe)")
            if 'anglo_saxon_accounting' in soc:
                print(f"  Compta anglo-saxonne   : {soc.get('anglo_saxon_accounting')}")
        except Exception as e:
            print(f"  Mise a jour du stock   : illisible — {e}")

    type_op = cfg.get('picking_type_id')
    if not type_op:
        print("  Type d'operation       : AUCUN — Odoo ne peut creer aucun transfert")
    else:
        print(f"  Type d'operation       : {m2o_nom(type_op)} (ID {m2o_id(type_op)})")
        try:
            t = appel('stock.picking.type', 'read', [[m2o_id(type_op)]], {'fields': champs(
                appel, 'stock.picking.type',
                ['active', 'default_location_src_id', 'default_location_dest_id'])})[0]
            print(f"    emplacement source   : {m2o_nom(t.get('default_location_src_id'))}")
            print(f"    emplacement dest.    : {m2o_nom(t.get('default_location_dest_id'))}")
            if t.get('active') is False:
                print("    ATTENTION : type d'operation archive")
        except Exception as e:
            print(f"    detail illisible — {e}")

    return mode_societe


# ------------------------------------------------------------ 2. sessions

def quantites_session(appel, session_id, champ_qte, champ_usage):
    """(vendu, deplace) par produit pour une session — hors services."""
    vendu = {}
    lignes = appel('pos.order.line', 'search_read', [[
        ('order_id.session_id', '=', session_id),
        ('order_id.state', 'in', ETATS_VENDUS),
        ('product_id.type', '!=', 'service'),
    ]], {'fields': ['product_id', 'qty']})
    for l in lignes:
        p = m2o_nom(l['product_id'])
        vendu[p] = vendu.get(p, 0.0) + float(l['qty'] or 0)

    deplace = {}
    if champ_qte:
        champs_mv = ['product_id', champ_qte] + ([champ_usage] if champ_usage else [])
        mouvements = appel('stock.move', 'search_read', [[
            ('picking_id.pos_session_id', '=', session_id),
            ('state', '=', 'done'),
        ]], {'fields': champs_mv})
        for m in mouvements:
            p = m2o_nom(m['product_id'])
            q = float(m.get(champ_qte) or 0)
            # Un retour client rentre en stock : il compte en negatif.
            if champ_usage and m.get(champ_usage) and m.get(champ_usage) != 'customer':
                q = -q
            deplace[p] = deplace.get(p, 0.0) + q
    return vendu, deplace


def section_sessions(appel, pos_id, limite):
    titre(f"2. SESSIONS — {limite} dernieres du PDV {pos_id}")

    sessions = appel('pos.session', 'search_read', [[('config_id', '=', pos_id)]], {
        'fields': champs(appel, 'pos.session',
                         ['name', 'state', 'start_at', 'stop_at', 'update_stock_at_closing']),
        'limit': limite, 'order': 'id desc'})
    if not sessions:
        print("  Aucune session.")
        return []

    champ_qte = next(iter(champs(appel, 'stock.move', ['quantity', 'quantity_done'])), None)
    champ_usage = next(iter(champs(appel, 'stock.move', ['location_dest_usage'])), None)

    resultats = []
    for s in sessions:
        sid = s['id']
        nb_cmd = appel('pos.order', 'search_count', [[
            ('session_id', '=', sid), ('state', 'in', ETATS_VENDUS)]])
        nb_cmd_tr = appel('pos.order', 'search_count', [[
            ('session_id', '=', sid), ('state', 'in', ETATS_VENDUS),
            ('picking_ids', '!=', False)]])
        transferts = appel('stock.picking', 'search_read', [[('pos_session_id', '=', sid)]],
                           {'fields': ['name', 'state', 'pos_order_id']})
        tr_session = [t for t in transferts if not t.get('pos_order_id')]
        tr_commande = [t for t in transferts if t.get('pos_order_id')]

        a_cloture = s.get('update_stock_at_closing')
        print(f"\n  {s['name']}  [{s['state']}]  "
              f"{(s.get('start_at') or '')[:16]} -> {(s.get('stop_at') or '…')[:16]}")
        print(f"    stock mis a jour a la cloture : "
              f"{'?' if a_cloture is None else ('oui' if a_cloture else 'NON (temps reel)')}")
        print(f"    commandes vendues            : {nb_cmd}  "
              f"(dont {nb_cmd_tr} avec transfert propre)")
        etats = {}
        for t in tr_session:
            etats[t['state']] = etats.get(t['state'], 0) + 1
        print(f"    transferts de session        : {len(tr_session)}  "
              f"{dict(etats) if etats else ''}")
        print(f"    transferts par commande      : {len(tr_commande)}")

        ecarts = None
        if s['state'] == 'closed' and nb_cmd:
            try:
                vendu, deplace = quantites_session(appel, sid, champ_qte, champ_usage)
                ecarts = {p: (vendu.get(p, 0.0), deplace.get(p, 0.0))
                          for p in set(vendu) | set(deplace)
                          if abs(vendu.get(p, 0.0) - deplace.get(p, 0.0)) > 0.001}
                if not ecarts:
                    print(f"    quantites                    : vendu = destocke "
                          f"({len(vendu)} produit(s))")
                else:
                    print("    quantites                    : ECARTS")
                    for p, (v, d) in sorted(ecarts.items()):
                        print(f"      {p[:44]:<44} vendu {v:>10g}  destocke {d:>10g}")
            except Exception as e:
                print(f"    quantites                    : comparaison impossible — {e}")

        resultats.append({
            'session': s, 'nb_cmd': nb_cmd, 'nb_cmd_tr': nb_cmd_tr,
            'tr_session': tr_session, 'tr_commande': tr_commande, 'ecarts': ecarts,
        })
    return resultats


# ------------------------------------------------------------ 3. commande

def section_commande(appel, order_id):
    titre(f"3. COMMANDE {order_id}")

    o = appel('pos.order', 'read', [[order_id]], {'fields': champs(
        appel, 'pos.order',
        ['name', 'pos_reference', 'state', 'session_id', 'partner_id', 'amount_total',
         'amount_paid', 'amount_return', 'picking_ids', 'to_invoice', 'account_move'])})
    if not o:
        print("  Commande introuvable.")
        return
    o = o[0]
    print(f"  Reference      : {o.get('name')} / {o.get('pos_reference')}")
    print(f"  Etat           : {o.get('state')}")
    print(f"  Session        : {m2o_nom(o.get('session_id'))}")
    print(f"  Client         : {m2o_nom(o.get('partner_id'))}")
    print(f"  Montants       : total {o.get('amount_total')}  paye {o.get('amount_paid')}  "
          f"rendu {o.get('amount_return')}")
    print(f"  Transferts     : {o.get('picking_ids') or 'aucun'}")
    if 'account_move' in o:
        print(f"  Facture        : {m2o_nom(o.get('account_move'))}")

    paiements = appel('pos.payment', 'search_read', [[('pos_order_id', '=', order_id)]],
                      {'fields': ['id', 'payment_method_id', 'amount', 'payment_date']})
    print(f"  Paiements      : {len(paiements)}")
    for p in paiements:
        print(f"    #{p['id']}  {m2o_nom(p['payment_method_id'])[:30]:<30} "
              f"{float(p['amount']):>12,.2f}  {p.get('payment_date')}")

    lignes = appel('pos.order.line', 'search_read', [[('order_id', '=', order_id)]],
                   {'fields': ['product_id', 'qty', 'price_subtotal_incl']})
    champs_prod = champs(appel, 'product.product', ['type', 'detailed_type', 'is_storable'])
    print(f"  Lignes         : {len(lignes)}")
    for l in lignes:
        pid = m2o_id(l['product_id'])
        info = ''
        try:
            prod = appel('product.product', 'read', [[pid]], {'fields': champs_prod})[0]
            info = '  '.join(f"{c}={prod.get(c)}" for c in champs_prod)
        except Exception as e:
            info = f"type illisible ({e})"
        print(f"    {m2o_nom(l['product_id'])[:36]:<36} qte {float(l['qty']):>8g}  {info}")
        if prod_est_service(info):
            print("      -> produit de type service : jamais destocke, quel que soit le mode")


def prod_est_service(info):
    return "type=service" in info or "detailed_type=service" in info


# ------------------------------------------------- 4. origine des transferts

def _minutes(debut, fin):
    """Ecart en minutes entre deux dates Odoo 'AAAA-MM-JJ HH:MM:SS'."""
    from datetime import datetime
    try:
        f = '%Y-%m-%d %H:%M:%S'
        return (datetime.strptime(fin[:19], f) - datetime.strptime(debut[:19], f)).total_seconds() / 60
    except Exception:
        return None


def section_origine(appel, pos_id, resultats):
    titre("4. ORIGINE DES TRANSFERTS — qui les cree, et quand ?")
    print(f"  Les commandes creees par l'API ont une reference 'Order-{pos_id}-<horodatage>'.")

    champs_cmd = champs(appel, 'pos.order', [
        'name', 'pos_reference', 'state', 'date_order', 'create_date',
        'create_uid', 'write_uid', 'picking_ids'])
    champs_tr = champs(appel, 'stock.picking', [
        'name', 'state', 'create_date', 'create_uid', 'date_done', 'origin'])

    for r in resultats:
        s = r['session']
        if not r['nb_cmd']:
            continue
        print(f"\n  {s['name']}  [{s['state']}]  cloturee le {(s.get('stop_at') or '…')[:16]}")
        commandes = appel('pos.order', 'search_read', [[
            ('session_id', '=', s['id']), ('state', 'in', ETATS_VENDUS)]],
            {'fields': champs_cmd, 'order': 'id'})
        for c in commandes:
            api = (c.get('pos_reference') or '').startswith(f'Order-{pos_id}-')
            print(f"    {c['name']:<14} {(c.get('pos_reference') or '')[:30]:<30} "
                  f"{'API ' if api else 'CAISSE?'}  etat {c['state']:<9} "
                  f"creee {(c.get('create_date') or '')[:16]} par {m2o_nom(c.get('create_uid'))}")
            if not c.get('picking_ids'):
                print("      transfert : aucun")
                continue
            for t in appel('stock.picking', 'read', [c['picking_ids']], {'fields': champs_tr}):
                apres_cmd = _minutes(c.get('create_date') or '', t.get('create_date') or '')
                apres_clot = (_minutes(s['stop_at'], t.get('create_date') or '')
                              if s.get('stop_at') else None)
                if apres_cmd is not None and apres_cmd <= 2:
                    moment = "dans la foulee de la vente"
                elif apres_clot is not None and -5 <= apres_clot <= 5:
                    moment = "au moment de la cloture"
                elif apres_cmd is not None:
                    moment = f"{apres_cmd:,.0f} min apres la vente"
                else:
                    moment = "?"
                print(f"      transfert {t['name']} [{t['state']}] "
                      f"cree {(t.get('create_date') or '')[:16]} par {m2o_nom(t.get('create_uid'))}"
                      f" — {moment}")
                if t['state'] != 'done':
                    print("        -> non valide : le stock n'a pas encore bouge")


def _chercher(appel, modele, domaine, champs_voulus, limite=50):
    try:
        return appel(modele, 'search_read', [domaine],
                     {'fields': champs(appel, modele, champs_voulus), 'limit': limite})
    except Exception as e:
        print(f"    ({modele} illisible : {e})")
        return None


def section_automatisations(appel):
    titre("5. AUTOMATISATIONS ODOO sur pos.order / pos.session / stock.picking")
    modeles = ['pos.order', 'pos.session', 'stock.picking']

    print("\n  Bouton NORMALISER (vues pos.order) :")
    vues = _chercher(appel, 'ir.ui.view',
                     [('model', '=', 'pos.order'), ('arch_db', 'ilike', 'normalis')],
                     ['name', 'arch_db', 'inherit_id'])
    for v in vues or []:
        module = ''
        donnees = _chercher(appel, 'ir.model.data',
                            [('model', '=', 'ir.ui.view'), ('res_id', '=', v['id'])],
                            ['module', 'name'], 1)
        if donnees:
            module = f"{donnees[0]['module']}.{donnees[0]['name']}"
        print(f"    vue {v['id']} « {v['name']} »  {module}")
        for b in re.findall(r'<button\b[^>]*>', v.get('arch_db') or '', re.I):
            if 'normalis' in b.lower():
                print(f"      {b[:200]}")
                cible = re.search(r'name="([^"]+)"', b)
                genre = re.search(r'type="([^"]+)"', b)
                if cible and genre and genre.group(1) == 'action' and cible.group(1).isdigit():
                    act = _chercher(appel, 'ir.actions.server',
                                    [('id', '=', int(cible.group(1)))],
                                    ['name', 'state', 'code'], 1)
                    if act:
                        print(f"      action serveur « {act[0]['name']} » :")
                        for ligne in (act[0].get('code') or '').splitlines()[:40]:
                            print(f"        | {ligne}")
    if vues == []:
        print("    aucune vue trouvee")

    print("\n  Actions serveur :")
    for a in _chercher(appel, 'ir.actions.server', [('model_id.model', 'in', modeles)],
                       ['name', 'model_name', 'state', 'binding_model_id']) or []:
        print(f"    {a['id']:>5}  {a.get('model_name', ''):<14} {a['state']:<10} {a['name']}")

    print("\n  Regles automatisees :")
    regles = _chercher(appel, 'base.automation', [('model_id.model', 'in', modeles)],
                       ['name', 'model_name', 'trigger', 'active'])
    for a in regles or []:
        print(f"    {a['id']:>5}  {a.get('model_name', ''):<14} {a.get('trigger', ''):<14} "
              f"{'actif' if a.get('active') else 'inactif'}  {a['name']}")
    if regles == []:
        print("    aucune")

    print("\n  Taches planifiees :")
    crons = _chercher(appel, 'ir.cron', [('model_id.model', 'in', modeles)],
                      ['name', 'active', 'interval_number', 'interval_type', 'nextcall'])
    for c in crons or []:
        print(f"    {c['id']:>5}  {'actif' if c.get('active') else 'inactif':<8} "
              f"tous les {c.get('interval_number')} {c.get('interval_type')}  {c.get('cron_name') or c['name']}")
    if crons == []:
        print("    aucune")

    print("\n  Modules POS / stock hors Odoo S.A. installes :")
    mods = _chercher(appel, 'ir.module.module',
                     [('state', '=', 'installed'), '|', ('name', 'ilike', 'pos'),
                      ('name', 'ilike', 'stock'), ('author', 'not ilike', 'Odoo S.A.')],
                     ['name', 'shortdesc', 'author'], 100)
    for m in mods or []:
        print(f"    {m['name']:<36} {(m.get('author') or '')[:24]:<24} {m.get('shortdesc')}")
    if mods == []:
        print("    aucun")


# ------------------------------------------------------------ conclusion

def conclusion(mode_societe, resultats):
    titre("CONCLUSION")

    plus_recente = resultats[0]['session'] if resultats else {}
    a_cloture = plus_recente.get('update_stock_at_closing')
    if a_cloture is None:
        a_cloture = {'closing': True, 'real': False}.get(mode_societe)

    if a_cloture is None:
        print("  Mode de mise a jour du stock indetermine : verifier a la main dans\n"
              "  Point de Vente > Configuration > Parametres > Inventaire.")
        return

    if a_cloture is False:
        print("  PROBLEME — stock mis a jour EN TEMPS REEL.\n"
              "  Dans ce mode, Odoo attend un transfert par commande, que seule la caisse\n"
              "  Odoo cree. action_pos_order_paid, appele par l'API, n'en cree pas.")
        avec_tr = [r for r in resultats if r['tr_commande']]
        if avec_tr:
            print("  Pourtant des commandes ont un transfert propre dans :")
            for r in avec_tr:
                etat = "non valide(s)" if r['ecarts'] else "ok"
                print(f"    {r['session']['name']} ({len(r['tr_commande'])} transfert(s), {etat})")
            print("  -> Quelque chose les cree. Relancer avec --origine pour savoir quoi.")
        else:
            print("  Aucune commande examinee n'a de transfert : le stock ne baisse pas.")
        return

    print("  Stock mis a jour A LA CLOTURE DE SESSION.")
    print("  -> L'absence de transfert par commande est normale : le 502 renvoye par\n"
          "     l'API au paiement est un faux positif.")

    fermees = [r for r in resultats if r['session']['state'] == 'closed' and r['nb_cmd']]
    if not fermees:
        print("  Aucune session cloturee avec ventes dans l'echantillon : relancer avec\n"
              "  --limite plus grand pour confirmer que la cloture destocke bien.")
        return

    sans_tr = [r for r in fermees if not r['tr_session'] and not r['tr_commande']]
    avec_ecart = [r for r in fermees if r['ecarts']]
    if sans_tr:
        print("  ANOMALIE — sessions cloturees avec ventes mais SANS transfert :")
        for r in sans_tr:
            print(f"    {r['session']['name']} ({r['nb_cmd']} commandes)")
    if avec_ecart:
        print("  ANOMALIE — sessions dont les quantites destockees different des ventes :")
        for r in avec_ecart:
            print(f"    {r['session']['name']} ({len(r['ecarts'])} produit(s) en ecart)")
    if not sans_tr and not avec_ecart:
        print(f"  Les {len(fermees)} session(s) cloturee(s) examinee(s) ont leurs transferts\n"
              "  et les quantites correspondent : le destockage a la cloture fonctionne.")


def main():
    opts = lire_args(sys.argv[1:])
    print(f"Version Odoo : {version_odoo(opts['base'])}")
    appel = connexion(opts['base'])

    mode_societe = section_configuration(appel, opts['pos_id'])
    resultats = section_sessions(appel, opts['pos_id'], opts['limite'])
    if opts['commande']:
        section_commande(appel, opts['commande'])
    if opts['origine']:
        section_origine(appel, opts['pos_id'], resultats)
        section_automatisations(appel)
    conclusion(mode_societe, resultats)


if __name__ == '__main__':
    main()
