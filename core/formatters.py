"""
Formatage des nombres dans les réponses API.

Stratégie :
- Tous les floats sont arrondis à 3 décimales max (gardés comme numbers JSON).
- Exception : les clés dans COMMA_STRING_KEYS sont converties en string avec
  virgule comme séparateur décimal — réservé aux valeurs affichées directement
  aux pompistes pour saisie manuelle (index pompe, volumes, etc.).

Exemples de rendu final (number) :
    297.87999999999  →  297.88
    3373573.0        →  3373573.0   (int si .0, sinon float arrondi)
    2.45             →  2.45
"""

# Clés dont la valeur doit être convertie en STRING avec virgule.
# À compléter uniquement pour les champs affichés/saisis par les pompistes.
COMMA_STRING_KEYS: set[str] = {
    # ex: "pump_index", "volume_display"  — à ajouter au besoin
}


def _round_float(value: float) -> float | int:
    """Arrondit un float à 3 décimales. Retourne un int si le résultat est entier."""
    rounded = round(value, 3)
    # Évite d'envoyer 3373573.0 au lieu de 3373573
    if rounded == int(rounded):
        return int(rounded)
    return rounded


def _to_comma_string(value: float) -> str:
    """Formate un float en string avec virgule et max 3 décimales."""
    rounded = round(value, 3)
    formatted = f"{rounded:.3f}".rstrip("0").rstrip(".")
    return formatted.replace(".", ",")


def clean_numbers(obj, parent_key: str = ""):
    """
    Parcourt récursivement un dict/list :
    - float dans COMMA_STRING_KEYS → string avec virgule
    - tout autre float             → arrondi, reste un number JSON
    """
    if isinstance(obj, dict):
        return {k: clean_numbers(v, parent_key=k) for k, v in obj.items()}
    if isinstance(obj, list):
        return [clean_numbers(item, parent_key=parent_key) for item in obj]
    if isinstance(obj, float):
        if parent_key in COMMA_STRING_KEYS:
            return _to_comma_string(obj)
        return _round_float(obj)
    return obj


# ---------------------------------------------------------------------------
# Client d'une vente anonyme
# ---------------------------------------------------------------------------
# Odoo exige un partenaire sur toute facture. Une vente à la pompe étant
# anonyme par nature, elle est rattachée à un compte collectif — « Comptant »,
# « Client divers », selon le plan comptable de la société. Ce nom sert la
# comptabilité, pas le client : sur le ticket remis en station, JNP veut un
# simple tiret, qui laisse la place à une inscription manuscrite.
#
# La fiche Odoo n'est pas renommée : seul l'affichage change.

# Libellés reconnus comme comptes collectifs, en minuscules.
NOMS_COMPTE_COLLECTIF = {
    "comptant", "client comptant", "client divers", "client anonyme",
    "divers", "anonyme",
}


def libelle_client_anonyme() -> str:
    """
    Ce qui s'affiche à la place du nom sur une vente anonyme.

    Lu à chaque appel plutôt qu'à l'import : une variable d'environnement
    changée après démarrage doit prendre effet sans redéployer.
    """
    import os
    return os.getenv("POS_ANONYMOUS_CUSTOMER_LABEL", "-")


def est_client_generique(nom: str | None) -> bool:
    """Le nom donné est-il celui d'un compte collectif plutôt qu'un client ?"""
    if not nom:
        return True
    return " ".join(str(nom).split()).lower() in NOMS_COMPTE_COLLECTIF


def nom_client_affiche(nom: str | None, generique: bool | None = None) -> str:
    """
    Nom du client tel qu'il doit figurer sur la facture.

    `generique` permet à l'appelant qui connaît déjà le compte collectif de
    la société — par son identifiant, plus fiable qu'un libellé — d'imposer
    la réponse. Sans lui, la décision se prend sur le nom.
    """
    if generique is None:
        generique = est_client_generique(nom)
    return libelle_client_anonyme() if generique else nom
