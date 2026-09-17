from fastapi import APIRouter
from datetime import datetime

from core.odoo_client import default_odoo_client
from core.config import logger

router = APIRouter(tags=["Système"])

@router.get("/health")
async def health_check():
    """
    Vérification de l'état de l'API
    
    Cette API permet de vérifier si le service est opérationnel et si la connexion à Odoo fonctionne.
    Utile pour les systèmes de monitoring et les vérifications de disponibilité.
    
    Returns:
    - **status**: État de santé de l'API ("healthy" ou "unhealthy")
    - **odoo_connection**: État de la connexion à Odoo ("ok" ou "error")
    - **timestamp**: Horodatage de la vérification au format ISO
    - **version**: Version de l'API
    - **error**: Message d'erreur (uniquement en cas d'échec)
    
    Note: Cet endpoint est public et ne nécessite pas d'authentification
    """
    try:
        # Test de connexion Odoo avec le client par défaut
        version = default_odoo_client.execute_kw('ir.module.module', 'search_count', [[]])
        
        return {
            "status": "healthy",
            "odoo_connection": "ok",
            "timestamp": datetime.utcnow().isoformat(),
            "version": "1.0.0"
        }
    except Exception as e:
        logger.error(f"Erreur lors de la vérification de santé: {e}")
        return {
            "status": "unhealthy",
            "odoo_connection": "error",
            "error": str(e),
            "timestamp": datetime.utcnow().isoformat(),
            "version": "1.0.0"
        }

@router.get("/")
async def root():
    """
    Page d'accueil de l'API
    
    Cette API fournit des informations de base sur le service et des liens vers la documentation.
    
    Returns:
    - **message**: Nom du service
    - **version**: Version de l'API
    - **docs**: Lien vers la documentation Swagger UI
    - **redoc**: Lien vers la documentation ReDoc
    - **health**: Lien vers le endpoint de vérification de santé
    
    Note: Cet endpoint est public et ne nécessite pas d'authentification
    """
    return {
        "message": "Odoo API Gateway",
        "version": "1.0.0",
        "docs": "/docs",
        "redoc": "/redoc",
        "health": "/health"
    }
