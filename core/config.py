import os
from dotenv import load_dotenv
import logging

# Charger les variables d'environnement
load_dotenv()

# Configuration du logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Configuration de sécurité
SECRET_KEY = os.getenv("JWT_SECRET_KEY", "your-super-secret-key-change-in-production")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 480  # 8 heures

# Liste des tokens invalidés/révoqués
REVOKED_TOKENS = set()

# Session active par utilisateur (user_key -> token courant)
# Permet d'empêcher les connexions simultanées et d'invalider l'ancienne
# session lorsqu'une nouvelle connexion (ou un changement de PIN/mot de
# passe) a lieu sur le même compte.
ACTIVE_SESSIONS = {}

# Configuration Odoo - Multi-base de données
#
# Aucune valeur par défaut : identifiants et clés viennent exclusivement du
# `.env`, dont le modèle est `.env.example`. Les valeurs étaient autrefois
# écrites ici, ce qui les exposait à quiconque lisait le dépôt — et les
# laissait dans l'historique Git même après correction.
#
# Une variable manquante fait échouer le démarrage, avec le nom de la
# variable en cause : mieux vaut un refus net qu'une connexion silencieuse
# à la mauvaise base.

def _config_odoo(prefixe: str, nom: str, transfer_type: str,
                 transfer_type_code: str) -> dict:
    valeurs = {
        "url": os.getenv(f"{prefixe}_URL", ""),
        "db": os.getenv(f"{prefixe}_NAME", ""),
        "username": os.getenv(f"{prefixe}_USERNAME", ""),
        "api_key": os.getenv(f"{prefixe}_API_KEY", ""),
    }
    manquantes = [f"{prefixe}_{suffixe}" for suffixe, valeur in
                  (("URL", valeurs["url"]), ("NAME", valeurs["db"]),
                   ("USERNAME", valeurs["username"]), ("API_KEY", valeurs["api_key"]))
                  if not valeur.strip()]
    if manquantes:
        raise RuntimeError(
            f"Configuration Odoo « {nom} » incomplète : "
            f"{', '.join(manquantes)} absente(s) du .env."
        )
    return {"name": nom, **valeurs,
            "transfer_type": transfer_type,
            "transfer_type_code": transfer_type_code}


# DB1: JNP Directe (transferts internes)
ODOO_DB1_CONFIG = _config_odoo("ODOO_DB1", "jnp_directe", "internal", "internal")

# DB2: Franchise (transferts réceptions)
ODOO_DB2_CONFIG = _config_odoo("ODOO_DB2", "franchise", "reception", "incoming")

# Normalisation des identifiants de connexion.
#
# Une espace ou un retour à la ligne en tête de valeur suffit à rendre une base
# injoignable, et le symptôme est trompeur : la connexion échoue avec un message
# de serveur indisponible, sans que rien ne signale la cause réelle. C'est
# arrivé sur l'URL de la base franchise, qui portait une espace initiale.
for _config in (ODOO_DB1_CONFIG, ODOO_DB2_CONFIG):
    for _cle in ("url", "db", "username", "api_key"):
        if isinstance(_config.get(_cle), str):
            _config[_cle] = _config[_cle].strip()

# Liste des configurations Odoo (ordre de priorité pour l'authentification)
ODOO_DATABASES = [ODOO_DB1_CONFIG, ODOO_DB2_CONFIG]

# Configuration par défaut (pour compatibilité avec l'ancien code)
ODOO_CONFIG = ODOO_DB1_CONFIG

# Utilisateurs API (en production, utilisez une vraie base de données)
API_USERS = {
    "admin": {
        "username": "admin",
        "hashed_password": "$2b$12$Ve.p30uPHQSVt2PBRTJU4.o37W2sD9vq7SMoR1UQJ4BkWb5/nsqVm",  # "admin123"
        "is_active": True,
        "scopes": ["read", "write", "delete"]
    },
    "readonly": {
        "username": "readonly", 
        "hashed_password": "$2b$12$KpqzDOHWwGPgX0hLDcLKBOHm8JoQs7kB9aL5pF9VqKcwG2LYmK5MG",  # "readonly123"
        "is_active": True,
        "scopes": ["read"]
    },
    "admin@jnpgroupe.com": {
        "username": "admin@jnpgroupe.com",
        "hashed_password": "$2b$12$M6olJi2HJk/MCApZHJkKx.oJPo50QkKz6.QVtW2brH/CCdh31HJSe",  # "zBfMQyOlYVkg8WB"
        "is_active": True,
        "scopes": ["read", "write", "delete"]
    }
}
