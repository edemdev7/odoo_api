"""
Module de surveillance des comptes fuel (crédit client)

Détecte les changements du champ 'credit' dans res.partner
et notifie un endpoint externe via webhook
"""

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta
import logging
import httpx
import os
from pydantic import BaseModel, Field

from core.security import require_scope
from core.odoo_client import get_odoo_client
from core.webhook_sender import send_encrypted_webhook
from models.responses import ApiResponse
from core.background_scheduler import get_scheduler

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/fuel-monitor", tags=["Fuel Account Monitor"])

# Configuration du webhook depuis les variables d'environnement
WEBHOOK_URL = os.getenv("FUEL_WEBHOOK_URL", "https://api-jnp-dev.opensi.co/public/odoo/webhook")
# Optional staging webhook URL - if set we will call both dev and staging
WEBHOOK_URL_STG = os.getenv("FUEL_WEBHOOK_URL_STG", None)  # e.g. https://api-jnp-stg.opensi.co/public/odoo/webhook
WEBHOOK_TIMEOUT = int(os.getenv("FUEL_WEBHOOK_TIMEOUT", "10"))

# Cache pour suivre les valeurs précédentes de credit
# Format: {partner_id: {'credit': float, 'last_check': datetime}}
credit_cache: Dict[int, Dict[str, Any]] = {}


class CompanyRechargeWebhook(BaseModel):
    """Modèle pour le webhook de recharge entreprise"""
    action: str = Field(default="COMPANY_RECHARGE", description="Action à effectuer")
    companyExternalId: str = Field(..., description="ID de l'entreprise dans Odoo")
    amount: float = Field(..., description="Montant ajouté au crédit")


class MonitorConfig(BaseModel):
    """Configuration de surveillance"""
    partner_ids: Optional[List[int]] = Field(None, description="IDs des partenaires à surveiller (None = tous)")
    check_interval_seconds: int = Field(60, description="Intervalle de vérification en secondes")
    webhook_url: str = Field(..., description="URL du webhook à appeler")


@router.get("/check-credit-changes", response_model=ApiResponse)
async def check_credit_changes(
    partner_id: Optional[int] = None,
    since_minutes: int = 5,
    background_tasks: BackgroundTasks = None,
    current_user: dict = Depends(require_scope("pos"))
):
    """
    Vérifier les changements récents du champ 'credit' (créances client)
    
    Compare les valeurs actuelles avec le cache pour détecter les augmentations.
    Si une augmentation est détectée, envoie un webhook.
    
    **Paramètres:**
    - **partner_id**: ID du partenaire spécifique (optionnel, sinon tous les clients)
    - **since_minutes**: Chercher les changements dans les X dernières minutes
    
    **Retourne:**
    - Liste des changements détectés avec montants
    """
    try:
        client = get_odoo_client(current_user)
        
        # Construire le domaine de recherche
        domain = [
            ('is_company', '=', True),
            ('customer_rank', '>', 0),  # Uniquement les clients
            ('active', '=', True)
        ]
        
        if partner_id:
            domain.append(('id', '=', partner_id))
        
        # Récupérer les partenaires avec leur crédit actuel
        partners = client.execute_kw(
            'res.partner',
            'search_read',
            [domain],
            {
                'fields': ['id', 'name', 'credit', 'credit_limit', 'vat', 'ref'],
                'order': 'write_date desc'
            }
        )
        
        changes_detected = []
        
        for partner in partners:
            partner_id = partner['id']
            current_credit = float(partner.get('credit', 0) or 0)
            partner_name = partner.get('name', 'Inconnu')
            
            # Vérifier si on a une valeur en cache
            if partner_id in credit_cache:
                previous_credit = credit_cache[partner_id]['credit']
                
                # Calculer la différence
                credit_increase = current_credit - previous_credit
                
                # Si le crédit a augmenté (nouveau paiement)
                if credit_increase > 0.01:  # Tolérance de 0.01 pour les arrondis
                    change_info = {
                        'partner_id': partner_id,
                        'partner_name': partner_name,
                        'vat': partner.get('vat', ''),
                        'ref': partner.get('ref', ''),
                        'previous_credit': previous_credit,
                        'current_credit': current_credit,
                        'amount_added': credit_increase,
                        'detected_at': datetime.now().isoformat()
                    }
                    
                    changes_detected.append(change_info)
                    
                    logger.info(
                        f"💰 Crédit augmenté détecté: {partner_name} (ID: {partner_id}) "
                        f"- Ancien: {previous_credit}, Nouveau: {current_credit}, "
                        f"Différence: +{credit_increase}"
                    )
                    
                    # Envoyer le webhook en arrière-plan
                    if background_tasks:
                        background_tasks.add_task(
                            send_recharge_webhook,
                            partner_id=str(partner_id),
                            amount=credit_increase
                        )
            
            # Mettre à jour le cache
            credit_cache[partner_id] = {
                'credit': current_credit,
                'last_check': datetime.now()
            }
        
        return ApiResponse(
            success=True,
            data={
                'changes_detected': changes_detected,
                'total_partners_checked': len(partners),
                'cache_size': len(credit_cache)
            },
            count=len(changes_detected),
            message=f"{len(changes_detected)} changement(s) de crédit détecté(s)"
        )
        
    except Exception as e:
        logger.error(f"Erreur lors de la vérification des crédits: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Erreur lors de la vérification: {str(e)}"
        )


async def send_recharge_webhook(partner_id: str, amount: float):
    """
    Envoyer le webhook de notification de recharge
    
    Les données sont encryptées avec RSA avant l'envoi.
    
    **Body envoyé:**
    ```
    Header: x-encrypted-data
    Value: <données encryptées en base64>
    ```
    
    **Données encryptées (JSON):**
    ```json
    {
        "action": "COMPANY_RECHARGE",
        "companyExternalId": "123",
        "amount": 50000.0
    }
    {
    {
        "action": "COMPANY_SUPPLY_VALIDATION",
        "supplyId": "string",
        "invoiceId": "string"
    }
    }    
    ```
    """
    try:
        # Préparer les données
        webhook_data = {
            "action": "COMPANY_RECHARGE",
            "companyExternalId": partner_id,
            "amount": amount
        }
        
        logger.info(f"📤 Préparation webhook pour partner {partner_id}")
        logger.info(f"   Montant: {amount} CFA")
        
        # Build list of URLs to call (dev + optional staging)
        urls = [WEBHOOK_URL]
        if WEBHOOK_URL_STG and WEBHOOK_URL_STG != WEBHOOK_URL:
            urls.append(WEBHOOK_URL_STG)

        logger.info(f"📤 Envoi webhook vers {len(urls)} endpoint(s): {urls}")

        # Use shared helper to encrypt once and post to all endpoints in parallel
        try:
            results = await send_encrypted_webhook(urls, webhook_data, timeout=WEBHOOK_TIMEOUT)
            # results are logged by the helper; we can optionally do extra checks here
            for url, status, info in results:
                if status not in (200, 201, 204):
                    logger.warning(f"[FUEL_MONITOR] Non-OK response from {url}: {status} - {info}")
        except Exception as e:
            logger.error(f"❌ Erreur lors de l'envoi des webhooks: {e}")
                
    except httpx.TimeoutException:
        logger.error(f"⏱️ Timeout lors de l'envoi du webhook vers {WEBHOOK_URL}")
    except Exception as e:
        logger.error(f"❌ Erreur lors de l'envoi du webhook: {e}")


@router.post("/initialize-cache", response_model=ApiResponse)
async def initialize_credit_cache(
    partner_ids: Optional[List[int]] = None,
    current_user: dict = Depends(require_scope("pos"))
):
    """
    Initialiser le cache avec les valeurs actuelles de crédit
    
    À appeler au démarrage ou pour réinitialiser la surveillance.
    
    **Paramètres:**
    - **partner_ids**: Liste des IDs à surveiller (optionnel, sinon tous les clients)
    """
    try:
        client = get_odoo_client(current_user)
        
        domain = [
            ('is_company', '=', True),
            ('customer_rank', '>', 0),
            ('active', '=', True)
        ]
        
        if partner_ids:
            domain.append(('id', 'in', partner_ids))
        
        # Récupérer tous les clients
        partners = client.execute_kw(
            'res.partner',
            'search_read',
            [domain],
            {
                'fields': ['id', 'name', 'credit'],
                'order': 'id asc'
            }
        )
        
        # Initialiser le cache
        global credit_cache
        credit_cache = {}
        
        for partner in partners:
            partner_id = partner['id']
            current_credit = float(partner.get('credit', 0) or 0)
            
            credit_cache[partner_id] = {
                'credit': current_credit,
                'last_check': datetime.now()
            }
        
        logger.info(f"✅ Cache initialisé avec {len(credit_cache)} partenaires")
        
        return ApiResponse(
            success=True,
            data={
                'cache_size': len(credit_cache),
                'partners_tracked': [
                    {'id': p['id'], 'name': p['name'], 'credit': p['credit']}
                    for p in partners[:10]  # Afficher les 10 premiers
                ]
            },
            count=len(credit_cache),
            message=f"Cache initialisé avec {len(credit_cache)} partenaires"
        )
        
    except Exception as e:
        logger.error(f"Erreur lors de l'initialisation du cache: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Erreur lors de l'initialisation: {str(e)}"
        )


@router.get("/cache-status", response_model=ApiResponse)
async def get_cache_status(
    current_user: dict = Depends(require_scope("pos"))
):
    """
    Afficher l'état actuel du cache de surveillance
    """
    try:
        cache_data = []
        
        for partner_id, data in credit_cache.items():
            cache_data.append({
                'partner_id': partner_id,
                'credit': data['credit'],
                'last_check': data['last_check'].isoformat()
            })
        
        return ApiResponse(
            success=True,
            data={
                'cache_size': len(credit_cache),
                'cached_partners': cache_data[:20],  # Limiter à 20 pour l'affichage
                'webhook_url': WEBHOOK_URL
            },
            count=len(credit_cache),
            message=f"{len(credit_cache)} partenaires en surveillance"
        )
        
    except Exception as e:
        logger.error(f"Erreur lors de la récupération du cache: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Erreur lors de la récupération: {str(e)}"
        )


@router.post("/manual-trigger", response_model=ApiResponse)
async def manual_trigger_webhook(
    partner_id: int,
    amount: float,
    background_tasks: BackgroundTasks,
    current_user: dict = Depends(require_scope("pos"))
):
    """
    Déclencher manuellement un webhook de recharge
    
    Utile pour tester le système sans attendre un vrai changement de crédit.
    """
    try:
        # Vérifier que le partenaire existe
        client = get_odoo_client(current_user)
        
        partner = client.execute_kw(
            'res.partner',
            'read',
            [partner_id],
            {'fields': ['id', 'name', 'credit']}
        )
        
        if not partner:
            raise HTTPException(status_code=404, detail="Partenaire non trouvé")
        
        # Envoyer le webhook
        background_tasks.add_task(
            send_recharge_webhook,
            partner_id=str(partner_id),
            amount=amount
        )
        
        return ApiResponse(
            success=True,
            data={
                'partner_id': partner_id,
                'partner_name': partner[0]['name'],
                'amount': amount,
                'webhook_url': WEBHOOK_URL
            },
            message=f"Webhook déclenché manuellement pour {partner[0]['name']}"
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Erreur lors du déclenchement manuel: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Erreur: {str(e)}"
        )


@router.put("/configure-webhook", response_model=ApiResponse)
async def configure_webhook_url(
    webhook_url: str,
    current_user: dict = Depends(require_scope("pos"))
):
    """
    Configurer l'URL du webhook à appeler
    """
    try:
        global WEBHOOK_URL
        WEBHOOK_URL = webhook_url
        
        logger.info(f"✅ URL du webhook configurée: {WEBHOOK_URL}")
        
        return ApiResponse(
            success=True,
            data={'webhook_url': WEBHOOK_URL},
            message="URL du webhook configurée avec succès"
        )
        
    except Exception as e:
        logger.error(f"Erreur lors de la configuration: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Erreur: {str(e)}"
        )


@router.delete("/cache/clear", response_model=ApiResponse)
async def clear_cache(
    partner_id: Optional[int] = None,
    current_user: dict = Depends(require_scope("pos"))
):
    """
    Vider le cache de crédit
    
    **Paramètres:**
    - **partner_id**: ID du partenaire spécifique (optionnel, sinon tout le cache)
    
    **Retourne:**
    - Confirmation du vidage du cache
    """
    try:
        global credit_cache
        
        if partner_id:
            # Vider uniquement pour un partenaire spécifique
            if partner_id in credit_cache:
                del credit_cache[partner_id]
                logger.info(f"🗑️  Cache vidé pour partner_id: {partner_id}")
                message = f"Cache vidé pour le partenaire {partner_id}"
            else:
                message = f"Aucun cache trouvé pour le partenaire {partner_id}"
        else:
            # Vider tout le cache
            cache_size = len(credit_cache)
            credit_cache = {}
            logger.info(f"🗑️  Cache complet vidé ({cache_size} entrées)")
            message = f"Cache complet vidé ({cache_size} entrées)"
        
        return ApiResponse(
            success=True,
            data={
                'cache_size': len(credit_cache),
                'partner_id_cleared': partner_id
            },
            message=message
        )
        
    except Exception as e:
        logger.error(f"Erreur lors du vidage du cache: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Erreur: {str(e)}"
        )


@router.get("/cache/status", response_model=ApiResponse)
async def get_cache_status(
    current_user: dict = Depends(require_scope("pos"))
):
    """
    Obtenir le statut du cache
    
    **Retourne:**
    - Informations sur le cache actuel
    """
    try:
        cache_info = []
        
        for partner_id, info in credit_cache.items():
            cache_info.append({
                'partner_id': partner_id,
                'credit': info.get('credit'),
                'last_check': info.get('last_check').isoformat() if info.get('last_check') else None
            })
        
        return ApiResponse(
            success=True,
            data={
                'cache_size': len(credit_cache),
                'entries': cache_info
            },
            count=len(credit_cache),
            message=f"Cache contient {len(credit_cache)} entrée(s)"
        )
        
    except Exception as e:
        logger.error(f"Erreur lors de la récupération du statut du cache: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Erreur: {str(e)}"
        )


@router.get("/scheduler/status", response_model=ApiResponse)
async def get_scheduler_status(
    current_user: dict = Depends(require_scope("pos"))
):
    """
    Obtenir le statut du scheduler de surveillance automatique
    
    **Retourne:**
    - État du scheduler (actif/inactif)
    - Nombre d'entrées dans le cache
    - Configuration actuelle
    """
    try:
        scheduler = get_scheduler()
        
        return ApiResponse(
            success=True,
            data={
                'is_running': scheduler.is_running,
                'cache_size': len(scheduler.cache),
                'webhook_url': WEBHOOK_URL,
                'check_interval_seconds': os.getenv("CREDIT_CHECK_INTERVAL", "60")
            },
            message=f"Scheduler {'actif' if scheduler.is_running else 'inactif'}"
        )
        
    except Exception as e:
        logger.error(f"Erreur lors de la récupération du statut: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Erreur: {str(e)}"
        )


@router.post("/scheduler/start", response_model=ApiResponse)
async def start_scheduler_manually(
    current_user: dict = Depends(require_scope("pos"))
):
    """
    Démarrer manuellement le scheduler de surveillance
    
    **Note:** Le scheduler se lance normalement automatiquement au démarrage de l'application.
    Utilisez cette route uniquement si vous l'avez arrêté manuellement.
    """
    try:
        scheduler = get_scheduler()
        
        if scheduler.is_running:
            return ApiResponse(
                success=True,
                message="Le scheduler est déjà en cours d'exécution"
            )
        
        scheduler.start()
        
        return ApiResponse(
            success=True,
            message="Scheduler de surveillance démarré avec succès"
        )
        
    except Exception as e:
        logger.error(f"Erreur lors du démarrage du scheduler: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Erreur: {str(e)}"
        )


@router.post("/scheduler/stop", response_model=ApiResponse)
async def stop_scheduler_manually(
    current_user: dict = Depends(require_scope("pos"))
):
    """
    Arrêter manuellement le scheduler de surveillance
    
    **Attention:** Cela désactive la surveillance automatique des crédits.
    Les webhooks ne seront plus envoyés automatiquement.
    """
    try:
        scheduler = get_scheduler()
        
        if not scheduler.is_running:
            return ApiResponse(
                success=True,
                message="Le scheduler est déjà arrêté"
            )
        
        scheduler.stop()
        
        return ApiResponse(
            success=True,
            message="Scheduler de surveillance arrêté"
        )
        
    except Exception as e:
        logger.error(f"Erreur lors de l'arrêt du scheduler: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Erreur: {str(e)}"
        )


@router.post("/scheduler/check-now", response_model=ApiResponse)
async def trigger_check_now(
    current_user: dict = Depends(require_scope("pos"))
):
    """
    Déclencher manuellement une vérification immédiate des crédits
    
    Cette route force une vérification immédiate sans attendre le prochain cycle du scheduler.
    Utile pour tester ou forcer une vérification après une opération spécifique.
    """
    try:
        scheduler = get_scheduler()
        
        # Lancer une vérification immédiate en arrière-plan
        import asyncio
        asyncio.create_task(scheduler.check_credits_once())
        
        return ApiResponse(
            success=True,
            message="Vérification des crédits déclenchée"
        )
        
    except Exception as e:
        logger.error(f"Erreur lors du déclenchement de la vérification: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Erreur: {str(e)}"
        )

