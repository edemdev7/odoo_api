#!/usr/bin/env python3
"""
Limite de credit bloquant la facturation des ventes comptoir.

Odoo refuse d'emettre une facture quand le client a depasse son plafond :

    "Le client 'Comptant' a atteint ou depasse sa limite de credit."

Or toutes les ventes anonymes sont rattachees a ce compte collectif. Si
son encours n'est jamais apure, le plafond finit par etre atteint et plus
aucune vente comptoir n'est facturable.

Ce script liste les champs de credit du partenaire, son encours, et les
factures qui composent cet encours — ce qui dit si le probleme est un
plafond trop bas ou un lettrage qui ne se fait pas.

AUCUNE DEPENDANCE : stdlib uniquement, lit le .env lui-meme. Fonctionne
meme quand le virtualenv est casse.

Lecture seule.

Usage :
    cd ~/Documents/projects/odoo_api
    python scripts/diag_limite_credit.py
    python scripts/diag_limite_credit.py 35683
"""

import os
import sys
import xmlrpc.client

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')
except AttributeError:
    pass

LARGEUR = 92
RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Valeurs de repli, identiques a celles de core/config.py.
DEFAUTS = {
    'ODOO_DB1_URL': 'https://holdingithiel-dagbehami-statging-012026-40829916.dev.odoo.com/',
    'ODOO_DB1_NAME': 'holdingithiel-dagbehami-statging-012026-40829916',
    'ODOO_DB1_USERNAME': 'api@jnpgroupe.com',
}


def titre(t):
    print()
    print("=" * LARGEUR)
    print(t)
    print("=" * LARGEUR)


def lire_env():
    """Charge le .env sans dependre de python-dotenv."""
    valeurs = {}
    chemin = os.path.join(RACINE, '.env')
    if os.path.exists(chemin):
        with open(chemin, encoding='utf-8', errors='replace') as f:
            for ligne in f:
                ligne = ligne.strip()
                if not ligne or ligne.startswith('#') or '=' not in ligne:
                    continue
                cle, valeur = ligne.split('=', 1)
                valeurs[cle.strip()] = valeur.strip().strip('"').strip("'")
    else:
        print(f"  (.env introuvable dans {RACINE} — repli sur les defauts)")

    def lire(cle):
        return os.getenv(cle) or valeurs.get(cle) or DEFAUTS.get(cle, '')

    return (lire('ODOO_DB1_URL').rstrip('/'), lire('ODOO_DB1_NAME'),
            lire('ODOO_DB1_USERNAME'), lire('ODOO_DB1_API_KEY'))


def main():
    partner_id = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else 35683

    url, db, user, cle = lire_env()
    if not cle:
        raise SystemExit("ODOO_DB1_API_KEY absente du .env et de l'environnement.")

    print(f"Connexion a {db}...")
    commun = xmlrpc.client.ServerProxy(f"{url}/xmlrpc/2/common")
    uid = commun.authenticate(db, user, cle, {})
    if not uid:
        raise SystemExit("Authentification refusee.")
    modeles = xmlrpc.client.ServerProxy(f"{url}/xmlrpc/2/object")

    def appel(modele, methode, args, kwargs=None):
        return modeles.execute_kw(db, uid, cle, modele, methode, args, kwargs or {})

    # ------------------------------------------------------------------
    # 1. Champs de credit disponibles
    # ------------------------------------------------------------------
    titre("CHAMPS LIES AU CREDIT SUR res.partner")
    champs = appel('res.partner', 'fields_get', [], {'attributes': ['string', 'type']})
    mots = ('credit', 'limit', 'plafond', 'encours', 'exempt', 'blocage', 'bloque')
    pertinents = sorted(k for k in champs if any(m in k.lower() for m in mots))
    for k in pertinents:
        print(f"  {k:<36} {champs[k]['type']:<10} {champs[k]['string']}")
    if not pertinents:
        print("  Aucun. Le blocage vient peut-etre d'un autre modele.")

    # ------------------------------------------------------------------
    # 2. Etat du partenaire
    # ------------------------------------------------------------------
    fiche = appel('res.partner', 'read', [[partner_id]],
                  {'fields': ['name'] + pertinents})
    if not fiche:
        raise SystemExit(f"Partenaire {partner_id} introuvable.")
    fiche = fiche[0]

    titre(f"PARTENAIRE {partner_id} — {fiche.get('name')}")
    for k in pertinents:
        valeur = fiche.get(k)
        print(f"  {k:<36} {valeur}")

    # ------------------------------------------------------------------
    # 3. De quoi l'encours est-il fait ?
    # ------------------------------------------------------------------
    titre("FACTURES NON SOLDEES DE CE PARTENAIRE")
    try:
        impayees = appel(
            'account.move', 'search_read',
            [[('partner_id', '=', partner_id),
              ('move_type', '=', 'out_invoice'),
              ('state', '=', 'posted'),
              ('payment_state', '!=', 'paid')]],
            {'fields': ['name', 'invoice_date', 'amount_total',
                        'amount_residual', 'payment_state'],
             'order': 'invoice_date desc', 'limit': 15}
        )
        total = appel(
            'account.move', 'search_count',
            [[('partner_id', '=', partner_id),
              ('move_type', '=', 'out_invoice'),
              ('state', '=', 'posted'),
              ('payment_state', '!=', 'paid')]]
        )
        print(f"  {total} facture(s) non soldee(s). Les 15 plus recentes :\n")
        print(f"  {'Numero':<26} {'Date':<12} {'Total':>12} {'Reste du':>12}  Etat")
        print("  " + "-" * (LARGEUR - 4))
        for f in impayees:
            print(f"  {(f.get('name') or '')[:26]:<26} "
                  f"{str(f.get('invoice_date'))[:12]:<12} "
                  f"{float(f.get('amount_total') or 0):>12,.0f} "
                  f"{float(f.get('amount_residual') or 0):>12,.0f}  "
                  f"{f.get('payment_state')}")
    except Exception as e:
        print(f"  Lecture impossible: {e}")

    # ------------------------------------------------------------------
    # 4. Lecture
    # ------------------------------------------------------------------
    titre("CE QUE CELA SIGNIFIE")
    print("""
  Un compte collectif « Comptant » porte toutes les ventes anonymes. Chaque
  facture y cree une creance, qui doit etre lettree aussitot avec son
  reglement — la vente etant payee comptant, l'encours devrait rester nul.

  Si la liste ci-dessus est longue et l'encours eleve, le lettrage ne se
  fait pas. Relever le plafond ne reglera rien : il sera depasse de nouveau.
  C'est le lettrage qu'il faut corriger, ou le controle de credit qu'il faut
  desactiver sur ce seul partenaire — un plafond de credit n'a pas de sens
  sur un compte de ventes comptant.

  Si au contraire la liste est courte, le plafond est simplement trop bas
  pour le volume de la station, et il suffit de le relever.

  Dans les deux cas, la decision appartient a la comptabilite de JNP.
""")


if __name__ == '__main__':
    main()
