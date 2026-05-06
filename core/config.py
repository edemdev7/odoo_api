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

# Configuration Odoo - Multi-base de données
# DB1: Base Test JNP Directe (Transferts internes)
ODOO_DB1_CONFIG = {
    "name": "jnp_directe",
    "url": os.getenv("ODOO_DB1_URL", "https://holdingithiel-dagbehami-test-30012085.dev.odoo.com"),
    "db": os.getenv("ODOO_DB1_NAME", "holdingithiel-dagbehami-test-30012085"),
    "username": os.getenv("ODOO_DB1_USERNAME", "api@jnpgroupe.com"),
    "api_key": os.getenv("ODOO_DB1_API_KEY", "a9be048e3bf796ebcece7b47a8f64f7ee60f343c"),
    "transfer_type": "internal",  # Transferts internes
    "transfer_type_code": "internal"
}

# DB2: Base Test Franchise (Transferts réceptions)
ODOO_DB2_CONFIG = {
    "name": "franchise",
    "url": os.getenv("ODOO_DB2_URL", "https://staging-apps.perfect-erp.com"),
    "db": os.getenv("ODOO_DB2_NAME", "staging-apps.perfect-erp.com"),
    "username": os.getenv("ODOO_DB2_USERNAME", "api@odoo.com"),
    "api_key": os.getenv("ODOO_DB2_API_KEY", "1ba8793e151954c349bf8511fd2bfee068338205"),
    "transfer_type": "reception",  # Transferts réceptions
    "transfer_type_code": "incoming"
}

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
