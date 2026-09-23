#!/usr/bin/env python3
"""
Diagnostic des anomalies 2 et 3 du rapport du 23/09.

Anomalie 2 : le montant demande est ignore, la quantite fait foi.
Anomalie 3 : un produit a stock nul a ete vendu sans etre bloque.

Ce script interroge Odoo en lecture seule pour etablir les faits plutot
que de raisonner sur des hypotheses.

Usage :
    cd ~/odoo_api
    python3 scripts/diag_anomalies.py
    python3 scripts/diag_anomalies.py 700982 700981   # commandes precises
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

LARGEUR = 84

PRODUIT_GAZ = 3003          # GAZ/RECHARGE 6KG
SESSION = 26761
EMPLACEMENT_NOM = 'JO27/Stock'


def titre(t):
    print()
    print("=" * LARGEUR)
    print(t)
    print("=" * LARGEUR)


def anomalie_3(client):
    titre("ANOMALIE 3 — GAZ/RECHARGE 6KG vendu a stock nul")

    produit = client.execute_kw(
        'product.product', 'read', [[PRODUIT_GAZ]],
        {'fields': ['id', 'name', 'type', 'categ_id', 'uom_id',
                    'available_in_pos', 'active', 'qty_available']}
    )
    if not produit:
        print(f"  Produit {PRODUIT_GAZ} introuvable.")
        return
    p = produit[0]

    print(f"  Nom                : {p['name']}")
    print(f"  Type Odoo          : {p['type']}")
    print(f"  Categorie          : {p['categ_id'][1] if p.get('categ_id') else '—'}")
    print(f"  Disponible en PdV  : {p.get('available_in_pos')}")
    print(f"  Stock global       : {p.get('qty_available')}")

    if p['type'] == 'product':
        print("""
  >>> Produit STOCKABLE. Le controle de vente aurait donc du le refuser.
      Mon hypothese du produit non suivi etait fausse : il faut chercher
      pourquoi _check_pos_sale_stock ne l'a pas bloque.""")
    else:
        print(f"""
  >>> Produit NON stockable (type = {p['type']}). Odoo ne suit pas son
      stock, le controle de vente l'ignore a juste titre, et le stock
      theorique negatif n'est qu'un artefact de calcul.""")

    # Emplacement de la station et quants du produit
    emplacements = client.execute_kw(
        'stock.location', 'search',
        [[('complete_name', '=like', 'JO27/%'), ('usage', '=', 'internal')]]
    )
    if emplacements:
        quants = client.execute_kw(
            'stock.quant', 'search_read',
            [[('product_id', '=', PRODUIT_GAZ),
              ('location_id', 'child_of', emplacements)]],
            {'fields': ['location_id', 'quantity', 'reserved_quantity']}
        )
        print(f"\n  Quants sur {EMPLACEMENT_NOM} : {len(quants)}")
        for q in quants:
            loc = q['location_id']
            print(f"    {loc[1] if isinstance(loc, list) else loc:<34} "
                  f"quantite={q.get('quantity')}  reserve={q.get('reserved_quantity')}")
        if not quants:
            print("    Aucun quant : le produit n'a jamais transite par cet emplacement.")
            print("    Le controle le traite alors comme 'produit_non_suivi'.")

    # Ventes du produit sur la session
    lignes = client.execute_kw(
        'pos.order.line', 'search_read',
        [[('product_id', '=', PRODUIT_GAZ),
          ('order_id.session_id', '=', SESSION)]],
        {'fields': ['order_id', 'qty', 'price_unit', 'price_subtotal_incl']}
    )
    print(f"\n  Ventes sur la session {SESSION} : {len(lignes)} ligne(s)")
    for l in lignes:
        o = l['order_id']
        print(f"    commande {o[1] if isinstance(o, list) else o:<22} "
              f"qty={l.get('qty')}  total={l.get('price_subtotal_incl')}")


def anomalie_2(client, commandes):
    titre("ANOMALIE 2 — ce qui a reellement ete enregistre dans Odoo")

    for order_id in commandes:
        cmd = client.execute_kw(
            'pos.order', 'search_read',
            [[('id', '=', order_id)]],
            {'fields': ['id', 'name', 'amount_total', 'amount_paid',
                        'amount_return', 'lines', 'date_order'], 'limit': 1}
        )
        if not cmd:
            print(f"\n  Commande {order_id} introuvable.")
            continue
        c = cmd[0]
        print(f"\n  Commande {order_id} — {c['name']}  ({c.get('date_order')})")
        print(f"    total={c.get('amount_total')}  paye={c.get('amount_paid')}  "
              f"rendu={c.get('amount_return')}")

        if c.get('lines'):
            champs = ['product_id', 'qty', 'price_unit', 'price_subtotal_incl']
            # La note porte la mention « Vente au montant » quand le champ
            # amount nous est parvenu : c'est le temoin recherche.
            try:
                dispo = client.execute_kw(
                    'pos.order.line', 'fields_get', [], {'attributes': ['type']}
                )
                for cand in ('customer_note', 'note'):
                    if cand in dispo:
                        champs.append(cand)
                        break
            except Exception:
                pass

            lignes = client.execute_kw(
                'pos.order.line', 'read', [c['lines']], {'fields': champs}
            )
            for l in lignes:
                prod = l.get('product_id')
                note = l.get('customer_note') or l.get('note') or ''
                print(f"    produit {prod[1] if isinstance(prod, list) else prod}")
                print(f"      qty={l.get('qty')}  prix={l.get('price_unit')}  "
                      f"total={l.get('price_subtotal_incl')}")
                print(f"      note : {note or '(vide)'}")
                if 'Vente au montant' in note:
                    print("      >>> Le champ amount EST parvenu jusqu'a nous.")
                else:
                    print("      >>> Aucune mention de montant : le champ n'est pas arrive,")
                    print("          ou le code de recalcul n'etait pas deploye.")


def main():
    commandes = [int(a) for a in sys.argv[1:]] or [700982, 700981]

    print("Connexion a Odoo...")
    client = OdooClient()

    anomalie_3(client)
    anomalie_2(client, commandes)

    titre("A CROISER AVEC LES LOGS DU SERVEUR")
    print("""
  journalctl -u <service> --since "15:15" | grep "Ligne recue"

  amount=500   le champ arrive, le defaut est chez nous
  amount=None  le champ se perd avant nous : intermediaire NestJS,
               ou schema Pydantic non deploye
""")


if __name__ == '__main__':
    main()
