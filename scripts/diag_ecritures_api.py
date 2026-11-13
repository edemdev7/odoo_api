#!/usr/bin/env python3
"""
Verifie deux points souleves par l'audit du schema comptable.

1. TAXES DES VENTES DE L'API
   L'API cree les lignes de vente sans taxes (pas de tax_ids, amount_tax a 0,
   prix TTC porte tel quel en hors taxe). Si c'est confirme, la TVA et l'ASAS
   des ventes de l'API ne sont jamais comptabilisees : tout part en chiffre
   d'affaires. Le script compare des ventes API a des ventes de la caisse Odoo
   sur les memes produits, et montre l'ecriture de cloture d'une session ou
   seules des ventes API ont ete faites.

2. CHAINE COMPLETE D'UNE RECHARGE JNP PASS
   Facture, paiement, releve bancaire : toutes les ecritures liees par
   lettrage, pour voir sur quel compte l'argent de la recharge arrive
   reellement (schema : 5522101 KKiaPay ; code actuel : journal PASS GD).

Lecture seule. Toutes les lectures sont bornees.

Usage :
    cd ~/Documents/projects/odoo_api
    python scripts/diag_ecritures_api.py 32
"""

import os
import sys

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')
except AttributeError:
    pass

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

LARGEUR = 96
ETATS_SOLDES = ['paid', 'done', 'invoiced']


def titre(t):
    print()
    print("=" * LARGEUR)
    print(t)
    print("=" * LARGEUR)


def m2o_id(v):
    return v[0] if isinstance(v, list) and v else (v or None)


def m2o_nom(v):
    return v[1] if isinstance(v, list) and len(v) > 1 else ('—' if not v else str(v))


class Lecteur:
    def __init__(self, appel):
        self.appel = appel
        self._comptes, self._taxes = {}, {}

    def compte(self, cid):
        if not cid:
            return '—'
        if cid not in self._comptes:
            r = self.appel('account.account', 'read', [[cid]], {'fields': ['code']})
            self._comptes[cid] = r[0]['code'] if r else '?'
        return self._comptes[cid]

    def noms_taxes(self, ids):
        manquants = [i for i in ids if i not in self._taxes]
        if manquants:
            for t in self.appel('account.tax', 'read', [manquants],
                                {'fields': ['name', 'company_id']}):
                self._taxes[t['id']] = f"{t['name']} [{m2o_nom(t.get('company_id'))}]"
        return [self._taxes.get(i, str(i)) for i in ids]

    def afficher_ecriture(self, move_id, retrait="    "):
        m = self.appel('account.move', 'read', [[move_id]],
                       {'fields': ['name', 'journal_id', 'date', 'move_type', 'state']})
        if not m:
            return
        m = m[0]
        print(f"{retrait}{m['name']}  [{m2o_nom(m['journal_id'])}]  {m['date']}  "
              f"{m['move_type']}  {m['state']}")
        for l in self.appel('account.move.line', 'search_read', [[('move_id', '=', move_id)]],
                            {'fields': ['account_id', 'name', 'debit', 'credit'], 'limit': 60}):
            print(f"{retrait}  {self.compte(m2o_id(l['account_id'])):<10} "
                  f"{(l.get('name') or '')[:40]:<40} D {float(l['debit']):>12,.0f}  "
                  f"C {float(l['credit']):>12,.0f}")


# ------------------------------------------------------------------ 1

def section_taxes(lec, pos_id):
    titre("1. TAXES — ventes de l'API comparees aux ventes de la caisse Odoo")
    champs_cmd = ['name', 'pos_reference', 'amount_total', 'amount_tax', 'lines']
    api = lec.appel('pos.order', 'search_read', [[
        ('session_id.config_id', '=', pos_id), ('state', 'in', ETATS_SOLDES),
        ('pos_reference', '=like', 'Order-%')]],
        {'fields': champs_cmd, 'order': 'id desc', 'limit': 5})
    caisse = lec.appel('pos.order', 'search_read', [[
        ('session_id.config_id', '=', pos_id), ('state', 'in', ETATS_SOLDES),
        ('pos_reference', 'not like', 'Order-%')]],
        {'fields': champs_cmd, 'order': 'id desc', 'limit': 3})

    sans_taxe = 0
    for libelle, commandes in (("Ventes API", api), ("Ventes caisse Odoo", caisse)):
        print(f"\n  {libelle} ({len(commandes)} dernieres)")
        for c in commandes:
            print(f"    {c['name']:<26} total {float(c['amount_total']):>10,.0f}   "
                  f"dont taxes {float(c['amount_tax']):>8,.0f}")
            if not c.get('lines'):
                continue
            for l in lec.appel('pos.order.line', 'read', [c['lines'][:10]], {'fields': [
                    'product_id', 'qty', 'price_subtotal', 'price_subtotal_incl', 'tax_ids']}):
                taxes = lec.noms_taxes(l.get('tax_ids') or [])
                print(f"      {m2o_nom(l['product_id'])[:30]:<30} HT {float(l['price_subtotal']):>9,.0f}  "
                      f"TTC {float(l['price_subtotal_incl']):>9,.0f}  taxes : {', '.join(taxes) or 'AUCUNE'}")
                if libelle == "Ventes API" and not l.get('tax_ids'):
                    sans_taxe += 1

    # Cloture d'une session ou il n'y a eu que des ventes API
    print("\n  Ecriture de cloture d'une session ne contenant que des ventes API :")
    sessions = lec.appel('pos.session', 'search_read', [[
        ('config_id', '=', pos_id), ('state', '=', 'closed'), ('move_id', '!=', False)]],
        {'fields': ['name', 'move_id'], 'order': 'id desc', 'limit': 15})
    trouvee = False
    for s in sessions:
        natives = lec.appel('pos.order', 'search_count', [[
            ('session_id', '=', s['id']), ('state', '!=', 'cancel'),
            ('pos_reference', 'not like', 'Order-%')]])
        api_n = lec.appel('pos.order', 'search_count', [[
            ('session_id', '=', s['id']), ('state', '!=', 'cancel'),
            ('pos_reference', '=like', 'Order-%')]])
        if api_n and not natives:
            print(f"    {s['name']} — {api_n} vente(s) API, aucune vente caisse")
            lec.afficher_ecriture(m2o_id(s['move_id']), retrait="      ")
            trouvee = True
            break
    if not trouvee:
        print("    aucune dans les 15 dernieres sessions cloturees")
    return sans_taxe


# ------------------------------------------------------------------ 2

def chaine_lettrage(lec, depart, maximum=8):
    """Ecritures reliees a `depart` par lettrage, de proche en proche."""
    vues, a_voir = [], [depart]
    while a_voir and len(vues) < maximum:
        mid = a_voir.pop(0)
        if mid in vues:
            continue
        vues.append(mid)
        lignes = lec.appel('account.move.line', 'search_read', [[('move_id', '=', mid)]],
                           {'fields': ['matched_debit_ids', 'matched_credit_ids'], 'limit': 60})
        partiels = [p for l in lignes
                    for p in (l.get('matched_debit_ids') or []) + (l.get('matched_credit_ids') or [])]
        if not partiels:
            continue
        for p in lec.appel('account.partial.reconcile', 'read', [partiels[:40]],
                           {'fields': ['debit_move_id', 'credit_move_id']}):
            autres = [m2o_id(p.get('debit_move_id')), m2o_id(p.get('credit_move_id'))]
            for ligne in lec.appel('account.move.line', 'read', [[a for a in autres if a]],
                                   {'fields': ['move_id']}):
                m = m2o_id(ligne['move_id'])
                if m not in vues and m not in a_voir:
                    a_voir.append(m)
    return vues


def section_recharge(lec):
    titre("2. CHAINE COMPLETE DE LA DERNIERE RECHARGE JNP PASS")
    prod = lec.appel('product.product', 'search_read', [[('default_code', '=', 'TVPASS_ESS')]],
                     {'fields': ['id'], 'limit': 1})
    pid = prod[0]['id'] if prod else 2742
    lignes = lec.appel('account.move.line', 'search_read', [[
        ('product_id', '=', pid), ('parent_state', '=', 'posted'),
        ('move_id.move_type', '=', 'out_invoice'), ('sale_line_ids', '!=', False)]],
        {'fields': ['move_id'], 'order': 'id desc', 'limit': 1})
    if not lignes:
        print("  Aucune recharge trouvee.")
        return
    depart = m2o_id(lignes[0]['move_id'])
    chaine = chaine_lettrage(lec, depart)
    print(f"  {len(chaine)} ecriture(s) reliee(s) par lettrage :\n")
    for mid in chaine:
        lec.afficher_ecriture(mid)
        print()
    print("  Lecture : l'argent recu doit finir au debit d'un compte de tresorerie")
    print("  (schema : 5522101 KKiaPay). S'il finit au debit de 419101, l'avance")
    print("  creee par la facture est annulee aussitot et l'encaissement n'apparait")
    print("  sur aucun compte de tresorerie.")


def main():
    from _odoo_direct import connexion
    argv = sys.argv[1:]
    if not argv or not argv[0].isdigit():
        print(__doc__)
        sys.exit(1)
    lec = Lecteur(connexion('DB1'))
    sans_taxe = section_taxes(lec, int(argv[0]))
    section_recharge(lec)
    titre("CONCLUSION")
    if sans_taxe:
        print(f"  {sans_taxe} ligne(s) de vente API sans aucune taxe sur l'echantillon :")
        print("  la TVA et l'ASAS de ces ventes ne sont pas comptabilisees.")
    else:
        print("  Les ventes API examinees portent des taxes.")


if __name__ == '__main__':
    main()
