from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
import importlib
import os
import sys

# Ajout du chemin courant au PYTHONPATH
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Import des routers
from api.auth import router as auth_router
from api.pos import router as pos_router
from api.odoo import router as odoo_router
from api.utils import router as utils_router
from core.config import logger

# Configuration et création de l'application FastAPI
app = FastAPI(
    title="Odoo API Gateway",
    description="API REST sécurisée pour intégration avec Odoo",
    version="1.0.0",
    docs_url="/docs",  # URL pour Swagger UI
    redoc_url="/redoc",  # URL pour ReDoc
    openapi_tags=[
        {
            "name": "Authentification",
            "description": "Opérations liées à l'authentification (login, PIN, etc.)"
        },
        {
            "name": "Point de Vente",
            "description": "Opérations liées au point de vente (produits, commandes)"
        },
        {
            "name": "Odoo - Public",
            "description": "Endpoints Odoo accessibles sans authentification"
        },
        {
            "name": "Odoo - Lecture",
            "description": "Opérations de lecture des données Odoo"
        },
        {
            "name": "Odoo - Écriture",
            "description": "Opérations de création et mise à jour des données Odoo"
        },
        {
            "name": "Odoo - Suppression",
            "description": "Opérations de suppression des données Odoo"
        },
        {
            "name": "Odoo - Utilitaires",
            "description": "Utilitaires et informations sur les modèles Odoo"
        },
        {
            "name": "Système",
            "description": "Endpoints système (état, versions, etc.)"
        }
    ]
)

# Middleware CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # À restreindre en production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Inclusion des routers
app.include_router(auth_router)
app.include_router(pos_router)
app.include_router(odoo_router)
app.include_router(utils_router)

logger.info("Application Odoo API Gateway démarrée")

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8001)
