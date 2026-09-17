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
from core.webhook_sender import send_encrypted_webhook
from core.config import ODOO_DB1_CONFIG  # Import de la config par défaut
import os

logger = logging.getLogger(__name__)

# Configuration
WEBHOOK_URL = os.getenv("FUEL_WEBHOOK_URL", "https://api-jnp-dev.opensi.co/public/odoo/webhook")
# Optional staging webhook URL - if set we will call both dev and staging
WEBHOOK_URL_STG = os.getenv("FUEL_WEBHOOK_URL_STG", "https://api-jnp-stg.opensi.co/public/odoo/webhook")
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
        """
        Vérifier si des factures TVPASS en attente ont été payées.

        Scanne directement Odoo pour trouver les factures TVPASS (identifiées
        par le tag [TVPASS_SUPPLY:...] dans la narration) qui sont passées à 'paid'.

        Cette méthode est robuste au redémarrage du serveur car elle ne dépend
        pas d'un cache en RAM — tout est lu depuis Odoo.
        """
        import re

        try:
            # Chercher les factures TVPASS qui viennent de passer à paid
            # Le tag TVPASS_SUPPLY dans narration identifie nos factures
            invoices = client.execute_kw(
                'account.move',
                'search_read',
                [[
                    ('move_type', '=', 'out_invoice'),
                    ('narration', 'ilike', 'TVPASS_SUPPLY'),
                    ('payment_state', '=', 'paid'),
                ]],
                {'fields': ['id', 'name', 'narration', 'partner_id', 'amount_total'],
                 'order': 'id desc', 'limit': 50}
            )

            if not invoices:
                logger.debug("🔍 [SCHEDULER] Aucune facture TVPASS payée à traiter")
                return

            for inv in invoices:
                inv_id = inv['id']
                narration = inv.get('narration', '') or ''

                # Extraire supply_id et payment_method du tag
                match = re.search(r'\[TVPASS_SUPPLY:([^:]+):([^\]]+)\]', narration)
                if not match:
                    continue

                supply_id = match.group(1)
                payment_method = match.group(2)

                # Vérifier si c'est une facture bank (les kkiapay ont déjà reçu le webhook)
                if payment_method != 'bank':
                    continue

                # Vérifier si on a déjà envoyé le webhook pour cette facture
                # On marque les factures traitées avec le tag [TVPASS_WEBHOOK_SENT]
                if 'TVPASS_WEBHOOK_SENT' in narration:
                    continue

                invoice_number = inv.get('name', f'INV-{inv_id}')
                partner_id = inv['partner_id'][0] if isinstance(inv.get('partner_id'), list) else inv.get('partner_id')
                amount = inv.get('amount_total', 0)

                logger.info(
                    f"💰 [SCHEDULER] Facture {invoice_number} payée ! "
                    f"Partner: {partner_id}, Montant: {amount}, supplyId: {supply_id}"
                )

                # Envoyer le webhook COMPANY_SUPPLY_VALIDATION
                await self.send_supply_validation_webhook(
                    supply_id=supply_id,
                    invoice_id=inv_id
                )

                # Marquer la facture comme traitée dans Odoo (persistent)
                try:
                    new_narration = narration + "\n[TVPASS_WEBHOOK_SENT]"
                    client.execute_kw(
                        'account.move', 'write',
                        [[inv_id], {'narration': new_narration}]
                    )
                    logger.info(f"✅ [SCHEDULER] Facture {invoice_number} marquée WEBHOOK_SENT")
                except Exception as e:
                    logger.warning(f"⚠️ [SCHEDULER] Impossible de marquer la facture: {e}")

                # Retirer de la liste en mémoire si elle y était
                if inv_id in self.pending_invoices:
                    del self.pending_invoices[inv_id]

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

        except Exception as e:
            logger.error(f"❌ [SCHEDULER] Erreur vérification factures en attente: {e}")

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
            # Build URL list (dev + optional staging)
            urls = [WEBHOOK_URL]
            if WEBHOOK_URL_STG and WEBHOOK_URL_STG != WEBHOOK_URL:
                urls.append(WEBHOOK_URL_STG)

            logger.info(f"📤 [SCHEDULER] Envoi webhook vers {len(urls)} endpoint(s): {urls}")

            try:
                results = await send_encrypted_webhook(urls, webhook_data, timeout=WEBHOOK_TIMEOUT, use_compression=False)
                for url, status, info in results:
                    if status not in (200, 201, 204):
                        logger.warning(f"⚠️ [SCHEDULER] Non-OK response from {url}: {status} - {info}")
            except Exception as e:
                logger.error(f"❌ [SCHEDULER] Exception lors de l'envoi des webhooks: {e}")
                    
        except Exception as e:
            logger.error(f"❌ [SCHEDULER] Erreur envoi webhook: {e}")

    async def send_supply_validation_webhook(self, supply_id: str, invoice_id: int):
        """Envoyer le webhook COMPANY_SUPPLY_VALIDATION quand une facture bank est payée"""
        try:
            webhook_data = {
                "action": "COMPANY_SUPPLY_VALIDATION",
                "supplyId": supply_id,
                "invoiceId": str(invoice_id)
            }

            logger.info(f"📤 [SCHEDULER] Préparation webhook COMPANY_SUPPLY_VALIDATION")
            logger.info(f"   supplyId: {supply_id}, invoiceId: {invoice_id}")

            urls = [WEBHOOK_URL]
            if WEBHOOK_URL_STG and WEBHOOK_URL_STG != WEBHOOK_URL:
                urls.append(WEBHOOK_URL_STG)

            try:
                results = await send_encrypted_webhook(urls, webhook_data, timeout=WEBHOOK_TIMEOUT, use_compression=False)
                for url, status, info in results:
                    if status in (200, 201, 204):
                        logger.info(
                            f"✅ [SCHEDULER] Webhook COMPANY_SUPPLY_VALIDATION envoyé - "
                            f"supplyId: {supply_id}, invoiceId: {invoice_id} - URL: {url} - Status: {status}"
                        )
                    else:
                        logger.warning(f"⚠️ [SCHEDULER] COMPANY_SUPPLY_VALIDATION non-OK from {url}: {status} - {info}")
            except Exception as e:
                logger.error(f"❌ [SCHEDULER] Exception lors de l'envoi du COMPANY_SUPPLY_VALIDATION: {e}")

        except Exception as e:
            logger.error(f"❌ [SCHEDULER] Erreur envoi webhook COMPANY_SUPPLY_VALIDATION: {e}")
    
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
