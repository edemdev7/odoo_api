#!/usr/bin/env python3
"""
Verifie, avant deploiement, les regroupements utilises par
GET /pos/{pos_id}/sessions/recent.

Rejoue les trois lectures Odoo de la route — cumuls de ventes, repartition
par moyen de paiement, detail produit — et signale celles que la base
refuse, plutot que de le decouvrir en production.

Lecture seule.

Usage :
    cd ~/Documents/projects/odoo_api
    python3 scripts/diag_sessions_recentes.py 4
    python3 scripts/diag_sessions_recentes.py 4 --limite 6 --produits
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
ETATS = ['paid', 'done', 'invoiced']


def titre(t):
    print()
    print("=" * LARGEUR)
    print(t)
    print("=" * LARGEUR)


def main():
    argv = sys.argv[1:]
    if not argv or not argv[0].isdigit():
        print(__doc__)
        sys.exit(1)

    pos_id = int(argv[0])
    limite, produits = 6, False
    i = 1
    while i < len(argv):
        a = argv[i]
        if a == '--produits':
            produits = True
        elif a.startswith('--limite'):
            limite = int(a.split('=', 1)[1] if '=' in a else argv[i + 1])
            if '=' not in a:
                i += 1
        else:
            raise SystemExit(f"Option inconnue : {a}")
        i += 1

    print("Connexion a Odoo...")
    client = OdooClient()

    cfg = client.execute_kw('pos.config', 'read', [[pos_id]], {'fields': ['name']})
    if not cfg:
        raise SystemExit(f"Point de vente {pos_id} introuvable.")

    titre(f"PDV {pos_id} — {cfg[0]['name']} — {limite} dernieres sessions")

    sessions = client.execute_kw(
        'pos.session', 'search_read', [[('config_id', '=', pos_id)]],
        {'fields': ['id', 'name', 'state', 'start_at', 'stop_at', 'user_id',
                    'cash_register_balance_start', 'cash_register_balance_end_real'],
         'limit': limite, 'order': 'id desc'}
    )
    if not sessions:
        print("  Aucune session.")
        return

    ids = [s['id'] for s in sessions]

    # 1. Cumuls de ventes
    cumuls = {}
    try:
        for l in client.execute_kw(
            'pos.order', 'read_group',
            [[('session_id', 'in', ids), ('state', 'in', ETATS)],
             ['amount_total', 'amount_paid', 'amount_return'], ['session_id']],
            {'lazy': False}
        ):
            sess = l.get('session_id')
            cumuls[sess[0] if isinstance(sess, list) else sess] = l
        print("  read_group pos.order ............. OK")
    except Exception as e:
        print(f"  read_group pos.order ............. ECHEC : {e}")

    # 2. Repartition par moyen de paiement
    paiements = {}
    try:
        for l in client.execute_kw(
            'pos.payment', 'read_group',
            [[('session_id', 'in', ids)], ['amount'],
             ['session_id', 'payment_method_id']],
            {'lazy': False}
        ):
            sess = l.get('session_id')
            sid = sess[0] if isinstance(sess, list) else sess
            meth = l.get('payment_method_id')
            paiements.setdefault(sid, []).append(
                (meth[1] if isinstance(meth, list) else '?', l.get('amount')))
        print("  read_group pos.payment ........... OK")
    except Exception as e:
        print(f"  read_group pos.payment ........... ECHEC : {e}")
        print("     -> la repartition par moyen de paiement sera omise")

    print(f"\n  {'Session':<26} {'Etat':<8} {'Cmd':>5} {'Montant':>12}  Paiements")
    print("  " + "-" * (LARGEUR - 4))
    for s in sessions:
        c = cumuls.get(s['id'], {})
        detail = ', '.join(
            f"{m} {float(a or 0):,.0f}" for m, a in paiements.get(s['id'], [])
        ) or '—'
        print(f"  {s['name'][:26]:<26} {s['state']:<8} "
              f"{int(c.get('__count') or 0):>5} "
              f"{float(c.get('amount_total') or 0):>12,.0f}  {detail}")

    if produits:
        titre("DETAIL PAR PRODUIT")
        for s in sessions:
            try:
                lignes = client.execute_kw(
                    'pos.order.line', 'read_group',
                    [[('order_id.session_id', '=', s['id']),
                      ('order_id.state', 'in', ETATS)],
                     ['qty', 'price_subtotal_incl'], ['product_id']],
                    {'lazy': False}
                )
            except Exception as e:
                print(f"\n  {s['name']} : ECHEC — {e}")
                continue
            print(f"\n  {s['name']} — {len(lignes)} produit(s)")
            for l in sorted(lignes,
                            key=lambda x: float(x.get('price_subtotal_incl') or 0),
                            reverse=True)[:10]:
                prod = l.get('product_id')
                print(f"    {(prod[1] if isinstance(prod, list) else '?')[:44]:<44} "
                      f"{float(l.get('qty') or 0):>10g} "
                      f"{float(l.get('price_subtotal_incl') or 0):>12,.0f}")


if __name__ == '__main__':
    main()
