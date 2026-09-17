from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
import json
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
from api.fuel_monitor import router as fuel_monitor_router
from api.accounting import router as accounting_router
from core.config import logger
from core.background_scheduler import start_credit_monitor, stop_credit_monitor
from core.formatters import clean_numbers


class NumberFormatterMiddleware(BaseHTTPMiddleware):
    """
    Formate tous les floats des réponses JSON :
    - Max 3 décimales, zéros supprimés
    - Séparateur décimal : virgule  (ex: 2,45 au lieu de 2.45)
    """

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)

        content_type = response.headers.get("content-type", "")
        if "application/json" not in content_type:
            return response

        # Lire le corps de la réponse
        body = b""
        async for chunk in response.body_iterator:
            body += chunk

        try:
            data = json.loads(body)
            cleaned = clean_numbers(data)
            headers = dict(response.headers)
            headers.pop("content-length", None)
            return JSONResponse(
                content=cleaned,
                status_code=response.status_code,
                headers=headers,
            )
        except Exception:
            # En cas d'erreur de parsing, retourner la réponse originale
            from starlette.responses import Response
            headers = dict(response.headers)
            headers.pop("content-length", None)
            return Response(
                content=body,
                status_code=response.status_code,
                headers=headers,
            )

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
            "name": "Fuel Account Monitor",
            "description": "Surveillance des comptes fuel et webhooks de recharge"
        },
        {
            "name": "Accounting",
            "description": "Gestion des écritures comptables (endpoints sécurisés par encryption)"
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

# Middleware formatage des nombres (virgule, 3 décimales max)
app.add_middleware(NumberFormatterMiddleware)

# Inclusion des routers
app.include_router(auth_router)
app.include_router(pos_router)
app.include_router(odoo_router)
app.include_router(utils_router)
app.include_router(fuel_monitor_router)
app.include_router(accounting_router)


# Events de démarrage et arrêt
@app.on_event("startup")
async def startup_event():
    """Démarrage de l'application"""
    logger.info("🚀 Application Odoo API Gateway démarrée")
    logger.info("🔄 Démarrage de la surveillance automatique des crédits...")
    await start_credit_monitor()


@app.on_event("shutdown")
async def shutdown_event():
    """Arrêt de l'application"""
    logger.info("🛑 Arrêt de l'application...")
    await stop_credit_monitor()


logger.info("Application Odoo API Gateway configurée")

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8001)
