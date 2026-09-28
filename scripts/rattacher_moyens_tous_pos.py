#!/usr/bin/env python3
"""
Rattache des moyens de paiement a l'ensemble des points de vente.

Version « parc complet » de ajouter_moyens_paiement.py, qui ne traite
qu'un seul PdV.

Deux limites structurelles a garder en tete :

  - Un `pos.payment.method` appartient a une societe. Un moyen ne peut
    donc etre rattache qu'aux PdV de sa propre societe. Le script
    resout les moyens societe par societe et signale celles ou le
    moyen n'existe pas.

  - L'interface Odoo verrouille le champ tant qu'une session est
    ouverte, mais la restriction est portee par la vue et non par le
    modele : l'ecriture XML-RPC passe sans fermer les caisses. Les
    sessions deja ouvertes ne verront toutefois les nouveaux moyens
    qu'apres rechargement du PdV.

Usage :
    cd ~/odoo_api
    python3 scripts/rattacher_moyens_tous_pos.py kkiapay token
    python3 scripts/rattacher_moyens_tous_pos.py kkiapay token --appliquer

    # restreindre le perimetre
    python3 scripts/rattacher_moyens_tous_pos.py kkiapay token --pos 4,32
    python3 scripts/rattacher_moyens_tous_pos.py kkiapay token --societe 1
    python3 scripts/rattacher_moyens_tous_pos.py kkiapay token --prefixe JO
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

LARGEUR = 88


def titre(t):
    print()
    print("=" * LARGEUR)
    print(t)
    print("=" * LARGEUR)


def option(argv, nom, defaut=None):
    """Lit --nom valeur ou --nom=valeur."""
    for i, a in enumerate(argv):
        if a == nom and i + 1 < len(argv):
            return argv[i + 1]
        if a.startswith(nom + '='):
            return a.split('=', 1)[1]
    return defaut


def main():
    argv = sys.argv[1:]
    appliquer = '--appliquer' in argv

    filtre_pos = option(argv, '--pos')
    filtre_societe = option(argv, '--societe')
    filtre_prefixe = option(argv, '--prefixe')

    # Ce qui reste apres retrait des options est la liste des moyens.
    consommes = set()
    for nom in ('--pos', '--societe', '--prefixe'):
        val = option(argv, nom)
        if val is not None:
            consommes.add(nom)
            consommes.add(val)
            consommes.add(f"{nom}={val}")
    recherches = [
        a.lower() for a in argv
        if not a.startswith('--') and a not in consommes
    ]

    if not recherches:
        print(__doc__)
        sys.exit(1)

    print("Connexion a Odoo...")
    client = OdooClient()

    # ------------------------------------------------------------------
    # Perimetre des points de vente
    # ------------------------------------------------------------------
    domaine = []
    if filtre_pos:
        ids = [int(x) for x in filtre_pos.replace(' ', '').split(',') if x]
        domaine.append(('id', 'in', ids))
    if filtre_societe:
        domaine.append(('company_id', '=', int(filtre_societe)))
    if filtre_prefixe:
        domaine.append(('name', '=like', f'{filtre_prefixe}%'))

    points = client.execute_kw(
        'pos.config', 'search_read', [domaine],
        {'fields': ['id', 'name', 'company_id', 'payment_method_ids',
                    'current_session_id', 'active'],
         'order': 'name asc'}
    )
    if not points:
        print("\n  Aucun point de vente dans ce perimetre.")
        sys.exit(1)

    titre(f"PERIMETRE — {len(points)} point(s) de vente")
    print(f"  Moyens demandes   : {', '.join(recherches)}")
    print(f"  Mode              : {'ECRITURE' if appliquer else 'simulation'}")

    # ------------------------------------------------------------------
    # Resolution des moyens, societe par societe
    # ------------------------------------------------------------------
    societes = {}
    for p in points:
        c = p.get('company_id')
        cid = c[0] if isinstance(c, list) else c
        societes.setdefault(cid, c[1] if isinstance(c, list) else str(cid))

    moyens_par_societe = {}      # {societe_id: {terme: {'id','name'}}}
    manquants = {}               # {societe_id: [termes absents]}
    ambigus = {}                 # {societe_id: {terme: [moyens]}}

    for cid, libelle in societes.items():
        dispo = client.execute_kw(
            'pos.payment.method', 'search_read',
            [[('company_id', '=', cid)]],
            {'fields': ['id', 'name'], 'order': 'name asc'}
        )
        resolus = {}
        for terme in recherches:
            trouve = [m for m in dispo if terme in m['name'].lower()]
            if not trouve:
                manquants.setdefault(cid, []).append(terme)
            elif len(trouve) > 1:
                # Une correspondance exacte leve l'ambiguite.
                exact = [m for m in trouve if m['name'].lower() == terme]
                if len(exact) == 1:
                    resolus[terme] = exact[0]
                else:
                    ambigus.setdefault(cid, {})[terme] = trouve
            else:
                resolus[terme] = trouve[0]
        moyens_par_societe[cid] = resolus

    titre("MOYENS RESOLUS PAR SOCIETE")
    for cid, libelle in societes.items():
        print(f"\n  Societe {cid} — {libelle}")
        for terme, m in moyens_par_societe[cid].items():
            print(f"    {terme:<16} -> {m['id']:>6}  {m['name']}")
        for terme in manquants.get(cid, []):
            print(f"    {terme:<16} -> ABSENT de cette societe")
        for terme, liste in ambigus.get(cid, {}).items():
            print(f"    {terme:<16} -> AMBIGU : "
                  + ', '.join(f"{m['id']}:{m['name']}" for m in liste))

    if manquants or ambigus:
        print("""
  Les termes absents ou ambigus seront ignores pour les PdV concernes.
  Un moyen absent doit d'abord etre cree dans la societe : il lui faut
  un journal et des comptes propres, ce que ce script ne devine pas.""")

    # ------------------------------------------------------------------
    # Plan d'action
    # ------------------------------------------------------------------
    a_faire = []     # [(pos, [moyens])]
    deja_ok = []
    sans_moyen = []

    for p in points:
        cid = p['company_id'][0] if isinstance(p.get('company_id'), list) else p.get('company_id')
        resolus = moyens_par_societe.get(cid, {})
        if not resolus:
            sans_moyen.append(p)
            continue
        actuels = set(p.get('payment_method_ids') or [])
        ajouts = [m for m in resolus.values() if m['id'] not in actuels]
        if ajouts:
            a_faire.append((p, ajouts))
        else:
            deja_ok.append(p)

    titre("PLAN")
    print(f"  Deja conformes            : {len(deja_ok)}")
    print(f"  A modifier                : {len(a_faire)}")
    print(f"  Sans moyen resolu         : {len(sans_moyen)}")

    if a_faire:
        print(f"\n  {'PdV':>6}  {'Nom':<34} {'Sess.':<6} Moyens a ajouter")
        print("  " + "-" * (LARGEUR - 4))
        for p, ajouts in a_faire:
            sess = 'oui' if p.get('current_session_id') else '—'
            noms = ', '.join(m['name'] for m in ajouts)
            print(f"  {p['id']:>6}  {p['name'][:34]:<34} {sess:<6} {noms}")

    if sans_moyen:
        print(f"\n  PdV sans aucun moyen resolu ({len(sans_moyen)}) :")
        for p in sans_moyen[:20]:
            print(f"    {p['id']:>6}  {p['name']}")
        if len(sans_moyen) > 20:
            print(f"    ... et {len(sans_moyen) - 20} autre(s)")

    if not a_faire:
        print("\n  Rien a ecrire.")
        return

    if not appliquer:
        print(f"""
  Simulation — rien n'a ete ecrit.

  Pour appliquer :

      python3 scripts/rattacher_moyens_tous_pos.py {' '.join(recherches)} --appliquer
""")
        return

    # ------------------------------------------------------------------
    # Ecriture, un PdV a la fois pour isoler les echecs
    # ------------------------------------------------------------------
    titre("ECRITURE")
    succes, echecs = [], []
    for p, ajouts in a_faire:
        # (4, id) ajoute sans toucher aux moyens deja en place.
        commandes = [(4, m['id']) for m in ajouts]
        try:
            client.execute_kw(
                'pos.config', 'write', [[p['id']], {'payment_method_ids': commandes}]
            )
            succes.append(p)
            print(f"  OK     {p['id']:>6}  {p['name'][:40]:<40} "
                  f"+{len(ajouts)} moyen(s)")
        except Exception as e:
            echecs.append((p, str(e)))
            print(f"  ECHEC  {p['id']:>6}  {p['name'][:40]:<40} {e}")

    # ------------------------------------------------------------------
    # Verification par relecture
    # ------------------------------------------------------------------
    titre("VERIFICATION")
    if succes:
        relu = client.execute_kw(
            'pos.config', 'read', [[p['id'] for p in succes]],
            {'fields': ['id', 'name', 'company_id', 'payment_method_ids']}
        )
        non_conformes = []
        for r in relu:
            cid = r['company_id'][0] if isinstance(r.get('company_id'), list) else r.get('company_id')
            attendus = {m['id'] for m in moyens_par_societe.get(cid, {}).values()}
            presents = set(r.get('payment_method_ids') or [])
            if not attendus.issubset(presents):
                non_conformes.append((r, attendus - presents))
        if non_conformes:
            print(f"  {len(non_conformes)} PdV n'ont pas tous les moyens apres ecriture :")
            for r, absents in non_conformes:
                print(f"    {r['id']:>6}  {r['name']}  manque {sorted(absents)}")
        else:
            print(f"  Les {len(succes)} PdV modifies portent bien les moyens demandes.")

    print(f"\n  Succes : {len(succes)}    Echecs : {len(echecs)}")
    if echecs:
        print("""
  Si un message evoque une session ouverte, la contrainte est alors
  portee par le modele pour ce PdV : il faudra fermer sa caisse.
""")

    ouvertes = [p for p in succes if p.get('current_session_id')]
    if ouvertes:
        print(f"""
  {len(ouvertes)} PdV avaient une session ouverte. Ils chargent leur
  configuration au demarrage : leurs caisses doivent etre rechargees
  pour voir les nouveaux moyens.
""")


if __name__ == '__main__':
    main()
