#!/usr/bin/env python3
"""
Connexion Odoo sans dependance externe, pour les scripts de diagnostic.

Pourquoi ce module : les scripts qui passent par `core.odoo_client` tombent
des que le virtualenv est casse ou qu'une montee de version a vide les
site-packages — ce qui arrive au pire moment, en pleine investigation.
Ici, stdlib uniquement.

La configuration est cherchee dans cet ordre :

  1. les variables d'environnement
  2. le fichier .env a la racine du projet
  3. les valeurs par defaut ecrites dans core/config.py, lues par analyse
     de texte plutot que par import

Le troisieme point merite une explication. `core/config.py` porte des
identifiants Odoo en dur — c'est une dette connue, inscrite dans
DETTE-TECHNIQUE.md. Les recopier ici creerait un second endroit a nettoyer
le jour ou ces cles seront tournees. On les lit donc a la source.
"""

import os
import re
import xmlrpc.client

RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _depuis_env_fichier():
    valeurs = {}
    chemin = os.path.join(RACINE, '.env')
    if not os.path.exists(chemin):
        return valeurs
    with open(chemin, encoding='utf-8', errors='replace') as f:
        for ligne in f:
            ligne = ligne.strip()
            if ligne and not ligne.startswith('#') and '=' in ligne:
                cle, valeur = ligne.split('=', 1)
                valeurs[cle.strip()] = valeur.strip().strip('"').strip("'")
    return valeurs


def _depuis_config_py():
    """
    Valeurs par defaut de core/config.py, extraites sans importer le module.

    On y cherche les motifs `os.getenv("CLE", "valeur")`.
    """
    valeurs = {}
    chemin = os.path.join(RACINE, 'core', 'config.py')
    if not os.path.exists(chemin):
        return valeurs
    with open(chemin, encoding='utf-8', errors='replace') as f:
        contenu = f.read()
    for cle, valeur in re.findall(
        r'os\.getenv\(\s*["\'](ODOO_[A-Z0-9_]+)["\']\s*,\s*["\']([^"\']*)["\']\s*\)',
        contenu
    ):
        valeurs.setdefault(cle, valeur)
    return valeurs


def configuration(base: str = 'DB1') -> tuple:
    """(url, db, username, api_key) pour la base demandee."""
    fichier = _depuis_env_fichier()
    defauts = _depuis_config_py()

    def lire(suffixe):
        cle = f'ODOO_{base}_{suffixe}'
        return (os.getenv(cle) or fichier.get(cle) or defauts.get(cle) or '').strip()

    return (lire('URL').rstrip('/'), lire('NAME'), lire('USERNAME'), lire('API_KEY'))


def connexion(base: str = 'DB1', silencieux: bool = False):
    """
    Retourne une fonction `appel(modele, methode, args, kwargs)`.

    Volontairement minimale : pas de reconnexion, pas de cache. Un script de
    diagnostic qui echoue doit echouer franchement.
    """
    url, db, user, cle = configuration(base)

    manquants = [n for n, v in
                 (('URL', url), ('NAME', db), ('USERNAME', user), ('API_KEY', cle))
                 if not v]
    if manquants:
        raise SystemExit(
            f"Configuration Odoo incomplete pour {base} : "
            f"{', '.join('ODOO_%s_%s' % (base, m) for m in manquants)} introuvable(s) "
            f"dans l'environnement, dans .env et dans core/config.py."
        )

    if not silencieux:
        print(f"Connexion a {db}...")

    commun = xmlrpc.client.ServerProxy(f"{url}/xmlrpc/2/common")
    uid = commun.authenticate(db, user, cle, {})
    if not uid:
        raise SystemExit(f"Authentification refusee pour {user} sur {db}.")

    modeles = xmlrpc.client.ServerProxy(f"{url}/xmlrpc/2/object")

    def appel(modele, methode, args, kwargs=None):
        return modeles.execute_kw(db, uid, cle, modele, methode, args, kwargs or {})

    if not silencieux:
        print(f"Authentifie — UID {uid}")
    return appel
