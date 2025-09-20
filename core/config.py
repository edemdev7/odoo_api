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
ACCESS_TOKEN_EXPIRE_MINUTES = 30

# Configuration Odoo
ODOO_CONFIG = {
    "url": os.getenv("ODOO_URL", "https://erp.jnpgroupe.com"),
    "db": os.getenv("ODOO_DB", "OMHI-TEST"),
    "username": os.getenv("ODOO_USERNAME", "admin@jnpgroupe.com"),
    "api_key": os.getenv("ODOO_API_KEY", "33e3aa2baad77fc78418d2747d6b0c5616d5dcb6")
}

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
