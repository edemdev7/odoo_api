#!/usr/bin/env python3
"""
Rattache des moyens de paiement a un point de vente.

L'interface Odoo verrouille ce champ tant qu'une session est ouverte. La
restriction est portee par la vue, pas par le modele : un ecriture XML-RPC
passe donc sans avoir a fermer la caisse.

Usage :
    cd ~/odoo_api
    python3 scripts/ajouter_moyens_paiement.py 32                    # inventaire
    python3 scripts/ajouter_moyens_paiement.py 32 kkiapay token      # simulation
    python3 scripts/ajouter_moyens_paiement.py 32 kkiapay token --appliquer
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

LARGEUR = 80


def titre(t):
    print()
    print("=" * LARGEUR)
    print(t)
    print("=" * LARGEUR)


def main():
    args = [a for a in sys.argv[1:] if a != '--appliquer']
    appliquer = '--appliquer' in sys.argv

    if not args:
        print(__doc__)
        sys.exit(1)

    pos_id = int(args[0])
    recherches = [a.lower() for a in args[1:]]

    print("Connexion a Odoo...")
    client = OdooClient()

    config = client.execute_kw(
        'pos.config', 'read', [[pos_id]],
        {'fields': ['name', 'payment_method_ids', 'company_id', 'current_session_id']}
    )
    if not config:
        print(f"  Point de vente {pos_id} introuvable.")
        sys.exit(1)
    config = config[0]

    titre(f"POINT DE VENTE {pos_id} — {config['name']}")

    societe = config.get('company_id')
    societe_id = societe[0] if isinstance(societe, list) else societe
    session = config.get('current_session_id')
    print(f"  Societe          : {societe[1] if isinstance(societe, list) else societe_id}")
    print(f"  Session en cours : {session[1] if isinstance(session, list) else 'aucune'}")

    actuels = config.get('payment_method_ids') or []
    if actuels:
        details = client.execute_kw(
            'pos.payment.method', 'read', [actuels],
            {'fields': ['id', 'name', 'is_cash_count', 'company_id']}
        )
        print(f"\n  Moyens rattaches ({len(details)}) :")
        for d in details:
            espece = "especes" if d.get('is_cash_count') else ""
            print(f"    {d['id']:>6}  {d['name']:<30} {espece}")
    else:
        print("\n  Aucun moyen de paiement rattache.")

    # Moyens disponibles dans la societe
    disponibles = client.execute_kw(
        'pos.payment.method', 'search_read',
        [[('company_id', '=', societe_id)]],
        {'fields': ['id', 'name', 'is_cash_count'], 'order': 'name asc'}
    )
    non_rattaches = [m for m in disponibles if m['id'] not in actuels]

    print(f"\n  Moyens existants mais non rattaches ({len(non_rattaches)}) :")
    for m in non_rattaches:
        print(f"    {m['id']:>6}  {m['name']}")
    if not non_rattaches:
        print("    (aucun)")

    if not recherches:
        print(f"""
{"=" * LARGEUR}
  Indiquez les moyens a rattacher, par nom :

      python3 scripts/ajouter_moyens_paiement.py {pos_id} kkiapay token
""")
        return

    # Resolution par nom, insensible a la casse et partielle
    a_ajouter = []
    for terme in recherches:
        trouve = [m for m in disponibles if terme in m['name'].lower()]
        if not trouve:
            print(f"\n  ATTENTION : aucun moyen de paiement ne correspond a « {terme} »")
            continue
        if len(trouve) > 1:
            print(f"\n  « {terme} » correspond a plusieurs moyens :")
            for m in trouve:
                print(f"    {m['id']:>6}  {m['name']}")
            print("    Precisez davantage le nom.")
            continue
        m = trouve[0]
        if m['id'] in actuels:
            print(f"\n  « {m['name']} » (ID {m['id']}) est deja rattache.")
        else:
            a_ajouter.append(m)

    if not a_ajouter:
        print("\n  Rien a ajouter.")
        return

    titre("A RATTACHER")
    for m in a_ajouter:
        print(f"  {m['id']:>6}  {m['name']}")

    if not appliquer:
        print(f"""
  Simulation — rien n'a ete ecrit.

  Pour appliquer :

      python3 scripts/ajouter_moyens_paiement.py {pos_id} {' '.join(recherches)} --appliquer
""")
        return

    # La commande (4, id) ajoute sans toucher aux moyens deja en place.
    commandes = [(4, m['id']) for m in a_ajouter]
    try:
        client.execute_kw(
            'pos.config', 'write', [[pos_id], {'payment_method_ids': commandes}]
        )
    except Exception as e:
        print(f"\n  Echec de l'ecriture : {e}")
        print("""
  Si le message evoque une session ouverte, il faudra la fermer : la
  contrainte est alors portee par le modele et non par la vue.
""")
        sys.exit(1)

    relu = client.execute_kw(
        'pos.config', 'read', [[pos_id]], {'fields': ['payment_method_ids']}
    )[0]
    final = client.execute_kw(
        'pos.payment.method', 'read', [relu['payment_method_ids']],
        {'fields': ['id', 'name']}
    )

    titre("RESULTAT")
    for m in final:
        marque = "  <- ajoute" if m['id'] in [a['id'] for a in a_ajouter] else ""
        print(f"  {m['id']:>6}  {m['name']}{marque}")

    print("""
  Les caisses ouvertes doivent etre rechargees pour voir les nouveaux
  moyens : le point de vente charge sa configuration au demarrage.
""")


if __name__ == '__main__':
    main()
