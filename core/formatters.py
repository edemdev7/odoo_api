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
