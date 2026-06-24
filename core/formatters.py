"""
Formatage des nombres dans les réponses API.

Règles :
- Max 3 décimales
- Zéros inutiles supprimés  (3373573.0 → "3373573", 1.100 → "1,1")
- Séparateur décimal : virgule  (2.45 → "2,45")

Exemples :
    297.87999999999  → "297,88"
    3373573.0        → "3373573"
    2.45             → "2,45"
    0.0              → "0"
    1.500            → "1,5"
"""


def format_number(value: float) -> str:
    """Formate un float selon les règles métier."""
    rounded = round(value, 3)
    # f-string à 3 décimales puis strip des zéros trailing
    formatted = f"{rounded:.3f}".rstrip("0").rstrip(".")
    return formatted.replace(".", ",")


def clean_numbers(obj):
    """
    Parcourt récursivement un dict/list et remplace chaque float
    par sa représentation formatée (str).
    Les int, str, bool et None ne sont pas touchés.
    """
    if isinstance(obj, dict):
        return {k: clean_numbers(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [clean_numbers(item) for item in obj]
    if isinstance(obj, float):
        return format_number(obj)
    return obj
