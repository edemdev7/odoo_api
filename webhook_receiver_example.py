"""
Exemple d'endpoint webhook pour recevoir les notifications de recharge

Ce fichier montre comment créer un endpoint qui reçoit les webhooks
envoyés par le fuel monitor.

Usage:
    python webhook_receiver_example.py
    
Puis testez avec:
    curl -X POST "http://localhost:3000/api/webhook/fuel-recharge" \
      -H "Content-Type: application/json" \
      -d '{"action":"COMPANY_RECHARGE","companyExternalId":"123","amount":50000}'
"""

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field
import uvicorn
import logging
from datetime import datetime

# Configuration du logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Création de l'application
app = FastAPI(title="Webhook Receiver Example")


class FuelRechargeWebhook(BaseModel):
    """Modèle du webhook reçu"""
    action: str = Field(..., description="Action (toujours COMPANY_RECHARGE)")
    companyExternalId: str = Field(..., description="ID Odoo de l'entreprise")
    amount: float = Field(..., description="Montant ajouté")


@app.post("/api/webhook/fuel-recharge")
async def receive_fuel_recharge(webhook: FuelRechargeWebhook, request: Request):
    """
    Endpoint qui reçoit les notifications de recharge de compte fuel
    
    Body attendu:
    {
        "action": "COMPANY_RECHARGE",
        "companyExternalId": "123",
        "amount": 50000.0
    }
    """
    try:
        logger.info("=" * 60)
        logger.info("🔔 WEBHOOK REÇU - Recharge de compte fuel")
        logger.info(f"   Timestamp: {datetime.now().isoformat()}")
        logger.info(f"   Client IP: {request.client.host}")
        logger.info("-" * 60)
        logger.info(f"   Action: {webhook.action}")
        logger.info(f"   Entreprise ID: {webhook.companyExternalId}")
        logger.info(f"   Montant: {webhook.amount} CFA")
        logger.info("=" * 60)
        
        # ====================================
        # VOTRE LOGIQUE MÉTIER ICI
        # ====================================
        
        # Exemple 1: Mettre à jour votre base de données
        # await update_company_balance(webhook.companyExternalId, webhook.amount)
        
        # Exemple 2: Envoyer une notification au client
        # await send_notification_to_client(
        #     company_id=webhook.companyExternalId,
        #     message=f"Votre compte a été crédité de {webhook.amount} CFA"
        # )
        
        # Exemple 3: Créer une transaction dans votre système
        # transaction = await create_transaction(
        #     company_id=webhook.companyExternalId,
        #     type="CREDIT",
        #     amount=webhook.amount,
        #     source="ODOO_FUEL_MONITOR"
        # )
        
        # Exemple 4: Déclencher d'autres actions métier
        # if webhook.amount > 100000:
        #     await notify_accounting_team(webhook)
        
        logger.info("✅ Webhook traité avec succès")
        
        return {
            "success": True,
            "message": "Webhook reçu et traité",
            "received_at": datetime.now().isoformat(),
            "data": {
                "company_id": webhook.companyExternalId,
                "amount_credited": webhook.amount
            }
        }
        
    except Exception as e:
        logger.error(f"❌ Erreur lors du traitement du webhook: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Erreur lors du traitement: {str(e)}"
        )


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "service": "Webhook Receiver",
        "timestamp": datetime.now().isoformat()
    }


@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "service": "Webhook Receiver Example",
        "endpoints": {
            "webhook": "/api/webhook/fuel-recharge",
            "health": "/health"
        },
        "documentation": "/docs"
    }


if __name__ == "__main__":
    logger.info("🚀 Démarrage du serveur webhook receiver")
    logger.info("   Endpoint: http://localhost:3000/api/webhook/fuel-recharge")
    logger.info("   Documentation: http://localhost:3000/docs")
    
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=3000,
        log_level="info"
    )
