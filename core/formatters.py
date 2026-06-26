"""
Formatage des nombres dans les réponses API.

Règles :
- Max 3 décimales, zéros inutiles supprimés  (3373573.0 → "3373573", 1.100 → "1,1")
- Séparateur décimal : virgule  (2.45 → "2,45")

Exemples :
    297.87999999999  → "297,88"
    3373573.0        → "3373573"
    2.45             → "2,45"
    0.0              → "0"
    1.500            → "1,5"

Certaines clés doivent rester des nombres (pas de conversion en string) car elles
sont utilisées programmatiquement côté client : voir NUMBER_KEYS.
"""

# Clés dont la valeur doit rester un float arrondi (pas converti en string)
NUMBER_KEYS = {
    "balance",
    "amount_total",
    "amount_paid",
    "amount_due",
    "amount_return",
    "amount_tax",
    "amount_residual",
    "credit",
    "debit",
    "credit_limit",
    "qty",
    "qty_available",
    "quantity",
    "stock_quantity",
}


def format_number(value: float) -> str:
    """Formate un float en string avec virgule et max 3 décimales."""
    rounded = round(value, 3)
    formatted = f"{rounded:.3f}".rstrip("0").rstrip(".")
    return formatted.replace(".", ",")


def round_number(value: float) -> float:
    """Arrondit un float à 3 décimales max (reste un number)."""
    return round(value, 3)


def clean_numbers(obj, parent_key: str = ""):
    """
    Parcourt récursivement un dict/list et formate chaque float :
    - Si la clé est dans NUMBER_KEYS → arrondi mais reste un float
    - Sinon → converti en string avec virgule
    Les int, str, bool et None ne sont pas touchés.
    """
    if isinstance(obj, dict):
        return {
            k: clean_numbers(v, parent_key=k)
            for k, v in obj.items()
        }
    if isinstance(obj, list):
        return [clean_numbers(item, parent_key=parent_key) for item in obj]
    if isinstance(obj, float):
        if parent_key in NUMBER_KEYS:
            return round_number(obj)
        return format_number(obj)
    return obj
