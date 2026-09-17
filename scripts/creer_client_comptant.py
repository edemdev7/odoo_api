#!/usr/bin/env python3
"""
Création du client comptant, sans passer par l'interface Odoo.

Odoo exige un partenaire sur toute facture. Les ventes à la pompe étant
anonymes, elles sont rattachées à un compte collectif — le « Client comptant ».

Ce script le crée par XML-RPC, ce qui contourne les vues : utile lorsque le
formulaire contact est inaccessible dans l'interface, par exemple à cause d'un
champ référencé par une vue mais absent du modèle.

Usage :
    cd ~/odoo_api
    python3 scripts/creer_client_comptant.py              # vérifie et crée
    python3 scripts/creer_client_comptant.py --verifier   # vérifie seulement
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

# Mêmes libellés que ceux cherchés par l'API, dans le même ordre
NOMS = ["Client comptant", "Client divers", "Comptant", "Client anonyme"]

LARGEUR = 72


def main():
    verifier_seulement = '--verifier' in sys.argv

    print("Connexion à Odoo...")
    client = OdooClient()

    print()
    print("=" * LARGEUR)
    print("RECHERCHE D'UN CLIENT COMPTANT EXISTANT")
    print("=" * LARGEUR)

    for nom in NOMS:
        trouves = client.execute_kw(
            'res.partner', 'search_read',
            [[('name', '=ilike', nom)]],
            {'fields': ['id', 'name', 'active'], 'limit': 5}
        )
        for t in trouves:
            etat = "actif" if t.get('active', True) else "ARCHIVÉ"
            print(f"  Trouvé : « {t['name']} » — ID {t['id']} ({etat})")
            if t.get('active', True):
                print()
                print("Rien à faire : l'API le résoudra automatiquement.")
                print(f"Pour lever toute ambiguïté, vous pouvez fixer dans le .env :")
                print(f"    POS_DEFAULT_PARTNER_ID={t['id']}")
                return

    print("  Aucun client comptant actif.")

    if verifier_seulement:
        print("\nMode vérification : aucune création effectuée.")
        return

    print()
    print("=" * LARGEUR)
    print("CRÉATION")
    print("=" * LARGEUR)

    valeurs = {
        'name': 'Client comptant',
        'company_type': 'person',
        'customer_rank': 1,
        'comment': (
            "Compte collectif des ventes au comptant. Porte les factures des "
            "ventes anonymes, où le client ne se présente pas."
        ),
    }

    try:
        partner_id = client.execute_kw('res.partner', 'create', [valeurs])
    except Exception as e:
        print(f"  Échec de la création : {e}")
        print()
        print("  Si le message évoque un champ obligatoire ajouté par un module,")
        print("  ajoutez-le au dictionnaire `valeurs` de ce script.")
        sys.exit(1)

    print(f"  Créé : « Client comptant » — ID {partner_id}")

    # Relecture, pour confirmer que l'enregistrement est bien exploitable
    relu = client.execute_kw(
        'res.partner', 'read', [[partner_id]],
        {'fields': ['id', 'name', 'active', 'customer_rank']}
    )
    if relu:
        print(f"  Vérifié : {relu[0]}")

    print()
    print("À faire ensuite : renseigner l'identifiant dans le .env du serveur,")
    print("puis redémarrer le service.")
    print()
    print(f"    POS_DEFAULT_PARTNER_ID={partner_id}")
    print()
    print("Ce n'est pas obligatoire — l'API retrouve le contact par son nom —")
    print("mais cela évite toute ambiguïté si un homonyme apparaît un jour.")


if __name__ == '__main__':
    main()
