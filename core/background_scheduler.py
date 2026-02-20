"""
Scheduler en arrière-plan pour la surveillance automatique des crédits

Ce module démarre automatiquement avec FastAPI et vérifie périodiquement
les changements de crédit des clients.
"""

import asyncio
import logging
from datetime import datetime
from typing import Dict, Any
import httpx

from core.odoo_client import OdooClient
from core.encryption import encrypt_webhook_data
import os

logger = logging.getLogger(__name__)

# Configuration
WEBHOOK_URL = os.getenv("FUEL_WEBHOOK_URL", "https://api-jnp-dev.opensi.co/public/odoo/webhook")
CHECK_INTERVAL = int(os.getenv("CREDIT_CHECK_INTERVAL", "60"))  # 60 secondes par défaut
WEBHOOK_TIMEOUT = int(os.getenv("FUEL_WEBHOOK_TIMEOUT", "10"))

# Cache global pour suivre les crédits
credit_monitor_cache: Dict[int, Dict[str, Any]] = {}

# Flag pour contrôler le scheduler
scheduler_running = False
scheduler_task = None


class CreditMonitorScheduler:
    """Scheduler pour surveiller automatiquement les crédits"""
    
    def __init__(self):
        self.is_running = False
        self.task = None
        self.cache: Dict[int, Dict[str, Any]] = {}
        
    async def check_credits_once(self):
        """Vérifier les crédits une seule fois"""
        try:
            # Connexion Odoo avec les credentials par défaut
            odoo_url = os.getenv("ODOO_URL")
            odoo_db = os.getenv("ODOO_DB")
            odoo_username = os.getenv("ODOO_USERNAME")
            odoo_password = os.getenv("ODOO_PASSWORD")
            
            if not all([odoo_url, odoo_db, odoo_username, odoo_password]):
                logger.warning("⚠️ Configuration Odoo incomplète pour le scheduler")
                return
            
            # Créer un client Odoo
            client = OdooClient(odoo_url, odoo_db, odoo_username, odoo_password)
            
            if not client.authenticate():
                logger.error("❌ Échec authentification Odoo pour le scheduler")
                return
            
            # Récupérer tous les clients actifs
            domain = [
                ('is_company', '=', True),
                ('customer_rank', '>', 0),
                ('active', '=', True)
            ]
            
            partners = client.execute_kw(
                'res.partner',
                'search_read',
                [domain],
                {
                    'fields': ['id', 'name', 'credit', 'vat', 'ref'],
                    'limit': 1000  # Limite de sécurité
                }
            )
            
            changes_detected = 0
            
            for partner in partners:
                partner_id = partner['id']
                current_credit = float(partner.get('credit', 0) or 0)
                partner_name = partner.get('name', 'Inconnu')
                
                # Vérifier si on a une valeur en cache
                if partner_id in self.cache:
                    previous_credit = self.cache[partner_id]['credit']
                    
                    # Calculer la différence
                    credit_increase = current_credit - previous_credit
                    
                    # Si le crédit a augmenté (nouveau paiement)
                    if credit_increase > 0.01:  # Tolérance de 0.01
                        changes_detected += 1
                        
                        logger.info(
                            f"💰 [SCHEDULER] Crédit augmenté: {partner_name} (ID: {partner_id}) "
                            f"- Ancien: {previous_credit}, Nouveau: {current_credit}, "
                            f"Différence: +{credit_increase}"
                        )
                        
                        # Envoyer le webhook immédiatement
                        await self.send_webhook(
                            partner_id=str(partner_id),
                            amount=credit_increase
                        )
                
                # Mettre à jour le cache
                self.cache[partner_id] = {
                    'credit': current_credit,
                    'last_check': datetime.now()
                }
            
            logger.debug(
                f"✅ [SCHEDULER] Vérification terminée: {len(partners)} clients, "
                f"{changes_detected} changement(s) détecté(s)"
            )
            
        except Exception as e:
            logger.error(f"❌ [SCHEDULER] Erreur lors de la vérification: {e}")
    
    async def send_webhook(self, partner_id: str, amount: float):
        """Envoyer le webhook de notification"""
        try:
            # Préparer les données
            webhook_data = {
                "action": "COMPANY_RECHARGE",
                "companyExternalId": partner_id,
                "amount": amount
            }
            
            logger.info(f"📤 [SCHEDULER] Préparation webhook pour partner {partner_id}")
            
            # Encrypter les données
            try:
                encrypted_data = encrypt_webhook_data(webhook_data, use_compression=False)
                logger.info(f"🔐 [SCHEDULER] Données encryptées (taille: {len(encrypted_data)} chars)")
            except Exception as e:
                logger.error(f"❌ [SCHEDULER] Erreur encryption: {e}")
                return
            
            # Envoyer la requête
            logger.info(f"📤 [SCHEDULER] Envoi webhook: {WEBHOOK_URL}")
            
            async with httpx.AsyncClient(timeout=WEBHOOK_TIMEOUT) as http_client:
                response = await http_client.post(
                    WEBHOOK_URL,
                    headers={
                        'Content-Type': 'application/json',
                        'x-encrypted-data': encrypted_data
                    }
                )
                
                if response.status_code in [200, 201, 204]:
                    logger.info(
                        f"✅ [SCHEDULER] Webhook envoyé avec succès pour partner {partner_id} "
                        f"- Montant: {amount} - Status: {response.status_code}"
                    )
                else:
                    logger.warning(
                        f"⚠️ [SCHEDULER] Webhook rejeté (HTTP {response.status_code}): "
                        f"{response.text[:200]}"
                    )
                    
        except Exception as e:
            logger.error(f"❌ [SCHEDULER] Erreur envoi webhook: {e}")
    
    async def run_scheduler(self):
        """Boucle principale du scheduler"""
        self.is_running = True
        logger.info(f"🚀 [SCHEDULER] Démarrage de la surveillance automatique des crédits")
        logger.info(f"⏱️  [SCHEDULER] Intervalle de vérification: {CHECK_INTERVAL} secondes")
        logger.info(f"🔗 [SCHEDULER] URL webhook: {WEBHOOK_URL}")
        
        while self.is_running:
            try:
                await self.check_credits_once()
                await asyncio.sleep(CHECK_INTERVAL)
            except asyncio.CancelledError:
                logger.info("⚠️ [SCHEDULER] Arrêt demandé")
                break
            except Exception as e:
                logger.error(f"❌ [SCHEDULER] Erreur dans la boucle: {e}")
                await asyncio.sleep(CHECK_INTERVAL)
        
        logger.info("🛑 [SCHEDULER] Surveillance arrêtée")
    
    def start(self):
        """Démarrer le scheduler"""
        if not self.task or self.task.done():
            self.task = asyncio.create_task(self.run_scheduler())
            logger.info("✅ [SCHEDULER] Tâche de surveillance créée")
        else:
            logger.warning("⚠️ [SCHEDULER] Déjà en cours d'exécution")
    
    def stop(self):
        """Arrêter le scheduler"""
        self.is_running = False
        if self.task and not self.task.done():
            self.task.cancel()
            logger.info("🛑 [SCHEDULER] Arrêt en cours...")


# Instance globale du scheduler
_scheduler_instance = None


def get_scheduler() -> CreditMonitorScheduler:
    """Obtenir l'instance globale du scheduler"""
    global _scheduler_instance
    if _scheduler_instance is None:
        _scheduler_instance = CreditMonitorScheduler()
    return _scheduler_instance


async def start_credit_monitor():
    """Démarrer la surveillance automatique des crédits (appelé au démarrage de FastAPI)"""
    scheduler = get_scheduler()
    scheduler.start()
    logger.info("✅ Surveillance automatique des crédits activée")


async def stop_credit_monitor():
    """Arrêter la surveillance (appelé à l'arrêt de FastAPI)"""
    scheduler = get_scheduler()
    scheduler.stop()
    logger.info("🛑 Surveillance automatique des crédits désactivée")
