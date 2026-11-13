#!/usr/bin/env python3
"""
Controle la facturation des ventes POS passees par l'API.

A lancer avant et apres le passage a POS_AUTO_INVOICE=toujours, pour savoir
si chaque vente produit bien ses ecritures sans attendre la cloture :

  1. Politique de facturation lue dans l'environnement / le .env.
  2. Pour les dernieres ventes du PDV : facture, etat de paiement (lettrage),
     ecritures de paiement, normalisation DGI.
  3. Client « Comptant » : encours, limite de credit, factures non soldees.
     C'est l'accumulation de creances sur ce compte qui a bloque toute la
     facturation en novembre 2026.
  4. Comptes bancaires : ceux de la societe doivent etre « fiables » pour
     facturer. Le script montre aussi combien de comptes tiers sont marques
     fiables — l'API les passait tous a fiable avant chaque facture.
  5. Factures en attente de normalisation DGI (action manuelle dans Odoo).

Lecture seule. Toutes les lectures sont bornees.

Usage :
    cd ~/Documents/projects/odoo_api
    python scripts/diag_facturation_pos.py 32
    python scripts/diag_facturation_pos.py 32 --limite 20
    python scripts/diag_facturation_pos.py 32 --commande 785506
"""

import os
import sys

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')
except AttributeError:
    pass

ICI = os.path.dirname(os.path.abspath(__file__))
RACINE = os.path.dirname(ICI)
sys.path.insert(0, ICI)

from _odoo_direct import connexion  # noqa: E402

LARGEUR = 92
ETATS_SOLDES = ['paid', 'done', 'invoiced']
NOMS_COMPTANT = ["Client comptant", "Client divers", "Comptant", "Client anonyme"]


def titre(t):
    print()
    print("=" * LARGEUR)
    print(t)
    print("=" * LARGEUR)


def m2o_id(v):
    return v[0] if isinstance(v, list) and v else (v or None)


def m2o_nom(v):
    return v[1] if isinstance(v, list) and len(v) > 1 else ('—' if not v else str(v))


def champs(appel, modele, voulus):
    try:
        dispo = appel(modele, 'fields_get', [], {'attributes': ['type']})
    except Exception:
        return list(voulus)
    return [c for c in voulus if c in dispo]


def variable(nom, defaut=''):
    """Variable lue comme le serveur la lirait : environnement, sinon .env."""
    if os.getenv(nom) is not None:
        return os.getenv(nom)
    chemin = os.path.join(RACINE, '.env')
    if os.path.exists(chemin):
        with open(chemin, encoding='utf-8', errors='replace') as f:
            for ligne in f:
                ligne = ligne.strip()
                if ligne.startswith(nom + '='):
                    return ligne.split('=', 1)[1].strip().strip('"').strip("'")
    return defaut


def masquer(numero):
    numero = (numero or '').replace(' ', '')
    return f"…{numero[-4:]}" if len(numero) > 4 else '…'


def lire_args(argv):
    if not argv or not argv[0].isdigit():
        print(__doc__)
        sys.exit(1)
    opts = {'pos_id': int(argv[0]), 'commande': None, 'limite': 10, 'base': 'DB1'}
    i = 1
    while i < len(argv):
        a = argv[i]
        if not a.startswith('--'):
            raise SystemExit(f"Argument inattendu : {a}")
        cle, _, val = a[2:].partition('=')
        if cle not in ('commande', 'limite', 'base'):
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

def section_politique():
    titre("1. POLITIQUE DE FACTURATION (environnement de CE poste)")
    mode = variable('POS_AUTO_INVOICE', 'client_nomme').strip().lower() or 'client_nomme'
    exclus = variable('POS_PAYMENT_METHODS_SANS_FACTURE', 'TOKEN,CARTE,CARD,JNP PASS')
    # Comme l'API : JNP PASS est toujours considere comme prepaye.
    if 'JNP PASS' not in exclus.upper():
        exclus += ',JNP PASS'
    print(f"  POS_AUTO_INVOICE                  : {mode}")
    print(f"  POS_PAYMENT_METHODS_SANS_FACTURE  : {exclus}")
    print(f"  POS_DEFAULT_PARTNER_ID            : {variable('POS_DEFAULT_PARTNER_ID') or '(vide)'}")
    print("  Attention : c'est le .env du SERVEUR qui fait foi pour l'API.")
    return [m.strip().upper() for m in exclus.split(',') if m.strip()]


# ------------------------------------------------------------------ 2

def section_ventes(appel, opts, exclus):
    titre("2. VENTES — facture, lettrage, normalisation")

    if opts['commande']:
        domaine = [('id', '=', opts['commande'])]
    else:
        domaine = [('session_id.config_id', '=', opts['pos_id']), ('state', 'in', ETATS_SOLDES)]
    commandes = appel('pos.order', 'search_read', [domaine], {
        'fields': champs(appel, 'pos.order', [
            'name', 'pos_reference', 'state', 'date_order', 'partner_id',
            'amount_total', 'account_move', 'payment_ids']),
        'order': 'id desc', 'limit': opts['limite']})
    if not commandes:
        print("  Aucune vente.")
        return []

    champs_fac = champs(appel, 'account.move', [
        'name', 'state', 'payment_state', 'amount_residual', 'invoice_date',
        'is_normalized', 'secu_codemecefdgi', 'normalization_date'])
    champs_pay = champs(appel, 'pos.payment', ['payment_method_id', 'amount', 'account_move_id'])

    bilan = []
    for c in commandes:
        paiements = appel('pos.payment', 'read', [c.get('payment_ids') or []],
                          {'fields': champs_pay}) if c.get('payment_ids') else []
        moyens = [m2o_nom(p.get('payment_method_id')) for p in paiements]
        prepaye = bool(moyens) and all(
            any(x in (m or '').upper() for x in exclus) for m in moyens)

        print(f"\n  {c['name']}  {(c.get('pos_reference') or '')[:28]}  [{c['state']}]  "
              f"{(c.get('date_order') or '')[:16]}  {float(c.get('amount_total') or 0):,.0f}")
        print(f"    client    : {m2o_nom(c.get('partner_id'))}")
        print(f"    paiements : {', '.join(moyens) or 'aucun'}"
              + ("  (prepaye : pas de facture attendue)" if prepaye else ""))

        fac_id = m2o_id(c.get('account_move'))
        verdict = None
        if not fac_id:
            verdict = 'prepaye' if prepaye else 'sans_facture'
            print("    facture   : aucune — " + (
                "normal, deja facture a la recharge" if prepaye
                else "la vente attend l'ecriture de cloture"))
        else:
            f = appel('account.move', 'read', [[fac_id]], {'fields': champs_fac})[0]
            print(f"    facture   : {f.get('name')}  etat {f.get('state')}  "
                  f"paiement {f.get('payment_state')}  reste du {float(f.get('amount_residual') or 0):,.0f}")
            if 'is_normalized' in f:
                print(f"    DGI       : " + (
                    f"normalisee le {(f.get('normalization_date') or '')[:16]} "
                    f"({f.get('secu_codemecefdgi') or 'code ?'})" if f.get('is_normalized')
                    else "NON normalisee (action manuelle dans Odoo)"))
            for p in paiements:
                if 'account_move_id' in p:
                    print(f"    ecriture paiement {m2o_nom(p.get('payment_method_id'))[:24]:<24} : "
                          f"{m2o_nom(p.get('account_move_id'))}")
            lettree = f.get('payment_state') in ('paid', 'in_payment')
            verdict = 'complete' if (f.get('state') == 'posted' and lettree) else 'incomplete'
            if not lettree:
                print("    -> facture non lettree : creance ouverte sur le client")
        bilan.append(verdict)
    return bilan


# ------------------------------------------------------------------ 3

def section_comptant(appel):
    titre("3. CLIENT « COMPTANT » — encours et limite de credit")
    pid = variable('POS_DEFAULT_PARTNER_ID')
    partenaire = None
    champs_p = champs(appel, 'res.partner', [
        'name', 'credit', 'credit_limit', 'use_partner_credit_limit'])
    if pid and pid.isdigit():
        r = appel('res.partner', 'read', [[int(pid)]], {'fields': champs_p})
        partenaire = r[0] if r else None
    if not partenaire:
        for nom in NOMS_COMPTANT:
            r = appel('res.partner', 'search_read', [[('name', '=ilike', nom)]],
                      {'fields': champs_p, 'limit': 1})
            if r:
                partenaire = r[0]
                break
    if not partenaire:
        print("  Aucun client comptant trouve : en mode « toujours », toute vente\n"
              "  anonyme echouera a la facturation. Renseigner POS_DEFAULT_PARTNER_ID.")
        return None

    print(f"  {partenaire['name']} (ID {partenaire['id']})")
    if 'credit' in partenaire:
        print(f"  encours client (creances)      : {float(partenaire.get('credit') or 0):,.0f}")
    if 'credit_limit' in partenaire:
        actif = partenaire.get('use_partner_credit_limit')
        print(f"  limite de credit               : {float(partenaire.get('credit_limit') or 0):,.0f}"
              + ("" if actif is None else f"  ({'active' if actif else 'inactive'})"))
    ouvertes = appel('account.move', 'search_count', [[
        ('partner_id', '=', partenaire['id']), ('move_type', '=', 'out_invoice'),
        ('state', '=', 'posted'), ('payment_state', 'not in', ('paid', 'in_payment', 'reversed'))]])
    print(f"  factures comptabilisees non soldees : {ouvertes}")
    return partenaire


# ------------------------------------------------------------------ 4

def section_banques(appel):
    titre("4. COMPTES BANCAIRES — « fiable » (allow_out_payment)")
    if 'allow_out_payment' not in champs(appel, 'res.partner.bank', ['allow_out_payment']):
        print("  Champ allow_out_payment absent sur cette version : rien a controler.")
        return
    societes = appel('res.company', 'search_read', [[]], {'fields': ['name', 'partner_id'], 'limit': 50})
    ids_soc = [m2o_id(s['partner_id']) for s in societes]
    comptes = appel('res.partner.bank', 'search_read', [[('partner_id', 'in', ids_soc)]],
                    {'fields': ['partner_id', 'acc_number', 'bank_id', 'allow_out_payment'],
                     'limit': 200})
    print("  Comptes de la societe (seuls concernes par la facturation) :")
    for c in comptes:
        print(f"    {m2o_nom(c['partner_id'])[:28]:<28} {masquer(c.get('acc_number')):<8} "
              f"{m2o_nom(c.get('bank_id'))[:24]:<24} "
              f"{'fiable' if c.get('allow_out_payment') else 'NON FIABLE'}")
    if not comptes:
        print("    aucun")
    tiers_fiables = appel('res.partner.bank', 'search_count', [[
        ('partner_id', 'not in', ids_soc), ('allow_out_payment', '=', True)]])
    tiers_total = appel('res.partner.bank', 'search_count', [[('partner_id', 'not in', ids_soc)]])
    print(f"  Comptes de tiers (fournisseurs, clients) marques fiables : {tiers_fiables}/{tiers_total}")
    if tiers_total and tiers_fiables == tiers_total:
        print("    -> tous fiables : probablement l'effet de l'ancien code de facturation.\n"
              "       A faire revoir par la comptabilite avant tout paiement fournisseur.")


# ------------------------------------------------------------------ 5

def section_normalisation(appel):
    titre("5. NORMALISATION DGI — factures clients en attente")
    if 'is_normalized' not in champs(appel, 'account.move', ['is_normalized']):
        print("  Champ is_normalized absent : module de normalisation non detecte.")
        return
    from datetime import date, timedelta
    debut = (date.today() - timedelta(days=30)).isoformat()
    base = [('move_type', '=', 'out_invoice'), ('state', '=', 'posted'),
            ('invoice_date', '>=', debut)]
    total = appel('account.move', 'search_count', [base])
    attente = appel('account.move', 'search_count', [base + [('is_normalized', '=', False)]])
    print(f"  Factures clients des 30 derniers jours : {total}, dont {attente} non normalisee(s).")
    print("  En mode « toujours », chaque vente payee en especes / mobile money\n"
          "  ajoute une facture a normaliser a la main.")


def main():
    opts = lire_args(sys.argv[1:])
    appel = connexion(opts['base'])
    exclus = section_politique()
    bilan = section_ventes(appel, opts, exclus)
    section_comptant(appel)
    section_banques(appel)
    section_normalisation(appel)

    titre("CONCLUSION — ventes examinees")
    if bilan:
        for cle, libelle in (('complete', "facturees et lettrees (ecritures immediates)"),
                             ('incomplete', "facturees mais creance ouverte"),
                             ('sans_facture', "sans facture (attendent la cloture)"),
                             ('prepaye', "prepayees (pas de facture attendue)")):
            n = bilan.count(cle)
            if n:
                print(f"  {n:>3}  {libelle}")


if __name__ == '__main__':
    main()
