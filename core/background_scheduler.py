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
from core.config import ODOO_DB1_CONFIG  # Import de la config par défaut
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
    """Scheduler pour surveiller automatiquement les crédits et les factures en attente"""
    
    def __init__(self):
        self.is_running = False
        self.task = None
        self.cache: Dict[int, Dict[str, Any]] = {}
        self.pending_invoices: Dict[int, Dict[str, Any]] = {}  # Factures bank en attente
        
    async def check_credits_once(self):
        """Vérifier les crédits une seule fois"""
        try:
            # Utiliser la configuration Odoo par défaut (DB1)
            config = {
                'url': ODOO_DB1_CONFIG['url'],
                'db': ODOO_DB1_CONFIG['db'],
                'username': ODOO_DB1_CONFIG['username'],
                'api_key': ODOO_DB1_CONFIG['api_key']
            }
            
            # Créer un client Odoo avec la configuration
            client = OdooClient(custom_config=config)
            
            # Authentifier (sera fait automatiquement lors du premier appel)
            # Tester avec un appel simple
            try:
                # Test de connexion en récupérant un partenaire au hasard
                test = client.execute_kw(
                    'res.partner',
                    'search',
                    [[]],
                    {'limit': 1}
                )
                logger.debug(f"✅ [SCHEDULER] Connexion Odoo réussie")
            except Exception as e:
                logger.error(f"❌ [SCHEDULER] Échec authentification Odoo: {e}")
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
            
            # Vérifier aussi les factures en attente (mode bank)
            await self.check_pending_invoices(client)
            
        except Exception as e:
            logger.error(f"❌ [SCHEDULER] Erreur lors de la vérification: {e}")

    async def check_pending_invoices(self, client: OdooClient):
        """Vérifier si des factures en attente (mode bank) ont été payées"""
        if not self.pending_invoices:
            return

        invoice_ids = list(self.pending_invoices.keys())
        logger.debug(f"🔍 [SCHEDULER] Vérification de {len(invoice_ids)} facture(s) en attente...")

        try:
            invoices = client.execute_kw(
                'account.move',
                'search_read',
                [[('id', 'in', invoice_ids)]],
                {'fields': ['id', 'name', 'payment_state', 'amount_total', 'state']}
            )

            for inv in invoices:
                inv_id = inv['id']
                payment_state = inv.get('payment_state', '')

                # Vérifier si la facture a été payée (paid ou in_payment)
                if payment_state in ('paid', 'in_payment'):
                    pending_info = self.pending_invoices[inv_id]
                    partner_id = pending_info['partner_id']
                    amount = pending_info['amount']
                    invoice_number = inv.get('name', pending_info.get('invoice_number', ''))

                    logger.info(
                        f"💰 [SCHEDULER] Facture {invoice_number} payée ! "
                        f"Partner: {partner_id}, Montant: {amount}"
                    )

                    # Envoyer le webhook TVPASS_RECHARGE
                    await self.send_tvpass_webhook(
                        partner_id=str(partner_id),
                        amount=amount,
                        invoice_id=inv_id,
                        invoice_number=invoice_number
                    )

                    # Mettre à jour le cache credit du partner
                    try:
                        updated_partner = client.execute_kw(
                            'res.partner', 'read', [partner_id],
                            {'fields': ['credit']}
                        )
                        if updated_partner:
                            self.cache[partner_id] = {
                                'credit': updated_partner[0]['credit'],
                                'last_check': datetime.now()
                            }
                    except Exception:
                        pass

                    # Retirer de la liste des factures en attente
                    del self.pending_invoices[inv_id]
                    logger.info(f"✅ [SCHEDULER] Facture {invoice_number} retirée des factures en attente")

        except Exception as e:
            logger.error(f"❌ [SCHEDULER] Erreur vérification factures en attente: {e}")
    
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

    async def send_tvpass_webhook(self, partner_id: str, amount: float,
                                   invoice_id: int, invoice_number: str):
        """Envoyer le webhook TVPASS_RECHARGE quand une facture bank est payée"""
        try:
            webhook_data = {
                "action": "TVPASS_RECHARGE",
                "companyExternalId": partner_id,
                "amount": amount,
                "invoice_id": invoice_id,
                "invoice_number": invoice_number
            }

            logger.info(f"📤 [SCHEDULER] Préparation webhook TVPASS_RECHARGE pour partner {partner_id}")
            logger.info(f"   Facture: {invoice_number} (ID: {invoice_id}), Montant: {amount}")

            try:
                encrypted_data = encrypt_webhook_data(webhook_data, use_compression=False)
                logger.info(f"🔐 [SCHEDULER] Données encryptées (taille: {len(encrypted_data)} chars)")
            except Exception as e:
                logger.error(f"❌ [SCHEDULER] Erreur encryption TVPASS: {e}")
                return

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
                        f"✅ [SCHEDULER] Webhook TVPASS_RECHARGE envoyé pour partner {partner_id} "
                        f"- Facture: {invoice_number} - Status: {response.status_code}"
                    )
                else:
                    logger.warning(
                        f"⚠️ [SCHEDULER] Webhook TVPASS rejeté (HTTP {response.status_code}): "
                        f"{response.text[:200]}"
                    )

        except Exception as e:
            logger.error(f"❌ [SCHEDULER] Erreur envoi webhook TVPASS: {e}")
    
    async def run_scheduler(self):
        """Boucle principale du scheduler"""
        self.is_running = True
        logger.info(f"🚀 [SCHEDULER] Démarrage de la surveillance (crédits + factures TVPASS)")
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
