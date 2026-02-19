"""
Module de gestion des écritures comptables

Permet de créer des écritures comptables via API avec encryption RSA.
"""

from fastapi import APIRouter, HTTPException, Request, Header
from typing import Optional
from datetime import datetime
import logging
from pydantic import BaseModel, Field

from core.encryption import decrypt_webhook_data
from core.odoo_client import OdooClient
from models.responses import ApiResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/accounting", tags=["Accounting"])


class CreditAccountRequest(BaseModel):
    """Modèle pour créer une écriture de crédit"""
    partner_id: int = Field(..., description="ID de l'entreprise (res.partner)")
    amount: float = Field(..., gt=0, description="Montant à créditer (doit être > 0)")
    reference: str = Field(..., description="Référence de la transaction (ex: KKIAPAY-XXX)")
    date: Optional[str] = Field(None, description="Date de l'écriture (YYYY-MM-DD)")
    description: Optional[str] = Field(None, description="Description de l'écriture")
    journal_id: Optional[int] = Field(None, description="ID du journal comptable (optionnel, sera détecté automatiquement)")


# Configuration par défaut pour les écritures comptables
DEFAULT_CREDIT_ACCOUNT = "419101"  # Compte client à créditer
DEFAULT_DEBIT_ACCOUNT = "411100"   # Compte de contrepartie à débiter


@router.post("/credit-account", response_model=ApiResponse)
async def credit_customer_account(
    request: Request,
    x_encrypted_data: Optional[str] = Header(None, description="Données encryptées en base64")
):
    """
    Créer une écriture comptable de crédit sur le compte 419101
    
    **Sécurité**: Les données doivent être encryptées avec RSA et envoyées dans le header `x-encrypted-data`.
    
    **Données encryptées (JSON):**
    ```json
    {
        "partner_id": 123,
        "amount": 50000,
        "reference": "KKIAPAY-TRX-12345",
        "date": "2026-02-19",
        "description": "Recharge compte fuel"
    }
    ```
    
    **Processus:**
    1. Décrypte les données du header
    2. Recherche les comptes comptables (419101 et compte de débit)
    3. Crée l'écriture comptable (account.move) avec deux lignes:
       - Ligne débit: Compte banque/caisse
       - Ligne crédit: Compte client 419101
    4. Valide l'écriture automatiquement
    5. Met à jour le solde du client
    
    **Retourne:**
    - ID de l'écriture créée
    - Numéro de pièce comptable
    - Statut de validation
    """
    try:
        # Vérifier que les données encryptées sont présentes
        if not x_encrypted_data:
            logger.error("❌ Données encryptées manquantes dans le header")
            raise HTTPException(
                status_code=401,
                detail="Données encryptées requises dans le header x-encrypted-data"
            )
        
        # Décrypter les données
        try:
            logger.info("🔓 Décryption des données...")
            data = decrypt_webhook_data(x_encrypted_data)
            logger.info(f"✅ Données décryptées: partner_id={data.get('partner_id')}, amount={data.get('amount')}")
        except Exception as e:
            logger.error(f"❌ Erreur décryption: {e}")
            raise HTTPException(
                status_code=401,
                detail="Impossible de décrypter les données. Vérifiez l'encryption."
            )
        
        # Valider les données avec Pydantic
        try:
            credit_request = CreditAccountRequest(**data)
        except Exception as e:
            logger.error(f"❌ Données invalides: {e}")
            raise HTTPException(
                status_code=400,
                detail=f"Données invalides: {str(e)}"
            )
        
        # Créer un client Odoo avec les credentials par défaut
        # (car cet endpoint n'a pas d'authentification JWT)
        client = OdooClient()
        
        # Vérifier que le partenaire existe
        partner = client.execute_kw(
            'res.partner',
            'search_read',
            [[('id', '=', credit_request.partner_id)]],
            {'fields': ['id', 'name', 'credit'], 'limit': 1}
        )
        
        if not partner:
            logger.error(f"❌ Partenaire {credit_request.partner_id} non trouvé")
            raise HTTPException(
                status_code=404,
                detail=f"Partenaire {credit_request.partner_id} non trouvé"
            )
        
        partner = partner[0]
        logger.info(f"✅ Partenaire trouvé: {partner['name']} (crédit actuel: {partner['credit']})")
        
        # Récupérer les comptes comptables par leur code
        # Compte crédit 419101 (compte client)
        credit_account = client.execute_kw(
            'account.account',
            'search_read',
            [[('code', '=', DEFAULT_CREDIT_ACCOUNT)]],
            {'fields': ['id', 'name', 'code', 'company_id'], 'limit': 1}
        )
        
        if not credit_account:
            logger.error(f"❌ Compte {DEFAULT_CREDIT_ACCOUNT} non trouvé")
            raise HTTPException(
                status_code=404,
                detail=f"Compte comptable {DEFAULT_CREDIT_ACCOUNT} non trouvé dans Odoo"
            )
        
        credit_account = credit_account[0]
        company_id = credit_account['company_id'][0] if credit_account.get('company_id') else None
        logger.info(f"✅ Compte crédit: {credit_account['code']} - {credit_account['name']}")
        if company_id:
            logger.info(f"   Société: {credit_account['company_id'][1]} (ID: {company_id})")
        
        # Récupérer le compte de débit (411100)
        debit_account = client.execute_kw(
            'account.account',
            'search_read',
            [[('code', '=', DEFAULT_DEBIT_ACCOUNT)]],
            {'fields': ['id', 'name', 'code', 'company_id'], 'limit': 1}
        )
        
        if not debit_account:
            logger.error(f"❌ Compte {DEFAULT_DEBIT_ACCOUNT} non trouvé")
            raise HTTPException(
                status_code=404,
                detail=f"Compte comptable {DEFAULT_DEBIT_ACCOUNT} non trouvé dans Odoo"
            )
        
        debit_account = debit_account[0]
        logger.info(f"✅ Compte débit: {debit_account['code']} - {debit_account['name']}")
        
        # Déterminer le journal à utiliser
        journal_id = credit_request.journal_id
        
        if not journal_id:
            # Chercher un journal de type 'general' ou 'sale' dans la MÊME société
            logger.info("🔍 Recherche d'un journal comptable...")
            
            # Préparer les filtres
            domain = [('type', 'in', ['general', 'sale'])]
            if company_id:
                domain.append(('company_id', '=', company_id))
            
            journals = client.execute_kw(
                'account.journal',
                'search_read',
                [domain],
                {'fields': ['id', 'name', 'code', 'type', 'company_id'], 'limit': 1, 'order': 'id asc'}
            )
            
            if not journals:
                error_msg = f"Aucun journal comptable de type 'general' ou 'sale' trouvé"
                if company_id:
                    error_msg += f" pour la société ID {company_id}"
                raise HTTPException(
                    status_code=404,
                    detail=error_msg
                )
            
            journal = journals[0]
            journal_id = journal['id']
            logger.info(f"✅ Journal automatique: {journal['code']} - {journal['name']} (ID: {journal_id})")
            if journal.get('company_id'):
                logger.info(f"   Société: {journal['company_id'][1]}")
        
        # Préparer la date
        move_date = credit_request.date or datetime.now().strftime('%Y-%m-%d')
        
        # Préparer la description
        description = credit_request.description or f"Recharge compte - {credit_request.reference}"
        
        # Créer l'écriture comptable (account.move) avec DEUX lignes équilibrées
        move_vals = {
            'move_type': 'entry',
            'date': move_date,
            'ref': credit_request.reference,
            'journal_id': journal_id,
            'line_ids': [
                # Ligne de débit sur compte 411100
                (0, 0, {
                    'account_id': debit_account['id'],
                    'partner_id': credit_request.partner_id,
                    'name': description,
                    'debit': credit_request.amount,
                    'credit': 0.0,
                }),
                # Ligne de crédit sur compte client 419101
                (0, 0, {
                    'account_id': credit_account['id'],
                    'partner_id': credit_request.partner_id,
                    'name': description,
                    'debit': 0.0,
                    'credit': credit_request.amount,
                })
            ]
        }
        
        logger.info(f"📝 Création de l'écriture comptable équilibrée...")
        logger.info(f"   Débit  {debit_account['code']}: {credit_request.amount}")
        logger.info(f"   Crédit {credit_account['code']}: {credit_request.amount}")
        
        # Créer l'écriture
        try:
            move_id = client.execute_kw('account.move', 'create', [move_vals])
            logger.info(f"✅ Écriture créée: ID={move_id}")
        except Exception as e:
            logger.error(f"❌ Erreur création écriture: {e}")
            raise HTTPException(
                status_code=500,
                detail=f"Erreur lors de la création de l'écriture: {str(e)}"
            )
        
        # Valider l'écriture (passer à l'état 'posted')
        try:
            client.execute_kw('account.move', 'action_post', [[move_id]])
            logger.info(f"✅ Écriture validée (posted)")
        except Exception as e:
            logger.warning(f"⚠️  Impossible de valider automatiquement: {e}")
            # Ce n'est pas critique, l'écriture existe en brouillon
        
        # Récupérer les informations de l'écriture créée
        created_move = client.execute_kw(
            'account.move',
            'read',
            [move_id],
            {'fields': ['id', 'name', 'ref', 'state', 'date', 'amount_total']}
        )
        
        if created_move:
            created_move = created_move[0]
            logger.info(f"✅ Écriture créée: {created_move['name']}")
            logger.info(f"   État: {created_move['state']}")
            logger.info(f"   Référence: {created_move['ref']}")
        
        # Récupérer le nouveau solde du client
        updated_partner = client.execute_kw(
            'res.partner',
            'read',
            [credit_request.partner_id],
            {'fields': ['credit', 'debit']}
        )
        
        new_credit = updated_partner[0]['credit'] if updated_partner else None
        
        logger.info(f"💰 Nouveau solde client: {new_credit}")
        
        return ApiResponse(
            success=True,
            data={
                'move_id': move_id,
                'move_name': created_move['name'] if created_move else None,
                'move_state': created_move['state'] if created_move else 'draft',
                'partner_id': credit_request.partner_id,
                'partner_name': partner['name'],
                'amount': credit_request.amount,
                'reference': credit_request.reference,
                'date': move_date,
                'accounts': {
                    'debit': f"{debit_account['code']} - {debit_account['name']}",
                    'credit': f"{credit_account['code']} - {credit_account['name']}"
                },
                'old_balance': partner['credit'],
                'new_balance': new_credit
            },
            message=f"Écriture comptable créée avec succès pour {partner['name']} - Montant: {credit_request.amount}"
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Erreur inattendue: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Erreur lors du traitement: {str(e)}"
        )


@router.get("/accounts/{account_code}", response_model=ApiResponse)
async def get_account_info(
    account_code: str,
    x_encrypted_data: Optional[str] = Header(None)
):
    """
    Récupérer les informations d'un compte comptable par son code
    
    Endpoint de vérification pour s'assurer que les comptes existent.
    Également protégé par encryption.
    """
    try:
        # Vérifier l'encryption (même pour GET)
        if not x_encrypted_data:
            raise HTTPException(
                status_code=401,
                detail="Données encryptées requises"
            )
        
        # Décrypter (même si vide, pour validation)
        try:
            decrypt_webhook_data(x_encrypted_data)
        except Exception as e:
            raise HTTPException(
                status_code=401,
                detail="Encryption invalide"
            )
        
        client = OdooClient()
        
        account = client.execute_kw(
            'account.account',
            'search_read',
            [[('code', '=', account_code)]],
            {'fields': ['id', 'name', 'code', 'account_type', 'currency_id'], 'limit': 1}
        )
        
        if not account:
            raise HTTPException(
                status_code=404,
                detail=f"Compte {account_code} non trouvé"
            )
        
        return ApiResponse(
            success=True,
            data=account[0],
            message=f"Compte {account_code} trouvé"
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Erreur: {e}")
        raise HTTPException(status_code=500, detail=str(e))
