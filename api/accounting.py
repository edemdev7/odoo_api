"""
Module de gestion des factures de rechargement TVPASS

Crée une commande de vente → facture → (paiement si kkiapay).
Les écritures comptables sont générées automatiquement par Odoo.
"""

from fastapi import APIRouter, HTTPException, Request, Header, BackgroundTasks
from fastapi.responses import Response
from typing import Optional
from datetime import datetime
import logging
import httpx
import os
import base64
from pydantic import BaseModel, Field
from enum import Enum

from core.encryption import decrypt_webhook_data, encrypt_webhook_data
from core.odoo_client import OdooClient
from models.responses import ApiResponse
from core.background_scheduler import get_scheduler

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/accounting", tags=["Accounting"])

# ============================================================
# CONSTANTES
# ============================================================
TVPASS_PRODUCT_CODE = "TVPASS_ESS"          # Référence interne du produit
TVPASS_PRODUCT_ID = 2999                     # ID du produit (fallback)
JPASS_JOURNAL_ID = 194                       # Journal PASS GD pour paiement kkiapay
WEBHOOK_ACTION = "COMPANY_SUPPLY_VALIDATION" # Action webhook quand facture payée

WEBHOOK_URL = os.getenv("FUEL_WEBHOOK_URL", "https://api-jnp-dev.opensi.co/public/odoo/webhook")
WEBHOOK_TIMEOUT = int(os.getenv("FUEL_WEBHOOK_TIMEOUT", "10"))


class PaymentMethodEnum(str, Enum):
    kkiapay = "kkiapay"
    bank = "bank"


class CreditAccountRequest(BaseModel):
    """Modèle pour créer une facture de rechargement TVPASS"""
    partner_id: int = Field(..., description="ID de l'entreprise (res.partner)")
    amount: float = Field(..., gt=0, description="Montant à facturer (doit être > 0)")
    reference: str = Field(..., description="Référence de la transaction (ex: KKIAPAY-XXX)")
    payment_method: PaymentMethodEnum = Field(..., description="Méthode de paiement: kkiapay ou bank")
    supply_id: str = Field(..., description="ID du supply côté appelant (retourné dans le webhook)")
    product_id: Optional[int] = Field(None, description="ID du produit (optionnel, défaut: TVPASS_ESS)")
    date: Optional[str] = Field(None, description="Date de la facture (YYYY-MM-DD)")
    description: Optional[str] = Field(None, description="Description de la facture")


# ============================================================
# FONCTIONS UTILITAIRES
# ============================================================

def find_tvpass_product(client: OdooClient, product_id: Optional[int] = None) -> dict:
    """Trouver le produit TVPASS_ESS par référence interne ou ID"""
    if product_id:
        products = client.execute_kw(
            'product.product',
            'search_read',
            [[('id', '=', product_id)]],
            {'fields': ['id', 'name', 'default_code', 'list_price', 'taxes_id'], 'limit': 1}
        )
        if products:
            return products[0]

    # Recherche par code interne
    products = client.execute_kw(
        'product.product',
        'search_read',
        [[('default_code', '=', TVPASS_PRODUCT_CODE)]],
        {'fields': ['id', 'name', 'default_code', 'list_price', 'taxes_id'], 'limit': 1}
    )
    if products:
        return products[0]

    # Fallback par ID connu
    products = client.execute_kw(
        'product.product',
        'search_read',
        [[('id', '=', TVPASS_PRODUCT_ID)]],
        {'fields': ['id', 'name', 'default_code', 'list_price', 'taxes_id'], 'limit': 1}
    )
    if products:
        return products[0]

    return None


def create_sale_order(client: OdooClient, partner_id: int, product: dict,
                      amount: float, reference: str, date: str,
                      description: str) -> int:
    """Créer et confirmer une commande de vente"""
    order_line_vals = {
        'product_id': product['id'],
        'name': description,
        'product_uom_qty': 1,
        'price_unit': amount,
    }

    order_vals = {
        'partner_id': partner_id,
        'date_order': date,
        'client_order_ref': reference,
        'order_line': [(0, 0, order_line_vals)],
    }

    logger.info(f"📝 Création commande de vente: partner={partner_id}, produit={product['name']}, montant={amount}")
    order_id = client.execute_kw('sale.order', 'create', [order_vals])
    logger.info(f"✅ Commande créée: ID={order_id}")

    # Confirmer la commande (draft → sale)
    client.execute_kw('sale.order', 'action_confirm', [[order_id]])
    logger.info(f"✅ Commande confirmée: ID={order_id}")

    return order_id


def create_invoice_from_order(client: OdooClient, order_id: int) -> int:
    """Créer et valider la facture depuis la commande de vente.

    Crée directement un account.move (out_invoice) lié au sale.order,
    car les wizards Odoo retournent des valeurs incompatibles avec XML-RPC.
    """

    # Récupérer la commande et ses lignes
    order = client.execute_kw(
        'sale.order',
        'read',
        [order_id],
        {'fields': ['partner_id', 'name', 'client_order_ref', 'order_line', 'currency_id', 'company_id']}
    )
    if not order:
        raise Exception(f"Commande {order_id} non trouvée")
    order = order[0]

    partner_id = order['partner_id'][0] if isinstance(order['partner_id'], list) else order['partner_id']
    company_id = order['company_id'][0] if isinstance(order['company_id'], list) else order['company_id']

    # Récupérer les lignes de la commande
    order_lines = client.execute_kw(
        'sale.order.line',
        'read',
        [order['order_line']],
        {'fields': ['product_id', 'name', 'product_uom_qty', 'price_unit', 'tax_id', 'product_uom']}
    )

    # Construire les lignes de facture
    invoice_lines = []
    for line in order_lines:
        product_id = line['product_id'][0] if isinstance(line['product_id'], list) else line['product_id']
        inv_line = {
            'product_id': product_id,
            'name': line['name'],
            'quantity': line['product_uom_qty'],
            'price_unit': line['price_unit'],
            'sale_line_ids': [(4, line['id'])],  # Lier à la ligne de commande
        }
        if line.get('tax_id'):
            inv_line['tax_ids'] = [(6, 0, line['tax_id'])]
        if line.get('product_uom'):
            uom_id = line['product_uom'][0] if isinstance(line['product_uom'], list) else line['product_uom']
            inv_line['product_uom_id'] = uom_id
        invoice_lines.append((0, 0, inv_line))

    # Créer la facture client
    invoice_vals = {
        'move_type': 'out_invoice',
        'partner_id': partner_id,
        'company_id': company_id,
        'invoice_origin': order['name'],
        'ref': order.get('client_order_ref') or order['name'],
        'invoice_line_ids': invoice_lines,
    }

    logger.info(f"📝 Création facture pour commande {order['name']}...")
    invoice_id = client.execute_kw('account.move', 'create', [invoice_vals])
    logger.info(f"✅ Facture créée: ID={invoice_id}")

    # Valider la facture (draft → posted)
    client.execute_kw('account.move', 'action_post', [[invoice_id]])
    logger.info(f"✅ Facture validée (posted): ID={invoice_id}")

    return invoice_id


def register_payment_kkiapay(client: OdooClient, invoice_id: int, amount: float,
                              reference: str, date: str) -> dict:
    """
    Enregistrer le paiement via le wizard account.payment.register pour le mode kkiapay.
    Le wizard gère automatiquement le paiement + lettrage.
    Ensuite on crée un relevé bancaire et on le rapproche via le wizard
    account.bank.statement.line pour passer de in_payment → paid.
    """
    # Récupérer la facture
    invoice = client.execute_kw(
        'account.move',
        'read',
        [invoice_id],
        {'fields': ['id', 'name', 'state', 'amount_residual', 'partner_id']}
    )
    if invoice:
        invoice = invoice[0]

    partner_id_val = invoice['partner_id'][0] if isinstance(invoice.get('partner_id'), list) else invoice.get('partner_id')
    logger.info(f"💳 Enregistrement paiement kkiapay: facture={invoice['name']}, montant={amount}")

    # ===== 1. Créer le paiement via le wizard account.payment.register =====
    # C'est la méthode officielle d'Odoo — gère paiement + lettrage auto
    try:
        # Créer le wizard dans le contexte de la facture
        wizard_context = {
            'active_model': 'account.move',
            'active_ids': [invoice_id],
        }
        wizard_vals = {
            'journal_id': JPASS_JOURNAL_ID,
            'amount': amount,
            'payment_date': date,
            'communication': reference,
        }
        wizard_id = client.execute_kw(
            'account.payment.register',
            'create',
            [wizard_vals],
            {'context': wizard_context}
        )
        logger.info(f"✅ Wizard paiement créé: ID={wizard_id}")

        # Exécuter le wizard — crée le paiement et fait le lettrage automatiquement
        result = client.execute_kw(
            'account.payment.register',
            'action_create_payments',
            [[wizard_id]],
            {'context': wizard_context}
        )
        logger.info(f"✅ Paiement enregistré via wizard")

        # Récupérer l'ID du paiement créé
        payment_ids = client.execute_kw(
            'account.payment',
            'search',
            [[
                ('partner_id', '=', partner_id_val),
                ('journal_id', '=', JPASS_JOURNAL_ID),
                ('amount', '=', amount),
            ]],
            {'order': 'id desc', 'limit': 1}
        )
        payment_id = payment_ids[0] if payment_ids else None

        if payment_id:
            # Récupérer le move_id du paiement
            payment_data = client.execute_kw(
                'account.payment', 'read', [payment_id],
                {'fields': ['move_id', 'state', 'is_reconciled']}
            )
            payment_move_id = payment_data[0]['move_id'][0] if payment_data and isinstance(payment_data[0].get('move_id'), list) else None
            logger.info(f"✅ Paiement ID={payment_id}, move_id={payment_move_id}, state={payment_data[0].get('state')}, reconciled={payment_data[0].get('is_reconciled')}")
        else:
            payment_move_id = None
            logger.warning("⚠️ Paiement créé mais ID non trouvé")

    except Exception as e:
        logger.warning(f"⚠️ Erreur wizard paiement: {e}")
        logger.info("🔄 Fallback: création manuelle du paiement...")

        # Fallback: création manuelle
        payment_vals = {
            'payment_type': 'inbound',
            'partner_type': 'customer',
            'partner_id': partner_id_val,
            'amount': amount,
            'journal_id': JPASS_JOURNAL_ID,
            'ref': reference,
            'date': date,
        }
        payment_id = client.execute_kw('account.payment', 'create', [payment_vals])
        logger.info(f"✅ Paiement créé (fallback): ID={payment_id}")

        client.execute_kw('account.payment', 'action_post', [[payment_id]])
        logger.info(f"✅ Paiement validé: ID={payment_id}")

        # Lettrage manuel des receivable
        payment_data = client.execute_kw('account.payment', 'read', [payment_id], {'fields': ['move_id']})
        payment_move_id = payment_data[0]['move_id'][0] if payment_data and isinstance(payment_data[0].get('move_id'), list) else None

        invoice_rec = client.execute_kw('account.move.line', 'search', [[
            ('move_id', '=', invoice_id), ('account_type', '=', 'asset_receivable'), ('reconciled', '=', False)
        ]])
        payment_rec = client.execute_kw('account.move.line', 'search', [[
            ('move_id', '=', payment_move_id), ('account_type', '=', 'asset_receivable'), ('reconciled', '=', False)
        ]]) if payment_move_id else []

        if invoice_rec and payment_rec:
            try:
                client.execute_kw('account.move.line', 'reconcile', [invoice_rec + payment_rec])
                logger.info(f"✅ Lettrage receivable effectué (fallback)")
            except Exception as e2:
                logger.warning(f"⚠️ Erreur lettrage: {e2}")

    # ===== 2. Rapprochement bancaire pour passer de in_payment → paid =====
    # Le journal JPASS type=bank crée une ligne outstanding (521007).
    # On crée un relevé bancaire puis on rapproche via le widget JS d'Odoo.
    if payment_move_id:
        try:
            # Trouver la ligne outstanding (521007, debit) du paiement
            outstanding_lines = client.execute_kw(
                'account.move.line',
                'search_read',
                [[
                    ('move_id', '=', payment_move_id),
                    ('account_type', '!=', 'asset_receivable'),
                    ('reconciled', '=', False),
                    ('debit', '>', 0),
                ]],
                {'fields': ['id', 'account_id', 'debit'], 'limit': 1}
            )

            if outstanding_lines:
                outstanding_line = outstanding_lines[0]
                outstanding_amount = outstanding_line['debit']
                logger.info(f"🏦 Ligne outstanding: ID={outstanding_line['id']}, montant={outstanding_amount}, compte={outstanding_line['account_id']}")

                # Créer une ligne de relevé bancaire
                stmt_line_id = client.execute_kw(
                    'account.bank.statement.line',
                    'create',
                    [{
                        'journal_id': JPASS_JOURNAL_ID,
                        'payment_ref': reference,
                        'partner_id': partner_id_val,
                        'amount': outstanding_amount,
                        'date': date,
                    }]
                )
                logger.info(f"✅ Relevé bancaire créé: ID={stmt_line_id}")

                # Récupérer le move_id du relevé
                stmt_data = client.execute_kw(
                    'account.bank.statement.line', 'read',
                    [stmt_line_id], {'fields': ['move_id']}
                )
                stmt_move_id = stmt_data[0]['move_id'][0] if stmt_data and isinstance(stmt_data[0].get('move_id'), list) else None

                if stmt_move_id:
                    # Trouver les lignes du relevé sur le compte suspens (471130)
                    # et la ligne liquidity (419101)
                    stmt_lines_all = client.execute_kw(
                        'account.move.line', 'search_read',
                        [[('move_id', '=', stmt_move_id)]],
                        {'fields': ['id', 'account_id', 'debit', 'credit', 'reconciled', 'account_type']}
                    )
                    logger.info(f"📋 Lignes du relevé bancaire (move {stmt_move_id}):")
                    for sl in stmt_lines_all:
                        acc = sl['account_id'][1] if isinstance(sl['account_id'], list) else sl['account_id']
                        logger.info(f"   Line {sl['id']}: {acc} D={sl['debit']} C={sl['credit']} type={sl['account_type']} reconciled={sl['reconciled']}")

                    # Chercher la ligne credit non-reconciliée du relevé sur n'importe quel compte
                    stmt_credit_lines = [
                        sl for sl in stmt_lines_all
                        if sl['credit'] > 0 and not sl['reconciled']
                    ]

                    if stmt_credit_lines:
                        # On doit créer une écriture de transfert entre les comptes
                        # 521007 (outstanding paiement) ↔ 471130 (suspens relevé)
                        # via une écriture manuelle pour les mettre sur le même compte
                        stmt_credit_line = stmt_credit_lines[0]
                        stmt_credit_account_id = stmt_credit_line['account_id'][0] if isinstance(stmt_credit_line['account_id'], list) else stmt_credit_line['account_id']
                        outstanding_account_id = outstanding_line['account_id'][0] if isinstance(outstanding_line['account_id'], list) else outstanding_line['account_id']

                        if stmt_credit_account_id == outstanding_account_id:
                            # Même compte — on peut reconcilier directement
                            lines_to_rec = [outstanding_line['id'], stmt_credit_line['id']]
                            logger.info(f"🔗 Rapprochement direct (même compte): {lines_to_rec}")
                            client.execute_kw('account.move.line', 'reconcile', [lines_to_rec])
                            logger.info(f"✅ Rapprochement bancaire effectué !")
                        else:
                            # Comptes différents — créer une écriture de transfert
                            logger.info(f"🔄 Comptes différents ({outstanding_account_id} vs {stmt_credit_account_id}), création écriture de transfert...")

                            # Créer une écriture journal pour transférer :
                            # Débit 471130 (annule le suspens) / Crédit 521007 (annule l'outstanding)
                            transfer_move_vals = {
                                'journal_id': JPASS_JOURNAL_ID,
                                'date': date,
                                'ref': f"Rapprochement auto {reference}",
                                'line_ids': [
                                    (0, 0, {
                                        'account_id': stmt_credit_account_id,
                                        'debit': outstanding_amount,
                                        'credit': 0,
                                        'name': f"Transfert rapprochement {reference}",
                                        'partner_id': partner_id_val,
                                    }),
                                    (0, 0, {
                                        'account_id': outstanding_account_id,
                                        'debit': 0,
                                        'credit': outstanding_amount,
                                        'name': f"Transfert rapprochement {reference}",
                                        'partner_id': partner_id_val,
                                    }),
                                ]
                            }
                            transfer_move_id = client.execute_kw('account.move', 'create', [transfer_move_vals])
                            logger.info(f"✅ Écriture de transfert créée: ID={transfer_move_id}")

                            # Valider l'écriture
                            client.execute_kw('account.move', 'action_post', [[transfer_move_id]])
                            logger.info(f"✅ Écriture de transfert validée")

                            # Récupérer les lignes de l'écriture de transfert
                            transfer_lines = client.execute_kw(
                                'account.move.line', 'search_read',
                                [[('move_id', '=', transfer_move_id)]],
                                {'fields': ['id', 'account_id', 'debit', 'credit', 'reconciled']}
                            )

                            # Reconcilier:
                            # 1. Outstanding (521007 débit) + Transfer (521007 crédit)
                            transfer_521007 = [tl['id'] for tl in transfer_lines
                                               if (tl['account_id'][0] if isinstance(tl['account_id'], list) else tl['account_id']) == outstanding_account_id]
                            if transfer_521007:
                                logger.info(f"🔗 Lettrage 521007: outstanding={outstanding_line['id']} + transfer={transfer_521007}")
                                client.execute_kw('account.move.line', 'reconcile',
                                                  [[outstanding_line['id']] + transfer_521007])
                                logger.info(f"✅ Outstanding 521007 lettré → facture paid !")

                            # Note: le compte suspens 471130 ne permet pas le lettrage dans Odoo,
                            # mais ce n'est pas nécessaire — seul le lettrage 521007 est requis
                            # pour que la facture passe de in_payment → paid.
                    else:
                        logger.warning(f"⚠️ Pas de ligne credit dans le relevé bancaire")
                else:
                    logger.warning(f"⚠️ Move du relevé bancaire non trouvé")
            else:
                logger.info(f"ℹ️ Pas de ligne outstanding à rapprocher")
        except Exception as e:
            logger.warning(f"⚠️ Erreur rapprochement bancaire: {e}")
            import traceback
            logger.warning(traceback.format_exc())

    # ===== 3. Vérifier le résultat =====
    updated_invoice = client.execute_kw(
        'account.move',
        'read',
        [invoice_id],
        {'fields': ['payment_state', 'amount_residual']}
    )

    payment_state = updated_invoice[0]['payment_state'] if updated_invoice else 'unknown'
    amount_residual = updated_invoice[0]['amount_residual'] if updated_invoice else -1

    logger.info(f"📊 État paiement facture: {payment_state}, reste dû: {amount_residual}")

    return {
        'payment_state': payment_state,
        'amount_residual': amount_residual
    }


def register_payment_bank(client: OdooClient, invoice_id: int, amount: float,
                           reference: str, date: str) -> dict:
    """
    Enregistrer le paiement pour le mode bank.
    Crée le paiement via le wizard + lettrage receivable → in_payment.
    PAS de rapprochement bancaire — c'est l'admin qui le fera manuellement.
    Quand l'admin fera le rapprochement, la facture passera à 'paid'
    et le scheduler enverra le webhook.
    """
    invoice = client.execute_kw(
        'account.move', 'read', [invoice_id],
        {'fields': ['id', 'name', 'state', 'amount_residual', 'partner_id']}
    )
    if invoice:
        invoice = invoice[0]

    partner_id_val = invoice['partner_id'][0] if isinstance(invoice.get('partner_id'), list) else invoice.get('partner_id')
    logger.info(f"🏦 Enregistrement paiement bank: facture={invoice['name']}, montant={amount}")

    # Créer le paiement via le wizard account.payment.register
    try:
        wizard_context = {
            'active_model': 'account.move',
            'active_ids': [invoice_id],
        }
        wizard_vals = {
            'journal_id': JPASS_JOURNAL_ID,
            'amount': amount,
            'payment_date': date,
            'communication': reference,
        }
        wizard_id = client.execute_kw(
            'account.payment.register', 'create',
            [wizard_vals], {'context': wizard_context}
        )
        logger.info(f"✅ Wizard paiement bank créé: ID={wizard_id}")

        client.execute_kw(
            'account.payment.register', 'action_create_payments',
            [[wizard_id]], {'context': wizard_context}
        )
        logger.info(f"✅ Paiement bank enregistré via wizard (→ in_payment)")

    except Exception as e:
        logger.warning(f"⚠️ Erreur wizard paiement bank: {e}")
        # Fallback: création manuelle
        logger.info("🔄 Fallback: création manuelle du paiement bank...")
        payment_vals = {
            'payment_type': 'inbound',
            'partner_type': 'customer',
            'partner_id': partner_id_val,
            'amount': amount,
            'journal_id': JPASS_JOURNAL_ID,
            'ref': reference,
            'date': date,
        }
        payment_id = client.execute_kw('account.payment', 'create', [payment_vals])
        client.execute_kw('account.payment', 'action_post', [[payment_id]])
        logger.info(f"✅ Paiement bank créé et validé (fallback): ID={payment_id}")

        # Lettrage manuel des receivable
        payment_data = client.execute_kw('account.payment', 'read', [payment_id], {'fields': ['move_id']})
        payment_move_id = payment_data[0]['move_id'][0] if payment_data and isinstance(payment_data[0].get('move_id'), list) else None

        invoice_rec = client.execute_kw('account.move.line', 'search', [[
            ('move_id', '=', invoice_id), ('account_type', '=', 'asset_receivable'), ('reconciled', '=', False)
        ]])
        payment_rec = client.execute_kw('account.move.line', 'search', [[
            ('move_id', '=', payment_move_id), ('account_type', '=', 'asset_receivable'), ('reconciled', '=', False)
        ]]) if payment_move_id else []

        if invoice_rec and payment_rec:
            try:
                client.execute_kw('account.move.line', 'reconcile', [invoice_rec + payment_rec])
                logger.info(f"✅ Lettrage receivable effectué (fallback)")
            except Exception as e2:
                logger.warning(f"⚠️ Erreur lettrage: {e2}")

    # PAS de rapprochement bancaire — l'admin le fera manuellement

    # Vérifier le résultat
    updated_invoice = client.execute_kw(
        'account.move', 'read', [invoice_id],
        {'fields': ['payment_state', 'amount_residual']}
    )
    payment_state = updated_invoice[0]['payment_state'] if updated_invoice else 'unknown'
    amount_residual = updated_invoice[0]['amount_residual'] if updated_invoice else -1

    logger.info(f"📊 État paiement facture bank: {payment_state}, reste dû: {amount_residual}")

    return {
        'payment_state': payment_state,
        'amount_residual': amount_residual
    }


def get_invoice_details(client: OdooClient, invoice_id: int) -> dict:
    """Récupérer les détails d'une facture"""
    invoice = client.execute_kw(
        'account.move',
        'read',
        [invoice_id],
        {'fields': [
            'id', 'name', 'ref', 'state', 'payment_state',
            'date', 'amount_total', 'amount_residual',
            'partner_id', 'invoice_origin'
        ]}
    )
    return invoice[0] if invoice else None


# ============================================================
# WEBHOOK
# ============================================================

async def send_supply_validation_webhook(supply_id: str, invoice_id: int):
    """
    Envoyer le webhook COMPANY_SUPPLY_VALIDATION quand la facture est payée.

    Payload encrypté:
    {
        "action": "COMPANY_SUPPLY_VALIDATION",
        "supplyId": "abc-123",
        "invoiceId": "163684"
    }
    """
    try:
        webhook_data = {
            "action": WEBHOOK_ACTION,
            "supplyId": supply_id,
            "invoiceId": str(invoice_id)
        }

        logger.info(f"📤 Préparation webhook {WEBHOOK_ACTION}")
        logger.info(f"   supplyId: {supply_id}, invoiceId: {invoice_id}")

        # Encrypter les données
        try:
            encrypted_data = encrypt_webhook_data(webhook_data, use_compression=False)
            logger.info(f"🔐 Données encryptées (taille: {len(encrypted_data)} chars)")
        except Exception as e:
            logger.error(f"❌ Erreur encryption webhook: {e}")
            return

        # Envoyer
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
                    f"✅ Webhook {WEBHOOK_ACTION} envoyé - "
                    f"supplyId: {supply_id}, invoiceId: {invoice_id} - Status: {response.status_code}"
                )
            else:
                logger.error(
                    f"❌ Webhook rejeté (HTTP {response.status_code}): {response.text[:200]}"
                )

    except httpx.TimeoutException:
        logger.error(f"⏱️ Timeout webhook vers {WEBHOOK_URL}")
    except Exception as e:
        logger.error(f"❌ Erreur envoi webhook: {e}")


# ============================================================
# ENDPOINT PRINCIPAL
# ============================================================

@router.post("/credit-account", response_model=ApiResponse)
async def credit_customer_account(
    request: Request,
    background_tasks: BackgroundTasks,
    x_encrypted_data: Optional[str] = Header(None, description="Données encryptées en base64")
):
    """
    Recharger le compte fuel d'un client via facture TVPASS.

    **Flux:**
    1. Crée une commande de vente (sale.order) avec le produit TVPASS_ESS
    2. Confirme la commande
    3. Crée la facture (account.move out_invoice)
    4. Valide la facture (posted)
    5. Si payment_method = kkiapay → enregistre le paiement + lettrage auto + webhook immédiat
    6. Si payment_method = bank → facture reste posted, webhook envoyé quand l'admin valide

    **Données encryptées (JSON):**
    ```json
    {
        "partner_id": 123,
        "amount": 50000,
        "reference": "KKIAPAY-TRX-12345",
        "payment_method": "kkiapay",
        "date": "2026-02-26",
        "description": "Recharge compte fuel TVPASS"
    }
    ```
    """
    try:
        # ===== 1. DÉCRYPTION =====
        if not x_encrypted_data:
            logger.error("❌ Données encryptées manquantes")
            raise HTTPException(
                status_code=401,
                detail="Données encryptées requises dans le header x-encrypted-data"
            )

        try:
            logger.info("🔓 Décryption des données...")
            data = decrypt_webhook_data(x_encrypted_data)
            logger.info(f"✅ Données décryptées: partner_id={data.get('partner_id')}, "
                        f"amount={data.get('amount')}, method={data.get('payment_method')}")
        except Exception as e:
            logger.error(f"❌ Erreur décryption: {e}")
            raise HTTPException(
                status_code=401,
                detail="Impossible de décrypter les données. Vérifiez l'encryption."
            )

        # ===== 2. VALIDATION =====
        try:
            credit_request = CreditAccountRequest(**data)
        except Exception as e:
            logger.error(f"❌ Données invalides: {e}")
            raise HTTPException(
                status_code=400,
                detail=f"Données invalides: {str(e)}"
            )

        # ===== 3. CONNEXION ODOO =====
        client = OdooClient()
        move_date = credit_request.date or datetime.now().strftime('%Y-%m-%d')
        description = credit_request.description or f"Recharge TVPASS - {credit_request.reference}"

        # ===== 4. VÉRIFIER LE PARTENAIRE =====
        partner = client.execute_kw(
            'res.partner',
            'search_read',
            [[('id', '=', credit_request.partner_id)]],
            {'fields': ['id', 'name', 'credit'], 'limit': 1}
        )
        if not partner:
            raise HTTPException(
                status_code=404,
                detail=f"Partenaire {credit_request.partner_id} non trouvé"
            )
        partner = partner[0]
        logger.info(f"✅ Partenaire: {partner['name']} (crédit actuel: {partner['credit']})")

        # ===== 5. TROUVER LE PRODUIT =====
        product = find_tvpass_product(client, credit_request.product_id)
        if not product:
            raise HTTPException(
                status_code=404,
                detail=f"Produit TVPASS_ESS (code={TVPASS_PRODUCT_CODE}) non trouvé dans Odoo"
            )
        logger.info(f"✅ Produit: {product['name']} (ID: {product['id']})")

        # ===== 6. CRÉER LA COMMANDE DE VENTE =====
        order_id = create_sale_order(
            client=client,
            partner_id=credit_request.partner_id,
            product=product,
            amount=credit_request.amount,
            reference=credit_request.reference,
            date=move_date,
            description=description
        )

        # Récupérer le nom de la commande
        order_data = client.execute_kw(
            'sale.order', 'read', [order_id],
            {'fields': ['name', 'state']}
        )
        order_name = order_data[0]['name'] if order_data else f"SO-{order_id}"

        # ===== 7. CRÉER ET VALIDER LA FACTURE =====
        invoice_id = create_invoice_from_order(client, order_id)

        # Récupérer les détails de la facture
        invoice = get_invoice_details(client, invoice_id)
        invoice_number = invoice['name'] if invoice else f"INV-{invoice_id}"
        invoice_state = invoice['state'] if invoice else 'unknown'
        invoice_amount = invoice['amount_total'] if invoice else credit_request.amount

        logger.info(f"📄 Facture: {invoice_number} | État: {invoice_state} | Montant: {invoice_amount}")

        # ===== 8. TRAITEMENT SELON LA MÉTHODE DE PAIEMENT =====
        payment_info = None
        webhook_sent = False

        if credit_request.payment_method == PaymentMethodEnum.kkiapay:
            # MODE KKIAPAY: Paiement + lettrage + webhook immédiat
            logger.info("💳 Mode KKIAPAY: enregistrement du paiement automatique...")

            payment_info = register_payment_kkiapay(
                client=client,
                invoice_id=invoice_id,
                amount=credit_request.amount,
                reference=credit_request.reference,
                date=move_date
            )

            # Mettre à jour le cache du scheduler
            scheduler = get_scheduler()
            updated_partner = client.execute_kw(
                'res.partner', 'read', [credit_request.partner_id],
                {'fields': ['credit']}
            )
            if updated_partner:
                new_credit = updated_partner[0]['credit']
                scheduler.cache[credit_request.partner_id] = {
                    'credit': new_credit,
                    'last_check': datetime.now()
                }
                logger.info(f"📝 Cache scheduler mis à jour: credit={new_credit}")

            # Envoyer le webhook immédiatement en arrière-plan
            background_tasks.add_task(
                send_supply_validation_webhook,
                supply_id=credit_request.supply_id,
                invoice_id=invoice_id
            )
            webhook_sent = True
            logger.info(f"📤 Webhook {WEBHOOK_ACTION} planifié (kkiapay) - supplyId={credit_request.supply_id}")

        else:
            # MODE BANK: Paiement + lettrage receivable → in_payment
            # PAS de rapprochement bancaire — l'admin le fera manuellement
            # Quand l'admin fera le rapprochement → paid → scheduler envoie webhook
            logger.info("🏦 Mode BANK: enregistrement du paiement (sans rapprochement bancaire)...")

            payment_info = register_payment_bank(
                client=client,
                invoice_id=invoice_id,
                amount=credit_request.amount,
                reference=credit_request.reference,
                date=move_date
            )

            # Sauvegarder dans le scheduler pour surveillance
            scheduler = get_scheduler()
            if not hasattr(scheduler, 'pending_invoices'):
                scheduler.pending_invoices = {}
            scheduler.pending_invoices[invoice_id] = {
                'partner_id': credit_request.partner_id,
                'amount': credit_request.amount,
                'invoice_number': invoice_number,
                'reference': credit_request.reference,
                'supply_id': credit_request.supply_id,
                'created_at': datetime.now().isoformat()
            }
            logger.info(f"📝 Facture {invoice_number} en attente de rapprochement bancaire (admin)")

        # ===== 9. PRÉPARER LA RÉPONSE =====
        final_partner = client.execute_kw(
            'res.partner', 'read', [credit_request.partner_id],
            {'fields': ['credit', 'debit']}
        )
        new_balance = final_partner[0]['credit'] if final_partner else None

        response_data = {
            'order_id': order_id,
            'order_name': order_name,
            'invoice_id': invoice_id,
            'invoice_number': invoice_number,
            'invoice_state': invoice_state,
            'partner_id': credit_request.partner_id,
            'partner_name': partner['name'],
            'amount': credit_request.amount,
            'reference': credit_request.reference,
            'supply_id': credit_request.supply_id,
            'payment_method': credit_request.payment_method.value,
            'date': move_date,
            'product': {
                'id': product['id'],
                'name': product['name'],
                'code': product.get('default_code', TVPASS_PRODUCT_CODE)
            },
            'old_balance': partner['credit'],
            'new_balance': new_balance,
            'webhook_sent': webhook_sent,
        }

        if payment_info:
            response_data['payment'] = payment_info

        if credit_request.payment_method == PaymentMethodEnum.bank:
            response_data['note'] = (
                "Facture créée et validée. En attente de paiement par l'administrateur. "
                "Le webhook sera envoyé automatiquement quand le paiement sera enregistré."
            )

        # Message de succès
        if credit_request.payment_method == PaymentMethodEnum.kkiapay:
            msg = (f"Facture {invoice_number} créée et payée (kkiapay) pour "
                   f"{partner['name']} - Montant: {credit_request.amount}")
        else:
            msg = (f"Facture {invoice_number} créée (en attente paiement bank) pour "
                   f"{partner['name']} - Montant: {credit_request.amount}")

        return ApiResponse(success=True, data=response_data, message=msg)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Erreur inattendue: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Erreur lors du traitement: {str(e)}"
        )


# ============================================================
# ENDPOINT DE VÉRIFICATION COMPTE
# ============================================================

@router.get("/accounts/{account_code}", response_model=ApiResponse)
async def get_account_info(
    account_code: str,
    x_encrypted_data: Optional[str] = Header(None)
):
    """
    Récupérer les informations d'un compte comptable par son code.
    Protégé par encryption.
    """
    try:
        if not x_encrypted_data:
            raise HTTPException(status_code=401, detail="Données encryptées requises")

        try:
            decrypt_webhook_data(x_encrypted_data)
        except Exception:
            raise HTTPException(status_code=401, detail="Encryption invalide")

        client = OdooClient()

        account = client.execute_kw(
            'account.account',
            'search_read',
            [[('code', '=', account_code)]],
            {'fields': ['id', 'name', 'code', 'account_type', 'currency_id'], 'limit': 1}
        )

        if not account:
            raise HTTPException(status_code=404, detail=f"Compte {account_code} non trouvé")

        return ApiResponse(success=True, data=account[0], message=f"Compte {account_code} trouvé")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Erreur: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================
# ENDPOINT FACTURES EN ATTENTE
# ============================================================

@router.get("/pending-invoices", response_model=ApiResponse)
async def get_pending_invoices(
    x_encrypted_data: Optional[str] = Header(None)
):
    """
    Lister les factures TVPASS en attente de paiement (mode bank).
    """
    try:
        if not x_encrypted_data:
            raise HTTPException(status_code=401, detail="Données encryptées requises")

        try:
            decrypt_webhook_data(x_encrypted_data)
        except Exception:
            raise HTTPException(status_code=401, detail="Encryption invalide")

        scheduler = get_scheduler()
        pending = getattr(scheduler, 'pending_invoices', {})

        return ApiResponse(
            success=True,
            data={'count': len(pending), 'invoices': pending},
            message=f"{len(pending)} facture(s) en attente de paiement"
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Erreur: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================
# ENDPOINT TÉLÉCHARGEMENT PDF FACTURE
# ============================================================

@router.get("/invoice/{invoice_id}/pdf")
async def download_invoice_pdf(invoice_id: int):
    """
    Télécharger le PDF d'une facture par son ID.
    
    Retourne le fichier PDF de la facture Odoo.
    
    **Paramètres:**
    - **invoice_id**: ID de la facture (account.move)
    
    **Retourne:**
    - Fichier PDF de la facture
    """
    try:
        client = OdooClient()

        # Vérifier que la facture existe
        invoice = client.execute_kw(
            'account.move', 'read', [invoice_id],
            {'fields': ['id', 'name', 'state', 'move_type']}
        )

        if not invoice:
            raise HTTPException(status_code=404, detail=f"Facture {invoice_id} non trouvée")

        invoice_data = invoice[0]
        invoice_name = invoice_data.get('name', f'INV-{invoice_id}')

        # Vérifier que c'est bien une facture client
        if invoice_data.get('move_type') not in ('out_invoice', 'out_refund'):
            raise HTTPException(
                status_code=400,
                detail=f"Le document {invoice_name} n'est pas une facture client"
            )

        logger.info(f"📄 Génération PDF pour facture {invoice_name} (ID: {invoice_id})")

        # Générer le PDF via le rapport Odoo
        report_name = 'account.report_invoice'

        try:
            # Appel XML-RPC pour générer le rapport PDF
            pdf_data = client.models.execute_kw(
                client.db, client.uid, client.api_key,
                'ir.actions.report',
                '_render_qweb_pdf',
                [report_name, [invoice_id]]
            )

            if pdf_data and isinstance(pdf_data, (list, tuple)) and len(pdf_data) > 0:
                pdf_content = pdf_data[0]

                # Si c'est en base64, décoder
                if isinstance(pdf_content, str):
                    pdf_content = base64.b64decode(pdf_content)
                elif isinstance(pdf_content, bytes):
                    try:
                        pdf_content = base64.b64decode(pdf_content)
                    except Exception:
                        pass

                safe_name = invoice_name.replace('/', '_')
                logger.info(f"✅ PDF généré pour {invoice_name} ({len(pdf_content)} bytes)")

                return Response(
                    content=pdf_content,
                    media_type="application/pdf",
                    headers={
                        "Content-Disposition": f'attachment; filename="{safe_name}.pdf"'
                    }
                )
            else:
                raise HTTPException(
                    status_code=500,
                    detail=f"Le rapport PDF pour {invoice_name} est vide"
                )

        except HTTPException:
            raise
        except Exception as e:
            logger.warning(f"⚠️ Erreur rapport _render_qweb_pdf: {e}")

            # Fallback: chercher un attachement PDF existant
            try:
                attachments = client.execute_kw(
                    'ir.attachment', 'search_read',
                    [[
                        ('res_model', '=', 'account.move'),
                        ('res_id', '=', invoice_id),
                        ('mimetype', '=', 'application/pdf')
                    ]],
                    {'fields': ['id', 'name', 'datas'], 'order': 'id desc', 'limit': 1}
                )

                if attachments and attachments[0].get('datas'):
                    pdf_content = base64.b64decode(attachments[0]['datas'])
                    safe_name = invoice_name.replace('/', '_')
                    logger.info(f"✅ PDF trouvé en pièce jointe pour {invoice_name}")

                    return Response(
                        content=pdf_content,
                        media_type="application/pdf",
                        headers={
                            "Content-Disposition": f'attachment; filename="{safe_name}.pdf"'
                        }
                    )
                else:
                    raise HTTPException(
                        status_code=500,
                        detail=f"Impossible de générer le PDF pour {invoice_name}: {str(e)}"
                    )
            except HTTPException:
                raise
            except Exception as e2:
                raise HTTPException(
                    status_code=500,
                    detail=f"Erreur génération PDF: {str(e)} / {str(e2)}"
                )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Erreur téléchargement PDF: {e}")
        raise HTTPException(status_code=500, detail=str(e))