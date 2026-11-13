#!/usr/bin/env python3
"""
Compare la configuration comptable d'Odoo au schema du comptable
(SCHEMAS_DES_ECRITURES_COMPTABLES_PLATEFORME_OPEN_SI.xlsx, novembre 2026).

Le schema decrit, pour chaque vente, deux ecritures :
  - la vente     : debit 4111000 client / credit 701xxxx du produit, TVA, ASAS ;
  - le reglement : debit tresorerie du moyen de paiement / credit 4111000.
Odoo produit lui-meme ces ecritures — a la facture, ou a la cloture de
session pour les ventes non facturees — a partir de sa configuration : compte
de vente et taxes de chaque produit, journal et comptes de chaque moyen de
paiement. L'API n'a pas a les ecrire : elle les doublerait.

Ce script verifie donc que la configuration et les ecritures reellement
passees correspondent au schema :
  1. Les comptes du schema existent-ils dans le plan comptable ?
  2. Produits vendus au PDV : compte de vente et comptes de taxes.
  3. Moyens de paiement du PDV : journal, compte de tresorerie, compte client.
  4. Ecritures reelles : derniere vente facturee, derniere cloture de session,
     dernieres recharges JNP PASS et ventes par carte (/accounting/debit-account).
  5. Ecarts constates.

Lecture seule. Toutes les lectures sont bornees.

Usage :
    cd ~/Documents/projects/odoo_api
    python scripts/audit_schema_comptable.py 32
    python scripts/audit_schema_comptable.py 32 --jours 90
"""

import os
import sys
from datetime import date, timedelta

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')
except AttributeError:
    pass

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

LARGEUR = 96

# ------------------------------------------------------------------------
# Schema du comptable, tel que transmis. A corriger ici s'il evolue.
# ------------------------------------------------------------------------

COMPTES_SCHEMA = {
    '4111000': "Clients",
    '419101':  "Clients, avances et acomptes recus / Carburant",
    '4191300': "Clients, avances et acomptes recus Promoteurs",
    '4431000': "TVA facturee sur ventes",
    '4431200': "TVA facturee sur avance sur consommation",
    '4478209': "Taxe ASAS",
    '5731101': "Caisse stations FCFA",
    '5522101': "Monnaie electronique - compte KKiaPay",
    '7011101': "Vente Gasoil dedouane",
    '7011201': "Vente Super / Essence dedouane",
    '7011501': "Vente Butane dedouane (recharge)",
    '7011400': "Vente de lubrifiants",
    '7011504': "Vente de bouteille vide de gaz",
    '7011505': "Vente d'accessoires de gaz",
}

TVA, ASAS = '4431000', '4478209'

# Familles de produits, testees dans cet ordre sur « nom + reference +
# categorie ». La famille est DEVINEE : elle est affichee pour controle.
# Le dernier element est l'ensemble des comptes de taxe attendus, ou None
# quand le schema n'en dit rien.
FAMILLES = [
    ('bouteille vide',  ('BOUTEILLE VIDE',),                               '7011504', None),
    ('lubrifiant',      ('LUBRIF', 'HUILE', 'ENOC', '10W', '15W', '20W',
                         '5W', 'GRAISSE', 'ADDITIF', 'CLEANER'),           '7011400', {TVA}),
    ('recharge gaz',    ('RECHARGE GAZ', 'BUTANE', 'GAZ 6', 'GAZ 12',
                         'GAZ 47', 'GAZ 50'),                              '7011501', {TVA, ASAS}),
    ('accessoire gaz',  ('ACCESSOIRE', 'DETENDEUR', 'BRULEUR', 'TUYAU',
                         'RECHAUD', 'GAZ'),                                '7011505', None),
    ('gasoil',          ('GASOIL', 'DIESEL', 'GAZOLE'),                    '7011101', {TVA, ASAS}),
    ('essence',         ('ESSENCE', 'SUPER'),                              '7011201', {TVA, ASAS}),
]

# Moyens de paiement : compte de tresorerie attendu au reglement.
MOYENS = [
    ('especes',  ('CASH', 'ESPECE', 'ESPÈCE'),        '5731101'),
    ('kkiapay',  ('KKIAPAY',),                        '5522101'),
    ('jnp pass', ('PASS', 'CARTE', 'CARD', 'TOKEN'),  '419101'),
]
COMPTE_CLIENT = '4111000'


# ------------------------------------------------------------------ outils

def titre(t):
    print()
    print("=" * LARGEUR)
    print(t)
    print("=" * LARGEUR)


def m2o_id(v):
    return v[0] if isinstance(v, list) and v else (v or None)


def m2o_nom(v):
    return v[1] if isinstance(v, list) and len(v) > 1 else ('—' if not v else str(v))


class Odoo:
    """Lectures Odoo avec caches : comptes, taxes, champs disponibles."""

    def __init__(self, appel):
        self.appel = appel
        self._comptes, self._taxes, self._champs = {}, {}, {}

    def champs(self, modele, voulus):
        """Garde les champs qui existent sur le modele (17 et 19 different)."""
        if modele not in self._champs:
            try:
                self._champs[modele] = set(self.appel(modele, 'fields_get', [],
                                                      {'attributes': ['type']}))
            except Exception:
                self._champs[modele] = set(voulus)
        return [c for c in voulus if c in self._champs[modele]]

    def compte(self, cid):
        """(code, nom) d'un compte, ou ('', '—')."""
        if not cid:
            return '', '—'
        if cid not in self._comptes:
            r = self.appel('account.account', 'read', [[cid]], {'fields': ['code', 'name']})
            self._comptes[cid] = (r[0]['code'], r[0]['name']) if r else ('?', '?')
        return self._comptes[cid]

    def comptes_de_taxe(self, tax_ids):
        """(codes, libelles) des comptes de taxe — lignes « tax » des factures."""
        codes, libelles = set(), []
        for tid in tax_ids or []:
            for code, libelle in self._taxe(tid):
                codes.add(code)
                libelles.append(libelle)
        return codes, libelles

    def _taxe(self, tid, profondeur=0):
        if tid in self._taxes:
            return self._taxes[tid]
        t = self.appel('account.tax', 'read', [[tid]], {'fields': self.champs(
            'account.tax', ['name', 'amount', 'amount_type', 'children_tax_ids',
                            'invoice_repartition_line_ids'])})
        resultat = []
        if t:
            t = t[0]
            if t.get('amount_type') == 'group' and profondeur < 3:
                # Groupe de taxes : on descend dans chaque taxe enfant.
                for enfant in t.get('children_tax_ids') or []:
                    resultat += self._taxe(enfant, profondeur + 1)
            else:
                lignes = t.get('invoice_repartition_line_ids') or []
                comptes = []
                if lignes:
                    for l in self.appel('account.tax.repartition.line', 'read', [lignes],
                                        {'fields': ['repartition_type', 'account_id']}):
                        if l.get('repartition_type') == 'tax':
                            comptes.append(self.compte(m2o_id(l.get('account_id')))[0] or '(aucun)')
                taux = f"{t.get('amount')}{'%' if t.get('amount_type') == 'percent' else ''}"
                libelle = f"{t.get('name')} ({taux})"
                resultat = ([(c, f"{libelle} -> {c}") for c in comptes]
                            or [('(aucun)', f"{libelle} -> aucun compte")])
        self._taxes[tid] = resultat
        return resultat

    def lignes_par_compte(self, move_ids, limite=500):
        """{code: [nom, debit, credit]} pour les ecritures donnees."""
        move_ids = [m for m in move_ids if m]
        if not move_ids:
            return {}
        lignes = self.appel('account.move.line', 'search_read',
                            [[('move_id', 'in', move_ids)]],
                            {'fields': ['account_id', 'debit', 'credit'], 'limit': limite})
        cumul = {}
        for l in lignes:
            code, nom = self.compte(m2o_id(l['account_id']))
            c = cumul.setdefault(code, [nom, 0.0, 0.0])
            c[1] += float(l.get('debit') or 0)
            c[2] += float(l.get('credit') or 0)
        return cumul


def code_conforme(actuel, attendu):
    """Meme compte, a des zeros de fin pres (419101 / 4191010)."""
    if not actuel or not attendu:
        return False
    return (actuel == attendu or actuel.startswith(attendu)
            or actuel.rstrip('0') == attendu.rstrip('0'))


def afficher_lignes(cumul, retrait="      "):
    if not cumul:
        print(f"{retrait}(aucune ligne)")
        return
    for code, (nom, d, c) in sorted(cumul.items()):
        print(f"{retrait}{code:<10} {nom[:44]:<44} D {d:>14,.0f}   C {c:>14,.0f}")


def lire_args(argv):
    if not argv or not argv[0].isdigit():
        print(__doc__)
        sys.exit(1)
    opts = {'pos_id': int(argv[0]), 'jours': 60, 'base': 'DB1'}
    i = 1
    while i < len(argv):
        a = argv[i]
        if not a.startswith('--'):
            raise SystemExit(f"Argument inattendu : {a}")
        cle, _, val = a[2:].partition('=')
        if cle not in ('jours', 'base'):
            raise SystemExit(f"Option inconnue : {a}")
        if not val:
            i += 1
            if i >= len(argv):
                raise SystemExit(f"Valeur manquante pour {a}")
            val = argv[i]
        opts[cle] = val.upper() if cle == 'base' else int(val)
        i += 1
    return opts


# ------------------------------------------------------------------ 1

def section_plan(o, ecarts):
    titre("1. PLAN COMPTABLE — les comptes du schema existent-ils ?")
    for code, libelle in COMPTES_SCHEMA.items():
        trouves = o.appel('account.account', 'search_read',
                          [[('code', '=like', code + '%')]],
                          {'fields': ['code', 'name'], 'limit': 3})
        if trouves:
            print(f"  {code:<9} {libelle[:40]:<40} -> " +
                  "; ".join(f"{t['code']} {t['name'][:30]}" for t in trouves))
        else:
            print(f"  {code:<9} {libelle[:40]:<40} -> INTROUVABLE")
            ecarts.append(f"Compte {code} ({libelle}) introuvable dans le plan comptable")


# ------------------------------------------------------------------ 2

def famille_de(texte):
    for nom, mots, compte, taxes in FAMILLES:
        if any(m in texte for m in mots):
            return nom, compte, taxes
    return None, None, None


def section_produits(o, pos_id, jours, ecarts):
    titre(f"2. PRODUITS VENDUS AU PDV {pos_id} ({jours} derniers jours) — compte de vente et taxes")
    depuis = (date.today() - timedelta(days=jours)).isoformat()
    groupes = o.appel('pos.order.line', 'read_group', [
        [('order_id.session_id.config_id', '=', pos_id),
         ('order_id.date_order', '>=', depuis + ' 00:00:00')],
        ['qty'], ['product_id']], {'lazy': False, 'limit': 200})
    pids = [m2o_id(g['product_id']) for g in groupes if g.get('product_id')]
    if not pids:
        print("  Aucune vente sur la periode.")
        return
    produits = o.appel('product.product', 'read', [pids], {'fields': o.champs('product.product', [
        'display_name', 'default_code', 'type', 'categ_id', 'taxes_id',
        'property_account_income_id'])})
    categs = {}
    cids = list({m2o_id(p.get('categ_id')) for p in produits if p.get('categ_id')})
    if cids:
        for c in o.appel('product.category', 'read', [cids], {'fields': o.champs(
                'product.category', ['complete_name', 'property_account_income_categ_id'])}):
            categs[c['id']] = c

    for p in sorted(produits, key=lambda x: x.get('display_name') or ''):
        categ = categs.get(m2o_id(p.get('categ_id')), {})
        texte = ' '.join(str(x or '') for x in (
            p.get('display_name'), p.get('default_code'), categ.get('complete_name'))).upper()
        famille, compte_att, taxes_att = famille_de(texte)

        # Compte de vente effectif : celui du produit, sinon celui de la categorie.
        compte_id = m2o_id(p.get('property_account_income_id'))
        origine = 'produit'
        if not compte_id:
            compte_id = m2o_id(categ.get('property_account_income_categ_id'))
            origine = 'categorie'
        code, nom = o.compte(compte_id)
        codes_taxe, libelles_taxe = o.comptes_de_taxe(p.get('taxes_id'))

        print(f"\n  {(p.get('display_name') or '')[:60]}  [{p.get('type')}]")
        print(f"    categorie       : {categ.get('complete_name') or '—'}")
        print(f"    famille devinee : {famille or '? (non classee : verifier a la main)'}")
        etat = ''
        if compte_att:
            etat = '  OK' if code_conforme(code, compte_att) else f"  ECART (attendu {compte_att})"
        print(f"    compte de vente : {code or 'AUCUN'} {nom[:40]} (via {origine}){etat}")
        print(f"    taxes           : {'; '.join(libelles_taxe) or 'aucune'}")
        if compte_att and not code_conforme(code, compte_att):
            ecarts.append(f"{p.get('display_name')} : vente sur {code or 'aucun compte'}, "
                          f"schema {compte_att}")
        if taxes_att is not None:
            manquantes = sorted(t for t in taxes_att
                                if not any(code_conforme(c, t) for c in codes_taxe))
            if manquantes:
                print(f"    -> taxe(s) du schema absente(s) : {', '.join(manquantes)}")
                ecarts.append(f"{p.get('display_name')} : taxe(s) {', '.join(manquantes)} "
                              f"absente(s) (comptes actuels : "
                              f"{', '.join(sorted(codes_taxe)) or 'aucun'})")


# ------------------------------------------------------------------ 3

def section_moyens(o, pos_id, ecarts):
    titre(f"3. MOYENS DE PAIEMENT DU PDV {pos_id} — comptes du reglement")
    cfg = o.appel('pos.config', 'read', [[pos_id]], {'fields': o.champs('pos.config', [
        'name', 'company_id', 'payment_method_ids', 'default_fiscal_position_id',
        'fiscal_position_ids'])})
    if not cfg:
        print("  PDV introuvable.")
        return
    cfg = cfg[0]

    # Positions fiscales : elles peuvent remplacer comptes et taxes a la vente.
    fps = set(cfg.get('fiscal_position_ids') or [])
    if cfg.get('default_fiscal_position_id'):
        fps.add(m2o_id(cfg['default_fiscal_position_id']))
    if fps:
        print(f"  Positions fiscales du PDV : {len(fps)} — elles peuvent changer "
              f"comptes et taxes, a verifier dans Odoo.")
        ecarts.append(f"Le PDV a {len(fps)} position(s) fiscale(s) : verifier leurs "
                      f"correspondances de comptes et de taxes")

    defaut_client = None
    soc_id = m2o_id(cfg.get('company_id'))
    if soc_id and o.champs('res.company', ['account_default_pos_receivable_account_id']):
        soc = o.appel('res.company', 'read', [[soc_id]],
                      {'fields': ['account_default_pos_receivable_account_id']})
        defaut_client = m2o_id(soc[0].get('account_default_pos_receivable_account_id')) if soc else None
        code, nom = o.compte(defaut_client)
        etat = 'OK' if code_conforme(code, COMPTE_CLIENT) else f"ECART (attendu {COMPTE_CLIENT})"
        print(f"  Compte client POS par defaut de la societe : {code or 'aucun'} {nom[:40]}  {etat}")
        if not code_conforme(code, COMPTE_CLIENT):
            ecarts.append(f"Compte client POS par defaut {code or 'aucun'}, schema {COMPTE_CLIENT}")

    ids = cfg.get('payment_method_ids') or []
    if not ids:
        print("  Aucun moyen de paiement.")
        return
    for m in o.appel('pos.payment.method', 'read', [ids], {'fields': o.champs(
            'pos.payment.method', ['name', 'type', 'is_cash_count', 'journal_id',
                                   'receivable_account_id', 'outstanding_account_id'])}):
        nom_m = (m.get('name') or '').upper()
        attendu = next((compte for _, mots, compte in MOYENS if any(x in nom_m for x in mots)), None)
        print(f"\n  {m.get('name')}  (type {m.get('type', '?')}, especes={m.get('is_cash_count')})")

        recv = m2o_id(m.get('receivable_account_id')) or defaut_client
        code_r, nom_r = o.compte(recv)
        etat_r = 'OK' if code_conforme(code_r, COMPTE_CLIENT) else f"ECART (attendu {COMPTE_CLIENT})"
        print(f"    compte client          : {code_r or 'aucun'} {nom_r[:40]}  {etat_r}"
              + ("" if m.get('receivable_account_id') else "  (defaut societe)"))
        if not code_conforme(code_r, COMPTE_CLIENT):
            ecarts.append(f"{m.get('name')} : compte client {code_r or 'aucun'}, "
                          f"schema {COMPTE_CLIENT}")

        jid = m2o_id(m.get('journal_id'))
        if not jid:
            print("    journal                : AUCUN (paiement « plus tard » sur compte client)")
            continue
        j = o.appel('account.journal', 'read', [[jid]], {'fields': o.champs(
            'account.journal', ['name', 'code', 'type', 'default_account_id'])})[0]
        code_t, nom_t = o.compte(m2o_id(j.get('default_account_id')))
        etat_t = ''
        if attendu:
            etat_t = 'OK' if code_conforme(code_t, attendu) else f"ECART (attendu {attendu})"
        print(f"    journal                : {j.get('name')} ({j.get('code')}, {j.get('type')})")
        print(f"    compte de tresorerie   : {code_t or 'aucun'} {nom_t[:40]}  {etat_t}")
        if attendu and not code_conforme(code_t, attendu):
            ecarts.append(f"{m.get('name')} : tresorerie {code_t or 'aucune'} "
                          f"(journal {j.get('name')}), schema {attendu}")
        if m.get('outstanding_account_id'):
            code_o, nom_o = o.compte(m2o_id(m.get('outstanding_account_id')))
            print(f"    compte d'attente       : {code_o} {nom_o[:40]}")
        if not attendu:
            print("    -> moyen absent du schema : compte attendu inconnu")
            ecarts.append(f"Moyen de paiement « {m.get('name')} » absent du schema du comptable")


# ------------------------------------------------------------------ 4

def section_ecritures(o, pos_id):
    titre("4. ECRITURES REELLEMENT PASSEES")

    # a. Derniere vente facturee du PDV, et ses ecritures de paiement
    print("\n  a) Derniere vente facturee du PDV")
    cmd = o.appel('pos.order', 'search_read', [[
        ('session_id.config_id', '=', pos_id), ('account_move', '!=', False)]],
        {'fields': ['name', 'account_move', 'payment_ids'], 'order': 'id desc', 'limit': 1})
    if cmd:
        c = cmd[0]
        print(f"    {c['name']} — facture {m2o_nom(c['account_move'])}")
        afficher_lignes(o.lignes_par_compte([m2o_id(c['account_move'])]))
        if c.get('payment_ids') and o.champs('pos.payment', ['account_move_id']):
            pmts = o.appel('pos.payment', 'read', [c['payment_ids'][:20]],
                           {'fields': ['payment_method_id', 'account_move_id']})
            moves = [m2o_id(p['account_move_id']) for p in pmts if p.get('account_move_id')]
            print("    ecriture(s) de paiement :")
            afficher_lignes(o.lignes_par_compte(moves))
    else:
        print("    aucune")

    # b. Derniere cloture de session (ventes non facturees)
    print("\n  b) Derniere session cloturee du PDV — ecriture de cloture")
    if o.champs('pos.session', ['move_id']):
        sess = o.appel('pos.session', 'search_read', [[
            ('config_id', '=', pos_id), ('state', '=', 'closed'), ('move_id', '!=', False)]],
            {'fields': ['name', 'move_id'], 'order': 'id desc', 'limit': 1})
        if sess:
            print(f"    {sess[0]['name']} — {m2o_nom(sess[0]['move_id'])}")
            afficher_lignes(o.lignes_par_compte([m2o_id(sess[0]['move_id'])]))
            print("    (les encaissements en especes passent en plus par le journal de caisse)")
        else:
            print("    aucune")

    # c. Recharges JNP PASS et ventes par carte (/accounting/debit-account).
    # Les deux utilisent le produit TVPASS ; une recharge passe par une
    # commande de vente, une vente par carte non.
    print("\n  c) Factures du produit TVPASS : recharges et ventes par carte")
    prod = o.appel('product.product', 'search_read', [[('default_code', '=', 'TVPASS_ESS')]],
                   {'fields': ['id'], 'limit': 1})
    pid = prod[0]['id'] if prod else 2742
    champs_l = o.champs('account.move.line', ['move_id', 'sale_line_ids'])
    lignes = o.appel('account.move.line', 'search_read', [[
        ('product_id', '=', pid), ('parent_state', '=', 'posted'),
        ('move_id.move_type', '=', 'out_invoice')]],
        {'fields': champs_l, 'order': 'id desc', 'limit': 40})
    recharges, ventes = [], []
    for l in lignes:
        (recharges if l.get('sale_line_ids') else ventes).append(m2o_id(l['move_id']))
    recharges = list(dict.fromkeys(recharges))[:3]
    ventes = list(dict.fromkeys(ventes))[:3]
    for libelle, moves in (("Recharges (via commande de vente)", recharges),
                           ("Ventes par carte (/accounting/debit-account, sans commande)", ventes)):
        print(f"\n    {libelle} : {len(moves)} derniere(s) examinee(s)")
        if not moves:
            continue
        print("    facture(s) :")
        afficher_lignes(o.lignes_par_compte(moves))
        # Reglements lettres avec ces factures
        recv = o.appel('account.move.line', 'search_read', [[
            ('move_id', 'in', moves), ('account_id.account_type', '=', 'asset_receivable')]],
            {'fields': ['matched_credit_ids'], 'limit': 50})
        partiels = [p for r in recv for p in (r.get('matched_credit_ids') or [])][:50]
        if partiels:
            reglements = o.appel('account.partial.reconcile', 'read', [partiels],
                                 {'fields': ['credit_move_id']})
            lignes_cr = [m2o_id(r['credit_move_id']) for r in reglements if r.get('credit_move_id')]
            mv = o.appel('account.move.line', 'read', [lignes_cr], {'fields': ['move_id']}) if lignes_cr else []
            print("    reglement(s) lettre(s) :")
            afficher_lignes(o.lignes_par_compte(list({m2o_id(x['move_id']) for x in mv})))


def main():
    from _odoo_direct import connexion
    opts = lire_args(sys.argv[1:])
    o = Odoo(connexion(opts['base']))
    ecarts = []
    section_plan(o, ecarts)
    section_produits(o, opts['pos_id'], opts['jours'], ecarts)
    section_moyens(o, opts['pos_id'], ecarts)
    section_ecritures(o, opts['pos_id'])

    titre("5. ECARTS AVEC LE SCHEMA DU COMPTABLE")
    if not ecarts:
        print("  Aucun ecart detecte sur la configuration examinee.")
    for e in ecarts:
        print(f"  - {e}")
    print("\n  Les familles de produits sont devinees a partir des noms : verifier les")
    print("  produits « non classes » et toute classification surprenante.")


if __name__ == '__main__':
    main()
