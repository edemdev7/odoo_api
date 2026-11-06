#!/usr/bin/env python3
"""
Renseigne la condition de paiement manquante sur les rechargements deja crees.

La passerelle creait les bons de commande TVPASS sans `payment_term_id`.
La configuration de JNP rendant ce champ obligatoire, le bon de commande
affiche « Champs invalides : Conditions de paiement » et devient
inexploitable depuis l'interface — on ne peut plus atteindre la facture ni
les ecritures comptables.

Le correctif est pose dans api/accounting.py pour les prochaines ventes.
Ce script reprend celles qui existent deja.

AUCUNE DEPENDANCE : stdlib uniquement, lit le .env lui-meme.

Usage :
    cd ~/Documents/projects/odoo_api
    python scripts/corriger_conditions_paiement.py                # simulation
    python scripts/corriger_conditions_paiement.py --appliquer
    python scripts/corriger_conditions_paiement.py --prefixe OVT --appliquer
"""

import os
import sys
import xmlrpc.client

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')
except AttributeError:
    pass

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _odoo_direct import connexion  # noqa: E402

LARGEUR = 92


def titre(t):
    print()
    print("=" * LARGEUR)
    print(t)
    print("=" * LARGEUR)



def main():
    argv = sys.argv[1:]
    appliquer = '--appliquer' in argv
    prefixe = None
    for i, a in enumerate(argv):
        if a == '--prefixe' and i + 1 < len(argv):
            prefixe = argv[i + 1]
        elif a.startswith('--prefixe='):
            prefixe = a.split('=', 1)[1]

    appel = connexion()

    # ------------------------------------------------------------------
    # Condition de paiement immediate
    # ------------------------------------------------------------------
    titre("CONDITION DE PAIEMENT A POSER")
    terme_id = None
    fixe = os.getenv("ACCOUNTING_PAYMENT_TERM_ID", "").strip()
    if fixe.isdigit():
        terme_id = int(fixe)
        print(f"  Imposee par ACCOUNTING_PAYMENT_TERM_ID : {terme_id}")
    else:
        donnees = appel('ir.model.data', 'search_read',
                        [[('module', '=', 'account'),
                          ('name', '=', 'account_payment_term_immediate')]],
                        {'fields': ['res_id'], 'limit': 1})
        if donnees:
            terme_id = donnees[0]['res_id']
        if not terme_id:
            for libelle in ('Paiement immédiat', 'Immediate Payment', 'Comptant'):
                trouve = appel('account.payment.term', 'search',
                               [[('name', '=ilike', libelle)]], {'limit': 1})
                if trouve:
                    terme_id = trouve[0]
                    break

    if not terme_id:
        print("  Aucune condition « immediate » dans cette base.")
        print("  Toutes les conditions disponibles :")
        for t in appel('account.payment.term', 'search_read', [[]],
                       {'fields': ['id', 'name'], 'limit': 30}):
            print(f"    {t['id']:>5}  {t['name']}")
        print("\n  Choisissez-en une et relancez avec "
              "ACCOUNTING_PAYMENT_TERM_ID=<id> dans le .env.")
        sys.exit(1)

    terme = appel('account.payment.term', 'read', [[terme_id]], {'fields': ['name']})[0]
    print(f"  {terme_id}  {terme['name']}")

    # ------------------------------------------------------------------
    # Commandes concernees
    # ------------------------------------------------------------------
    domaine = [('payment_term_id', '=', False)]
    if prefixe:
        domaine.append(('name', '=like', f'{prefixe}%'))

    commandes = appel('sale.order', 'search_read', [domaine],
                      {'fields': ['id', 'name', 'partner_id', 'state',
                                  'amount_total', 'date_order'],
                       'order': 'id desc', 'limit': 500})

    titre(f"BONS DE COMMANDE SANS CONDITION DE PAIEMENT — {len(commandes)}")
    if not commandes:
        print("  Aucun. Rien a reprendre.")
    else:
        print(f"  {'Numero':<26} {'Etat':<10} {'Montant':>12}  Client")
        print("  " + "-" * (LARGEUR - 4))
        for c in commandes[:25]:
            part = c.get('partner_id')
            print(f"  {(c.get('name') or '')[:26]:<26} {c.get('state'):<10} "
                  f"{float(c.get('amount_total') or 0):>12,.0f}  "
                  f"{part[1] if isinstance(part, list) else '—'}")
        if len(commandes) > 25:
            print(f"    ... et {len(commandes) - 25} autre(s)")

    # ------------------------------------------------------------------
    # Factures concernees
    # ------------------------------------------------------------------
    domaine_factures = [('move_type', '=', 'out_invoice'),
                        ('invoice_payment_term_id', '=', False),
                        ('state', '=', 'draft')]
    if prefixe:
        # Meme perimetre que les commandes : la facture issue d'un bon
        # OVT/... porte ce numero dans `invoice_origin`.
        domaine_factures.append(('invoice_origin', '=like', f'{prefixe}%'))

    factures = appel('account.move', 'search_read', [domaine_factures],
                     {'fields': ['id', 'name', 'amount_total', 'invoice_origin'],
                      'order': 'id desc', 'limit': 500})

    titre(f"FACTURES BROUILLON SANS CONDITION DE PAIEMENT — {len(factures)}")
    for f in factures[:15]:
        print(f"  {(f.get('name') or '')[:26]:<26} "
              f"{float(f.get('amount_total') or 0):>12,.0f}  "
              f"origine {f.get('invoice_origin') or '—'}")
    print("\n  Les factures comptabilisees ne sont pas touchees : leur modifier")
    print("  une echeance demanderait de les repasser en brouillon.")

    if not appliquer:
        print(f"""
{"=" * LARGEUR}
  Simulation — rien n'a ete ecrit.

      python scripts/corriger_conditions_paiement.py --appliquer
""")
        return

    # ------------------------------------------------------------------
    # Ecriture
    # ------------------------------------------------------------------
    titre("ECRITURE")
    succes, echecs = 0, []
    for c in commandes:
        try:
            appel('sale.order', 'write', [[c['id']], {'payment_term_id': terme_id}])
            succes += 1
        except Exception as e:
            echecs.append((c.get('name'), str(e)))
    print(f"  Bons de commande : {succes} corrige(s), {len(echecs)} echec(s)")
    for nom, err in echecs[:10]:
        print(f"    {nom} : {err}")

    succes_f, echecs_f = 0, []
    for f in factures:
        try:
            appel('account.move', 'write',
                  [[f['id']], {'invoice_payment_term_id': terme_id}])
            succes_f += 1
        except Exception as e:
            echecs_f.append((f.get('name'), str(e)))
    print(f"  Factures brouillon : {succes_f} corrigee(s), {len(echecs_f)} echec(s)")
    for nom, err in echecs_f[:10]:
        print(f"    {nom} : {err}")

    restant = appel('sale.order', 'search_count', [domaine])
    titre("VERIFICATION")
    print(f"  Bons de commande encore sans condition de paiement : {restant}")
    if not prefixe:
        print("""
  Rappel : sans --prefixe, ce script a touche TOUS les bons de commande de
  la base, y compris ceux crees dans Odoo par les equipes JNP. Si ce n'etait
  pas l'intention, la condition se retire par un write a False sur les
  enregistrements concernes.""")


if __name__ == '__main__':
    main()
