#!/usr/bin/env python3
"""
Pourquoi les ventes par carte JNP PASS restent en « Nouveau » puis passent
en « Annule » a la fermeture de session.

Les deux symptomes n'en font qu'un : une commande sans paiement enregistre
reste en `draft`, et la fermeture de session annule les `draft` — sans quoi
Odoo refuse de fermer la caisse.

Ce script etablit, commande par commande, s'il existe un pos.payment en
face du montant, et avec quel moyen.

Lecture seule.

Usage :
    cd ~/Documents/projects/odoo_api
    python3 scripts/diag_ventes_carte.py --session POS/261105/30032/163922
    python3 scripts/diag_ventes_carte.py --pos 32 --jours 3
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

LARGEUR = 96


def titre(t):
    print()
    print("=" * LARGEUR)
    print(t)
    print("=" * LARGEUR)


def lire_arguments(argv):
    session, pos_id, jours = None, None, None
    i = 0
    while i < len(argv):
        a = argv[i]
        nom, valeur = (a.split('=', 1) if '=' in a
                       else (a, argv[i + 1] if i + 1 < len(argv) else None))
        if '=' not in a:
            i += 1
        if nom == '--session':
            session = valeur
        elif nom == '--pos':
            pos_id = valeur
        elif nom == '--jours':
            jours = valeur
        else:
            raise SystemExit(f"Option inconnue : {nom}")
        i += 1
    return session, pos_id, jours


def analyser_session(client, s):
    titre(f"SESSION {s['name']}  ({s['state']}, ouverte le {s['start_at']})")

    commandes = client.execute_kw(
        'pos.order', 'search_read', [[('session_id', '=', s['id'])]],
        {'fields': ['id', 'name', 'state', 'amount_total', 'amount_paid',
                    'amount_return', 'date_order', 'account_move', 'pos_reference'],
         'order': 'date_order asc'}
    )
    if not commandes:
        print("  Aucune commande.")
        return {}

    ids = [c['id'] for c in commandes]
    paiements = {}
    try:
        for p in client.execute_kw(
            'pos.payment', 'search_read', [[('pos_order_id', 'in', ids)]],
            {'fields': ['pos_order_id', 'payment_method_id', 'amount', 'payment_date']}
        ):
            cmd = p.get('pos_order_id')
            cid = cmd[0] if isinstance(cmd, list) else cmd
            paiements.setdefault(cid, []).append(p)
    except Exception as e:
        print(f"  Paiements illisibles: {e}")

    print(f"  {'Commande':<22} {'Etat':<9} {'Total':>10} {'Paye':>10} "
          f"{'Facture':>8}  Paiements enregistres")
    print("  " + "-" * (LARGEUR - 4))

    compte = {}
    sans_paiement = []
    for c in commandes:
        etat = c['state']
        compte[etat] = compte.get(etat, 0) + 1
        regles = paiements.get(c['id'], [])
        detail = ', '.join(
            f"{(p['payment_method_id'][1] if isinstance(p.get('payment_method_id'), list) else '?')}"
            f" {float(p.get('amount') or 0):,.0f}"
            for p in regles
        ) or 'AUCUN'
        if not regles:
            sans_paiement.append(c)
        move = c.get('account_move')
        print(f"  {c['name'][:22]:<22} {etat:<9} "
              f"{float(c.get('amount_total') or 0):>10,.0f} "
              f"{float(c.get('amount_paid') or 0):>10,.0f} "
              f"{('oui' if move else '—'):>8}  {detail}")

    print(f"\n  Repartition des etats : {compte}")

    if sans_paiement:
        print(f"""
  >>> {len(sans_paiement)} commande(s) SANS AUCUN pos.payment.

      C'est la cause. La passerelle ne passe une commande en « paye » que
      lorsqu'un paiement lui est transmis sur
      POST /pos/{{pos_id}}/orders/{{order_id}}/payments.
      Sans cet appel, la commande reste en brouillon — et la fermeture de
      session l'annule, parce qu'Odoo refuse de fermer une caisse qui en
      contient.

      A verifier cote appli / NestJS : l'encaissement par carte appelle-t-il
      bien cet endpoint apres l'autorisation du paiement ?""")
    else:
        print("""
  Toutes les commandes portent un paiement. Si certaines restent en
  brouillon, c'est que le total paye n'atteint pas le total de la commande.""")

    return compte


def main():
    session_ref, pos_id, jours = lire_arguments(sys.argv[1:])
    if not session_ref and not pos_id:
        print(__doc__)
        sys.exit(1)

    print("Connexion a Odoo...")
    client = OdooClient()

    # --- Moyens de paiement « carte » declares ---
    titre("MOYENS DE PAIEMENT RATTACHES")
    try:
        if pos_id:
            cfg = client.execute_kw(
                'pos.config', 'read', [[int(pos_id)]],
                {'fields': ['name', 'payment_method_ids']})[0]
            methodes = client.execute_kw(
                'pos.payment.method', 'read', [cfg['payment_method_ids']],
                {'fields': ['id', 'name', 'is_cash_count', 'journal_id']})
            print(f"  PDV {pos_id} — {cfg['name']}")
            for m in methodes:
                journal = m.get('journal_id')
                print(f"    {m['id']:>5}  {m['name']:<28} "
                      f"{'especes' if m.get('is_cash_count') else '':<9} "
                      f"journal: {journal[1] if isinstance(journal, list) else '—'}")
    except Exception as e:
        print(f"  Illisible: {e}")

    # --- Sessions a analyser ---
    if session_ref:
        sessions = client.execute_kw(
            'pos.session', 'search_read', [[('name', '=', session_ref)]],
            {'fields': ['id', 'name', 'state', 'start_at', 'config_id']})
        if not sessions:
            raise SystemExit(f"Session « {session_ref} » introuvable.")
    else:
        depuis = (datetime.now() - timedelta(days=int(jours or 3))
                  ).strftime('%Y-%m-%d 00:00:00')
        sessions = client.execute_kw(
            'pos.session', 'search_read',
            [[('config_id', '=', int(pos_id)), ('start_at', '>=', depuis)]],
            {'fields': ['id', 'name', 'state', 'start_at', 'config_id'],
             'order': 'id desc', 'limit': 10})
        if not sessions:
            raise SystemExit("Aucune session sur la periode.")

    cumul = {}
    for s in sessions:
        for etat, n in (analyser_session(client, s) or {}).items():
            cumul[etat] = cumul.get(etat, 0) + n

    titre("SYNTHESE")
    print(f"  Etats rencontres : {cumul}")
    print("""
  Rappel du cycle attendu :

    POST /pos/{pos_id}/orders                      -> draft   « Nouveau »
    POST /pos/{pos_id}/orders/{id}/payments        -> paid    « Paye »
    fermeture de session                           -> les draft restants
                                                      passent en cancel

  Une commande « Annulee » apres fermeture n'a donc jamais ete encaissee
  cote Odoo, quelle qu'ait ete la transaction cote carte.
""")


if __name__ == '__main__':
    main()
