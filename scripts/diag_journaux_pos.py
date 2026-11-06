#!/usr/bin/env python3
"""
Quel journal comptable est impacte par une vente comptoir ?

Odoo prevoit deux chemins distincts pour une vente en point de vente :

  A. VENTE NON FACTUREE — le defaut.
     Rien n'est comptabilise a la vente. A la cloture de session, Odoo
     poste UNE seule ecriture recapitulative dans le journal du point de
     vente : debit caisse/banque, credit ventes. Aucune creance client.

  B. VENTE FACTUREE — sur demande.
     Odoo emet une facture client dans le journal des ventes, et exclut
     cette commande de l'ecriture de session. Une creance nait sur le
     partenaire, qui doit ensuite etre lettree avec son reglement.

La passerelle force aujourd'hui le chemin B sur toute vente reglee
autrement que par token ou carte. D'ou des factures FVT/... pour des
ventes a la pompe, et un encours qui s'accumule sur le client
« Comptant » — jusqu'a declencher le blocage de limite de credit.

Ce script etablit quels journaux sont configures et lesquels ont
reellement recu des ecritures.

AUCUNE DEPENDANCE : stdlib uniquement.

Usage :
    cd ~/Documents/projects/odoo_api
    python scripts/diag_journaux_pos.py
    python scripts/diag_journaux_pos.py --pos 32 --sessions 5
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _odoo_direct import connexion  # noqa: E402

LARGEUR = 94

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')
except AttributeError:
    pass


def titre(t):
    print()
    print("=" * LARGEUR)
    print(t)
    print("=" * LARGEUR)


def nom(valeur, defaut='—'):
    return valeur[1] if isinstance(valeur, list) else defaut


def main():
    argv = sys.argv[1:]
    pos_id, nb_sessions = 32, 5
    i = 0
    while i < len(argv):
        a = argv[i]
        cle, val = (a.split('=', 1) if '=' in a
                    else (a, argv[i + 1] if i + 1 < len(argv) else None))
        if '=' not in a:
            i += 1
        if cle == '--pos':
            pos_id = int(val)
        elif cle == '--sessions':
            nb_sessions = int(val)
        else:
            raise SystemExit(f"Option inconnue : {cle}")
        i += 1

    appel = connexion()

    # ------------------------------------------------------------------
    # 1. Journaux configures sur le point de vente
    # ------------------------------------------------------------------
    config = appel('pos.config', 'read', [[pos_id]],
                   {'fields': ['name', 'journal_id', 'invoice_journal_id',
                               'payment_method_ids']})
    if not config:
        raise SystemExit(f"Point de vente {pos_id} introuvable.")
    config = config[0]

    titre(f"JOURNAUX DU POINT DE VENTE {pos_id} — {config['name']}")
    print(f"  Journal du point de vente  : {nom(config.get('journal_id'))}")
    print(f"     -> recoit l'ecriture recapitulative a la cloture de session")
    print(f"  Journal des factures       : {nom(config.get('invoice_journal_id'))}")
    print(f"     -> recoit les factures emises a la demande")

    # ------------------------------------------------------------------
    # 2. Journal de chaque moyen de paiement
    # ------------------------------------------------------------------
    titre("JOURNAL DE CONTREPARTIE PAR MOYEN DE PAIEMENT")
    methodes = appel('pos.payment.method', 'read',
                     [config.get('payment_method_ids') or []],
                     {'fields': ['name', 'journal_id', 'is_cash_count']})
    print(f"  {'ID':>5}  {'Moyen':<24} {'Especes':<9} Journal de contrepartie")
    print("  " + "-" * (LARGEUR - 4))
    for m in methodes:
        print(f"  {m['id']:>5}  {m['name'][:24]:<24} "
              f"{('oui' if m.get('is_cash_count') else ''):<9} "
              f"{nom(m.get('journal_id'))}")
    print("""
  Un moyen sans journal de contrepartie ne genere aucune ecriture : son
  encaissement reste en suspens a la cloture.""")

    # ------------------------------------------------------------------
    # 3. Ce que les dernieres sessions ont reellement produit
    # ------------------------------------------------------------------
    titre(f"ECRITURES DES {nb_sessions} DERNIERES SESSIONS")
    sessions = appel('pos.session', 'search_read',
                     [[('config_id', '=', pos_id)]],
                     {'fields': ['name', 'state', 'start_at', 'move_id'],
                      'order': 'id desc', 'limit': nb_sessions})

    for s in sessions:
        print(f"\n  {s['name']}  ({s['state']})")

        # Ecriture recapitulative de session
        move = s.get('move_id')
        if move:
            details = appel('account.move', 'read', [[move[0]]],
                            {'fields': ['name', 'journal_id', 'state', 'amount_total']})
            d = details[0] if details else {}
            print(f"    Ecriture de session : {d.get('name')} "
                  f"dans « {nom(d.get('journal_id'))} » ({d.get('state')})")
        else:
            print("    Ecriture de session : AUCUNE")

        # Commandes et leurs factures
        commandes = appel('pos.order', 'search_read',
                          [[('session_id', '=', s['id'])]],
                          {'fields': ['id', 'state', 'amount_total', 'account_move']})
        facturees = [c for c in commandes if c.get('account_move')]
        print(f"    Commandes : {len(commandes)} dont {len(facturees)} facturee(s)")

        if facturees:
            moves = appel('account.move', 'read',
                          [[c['account_move'][0] for c in facturees]],
                          {'fields': ['name', 'journal_id', 'partner_id',
                                      'amount_total', 'payment_state']})
            journaux = {}
            for m in moves:
                journaux.setdefault(nom(m.get('journal_id')), []).append(m)
            for journal, liste in journaux.items():
                total = sum(float(m.get('amount_total') or 0) for m in liste)
                impayees = [m for m in liste if m.get('payment_state') != 'paid']
                print(f"      « {journal} » : {len(liste)} facture(s), "
                      f"{total:,.0f} — dont {len(impayees)} non lettree(s)")
                for m in liste[:3]:
                    print(f"          {m['name']:<24} {nom(m.get('partner_id'))[:22]:<22} "
                          f"{m.get('payment_state')}")

    # ------------------------------------------------------------------
    # 4. Lecture
    # ------------------------------------------------------------------
    titre("LECTURE")
    print(f"""
  Si les ventes a la pompe produisent des factures dans « {nom(config.get('invoice_journal_id'))} »
  plutot qu'une ecriture unique dans « {nom(config.get('journal_id'))} », c'est que la
  passerelle les facture systematiquement.

  Trois consequences, qu'on a toutes rencontrees :

    - le journal des ventes se remplit d'une facture par plein d'essence ;
    - chaque facture cree une creance sur « Comptant », d'ou l'encours qui
      grossit et le blocage de limite de credit ;
    - la cloture de session ne recapitule plus rien, les commandes
      facturees en etant exclues.

  Le comportement attendu par une comptabilite est l'inverse : pas de
  facture par defaut, et une facture uniquement quand le client la demande
  a son nom. C'est une decision metier a trancher avec JNP, pas un reglage
  technique — mais elle conditionne le reste.

  Cote passerelle, le perimetre de facturation se pilote deja par
  POS_PAYMENT_METHODS_SANS_FACTURE dans le .env.
""")


if __name__ == '__main__':
    main()
