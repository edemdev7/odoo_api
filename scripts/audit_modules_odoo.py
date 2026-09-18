#!/usr/bin/env python3
"""
Audit des personnalisations d'une instance Odoo.

Avant d'ajouter un module a un Odoo existant, il faut savoir ce qui a deja ete
fait : quels modules non standard sont installes, quels champs ont ete ajoutes
aux modeles, quelles vues sont cassees.

Ce script est en lecture seule.

Usage :
    cd ~/odoo_api
    python3 scripts/audit_modules_odoo.py account.move > audit_facture.txt 2>&1
    python3 scripts/audit_modules_odoo.py
"""

import sys
import os
import re

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

# Prefixes des modules livres par Odoo. Tout le reste est du sur-mesure.
PREFIXES_STANDARD = (
    'account', 'analytic', 'auth_', 'barcodes', 'base', 'board', 'bus',
    'calendar', 'contacts', 'crm', 'delivery', 'digest', 'fleet', 'google_',
    'hr', 'html_editor', 'iap', 'im_livechat', 'link_tracker', 'mail',
    'maintenance', 'mass_mailing', 'membership', 'microsoft_', 'mrp', 'note',
    'onboarding', 'partner_', 'payment', 'phone_validation', 'point_of_sale',
    'portal', 'privacy_', 'product', 'project', 'purchase', 'rating',
    'repair', 'resource', 'sale', 'sign', 'sms', 'snailmail', 'social_media',
    'spreadsheet', 'stock', 'survey', 'transifex', 'uom', 'utm', 'web',
    'website', 'gamification',
)

# Termes indiquant un champ lie a la facture normalisee beninoise
MOTS_FISCAUX = ('mecef', 'dgi', 'nim', 'ifu', 'compteur', 'norm', 'fiscal', 'qr')


def titre(texte):
    print()
    print("=" * LARGEUR)
    print(texte)
    print("=" * LARGEUR)


def est_standard(nom):
    return any(nom == p.rstrip('_') or nom.startswith(p) for p in PREFIXES_STANDARD)


def modules_personnalises(client):
    titre("MODULES NON STANDARD INSTALLES")

    modules = client.execute_kw(
        'ir.module.module', 'search_read',
        [[('state', '=', 'installed')]],
        {'fields': ['name', 'shortdesc', 'author', 'installed_version'],
         'order': 'name asc'}
    )
    sur_mesure = [m for m in modules if not est_standard(m['name'])]

    print(f"  {len(modules)} modules installes, dont {len(sur_mesure)} non standard\n")
    for m in sur_mesure:
        auteur = (m.get('author') or '')[:28]
        print(f"  {m['name']:<38} {auteur:<30} {m.get('installed_version') or ''}")
        if m.get('shortdesc') and m['shortdesc'] != m['name']:
            print(f"      {m['shortdesc'][:84]}")
    if not sur_mesure:
        print("  Aucun.")


def champs_du_modele(client, modele):
    """Tous les champs non standard, avec mise en avant des champs fiscaux."""
    print(f"\n  ---- {modele} ----")

    tous = client.execute_kw(
        'ir.model.fields', 'search_read',
        [[('model', '=', modele)]],
        {'fields': ['name', 'field_description', 'ttype', 'state', 'store'],
         'order': 'name asc'}
    )

    manuels = [c for c in tous if c.get('state') == 'manual']
    prefixes_x = [c for c in tous if c['name'].startswith('x_') and c.get('state') != 'manual']
    fiscaux = [
        c for c in tous
        if any(mot in c['name'].lower() or mot in (c.get('field_description') or '').lower()
               for mot in MOTS_FISCAUX)
    ]

    if fiscaux:
        print(f"\n  CHAMPS FISCAUX / MECeF ({len(fiscaux)}) :")
        for c in fiscaux:
            origine = 'manuel' if c.get('state') == 'manual' else 'module'
            print(f"    {c['name']:<36} {c['ttype']:<12} {origine:<8} "
                  f"{(c.get('field_description') or '')[:36]}")
    else:
        print("\n  Aucun champ fiscal / MECeF detecte.")

    autres = [c for c in (manuels + prefixes_x) if c not in fiscaux]
    if autres:
        print(f"\n  Autres champs hors standard ({len(autres)}) :")
        for c in autres:
            origine = 'manuel' if c.get('state') == 'manual' else 'module'
            print(f"    {c['name']:<36} {c['ttype']:<12} {origine:<8} "
                  f"{(c.get('field_description') or '')[:36]}")

    print(f"\n  Total : {len(tous)} champs sur {modele}")


def vues_cassees(client, modeles):
    titre("VUES REFERENCANT UN CHAMP ABSENT")
    print("  Une vue citant un champ inexistant rend le formulaire inaccessible.")
    print("  C'est le symptome observe sur res.partner avec is_exonere.\n")

    for modele in modeles:
        noms = set(
            c['name'] for c in client.execute_kw(
                'ir.model.fields', 'search_read',
                [[('model', '=', modele)]], {'fields': ['name']}
            )
        )
        vues = client.execute_kw(
            'ir.ui.view', 'search_read',
            [[('model', '=', modele)]],
            {'fields': ['id', 'name', 'type', 'arch_db', 'active']}
        )
        anomalies = []
        for v in vues:
            cites = set(re.findall(r'<field[^>]+name="([a-zA-Z0-9_]+)"', v.get('arch_db') or ''))
            manquants = sorted(m for m in (cites - noms) if m.startswith('x_'))
            if manquants:
                anomalies.append((v, manquants))

        print(f"  {modele} : {len(anomalies)} vue(s) suspecte(s) sur {len(vues)}")
        for v, manquants in anomalies[:10]:
            etat = "active" if v.get('active') else "archivee"
            print(f"    Vue {v['id']:<8} {(v['name'] or '')[:42]:<44} [{etat}]")
            print(f"        absents du modele : {', '.join(manquants[:6])}")


def exemple_facture(client):
    """Valeurs reelles sur la derniere facture, pour voir ce qui est rempli."""
    titre("DERNIERE FACTURE — VALEURS DES CHAMPS FISCAUX")

    champs = client.execute_kw(
        'ir.model.fields', 'search_read',
        [[('model', '=', 'account.move')]],
        {'fields': ['name', 'field_description']}
    )
    noms_fiscaux = [
        c['name'] for c in champs
        if any(mot in c['name'].lower() or mot in (c.get('field_description') or '').lower()
               for mot in MOTS_FISCAUX)
    ]
    if not noms_fiscaux:
        print("  Aucun champ fiscal sur account.move.")
        return

    factures = client.execute_kw(
        'account.move', 'search_read',
        [[('move_type', '=', 'out_invoice'), ('state', '=', 'posted')]],
        {'fields': ['name'] + noms_fiscaux, 'limit': 3, 'order': 'id desc'}
    )
    for f in factures:
        print(f"\n  Facture {f.get('name')}")
        for n in noms_fiscaux:
            valeur = f.get(n)
            if valeur not in (False, None, ''):
                print(f"    {n:<36} = {valeur}")


def main():
    modeles = sys.argv[1:] or ['account.move', 'res.partner', 'pos.order']

    print("Connexion a Odoo...")
    client = OdooClient()

    modules_personnalises(client)

    titre("CHAMPS PAR MODELE")
    for m in modeles:
        try:
            champs_du_modele(client, m)
        except Exception as e:
            print(f"\n  {m} : illisible ({e})")

    vues_cassees(client, modeles)

    if 'account.move' in modeles:
        try:
            exemple_facture(client)
        except Exception as e:
            print(f"  Exemple de facture illisible : {e}")

    titre("FIN")
    print("""
  Ce qu'on cherche ici : les champs portant le code MECeF, le NIM, les
  compteurs et l'heure de certification. Leurs noms exacts permettront de
  les exposer dans /invoice/details, pour que le mobile imprime un document
  conforme au modele fourni par JNP.
""")


if __name__ == '__main__':
    main()
