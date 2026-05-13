from fastapi import APIRouter, Depends, HTTPException, Path, Body, Query
from fastapi.responses import Response
from typing import List, Dict, Any, Optional
import time
import base64
from datetime import datetime

from models.schemas import (
    PosProductSearchRequest, PosOrderCreateRequest, PosShopUpdateRequest,
    PosShopArchiveRequest, PosShop, PosSessionStatus, PosSessionInitializeRequest,
    PosSessionResponse, PosPump, PosOpenSessionRequest, PosCloseSessionRequest,
    PumpDetails, PumpSelectionRequest, PosOrderCreateFullRequest,
    CashRegisterCloseRequest, PumpIndexValidation, CashRegisterValidation,
    StationPumpData, PosOpenSessionWithPumpsRequest, PosUnifiedOpenSessionRequest,
    PosCreateRequest, PosEmployeeAssignmentRequest, PosConfigResponse,
    ProductCreateRequest, PosProductAssignmentRequest, StockMovementRequest,
    StockLevelRequest, ProductStockResponse, StockPickingResponse,
    StockPickingStateUpdateRequest, StockPickingListRequest,
    PosOrderCreateSimpleRequest, PosAddPaymentRequest,
    PosPaymentMethodCreateRequest
)
from models.responses import ApiResponse
from core.security import require_scope
from core.odoo_client import get_odoo_client
from core.config import logger
from core.pump_manager import pump_manager
from api.accounting import _generate_pdf_via_wizard

router = APIRouter(prefix="/pos", tags=["Point de Vente"])

# ===== HELPER FUNCTIONS =====

def verify_manager_role(current_user: dict, client) -> bool:
    """
    Vérifie si l'utilisateur actuel est un gérant
    
    Args:
        current_user: Données de l'utilisateur depuis le token JWT
        client: Client Odoo pour les requêtes
        
    Returns:
        bool: True si gérant, False sinon
    """
    is_manager = False
    
    if current_user.get("auth_type") == "pin":
        # Vérifier d'abord dans les additional_info
        additional_info = current_user.get("additional_info", {})
        job_title = additional_info.get("job", "").lower() if additional_info.get("job") else ""
        
        logger.debug(f"Vérification gérant pour {current_user.get('username')}: job={job_title}")
        is_manager = 'gérant' in job_title or 'manager' in job_title or 'chef' in job_title or 'responsable' in job_title
        
        # Si pas trouvé dans additional_info, chercher dans Odoo
        if not is_manager and current_user.get("employee_id"):
            try:
                employee_data = client.execute_kw(
                    'hr.employee',
                    'read',
                    [current_user["employee_id"]],
                    {'fields': ['job_id']}
                )
                if employee_data and employee_data[0].get('job_id'):
                    job_name = employee_data[0]['job_id'][1].lower()
                    logger.debug(f"Job depuis Odoo: {job_name}")
                    is_manager = any(keyword in job_name for keyword in ['gérant', 'manager', 'chef', 'responsable'])
            except Exception as e:
                logger.warning(f"Erreur lors de la récupération du job depuis Odoo: {e}")
    
    return is_manager

# ===== LISTE DES POINTS DE VENTE =====

@router.get("/list", response_model=ApiResponse, summary="Lister tous les points de vente")
async def list_all_pos_configs(
    active_only: bool = True,
    page: int = Query(1, ge=1, description="Numéro de page (commence à 1)"),
    page_size: int = Query(20, ge=1, description="Nombre d'éléments par page"),
    current_user: dict = Depends(require_scope("pos"))
):
    """
    Lister tous les points de vente (POS) disponibles dans la base de données authentifiée
    
    Cette route retourne les configurations de points de vente accessibles pour l'employé connecté.
    Par défaut, filtre uniquement les POS actifs de la société de l'employé.
    
    **Pagination :**
    - **page** : Numéro de page (défaut: 1)
    - **page_size** : Nombre d'éléments par page (défaut: 20, pas de limite)
    
    **Informations retournées pour chaque POS :**
    - **id** : Identifiant unique du POS
    - **name** : Nom du point de vente
    - **company_id** : Société associée
    - **warehouse_id** : Entrepôt associé
    - **picking_type_id** : Type d'opération de stock
    - **session_state** : État de la session en cours (opened/closed/opening_control/closing_control)
    - **current_session_id** : ID de la session active (si existante)
    - **pricelist_id** : Liste de prix par défaut
    - **currency_id** : Devise utilisée
    - **iface_tax_included** : Prix TTC affichés
    - **cash_control** : Contrôle de caisse activé
    
    **Utilité :**
    - Connaître les POS ID disponibles pour vos requêtes API
    - Vérifier l'état des sessions
    - Identifier les configurations actives
    
    **Requires:** Authentification JWT avec scope 'pos'
    """
    try:
        from core.security import get_odoo_config_from_user
        
        client = get_odoo_client(current_user)
        
        # Récupérer la configuration de la base authentifiée
        db_config = get_odoo_config_from_user(current_user)
        db_name = db_config['name'] if db_config else "Base par défaut"
        
        # Construire le domaine de recherche
        domain = []
        
        # Filtrer par statut actif si demandé
        if active_only:
            domain.append(('active', '=', True))
        
        # Récupérer la société de l'employé pour filtrer
        employee_id = current_user.get('employee_id')
        
        if employee_id:
            try:
                # Récupérer la société de l'employé connecté
                employee = client.execute_kw(
                    'hr.employee',
                    'read',
                    [employee_id],
                    {'fields': ['company_id']}
                )
                
                if employee and employee[0].get('company_id'):
                    company_id = employee[0]['company_id'][0] if isinstance(employee[0]['company_id'], list) else employee[0]['company_id']
                    domain.append(('company_id', '=', company_id))
                    logger.info(f"Filtrage des POS par société ID {company_id} de l'employé {employee_id}")
            except Exception as e:
                    logger.warning(f"Impossible de filtrer par société de l'employé: {e}")
        
        # Compter le total d'éléments pour la pagination
        total_count = client.execute_kw(
            'pos.config',
            'search_count',
            [domain]
        )
        
        # Calculer l'offset pour la pagination
        offset = (page - 1) * page_size
        
        # Paramètres de recherche avec pagination
        search_params = {
            'fields': [
                'id', 'name', 'company_id', 'warehouse_id', 
                'picking_type_id', 'current_session_id',
                'pricelist_id', 'currency_id', 'iface_tax_included',
                'cash_control', 'module_pos_hr', 'active'
            ],
            'order': 'id asc',
            'limit': page_size,
            'offset': offset
        }
        
        logger.info(f"Recherche POS avec domaine: {domain}, page: {page}, page_size: {page_size}")        # Rechercher les POS configs avec les filtres
        pos_configs = client.execute_kw(
            'pos.config',
            'search_read',
            [domain],
            search_params
        )
        
        if not pos_configs:
            logger.warning(f"Aucun point de vente trouvé dans la base {db_name}")
            return {
                "success": True,
                "message": f"Aucun point de vente trouvé dans la base de données {db_name}",
                "data": [],
                "metadata": {
                    "database": db_name,
                    "total_count": 0,
                    "page": page,
                    "page_size": page_size,
                    "total_pages": 0
                }
            }
        
        # Enrichir les données avec des informations supplémentaires
        enriched_pos = []
        for pos in pos_configs:
            # Déterminer l'état de la session
            current_session_id = pos['current_session_id'][0] if isinstance(pos['current_session_id'], list) else pos.get('current_session_id')
            session_state = 'closed'
            balance = 0.0
            
            # Si une session existe, récupérer son état et le solde
            if current_session_id:
                try:
                    session = client.execute_kw(
                        'pos.session',
                        'read',
                        [current_session_id],
                        {'fields': ['state', 'cash_register_balance_end_real', 'cash_register_balance_start']}
                    )
                    if session and len(session) > 0:
                        session_state = session[0].get('state', 'closed')
                        # Récupérer le solde de la session active
                        balance = float(session[0].get('cash_register_balance_end_real', 0) or 
                                      session[0].get('cash_register_balance_start', 0) or 0)
                except Exception as e:
                    logger.warning(f"Erreur récupération session pour POS {pos['id']}: {e}")
                    session_state = 'opened'  # Assumer que la session est ouverte si l'ID existe
                    balance = 0.0
            else:
                # Si pas de session active, récupérer le solde de la dernière session fermée
                try:
                    last_sessions = client.execute_kw(
                        'pos.session',
                        'search_read',
                        [[('config_id', '=', pos['id']), ('state', '=', 'closed')]],
                        {'fields': ['cash_register_balance_end_real'], 'order': 'create_date desc', 'limit': 1}
                    )
                    if last_sessions:
                        balance = float(last_sessions[0].get('cash_register_balance_end_real', 0) or 0)
                except Exception as e:
                    logger.warning(f"Impossible de récupérer le dernier solde pour POS {pos['id']}: {e}")
                    balance = 0.0
            
            pos_data = {
                "id": pos['id'],
                "name": pos['name'],
                "active": pos.get('active', True),
                "odoo_database": db_name,
                "company": {
                    "id": pos['company_id'][0] if isinstance(pos['company_id'], list) else pos['company_id'],
                    "name": pos['company_id'][1] if isinstance(pos['company_id'], list) and len(pos['company_id']) > 1 else "N/A"
                } if pos.get('company_id') else None,
                "warehouse": {
                    "id": pos['warehouse_id'][0] if isinstance(pos['warehouse_id'], list) else pos['warehouse_id'],
                    "name": pos['warehouse_id'][1] if isinstance(pos['warehouse_id'], list) and len(pos['warehouse_id']) > 1 else "N/A"
                } if pos.get('warehouse_id') else None,
                "picking_type": {
                    "id": pos['picking_type_id'][0] if isinstance(pos['picking_type_id'], list) else pos['picking_type_id'],
                    "name": pos['picking_type_id'][1] if isinstance(pos['picking_type_id'], list) and len(pos['picking_type_id']) > 1 else "N/A"
                } if pos.get('picking_type_id') else None,
                "session_state": session_state,
                "current_session_id": current_session_id,
                "balance": balance,
                "pricelist": {
                    "id": pos['pricelist_id'][0] if isinstance(pos['pricelist_id'], list) else pos['pricelist_id'],
                    "name": pos['pricelist_id'][1] if isinstance(pos['pricelist_id'], list) and len(pos['pricelist_id']) > 1 else "N/A"
                } if pos.get('pricelist_id') else None,
                "currency": {
                    "id": pos['currency_id'][0] if isinstance(pos['currency_id'], list) else pos['currency_id'],
                    "name": pos['currency_id'][1] if isinstance(pos['currency_id'], list) and len(pos['currency_id']) > 1 else "N/A"
                } if pos.get('currency_id') else None,
                "settings": {
                    "tax_included": pos.get('iface_tax_included', False),
                    "cash_control": pos.get('cash_control', False),
                    "employee_login": pos.get('module_pos_hr', False)
                }
            }
            
            enriched_pos.append(pos_data)
        
        logger.info(f"{len(pos_configs)} point(s) de vente trouvé(s) dans la base {db_name}")
        
        # Calculer le nombre total de pages
        total_pages = (total_count + page_size - 1) // page_size
        
        return {
            "success": True,
            "message": f"{len(pos_configs)} point(s) de vente trouvé(s)",
            "data": enriched_pos,
            "metadata": {
                "database": db_name,
                "total_count": total_count,
                "page": page,
                "page_size": page_size,
                "total_pages": total_pages,
                "active_count": sum(1 for p in pos_configs if p.get('active', True)),
                "with_open_session": sum(1 for p in enriched_pos if p.get('session_state') == 'opened')
            }
        }
        
    except Exception as e:
        logger.error(f"Erreur lors de la récupération des points de vente: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Erreur lors de la récupération des points de vente: {str(e)}"
        )

# ===== GESTION ADMINISTRATIVE DES PDV =====

@router.post("/create", response_model=ApiResponse)
async def create_pos_config(
    config_data: PosCreateRequest = Body(...),
    current_user: dict = Depends(require_scope("pos"))
):
    """
    Créer un nouveau point de vente (PDV) - Gérants uniquement
    
    Cette route permet de créer une nouvelle configuration de point de vente dans Odoo.
    
    **Paramètres obligatoires :**
    - **name** : Nom du point de vente
    
    **Paramètres optionnels :**
    - **company_id** : ID de la société (par défaut : société principale)
    - **picking_type_id** : Type d'opération pour les livraisons
    - **journal_id** : Journal comptable pour les écritures POS
    - **currency_id** : Devise du PDV
    - **pricelist_id** : Liste de prix par défaut
    - **receipt_header/footer** : Personnalisation des reçus
    - **cash_control** : Contrôle de caisse avancé (défaut: True)
    - **module_pos_hr** : Connexion par employés (défaut: True)
    
    **Requires:** Authentification JWT avec scope 'pos' + Profil gérant
    """
    try:
        client = get_odoo_client(current_user)
        
        # Vérifier si l'utilisateur est gérant
        if not verify_manager_role(current_user, client):
            raise HTTPException(
                status_code=403,
                detail="Seuls les gérants peuvent créer un point de vente"
            )
        
        # Vérifier que le nom n'existe pas déjà
        existing_pos = client.execute_kw(
            'pos.config',
            'search',
            [[('name', '=', config_data.name)]]
        )
        
        if existing_pos:
            raise HTTPException(
                status_code=400,
                detail=f"Un PDV avec le nom '{config_data.name}' existe déjà"
            )
        
        # Préparer les données de création
        pos_vals = {
            'name': config_data.name,
            'iface_tax_included': config_data.iface_tax_included,
            'cash_control': config_data.cash_control,
            'module_pos_hr': config_data.module_pos_hr,
        }
        
        # Ajouter les champs optionnels s'ils sont fournis
        if config_data.company_id:
            pos_vals['company_id'] = config_data.company_id
        else:
            # Récupérer la société par défaut
            try:
                company = client.execute_kw('res.company', 'search', [[]], {'limit': 1})
                if company:
                    pos_vals['company_id'] = company[0]
            except Exception as e:
                logger.warning(f"Impossible de récupérer la société par défaut: {e}")
        
        if config_data.picking_type_id:
            pos_vals['picking_type_id'] = config_data.picking_type_id
        else:
            # Essayer de trouver un type d'opération par défaut
            try:
                picking_types = client.execute_kw(
                    'stock.picking.type',
                    'search',
                    [[('code', '=', 'outgoing'), ('warehouse_id.company_id', '=', pos_vals.get('company_id'))]],
                    {'limit': 1}
                )
                if picking_types:
                    pos_vals['picking_type_id'] = picking_types[0]
            except Exception as e:
                logger.warning(f"Impossible de récupérer le type d'opération par défaut: {e}")
        
        if config_data.journal_id:
            pos_vals['journal_id'] = config_data.journal_id
        
        if config_data.currency_id:
            pos_vals['currency_id'] = config_data.currency_id
        
        if config_data.pricelist_id:
            pos_vals['pricelist_id'] = config_data.pricelist_id
        
        if config_data.receipt_header:
            pos_vals['receipt_header'] = config_data.receipt_header
        
        if config_data.receipt_footer:
            pos_vals['receipt_footer'] = config_data.receipt_footer
        
        # Créer le PDV
        pos_id = client.execute_kw('pos.config', 'create', [pos_vals])
        
        # Récupérer les informations du PDV créé
        pos_config = client.execute_kw(
            'pos.config',
            'read',
            [pos_id],
            {'fields': ['id', 'name', 'company_id', 'active', 'basic_employee_ids', 'advanced_employee_ids']}
        )[0]
        
        logger.info(f"PDV créé avec succès: {config_data.name} (ID: {pos_id})")
        
        return ApiResponse(
            success=True,
            data={
                'pos_id': pos_id,
                'name': pos_config['name'],
                'company_id': pos_config.get('company_id'),
                'active': pos_config.get('active', True),
                'created': True
            },
            message=f"Point de vente '{config_data.name}' créé avec succès"
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Erreur lors de la création du PDV: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Erreur lors de la création du PDV: {str(e)}"
        )

@router.put("/{pos_id}", response_model=ApiResponse, summary="Modifier un point de vente")
async def update_pos_config(
    pos_id: int = Path(..., description="ID du point de vente à modifier"),
    config_data: PosCreateRequest = Body(...),
    current_user: dict = Depends(require_scope("pos"))
):
    """
    Modifier les informations d'un point de vente - Gérants uniquement
    
    Cette route permet de mettre à jour la configuration d'un point de vente existant.
    
    **Paramètres modifiables :**
    - **name** : Nom du point de vente
    - **company_id** : ID de la société
    - **picking_type_id** : Type d'opération pour les livraisons
    - **journal_id** : Journal comptable
    - **currency_id** : Devise du PDV
    - **pricelist_id** : Liste de prix
    - **receipt_header/footer** : Personnalisation des reçus
    - **cash_control** : Contrôle de caisse
    - **module_pos_hr** : Connexion par employés
    
    **Requires:** Authentification JWT avec scope 'pos' + Profil gérant
    """
    try:
        client = get_odoo_client(current_user)
        
        # Vérifier si l'utilisateur est gérant
        if not verify_manager_role(current_user, client):
            raise HTTPException(
                status_code=403,
                detail="Seuls les gérants peuvent modifier un point de vente"
            )
        
        # Vérifier que le PDV existe
        existing_pos = client.execute_kw(
            'pos.config',
            'search_read',
            [[('id', '=', pos_id)]],
            {'fields': ['id', 'name'], 'limit': 1}
        )
        
        if not existing_pos:
            raise HTTPException(status_code=404, detail="Point de vente non trouvé")
        
        # Vérifier que le nouveau nom n'est pas déjà utilisé par un autre PDV
        if config_data.name != existing_pos[0]['name']:
            name_conflict = client.execute_kw(
                'pos.config',
                'search',
                [[('name', '=', config_data.name), ('id', '!=', pos_id)]]
            )
            
            if name_conflict:
                raise HTTPException(
                    status_code=400,
                    detail=f"Un PDV avec le nom '{config_data.name}' existe déjà"
                )
        
        # Préparer les données de mise à jour
        update_vals = {
            'name': config_data.name,
            'iface_tax_included': config_data.iface_tax_included,
            'cash_control': config_data.cash_control,
            'module_pos_hr': config_data.module_pos_hr,
        }
        
        # Ajouter les champs optionnels s'ils sont fournis
        if config_data.company_id:
            update_vals['company_id'] = config_data.company_id
        
        if config_data.picking_type_id:
            update_vals['picking_type_id'] = config_data.picking_type_id
        
        if config_data.journal_id:
            update_vals['journal_id'] = config_data.journal_id
        
        if config_data.currency_id:
            update_vals['currency_id'] = config_data.currency_id
        
        if config_data.pricelist_id:
            update_vals['pricelist_id'] = config_data.pricelist_id
        
        if config_data.receipt_header:
            update_vals['receipt_header'] = config_data.receipt_header
        
        if config_data.receipt_footer:
            update_vals['receipt_footer'] = config_data.receipt_footer
        
        # Mettre à jour le PDV
        client.execute_kw('pos.config', 'write', [[pos_id], update_vals])
        
        # Récupérer les informations mises à jour
        updated_pos = client.execute_kw(
            'pos.config',
            'read',
            [pos_id],
            {'fields': ['id', 'name', 'company_id', 'active']}
        )[0]
        
        logger.info(f"PDV modifié avec succès: {config_data.name} (ID: {pos_id})")
        
        return ApiResponse(
            success=True,
            data={
                'pos_id': pos_id,
                'name': updated_pos['name'],
                'company_id': updated_pos.get('company_id'),
                'active': updated_pos.get('active', True),
                'updated': True
            },
            message=f"Point de vente '{config_data.name}' modifié avec succès"
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Erreur lors de la modification du PDV: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Erreur lors de la modification du PDV: {str(e)}"
        )

@router.delete("/{pos_id}", response_model=ApiResponse, summary="Supprimer un point de vente")
async def delete_pos_config(
    pos_id: int = Path(..., description="ID du point de vente à supprimer"),
    force: bool = False,
    current_user: dict = Depends(require_scope("pos"))
):
    """
    Supprimer (archiver) un point de vente - Gérants uniquement
    
    Cette route permet d'archiver un point de vente (désactivation).
    Par défaut, le PDV est seulement désactivé (archive) pour préserver l'historique.
    
    **Paramètres :**
    - **force** : Si True, supprime définitivement le PDV (⚠️ DANGER : perte de données)
    
    **Sécurité :**
    - Impossible de supprimer un PDV avec une session active
    - La suppression force n'est autorisée que si aucune session n'existe
    
    **Requires:** Authentification JWT avec scope 'pos' + Profil gérant
    """
    try:
        client = get_odoo_client(current_user)
        
        # Vérifier si l'utilisateur est gérant
        if not verify_manager_role(current_user, client):
            raise HTTPException(
                status_code=403,
                detail="Seuls les gérants peuvent supprimer un point de vente"
            )
        
        # Vérifier que le PDV existe
        pos_config = client.execute_kw(
            'pos.config',
            'search_read',
            [[('id', '=', pos_id)]],
            {'fields': ['id', 'name', 'current_session_id'], 'limit': 1}
        )
        
        if not pos_config:
            raise HTTPException(status_code=404, detail="Point de vente non trouvé")
        
        pos_config = pos_config[0]
        pos_name = pos_config['name']
        
        # Vérifier s'il y a une session active
        if pos_config.get('current_session_id'):
            raise HTTPException(
                status_code=400,
                detail="Impossible de supprimer un PDV avec une session active. Fermez d'abord la session."
            )
        
        if force:
            # Vérifier s'il existe des sessions (même fermées)
            existing_sessions = client.execute_kw(
                'pos.session',
                'search_count',
                [[('config_id', '=', pos_id)]]
            )
            
            if existing_sessions > 0:
                raise HTTPException(
                    status_code=400,
                    detail=f"Impossible de supprimer définitivement : {existing_sessions} session(s) existent. Utilisez l'archivage (force=false) à la place."
                )
            
            # Suppression définitive
            client.execute_kw('pos.config', 'unlink', [[pos_id]])
            
            logger.warning(f"PDV SUPPRIMÉ DÉFINITIVEMENT: {pos_name} (ID: {pos_id})")
            
            return ApiResponse(
                success=True,
                data={
                    'pos_id': pos_id,
                    'deleted': True,
                    'permanently': True
                },
                message=f"Point de vente '{pos_name}' supprimé définitivement"
            )
        else:
            # Archivage (désactivation)
            client.execute_kw('pos.config', 'write', [[pos_id], {'active': False}])
            
            logger.info(f"PDV archivé: {pos_name} (ID: {pos_id})")
            
            return ApiResponse(
                success=True,
                data={
                    'pos_id': pos_id,
                    'archived': True,
                    'permanently': False
                },
                message=f"Point de vente '{pos_name}' archivé avec succès"
            )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Erreur lors de la suppression du PDV: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Erreur lors de la suppression du PDV: {str(e)}"
        )

@router.post("/{pos_id}/assign-employees", response_model=ApiResponse)
async def assign_employees_to_pos(
    pos_id: int = Path(..., description="ID du point de vente"),
    assignment_data: PosEmployeeAssignmentRequest = Body(...),
    current_user: dict = Depends(require_scope("pos"))
):
    """
    Affecter des employés à un point de vente
    
    Cette route permet d'affecter ou de retirer des employés d'un PDV avec deux niveaux d'accès :
    - **basic** : Accès employé standard (basic_employee_ids)
    - **advanced** : Accès manager/gérant (advanced_employee_ids)
    
    **Paramètres :**
    - **employee_ids** : Liste des IDs d'employés à affecter
    - **access_level** : Niveau d'accès ("basic" ou "advanced")
    - **replace** : True pour remplacer les affectations existantes, False pour ajouter
    
    **Requires:** Authentification JWT avec scope 'pos'
    """
    try:
        client = get_odoo_client(current_user)
        
        # Vérifier que le PDV existe
        pos_config = client.execute_kw(
            'pos.config',
            'search_read',
            [[('id', '=', pos_id)]],
            {'fields': ['id', 'name', 'basic_employee_ids', 'advanced_employee_ids'], 'limit': 1}
        )
        
        if not pos_config:
            raise HTTPException(status_code=404, detail="Point de vente non trouvé")
        
        pos_config = pos_config[0]
        
        # Vérifier que tous les employés existent
        valid_employees = client.execute_kw(
            'hr.employee',
            'search',
            [[('id', 'in', assignment_data.employee_ids), ('active', '=', True)]]
        )
        
        if len(valid_employees) != len(assignment_data.employee_ids):
            invalid_ids = set(assignment_data.employee_ids) - set(valid_employees)
            raise HTTPException(
                status_code=400,
                detail=f"Employés introuvables ou inactifs: {list(invalid_ids)}"
            )
        
        # Déterminer le champ à mettre à jour
        field_name = f"{assignment_data.access_level}_employee_ids"
        current_employees = pos_config.get(field_name, [])
        
        # Calculer les nouvelles affectations
        if assignment_data.replace:
            # Remplacer complètement
            new_employees = assignment_data.employee_ids
            action_msg = "remplacées"
        else:
            # Ajouter aux existants (éviter les doublons)
            new_employees = list(set(current_employees + assignment_data.employee_ids))
            action_msg = "ajoutées"
        
        # Mettre à jour le PDV
        update_vals = {field_name: [(6, 0, new_employees)]}  # (6, 0, ids) = remplacer par cette liste
        
        success = client.execute_kw(
            'pos.config',
            'write',
            [[pos_id], update_vals]
        )
        
        if not success:
            raise HTTPException(
                status_code=500,
                detail="Erreur lors de la mise à jour des affectations"
            )
        
        # Récupérer les noms des employés pour la réponse
        employee_names = client.execute_kw(
            'hr.employee',
            'read',
            [assignment_data.employee_ids],
            {'fields': ['id', 'name']}
        )
        
        logger.info(f"Affectations {action_msg} pour PDV {pos_config['name']}: {len(assignment_data.employee_ids)} employés ({assignment_data.access_level})")
        
        return ApiResponse(
            success=True,
            data={
                'pos_id': pos_id,
                'pos_name': pos_config['name'],
                'access_level': assignment_data.access_level,
                'employees_assigned': [{'id': emp['id'], 'name': emp['name']} for emp in employee_names],
                'total_employees': len(new_employees),
                'action': 'replaced' if assignment_data.replace else 'added'
            },
            message=f"{len(assignment_data.employee_ids)} employé(s) affecté(s) au PDV '{pos_config['name']}' avec accès {assignment_data.access_level}"
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Erreur lors de l'affectation des employés au PDV {pos_id}: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Erreur lors de l'affectation: {str(e)}"
        )

@router.get("/{pos_id}/config", response_model=ApiResponse)
async def get_pos_config_details(
    pos_id: int = Path(..., description="ID du point de vente"),
    current_user: dict = Depends(require_scope("pos"))
):
    """
    Récupérer les détails de configuration d'un PDV
    
    Cette route retourne les informations détaillées d'un point de vente,
    y compris les employés affectés et la session active.
    
    **Requires:** Authentification JWT avec scope 'pos'
    """
    try:
        client = get_odoo_client(current_user)
        
        # Récupérer la configuration du PDV
        pos_config = client.execute_kw(
            'pos.config',
            'search_read',
            [[('id', '=', pos_id)]],
            {'fields': [
                'id', 'name', 'company_id', 'active', 'basic_employee_ids', 'advanced_employee_ids',
                'current_session_id', 'current_session_state', 'receipt_header', 'receipt_footer',
                'cash_control', 'module_pos_hr', 'journal_id', 'currency_id', 'pricelist_id'
            ], 'limit': 1}
        )
        
        if not pos_config:
            raise HTTPException(status_code=404, detail="Point de vente non trouvé")
        
        pos_config = pos_config[0]
        
        # Récupérer les noms des employés affectés
        all_employee_ids = pos_config.get('basic_employee_ids', []) + pos_config.get('advanced_employee_ids', [])
        employee_details = {}
        
        if all_employee_ids:
            employees = client.execute_kw(
                'hr.employee',
                'read',
                [all_employee_ids],
                {'fields': ['id', 'name', 'job_id']}
            )
            employee_details = {emp['id']: emp for emp in employees}
        
        # Construire la réponse avec les détails des employés
        basic_employees = [
            {
                'id': emp_id,
                'name': employee_details.get(emp_id, {}).get('name', f'Employé {emp_id}'),
                'job': employee_details.get(emp_id, {}).get('job_id', [None, 'Non défini'])[1] if employee_details.get(emp_id, {}).get('job_id') else 'Non défini'
            }
            for emp_id in pos_config.get('basic_employee_ids', [])
        ]
        
        advanced_employees = [
            {
                'id': emp_id,
                'name': employee_details.get(emp_id, {}).get('name', f'Employé {emp_id}'),
                'job': employee_details.get(emp_id, {}).get('job_id', [None, 'Non défini'])[1] if employee_details.get(emp_id, {}).get('job_id') else 'Non défini'
            }
            for emp_id in pos_config.get('advanced_employee_ids', [])
        ]
        
        config_details = {
            'id': pos_config['id'],
            'name': pos_config['name'],
            'company_id': pos_config.get('company_id'),
            'active': pos_config.get('active', True),
            'current_session_id': pos_config.get('current_session_id'),
            'current_session_state': pos_config.get('current_session_state'),
            'employees': {
                'basic': basic_employees,
                'advanced': advanced_employees,
                'total': len(basic_employees) + len(advanced_employees)
            },
            'configuration': {
                'cash_control': pos_config.get('cash_control', False),
                'module_pos_hr': pos_config.get('module_pos_hr', False),
                'receipt_header': pos_config.get('receipt_header'),
                'receipt_footer': pos_config.get('receipt_footer'),
                'journal_id': pos_config.get('journal_id'),
                'currency_id': pos_config.get('currency_id'),
                'pricelist_id': pos_config.get('pricelist_id')
            }
        }
        
        return ApiResponse(
            success=True,
            data=config_details,
            message=f"Configuration du PDV '{pos_config['name']}' récupérée"
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Erreur lors de la récupération de la config PDV {pos_id}: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Erreur lors de la récupération: {str(e)}"
        )

# ===== GESTION DES PRODUITS ET STOCK =====

@router.post("/products/create", response_model=ApiResponse)
async def create_product(
    product_data: ProductCreateRequest = Body(...),
    current_user: dict = Depends(require_scope("pos"))
):
    """
    Créer un nouveau produit dans Odoo
    
    Cette route permet de créer un produit avec toutes les informations nécessaires
    pour une utilisation dans le POS et la gestion de stock.
    
    **Champs obligatoires :**
    - **name** : Nom du produit
    - **list_price** : Prix de vente public
    
    **Champs optionnels :**
    - **default_code** : Référence interne
    - **barcode** : Code-barres
    - **categ_id** : Catégorie de produit
    - **type** : Type (product/service/consu)
    - **taxes_id** : Taxes applicables
    - **description** : Description détaillée
    
    **Requires:** Authentification JWT avec scope 'pos'
    """
    try:
        client = get_odoo_client(current_user)
        
        # Vérifier si le produit existe déjà (par nom ou code)
        domain = [('name', '=', product_data.name)]
        if product_data.default_code:
            domain = ['|', ('name', '=', product_data.name), ('default_code', '=', product_data.default_code)]
        
        existing_products = client.execute_kw(
            'product.template',
            'search',
            [domain]
        )
        
        if existing_products:
            raise HTTPException(
                status_code=400,
                detail=f"Un produit avec ce nom ou cette référence existe déjà"
            )
        
        # Préparer les données du produit
        product_vals = {
            'name': product_data.name,
            'list_price': product_data.list_price,
            'standard_price': product_data.standard_price or 0.0,
            'type': product_data.type,
            'active': product_data.active,
            'sale_ok': product_data.sale_ok,
            'purchase_ok': product_data.purchase_ok,
            'available_in_pos': product_data.available_in_pos,
            'weight': product_data.weight or 0.0,
            'volume': product_data.volume or 0.0,
        }
        
        # Ajouter les champs optionnels
        if product_data.default_code:
            product_vals['default_code'] = product_data.default_code
        
        if product_data.barcode:
            product_vals['barcode'] = product_data.barcode
        
        if product_data.description:
            product_vals['description'] = product_data.description
        
        if product_data.description_sale:
            product_vals['description_sale'] = product_data.description_sale
        
        # Gérer la catégorie
        if product_data.categ_id:
            product_vals['categ_id'] = product_data.categ_id
        else:
            # Récupérer la catégorie par défaut "Tous"
            try:
                default_categ = client.execute_kw(
                    'product.category',
                    'search',
                    [['|', ('name', '=', 'All'), ('name', '=', 'Tous')]],
                    {'limit': 1}
                )
                if default_categ:
                    product_vals['categ_id'] = default_categ[0]
            except Exception as e:
                logger.warning(f"Impossible de récupérer la catégorie par défaut: {e}")
        
        # Gérer les unités de mesure
        if product_data.uom_id:
            product_vals['uom_id'] = product_data.uom_id
            product_vals['uom_po_id'] = product_data.uom_po_id or product_data.uom_id
        else:
            # Récupérer l'unité "Unité" par défaut
            try:
                default_uom = client.execute_kw(
                    'uom.uom',
                    'search',
                    [['|', ('name', '=', 'Unit'), ('name', '=', 'Unité')]],
                    {'limit': 1}
                )
                if default_uom:
                    product_vals['uom_id'] = default_uom[0]
                    product_vals['uom_po_id'] = default_uom[0]
            except Exception as e:
                logger.warning(f"Impossible de récupérer l'unité par défaut: {e}")
        
        # Gérer les taxes
        if product_data.taxes_id:
            product_vals['taxes_id'] = [(6, 0, product_data.taxes_id)]
        
        if product_data.supplier_taxes_id:
            product_vals['supplier_taxes_id'] = [(6, 0, product_data.supplier_taxes_id)]
        
        # Créer le produit
        product_id = client.execute_kw('product.template', 'create', [product_vals])
        
        # Récupérer les informations du produit créé
        product_info = client.execute_kw(
            'product.template',
            'read',
            [product_id],
            {'fields': ['id', 'name', 'default_code', 'list_price', 'categ_id', 'available_in_pos']}
        )[0]
        
        logger.info(f"Produit créé avec succès: {product_data.name} (ID: {product_id})")
        
        return ApiResponse(
            success=True,
            data={
                'product_id': product_id,
                'name': product_info['name'],
                'default_code': product_info.get('default_code'),
                'list_price': product_info['list_price'],
                'category': product_info.get('categ_id'),
                'available_in_pos': product_info.get('available_in_pos'),
                'created': True
            },
            message=f"Produit '{product_data.name}' créé avec succès"
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Erreur lors de la création du produit: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Erreur lors de la création du produit: {str(e)}"
        )

@router.post("/{pos_id}/products/assign", response_model=ApiResponse)
async def assign_products_to_pos(
    pos_id: int = Path(..., description="ID du point de vente"),
    assignment_data: PosProductAssignmentRequest = Body(...),
    current_user: dict = Depends(require_scope("pos"))
):
    """
    Ajouter des produits à un point de vente
    
    Cette route permet d'ajouter ou de remplacer les produits disponibles dans un PDV.
    Seuls les produits marqués comme 'available_in_pos' peuvent être ajoutés.
    
    **Paramètres :**
    - **product_ids** : Liste des IDs de produits à ajouter
    - **replace** : True pour remplacer tous les produits, False pour ajouter
    
    **Requires:** Authentification JWT avec scope 'pos'
    """
    try:
        client = get_odoo_client(current_user)
        
        # Vérifier que le PDV existe
        pos_config = client.execute_kw(
            'pos.config',
            'search_read',
            [[('id', '=', pos_id)]],
            {'fields': ['id', 'name'], 'limit': 1}
        )
        
        if not pos_config:
            raise HTTPException(status_code=404, detail="Point de vente non trouvé")
        
        pos_config = pos_config[0]
        
        # Vérifier que tous les produits existent et sont disponibles pour le POS
        products_info = client.execute_kw(
            'product.template',
            'search_read',
            [[('id', 'in', assignment_data.product_ids)]],
            {'fields': ['id', 'name', 'available_in_pos', 'active']}
        )
        
        if len(products_info) != len(assignment_data.product_ids):
            found_ids = [p['id'] for p in products_info]
            missing_ids = set(assignment_data.product_ids) - set(found_ids)
            raise HTTPException(
                status_code=400,
                detail=f"Produits introuvables: {list(missing_ids)}"
            )
        
        # Vérifier que tous les produits sont disponibles pour le POS
        unavailable_products = [p for p in products_info if not p.get('available_in_pos') or not p.get('active')]
        if unavailable_products:
            unavailable_names = [p['name'] for p in unavailable_products]
            raise HTTPException(
                status_code=400,
                detail=f"Produits non disponibles pour le POS: {unavailable_names}"
            )
        
        # Récupérer les produits actuellement assignés au PDV
        current_products = []
        try:
            # Note: Dans Odoo, les produits POS sont généralement gérés via les catégories
            # ou via un champ many2many sur pos.config si il existe
            # Ici on va essayer de récupérer via les catégories disponibles
            pos_full_config = client.execute_kw(
                'pos.config',
                'read',
                [pos_id],
                {'fields': ['iface_available_categ_ids']}
            )[0]
            
            if pos_full_config.get('iface_available_categ_ids'):
                # Récupérer les produits des catégories actuelles
                current_products_search = client.execute_kw(
                    'product.template',
                    'search',
                    [[('categ_id', 'in', pos_full_config['iface_available_categ_ids']), ('available_in_pos', '=', True)]]
                )
                current_products = current_products_search
        except Exception as e:
            logger.warning(f"Impossible de récupérer les produits actuels du PDV: {e}")
        
        # Pour cette implémentation, on va utiliser les catégories des produits
        # Récupérer les catégories des produits à ajouter
        new_categories = list(set([p.get('categ_id')[0] for p in products_info if p.get('categ_id')]))
        
        # Déterminer les catégories finales
        if assignment_data.replace:
            final_categories = new_categories
            action_msg = "remplacés"
        else:
            # Récupérer les catégories actuelles
            current_categories = pos_full_config.get('iface_available_categ_ids', []) if 'pos_full_config' in locals() else []
            final_categories = list(set(current_categories + new_categories))
            action_msg = "ajoutés"
        
        # Mettre à jour les catégories disponibles dans le PDV
        update_vals = {
            'iface_available_categ_ids': [(6, 0, final_categories)] if final_categories else False
        }
        
        success = client.execute_kw(
            'pos.config',
            'write',
            [[pos_id], update_vals]
        )
        
        if not success:
            raise HTTPException(
                status_code=500,
                detail="Erreur lors de la mise à jour des produits du PDV"
            )
        
        logger.info(f"Produits {action_msg} pour PDV {pos_config['name']}: {len(assignment_data.product_ids)} produits")
        
        return ApiResponse(
            success=True,
            data={
                'pos_id': pos_id,
                'pos_name': pos_config['name'],
                'products_assigned': [{'id': p['id'], 'name': p['name']} for p in products_info],
                'categories_updated': final_categories,
                'action': 'replaced' if assignment_data.replace else 'added'
            },
            message=f"{len(assignment_data.product_ids)} produit(s) {action_msg} au PDV '{pos_config['name']}'"
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Erreur lors de l'affectation des produits au PDV {pos_id}: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Erreur lors de l'affectation: {str(e)}"
        )

@router.post("/{pos_id}/stock/movement", response_model=ApiResponse)
async def create_stock_movement(
    pos_id: int = Path(..., description="ID du point de vente"),
    movement_data: StockMovementRequest = Body(...),
    current_user: dict = Depends(require_scope("pos"))
):
    """
    Créer un mouvement de stock pour un produit
    
    Cette route permet de faire des entrées ou sorties de stock pour un produit
    dans l'emplacement associé au point de vente.
    
    **Paramètres :**
    - **product_id** : ID du produit
    - **quantity** : Quantité (+ pour entrée, - pour sortie)
    - **reference** : Référence du mouvement
    - **reason** : Raison du mouvement
    
    **Requires:** Authentification JWT avec scope 'pos'
    """
    try:
        client = get_odoo_client(current_user)
        
        # Vérifier que le PDV existe et récupérer son entrepôt
        pos_config = client.execute_kw(
            'pos.config',
            'search_read',
            [[('id', '=', pos_id)]],
            {'fields': ['id', 'name', 'picking_type_id', 'warehouse_id'], 'limit': 1}
        )
        
        if not pos_config:
            raise HTTPException(status_code=404, detail="Point de vente non trouvé")
        
        pos_config = pos_config[0]
        
        # Vérifier que le produit existe
        product_info = client.execute_kw(
            'product.product',
            'search_read',
            [[('id', '=', movement_data.product_id)]],
            {'fields': ['id', 'name', 'default_code', 'type'], 'limit': 1}
        )
        
        if not product_info:
            raise HTTPException(status_code=404, detail="Produit non trouvé")
        
        product_info = product_info[0]
        
        if product_info['type'] != 'product':
            raise HTTPException(
                status_code=400,
                detail="Les mouvements de stock ne sont possibles que pour les produits stockables"
            )
        
        # Déterminer les emplacements
        if movement_data.location_id and movement_data.location_dest_id:
            location_src = movement_data.location_id
            location_dest = movement_data.location_dest_id
        else:
            # Récupérer l'emplacement de stock du PDV
            try:
                warehouse_id = pos_config.get('warehouse_id')
                if warehouse_id:
                    warehouse_id = warehouse_id[0] if isinstance(warehouse_id, list) else warehouse_id
                    warehouse_info = client.execute_kw(
                        'stock.warehouse',
                        'read',
                        [warehouse_id],
                        {'fields': ['lot_stock_id']}
                    )
                    stock_location = warehouse_info[0]['lot_stock_id'][0] if warehouse_info else None
                else:
                    # Récupérer l'emplacement de stock par défaut
                    stock_locations = client.execute_kw(
                        'stock.location',
                        'search',
                        [[('usage', '=', 'internal')]],
                        {'limit': 1}
                    )
                    stock_location = stock_locations[0] if stock_locations else None
                
                if not stock_location:
                    raise HTTPException(
                        status_code=400,
                        detail="Impossible de déterminer l'emplacement de stock"
                    )
                
                # Récupérer l'emplacement d'inventaire
                inventory_location = client.execute_kw(
                    'stock.location',
                    'search',
                    [[('usage', '=', 'inventory')]],
                    {'limit': 1}
                )
                
                if not inventory_location:
                    raise HTTPException(
                        status_code=400,
                        detail="Emplacement d'inventaire non trouvé"
                    )
                
                inventory_location = inventory_location[0]
                
                # Déterminer source et destination selon le type de mouvement
                if movement_data.quantity > 0:
                    # Entrée de stock : depuis inventaire vers stock
                    location_src = inventory_location
                    location_dest = stock_location
                else:
                    # Sortie de stock : depuis stock vers inventaire
                    location_src = stock_location
                    location_dest = inventory_location
                    movement_data.quantity = abs(movement_data.quantity)  # Quantité positive
                    
            except Exception as e:
                logger.error(f"Erreur lors de la récupération des emplacements: {e}")
                raise HTTPException(
                    status_code=500,
                    detail="Erreur lors de la configuration des emplacements"
                )
        
        # Créer le mouvement de stock
        move_vals = {
            'name': movement_data.reference or f"Mouvement {product_info['name']}",
            'product_id': movement_data.product_id,
            'product_uom_qty': movement_data.quantity,
            'location_id': location_src,
            'location_dest_id': location_dest,
            'origin': movement_data.reason or f"POS {pos_config['name']}"
        }
        
        # Récupérer l'unité de mesure du produit
        try:
            product_uom = client.execute_kw(
                'product.product',
                'read',
                [movement_data.product_id],
                {'fields': ['uom_id']}
            )[0]
            move_vals['product_uom'] = product_uom['uom_id'][0]
        except Exception as e:
            logger.warning(f"Impossible de récupérer l'UOM du produit: {e}")
        
        move_id = client.execute_kw('stock.move', 'create', [move_vals])
        
        # Confirmer et valider le mouvement
        try:
            # Confirmer le mouvement
            client.execute_kw('stock.move', 'action_confirm', [[move_id]])
            
            # Forcer la disponibilité (pour les mouvements d'inventaire)
            client.execute_kw('stock.move', 'action_assign', [[move_id]])
            
            # Valider le mouvement
            client.execute_kw('stock.move', 'action_done', [[move_id]])
            
        except Exception as e:
            logger.warning(f"Erreur lors de la validation du mouvement: {e}")
            # Le mouvement est créé mais pas forcément validé
        
        # Récupérer le stock mis à jour
        try:
            stock_info = client.execute_kw(
                'stock.quant',
                'search_read',
                [[('product_id', '=', movement_data.product_id), ('location_id', '=', location_dest if movement_data.quantity > 0 else location_src)]],
                {'fields': ['quantity'], 'limit': 1}
            )
            new_stock = stock_info[0]['quantity'] if stock_info else 0
        except Exception as e:
            logger.warning(f"Impossible de récupérer le stock mis à jour: {e}")
            new_stock = "Non disponible"
        
        logger.info(f"Mouvement de stock créé: {product_info['name']} - Quantité: {movement_data.quantity}")
        
        return ApiResponse(
            success=True,
            data={
                'move_id': move_id,
                'product_id': movement_data.product_id,
                'product_name': product_info['name'],
                'quantity': movement_data.quantity,
                'location_src': location_src,
                'location_dest': location_dest,
                'new_stock': new_stock,
                'reference': move_vals['name']
            },
            message=f"Mouvement de stock créé: {movement_data.quantity} {product_info['name']}"
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Erreur lors de la création du mouvement de stock: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Erreur lors du mouvement de stock: {str(e)}"
        )

@router.get("/{pos_id}/stock/{product_id}", response_model=ApiResponse)
async def get_product_stock_level(
    pos_id: int = Path(..., description="ID du point de vente"),
    product_id: int = Path(..., description="ID du produit"),
    current_user: dict = Depends(require_scope("pos"))
):
    """
    Récupérer le niveau de stock d'un produit pour un PDV
    
    Cette route retourne le stock actuel, réservé et disponible d'un produit
    dans l'emplacement associé au point de vente.
    
    **Requires:** Authentification JWT avec scope 'pos'
    """
    try:
        client = get_odoo_client(current_user)
        
        # Vérifier que le PDV et le produit existent
        pos_config = client.execute_kw(
            'pos.config',
            'search_read',
            [[('id', '=', pos_id)]],
            {'fields': ['id', 'name', 'warehouse_id'], 'limit': 1}
        )
        
        if not pos_config:
            raise HTTPException(status_code=404, detail="Point de vente non trouvé")
        
        product_info = client.execute_kw(
            'product.product',
            'search_read',
            [[('id', '=', product_id)]],
            {'fields': ['id', 'name', 'default_code', 'type', 'uom_id'], 'limit': 1}
        )
        
        if not product_info:
            raise HTTPException(status_code=404, detail="Produit non trouvé")
        
        pos_config = pos_config[0]
        product_info = product_info[0]
        
        if product_info['type'] != 'product':
            # Pour les services et consommables, retourner stock infini
            return ApiResponse(
                success=True,
                data=ProductStockResponse(
                    product_id=product_id,
                    product_name=product_info['name'],
                    product_code=product_info.get('default_code'),
                    current_stock=999999,
                    available_stock=999999,
                    unit_of_measure=product_info.get('uom_id', [None, 'Unité'])[1],
                    location_name="Service/Consommable",
                    last_update=datetime.now().isoformat()
                ).dict(),
                message="Produit de type service/consommable - Stock illimité"
            )
        
        # Récupérer l'emplacement de stock du PDV
        warehouse_id = pos_config.get('warehouse_id')
        stock_location_id = None
        location_name = "Stock principal"
        
        if warehouse_id:
            warehouse_id = warehouse_id[0] if isinstance(warehouse_id, list) else warehouse_id
            try:
                warehouse_info = client.execute_kw(
                    'stock.warehouse',
                    'read',
                    [warehouse_id],
                    {'fields': ['lot_stock_id', 'name']}
                )
                if warehouse_info:
                    stock_location_id = warehouse_info[0]['lot_stock_id'][0]
                    location_name = f"Stock {warehouse_info[0]['name']}"
            except Exception as e:
                logger.warning(f"Erreur récupération entrepôt: {e}")
        
        if not stock_location_id:
            # Récupérer l'emplacement de stock par défaut
            stock_locations = client.execute_kw(
                'stock.location',
                'search_read',
                [[('usage', '=', 'internal')]],
                {'fields': ['id', 'name'], 'limit': 1}
            )
            if stock_locations:
                stock_location_id = stock_locations[0]['id']
                location_name = stock_locations[0]['name']
        
        if not stock_location_id:
            raise HTTPException(
                status_code=400,
                detail="Impossible de déterminer l'emplacement de stock du PDV"
            )
        
        # Récupérer les informations de stock
        stock_quants = client.execute_kw(
            'stock.quant',
            'search_read',
            [[('product_id', '=', product_id), ('location_id', '=', stock_location_id)]],
            {'fields': ['quantity', 'reserved_quantity']}
        )
        
        current_stock = sum(q['quantity'] for q in stock_quants)
        reserved_stock = sum(q['reserved_quantity'] for q in stock_quants)
        available_stock = current_stock - reserved_stock
        
        # Récupérer l'unité de mesure
        uom_name = product_info.get('uom_id', [None, 'Unité'])[1] if product_info.get('uom_id') else 'Unité'
        
        stock_response = ProductStockResponse(
            product_id=product_id,
            product_name=product_info['name'],
            product_code=product_info.get('default_code'),
            current_stock=current_stock,
            reserved_stock=reserved_stock,
            available_stock=available_stock,
            unit_of_measure=uom_name,
            location_name=location_name,
            last_update=datetime.now().isoformat()
        )
        
        return ApiResponse(
            success=True,
            data=stock_response.dict(),
            message=f"Stock de {product_info['name']}: {available_stock} {uom_name} disponible(s)"
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Erreur lors de la récupération du stock: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Erreur lors de la récupération du stock: {str(e)}"
        )

@router.post("/{pos_id}/stock/{product_id}/adjust", response_model=ApiResponse)
async def adjust_product_stock(
    pos_id: int = Path(..., description="ID du point de vente"),
    product_id: int = Path(..., description="ID du produit"),
    adjustment_data: StockLevelRequest = Body(...),
    current_user: dict = Depends(require_scope("pos"))
):
    """
    Ajuster le niveau de stock d'un produit
    
    Cette route permet de définir directement la quantité en stock d'un produit
    en créant un ajustement d'inventaire.
    
    **Paramètres :**
    - **new_quantity** : Nouvelle quantité en stock
    - **reason** : Raison de l'ajustement
    
    **Requires:** Authentification JWT avec scope 'pos'
    """
    try:
        client = get_odoo_client(current_user)
        
        # D'abord récupérer le stock actuel
        current_stock_response = await get_product_stock_level(pos_id, product_id, current_user)
        current_stock_data = current_stock_response.data
        current_stock = current_stock_data['current_stock']
        
        # Calculer la différence
        quantity_diff = adjustment_data.new_quantity - current_stock
        
        if abs(quantity_diff) < 0.001:  # Pas de changement significatif
            return ApiResponse(
                success=True,
                data=current_stock_data,
                message="Aucun ajustement nécessaire - stock déjà à la bonne valeur"
            )
        
        # Créer un mouvement d'ajustement via StockMovementRequest
        movement_request = StockMovementRequest(
            product_id=product_id,
            quantity=quantity_diff,
            reference=f"Ajustement stock - {adjustment_data.reason}",
            reason=adjustment_data.reason
        )
        
        # Utiliser l'endpoint de mouvement de stock
        movement_response = await create_stock_movement(pos_id, movement_request, current_user)
        
        if not movement_response.success:
            raise HTTPException(
                status_code=500,
                detail="Erreur lors de la création du mouvement d'ajustement"
            )
        
        # Récupérer le nouveau stock
        updated_stock_response = await get_product_stock_level(pos_id, product_id, current_user)
        
        logger.info(f"Ajustement de stock: {current_stock_data['product_name']} - {current_stock} → {adjustment_data.new_quantity}")
        
        return ApiResponse(
            success=True,
            data={
                'adjustment': {
                    'previous_stock': current_stock,
                    'new_stock': adjustment_data.new_quantity,
                    'quantity_diff': quantity_diff,
                    'reason': adjustment_data.reason
                },
                'current_stock_info': updated_stock_response.data,
                'movement_info': movement_response.data
            },
            message=f"Stock ajusté: {current_stock} → {adjustment_data.new_quantity} {current_stock_data['unit_of_measure']}"
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Erreur lors de l'ajustement du stock: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Erreur lors de l'ajustement: {str(e)}"
        )

# ===== GESTION DES INVENTAIRES (STOCK.PICKING) =====

@router.get("/{pos_id}/inventory/transfers", response_model=ApiResponse)
async def get_pos_inventory_transfers(
    pos_id: int = Path(..., description="ID du point de vente"),
    state: Optional[str] = None,
    picking_type_code: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    partner_id: Optional[int] = None,
    page: int = Query(1, ge=1, description="Numéro de page (commence à 1)"),
    page_size: int = Query(50, ge=1, le=200, description="Nombre d'éléments par page (max 200)"),
    current_user: dict = Depends(require_scope("pos"))
):
    """
    Récupérer les transferts de stock (inventaires) pour un point de vente
    
    Cette route permet de consulter tous les transferts de stock (stock.picking)
    liés à un point de vente spécifique. Utile pour gérer les inventaires,
    réceptions, livraisons et transferts internes.
    
    **Pagination :**
    - **page** : Numéro de page (défaut: 1)
    - **page_size** : Nombre d'éléments par page (défaut: 50, max: 200)
    
    **Filtres disponibles :**
    - **state** : État du transfert (draft/waiting/ready/done/cancel)
    - **picking_type_code** : Type d'opération (incoming/outgoing/internal)
    - **date_from/date_to** : Période de recherche (YYYY-MM-DD)
    - **partner_id** : Filtrer par partenaire/fournisseur
    
    **États des transferts :**
    - **draft** : Brouillon, non confirmé
    - **waiting** : En attente d'une autre opération
    - **ready** : Prêt à être traité
    - **done** : Terminé/traité
    - **cancel** : Annulé
    
    **Requires:** Authentification JWT avec scope 'pos'
    """
    try:
        client = get_odoo_client(current_user)
        
        # Vérifier que le PDV existe et récupérer ses informations
        pos_config = client.execute_kw(
            'pos.config',
            'search_read',
            [[('id', '=', pos_id)]],
            {'fields': ['id', 'name', 'warehouse_id', 'company_id'], 'limit': 1}
        )
        
        if not pos_config:
            raise HTTPException(status_code=404, detail="Point de vente non trouvé")
        
        pos_config = pos_config[0]
        
        # Construire le domaine de recherche
        # STRATÉGIE: Filtrer par location_dest_id OU location_id pour attraper TOUS les transferts du PDV
        # - Arrivées (incoming/internal) : location_dest_id ILIKE "JO70/"
        # - Sorties (outgoing/internal) : location_id ILIKE "JO70/"
        # - Internes : location_id OU location_dest_id ILIKE "JO70/"
        domain = []
        
        if pos_config.get('warehouse_id'):
            try:
                warehouse_id = pos_config['warehouse_id'][0] if isinstance(pos_config['warehouse_id'], list) else pos_config['warehouse_id']
                logger.info(f"PDV {pos_config['name']} - warehouse_id: {warehouse_id}")
                
                # Extraire le code du PDV
                pos_name_short = pos_config['name'].split()[0]  # "JO70" de "JO70 COVE"
                pos_location_pattern = f"{pos_name_short}/"  # "JO70/"
                logger.info(f"Cherchant transferts pour PDV '{pos_name_short}' (pattern: '{pos_location_pattern}')")
                
                # Chercher les locations qui contiennent le code PDV dans leur chemin complet
                pos_locations = client.execute_kw(
                    'stock.location',
                    'search',
                    [[
                        ('warehouse_id', '=', warehouse_id),
                        ('usage', '=', 'internal'),
                        ('complete_name', 'ilike', pos_location_pattern)  # "JO70/"
                    ]],
                    {}
                )
                
                if pos_locations:
                    logger.info(f"Trouvé {len(pos_locations)} emplacements pour PDV {pos_name_short}")
                    # Filtrer les transferts où location_id OU location_dest_id appartient au PDV
                    # Cela capture :
                    # - Les arrivées (location_dest_id = JO70/Stock)
                    # - Les sorties (location_id = JO70/Stock)
                    # - Les internes (les deux)
                    domain = ['|',
                        ('location_dest_id', 'in', pos_locations),
                        ('location_id', 'in', pos_locations)
                    ]
                else:
                    logger.warning(f"Aucun emplacement trouvé pour PDV {pos_name_short}")
                    # Fallback: filtrer directement par ilike sur complete_name
                    # Cela capture les transferts arrivant ET partant du PDV
                    logger.info(f"Fallback: cherchant par location_id ou location_dest_id ilike '{pos_location_pattern}'...")
                    domain = ['|',
                        ('location_dest_id.complete_name', 'ilike', pos_location_pattern),
                        ('location_id.complete_name', 'ilike', pos_location_pattern)
                    ]
            except Exception as e:
                logger.error(f"Erreur récupération locations PDV: {e}")
                # Fallback: filtrer par société
                if pos_config.get('company_id'):
                    try:
                        company_id = pos_config['company_id'][0] if isinstance(pos_config['company_id'], list) else pos_config['company_id']
                        domain.append(('company_id', '=', company_id))
                        logger.info(f"Fallback after error: Filtrage par company_id: {company_id}")
                    except Exception as e2:
                        logger.warning(f"Impossible de filtrer par société: {e2}")
        elif pos_config.get('company_id'):
            # Si warehouse n'existe pas, utiliser company_id comme fallback
            try:
                company_id = pos_config['company_id'][0] if isinstance(pos_config['company_id'], list) else pos_config['company_id']
                domain.append(('company_id', '=', company_id))
                logger.info(f"Filtrage par company_id (pas de warehouse): {company_id}")
            except Exception as e:
                logger.warning(f"Impossible de filtrer par société: {e}")
        
        # **IMPORTANT:** Filtrer automatiquement par type de transfert en fonction de la base de données
        # MAIS: Si on filtre par warehouse du PDV, le picking_type_code est déjà implicitement filtré
        # via picking_type_id.warehouse_id, donc ne pas appliquer le filtre picking_type_code automatique
        from core.security import get_odoo_config_from_user
        
        db_config = get_odoo_config_from_user(current_user)
        
        # N'appliquer le filtre de picking_type_code que si c'est explicitement demandé
        # ET si on ne filtre pas par warehouse du PDV
        should_auto_filter_picking_type = (
            db_config and 'transfer_type_code' in db_config and 
            not (pos_config.get('warehouse_id'))  # Si pas de warehouse filtrage, appliquer auto-filter
        )
        
        if should_auto_filter_picking_type:
            # Si le code n'est pas fourni dans la requête, utiliser celui de la DB
            if not picking_type_code:
                picking_type_code = db_config['transfer_type_code']
                logger.info(f"Filtrage automatique par type de transfert de la DB: {picking_type_code}")
            else:
                # Si un code est fourni, vérifier qu'il correspond au type autorisé pour cette DB
                if picking_type_code != db_config['transfer_type_code']:
                    logger.warning(
                        f"Type de transfert '{picking_type_code}' demandé ne correspond pas "
                        f"au type autorisé '{db_config['transfer_type_code']}' pour cette base"
                    )
                    raise HTTPException(
                        status_code=403,
                        detail=f"Cette base de données ne gère que les transferts de type '{db_config['transfer_type_code']}'"
                    )
        elif picking_type_code is None and not should_auto_filter_picking_type:
            # Si pas d'auto-filter et pas de picking_type_code fourni, ne pas en ajouter
            logger.info(f"Pas de filtrage automatique picking_type (PDV avec warehouse spécifique)")
        
        # Ajouter les filtres optionnels
        if state:
            domain.append(('state', '=', state))
        
        if picking_type_code:
            domain.append(('picking_type_code', '=', picking_type_code))
            logger.info(f"Filtrage par picking_type_code: {picking_type_code}")
        
        if partner_id:
            domain.append(('partner_id', '=', partner_id))
        
        if date_from:
            domain.append(('date', '>=', f"{date_from} 00:00:00"))
        
        if date_to:
            domain.append(('date', '<=', f"{date_to} 23:59:59"))
        
        # Compter le total d'éléments pour la pagination
        total_count = client.execute_kw(
            'stock.picking',
            'search_count',
            [domain]
        )
        
        # Calculer l'offset pour la pagination
        offset = (page - 1) * page_size
        
        logger.info(f"Recherche transferts avec domaine: {domain}, page: {page}, page_size: {page_size}")
        
        # Récupérer les transferts avec tous les détails possibles
        fields = [
            # Champs de base
            'id', 'name', 'origin', 'state', 'picking_type_code', 'partner_id',
            'location_id', 'location_dest_id', 'scheduled_date', 'date_done',
            'user_id', 'company_id', 'products_availability', 'products_availability_state',
            'move_ids', 'pos_session_id', 'pos_order_id', 'note',
            
            # Champ personnalisé pour le code du transfert
            'x_studio_code',
            
            # Champs détaillés supplémentaires
            'picking_type_id', 'priority', 'date', 'date_deadline',
            'move_type', 'group_id', 'has_scrap_move', 'has_packages', 
            'show_check_availability', 'is_locked', 'package_level_ids', 
            'package_level_ids_details',
            
            # Informations produits et quantités
            'move_ids_without_package', 'move_line_ids', 'move_line_ids_without_package',
            'move_line_exist', 'show_operations', 'show_reserved',
            
            # Informations warehouse et stock
            'picking_type_entire_packs', 'use_create_lots', 'use_existing_lots',
            'printed', 'show_lots_text', 'has_tracking', 'owner_id',
            
            # Champs de workflow et validation
            'backorder_id', 'backorder_ids', 'return_id', 'return_ids', 'return_count',
            'signature', 'is_signed', 'batch_id',
            
            # Informations utilisateur et création
            'create_date', 'write_date', 'create_uid', 'write_uid',
            
            # Champs de vente et achat
            'sale_id', 'purchase_id',
            
            # Autres champs utiles
            'json_popover', 'activity_ids', 'activity_state', 'activity_user_id', 
            'activity_type_id', 'message_needaction', 'message_has_error', 
            'message_attachment_count', 'country_code', 'has_deadline_issue',
            'delay_alert_date', 'quality_check_todo', 'quality_check_fail'
        ]
        
        # Essayer d'abord avec le champ personnalisé x_studio_code
        transfers = None
        try:
            transfers = client.execute_kw(
                'stock.picking',
                'search_read',
                [domain],
                {
                    'fields': fields,
                    'limit': page_size,
                    'offset': offset,
                    'order': 'date desc, id desc'
                }
            )
        except Exception as e:
            # Si x_studio_code n'existe pas, retirer ce champ et réessayer
            if 'x_studio_code' in str(e):
                logger.debug(f"Champ x_studio_code non disponible, récupération sans ce champ")
                fields.remove('x_studio_code')
                transfers = client.execute_kw(
                    'stock.picking',
                    'search_read',
                    [domain],
                    {
                        'fields': fields,
                        'limit': page_size,
                        'offset': offset,
                        'order': 'date desc, id desc'
                    }
                )
            else:
                raise
        
        # Enrichir chaque transfert avec les détails des mouvements
        for transfer in transfers:
            # Enrichir avec les détails des localisations (source et destination)
            location_details = {}
            location_ids_to_fetch = []
            
            # Collecter les IDs de localisation à récupérer
            if transfer.get('location_id') and isinstance(transfer['location_id'], (list, tuple)):
                location_ids_to_fetch.append(transfer['location_id'][0])
            elif transfer.get('location_id') and isinstance(transfer['location_id'], int):
                location_ids_to_fetch.append(transfer['location_id'])
            
            if transfer.get('location_dest_id') and isinstance(transfer['location_dest_id'], (list, tuple)):
                location_ids_to_fetch.append(transfer['location_dest_id'][0])
            elif transfer.get('location_dest_id') and isinstance(transfer['location_dest_id'], int):
                location_ids_to_fetch.append(transfer['location_dest_id'])
            
            # Récupérer les détails des localisations
            if location_ids_to_fetch:
                try:
                    # Dédupliquer les IDs
                    location_ids_to_fetch = list(set(location_ids_to_fetch))
                    
                    locations_data = client.execute_kw(
                        'stock.location',
                        'read',
                        [location_ids_to_fetch],
                        {
                            'fields': [
                                'id', 'name', 'complete_name', 'usage', 'active',
                                'warehouse_id', 'company_id', 'parent_path',
                                'barcode', 'location_id', 'comment', 'scrap_location',
                                'removal_strategy_id'
                            ]
                        }
                    )
                    
                    # Créer un mapping des localisations
                    location_details = {loc['id']: loc for loc in locations_data}
                
                except Exception as e:
                    logger.warning(f"Erreur récupération détails localisations pour transfert {transfer['id']}: {e}")
                    location_details = {}
            
            # Ajouter les détails des localisations au transfert
            transfer['location_source_details'] = None
            transfer['location_destination_details'] = None
            
            if transfer.get('location_id'):
                source_loc_id = transfer['location_id'][0] if isinstance(transfer['location_id'], (list, tuple)) else transfer['location_id']
                transfer['location_source_details'] = location_details.get(source_loc_id, None)
            
            if transfer.get('location_dest_id'):
                dest_loc_id = transfer['location_dest_id'][0] if isinstance(transfer['location_dest_id'], (list, tuple)) else transfer['location_dest_id']
                transfer['location_destination_details'] = location_details.get(dest_loc_id, None)
            
            # Enrichir avec les infos des acteurs (chauffeur, gérant, etc.)
            transfer['location_source_actor'] = None
            transfer['location_destination_actor'] = None
            transfer['related_contacts'] = []
            
            # Batch fetch pour les acteurs et partenaires
            partners_to_fetch = set()
            
            # Collecter les IDs de partenaires à récupérer
            if transfer.get('partner_id') and isinstance(transfer['partner_id'], (list, tuple)):
                partners_to_fetch.add(transfer['partner_id'][0])
            elif transfer.get('partner_id') and isinstance(transfer['partner_id'], int):
                partners_to_fetch.add(transfer['partner_id'])
            
            # Batch fetch des partenaires et leurs contacts
            partners_map = {}
            if partners_to_fetch:
                try:
                    partners_data = client.execute_kw(
                        'res.partner',
                        'read',
                        list(partners_to_fetch),
                        {'fields': ['id', 'name', 'phone', 'mobile', 'email', 'function', 'child_ids']}
                    )
                    partners_map = {p['id']: p for p in partners_data}
                except Exception as e:
                    logger.debug(f"Erreur récupération partenaires: {e}")
            
            # Batch fetch des contacts (enfants des partenaires)
            all_contact_ids = set()
            for partner_id in partners_to_fetch:
                partner = partners_map.get(partner_id)
                if partner and partner.get('child_ids'):
                    all_contact_ids.update(partner['child_ids'] if isinstance(partner['child_ids'], (list, tuple)) else [partner['child_ids']])
            
            contacts_map = {}
            if all_contact_ids:
                try:
                    contacts_data = client.execute_kw(
                        'res.partner',
                        'read',
                        list(all_contact_ids),
                        {'fields': ['id', 'name', 'phone', 'mobile', 'email', 'function']}
                    )
                    contacts_map = {c['id']: c for c in contacts_data}
                except Exception as e:
                    logger.debug(f"Erreur récupération contacts: {e}")
            
            # Détecter le partenaire source (qui expédie)
            source_actor = None
            if transfer.get('partner_id'):
                partner_id = transfer['partner_id'][0] if isinstance(transfer['partner_id'], (list, tuple)) else transfer['partner_id']
                source_actor = partners_map.get(partner_id)
            
            # Ajouter l'acteur source au transfert
            if source_actor:
                transfer['location_source_actor'] = {
                    'id': source_actor['id'],
                    'name': source_actor.get('name', ''),
                    'phone': source_actor.get('phone'),
                    'mobile': source_actor.get('mobile'),
                    'email': source_actor.get('email'),
                    'function': source_actor.get('function')
                }
            
            # Détecter le gérant de la station de destination (du POS actuel)
            destination_actor = None
            
            # Récupérer les gérants (advanced_employee_ids) du POS courant
            if pos_config.get('id'):
                try:
                    pos_managers = client.execute_kw(
                        'pos.config',
                        'read',
                        [pos_config['id']],
                        {'fields': ['advanced_employee_ids']}
                    )
                    
                    if pos_managers and pos_managers[0].get('advanced_employee_ids'):
                        # Récupérer le premier gérant
                        manager_id = pos_managers[0]['advanced_employee_ids'][0]
                        
                        try:
                            manager_data = client.execute_kw(
                                'hr.employee',
                                'read',
                                [manager_id],
                                {'fields': ['id', 'name', 'work_phone', 'mobile_phone', 'work_email', 'job_title']}
                            )
                            
                            if manager_data:
                                destination_actor = manager_data[0]
                        except Exception as e:
                            logger.debug(f"Erreur récupération gérant: {e}")
                except Exception as e:
                    logger.debug(f"Erreur récupération gérants du POS {pos_config.get('id')}: {e}")
            
            # Ajouter l'acteur destination au transfert
            if destination_actor:
                transfer['location_destination_actor'] = {
                    'id': destination_actor['id'],
                    'name': destination_actor.get('name', ''),
                    'phone': destination_actor.get('work_phone'),
                    'mobile': destination_actor.get('mobile_phone'),
                    'email': destination_actor.get('work_email'),
                    'function': destination_actor.get('job_title')
                }
            
            # Collecter tous les contacts associés
            related_contacts_set = set()
            if source_actor:
                related_contacts_set.add(source_actor['id'])
            
            for partner_id in partners_to_fetch:
                related_contacts_set.add(partner_id)
                partner = partners_map.get(partner_id)
                if partner and partner.get('child_ids'):
                    child_ids = partner['child_ids'] if isinstance(partner['child_ids'], (list, tuple)) else [partner['child_ids']]
                    related_contacts_set.update(child_ids)
            
            # Formater les contacts associés
            transfer['related_contacts'] = []
            for contact_id in related_contacts_set:
                if contact_id in partners_map:
                    contact = partners_map[contact_id]
                elif contact_id in contacts_map:
                    contact = contacts_map[contact_id]
                else:
                    continue
                
                transfer['related_contacts'].append({
                    'id': contact['id'],
                    'name': contact.get('name', ''),
                    'phone': contact.get('phone'),
                    'mobile': contact.get('mobile'),
                    'email': contact.get('email'),
                    'function': contact.get('function')
                })
            
            # Récupérer les détails des mouvements de stock (stock.move)
            if transfer.get('move_ids'):
                try:
                    move_details = client.execute_kw(
                        'stock.move',
                        'read',
                        [transfer['move_ids']],
                        {
                            'fields': [
                                'id', 'name', 'product_id', 'product_uom_qty', 'product_qty',
                                'product_uom', 'state', 'location_id', 'location_dest_id',
                                'date', 'date_deadline', 'origin', 'procure_method',
                                'description_picking', 'additional', 'picking_type_id', 
                                'warehouse_id', 'partner_id', 'company_id', 'price_unit',
                                'create_date', 'write_date', 'product_packaging_id',
                                'product_packaging_qty', 'availability', 'forecast_availability',
                                'reference', 'sequence', 'priority', 'picked'
                            ]
                        }
                    )
                    
                    # Enrichir avec les informations produits détaillées
                    product_ids = [move['product_id'][0] for move in move_details if move.get('product_id')]
                    if product_ids:
                        products_info = client.execute_kw(
                            'product.product',
                            'read',
                            [product_ids],
                            {
                                'fields': [
                                    'id', 'name', 'display_name', 'default_code', 'barcode', 'categ_id',
                                    'uom_id', 'uom_po_id', 'list_price', 'standard_price',
                                    'type', 'tracking', 'weight', 'volume', 'sale_ok', 
                                    'purchase_ok', 'active', 'description',
                                    'description_sale', 'description_purchase', 'taxes_id',
                                    'supplier_taxes_id', 'product_tmpl_id', 'product_variant_ids'
                                ]
                            }
                        )
                        
                        # Créer un mapping des produits
                        products_map = {p['id']: p for p in products_info}
                        
                        # Ajouter les infos produits aux mouvements
                        for move in move_details:
                            if move.get('product_id'):
                                product_id = move['product_id'][0]
                                move['product_details'] = products_map.get(product_id, {})
                    
                    transfer['move_details'] = move_details
                    
                except Exception as e:
                    logger.warning(f"Erreur récupération détails mouvements pour transfert {transfer['id']}: {e}")
                    transfer['move_details'] = []
            else:
                transfer['move_details'] = []
            
            # Récupérer les détails des opérations de stock (stock.move.line)
            if transfer.get('move_line_ids'):
                try:
                    move_line_details = client.execute_kw(
                        'stock.move.line',
                        'read',
                        [transfer['move_line_ids']],
                        {
                            'fields': [
                                'id', 'move_id', 'product_id', 'product_uom_id', 'qty_done',
                                'quantity', 'lot_id', 'lot_name', 'package_id',
                                'result_package_id', 'date', 'owner_id', 'location_id',
                                'location_dest_id', 'picking_id', 'company_id', 'state',
                                'reference', 'description_picking', 'picked', 'tracking',
                                'product_packaging_id', 'product_packaging_qty'
                            ]
                        }
                    )
                    transfer['move_line_details'] = move_line_details
                except Exception as e:
                    logger.warning(f"Erreur récupération détails move_line pour transfert {transfer['id']}: {e}")
                    transfer['move_line_details'] = []
            else:
                transfer['move_line_details'] = []
            
            # Ajouter des informations sur le type de picking avec plus de détails
            if transfer.get('picking_type_id'):
                try:
                    picking_type_info = client.execute_kw(
                        'stock.picking.type',
                        'read',
                        [transfer['picking_type_id'][0]],
                        {
                            'fields': [
                                'id', 'name', 'code', 'sequence_id', 'default_location_src_id',
                                'default_location_dest_id', 'warehouse_id', 'active',
                                'use_create_lots', 'use_existing_lots', 'show_entire_packs',
                                'show_reserved', 'show_operations', 'auto_show_reception_report',
                                'create_backorder', 'sequence_code', 'color'
                            ]
                        }
                    )
                    transfer['picking_type_details'] = picking_type_info[0] if picking_type_info else {}
                except Exception as e:
                    logger.warning(f"Erreur récupération type picking pour transfert {transfer['id']}: {e}")
                    transfer['picking_type_details'] = {}
            else:
                transfer['picking_type_details'] = {}
        
        # Formater les résultats - Créer directement le dictionnaire avec tous les détails
        def clean_odoo_value(value):
            """Nettoyer les valeurs False d'Odoo"""
            return None if value is False else value
        
        formatted_transfers = []
        for transfer in transfers:
            try:
                # Créer le dictionnaire complet avec nettoyage des valeurs False
                formatted_transfer = {
                    # Champs de base
                    'id': transfer['id'],
                    'name': transfer.get('name', ''),
                    'code': clean_odoo_value(transfer.get('x_studio_code')),
                    'origin': clean_odoo_value(transfer.get('origin')),
                    'state': transfer.get('state', 'draft'),
                    'picking_type_code': clean_odoo_value(transfer.get('picking_type_code')),
                    'partner_id': clean_odoo_value(transfer.get('partner_id')),
                    'location_id': clean_odoo_value(transfer.get('location_id')),
                    'location_dest_id': clean_odoo_value(transfer.get('location_dest_id')),
                    'scheduled_date': clean_odoo_value(transfer.get('scheduled_date')),
                    'date_done': clean_odoo_value(transfer.get('date_done')),
                    'user_id': clean_odoo_value(transfer.get('user_id')),
                    'company_id': clean_odoo_value(transfer.get('company_id')),
                    'products_availability': clean_odoo_value(transfer.get('products_availability')),
                    'products_availability_state': clean_odoo_value(transfer.get('products_availability_state')),
                    'move_ids': transfer.get('move_ids', []) if transfer.get('move_ids') is not False else [],
                    'pos_session_id': clean_odoo_value(transfer.get('pos_session_id')),
                    'pos_order_id': clean_odoo_value(transfer.get('pos_order_id')),
                    'note': clean_odoo_value(transfer.get('note')),
                    
                    # Champs détaillés supplémentaires
                    'picking_type_id': clean_odoo_value(transfer.get('picking_type_id')),
                    'priority': clean_odoo_value(transfer.get('priority')),
                    'date': clean_odoo_value(transfer.get('date')),
                    'date_deadline': clean_odoo_value(transfer.get('date_deadline')),
                    'move_type': clean_odoo_value(transfer.get('move_type')),
                    'group_id': clean_odoo_value(transfer.get('group_id')),
                    'has_scrap_move': clean_odoo_value(transfer.get('has_scrap_move')),
                    'has_packages': clean_odoo_value(transfer.get('has_packages')),
                    'is_locked': clean_odoo_value(transfer.get('is_locked')),
                    'package_level_ids': clean_odoo_value(transfer.get('package_level_ids')),
                    'package_level_ids_details': clean_odoo_value(transfer.get('package_level_ids_details')),
                    'show_check_availability': clean_odoo_value(transfer.get('show_check_availability')),
                    
                    # Informations produits et quantités
                    'move_ids_without_package': clean_odoo_value(transfer.get('move_ids_without_package')),
                    'move_line_ids': clean_odoo_value(transfer.get('move_line_ids')),
                    'move_line_ids_without_package': clean_odoo_value(transfer.get('move_line_ids_without_package')),
                    'move_line_exist': clean_odoo_value(transfer.get('move_line_exist')),
                    'show_operations': clean_odoo_value(transfer.get('show_operations')),
                    'show_reserved': clean_odoo_value(transfer.get('show_reserved')),
                    
                    # Informations warehouse et stock
                    'picking_type_entire_packs': clean_odoo_value(transfer.get('picking_type_entire_packs')),
                    'use_create_lots': clean_odoo_value(transfer.get('use_create_lots')),
                    'use_existing_lots': clean_odoo_value(transfer.get('use_existing_lots')),
                    'printed': clean_odoo_value(transfer.get('printed')),
                    'show_lots_text': clean_odoo_value(transfer.get('show_lots_text')),
                    'has_tracking': clean_odoo_value(transfer.get('has_tracking')),
                    'owner_id': clean_odoo_value(transfer.get('owner_id')),
                    
                    # Informations de workflow
                    'backorder_id': clean_odoo_value(transfer.get('backorder_id')),
                    'backorder_ids': clean_odoo_value(transfer.get('backorder_ids')),
                    'return_id': clean_odoo_value(transfer.get('return_id')),
                    'return_ids': clean_odoo_value(transfer.get('return_ids')),
                    'return_count': clean_odoo_value(transfer.get('return_count')),
                    'signature': clean_odoo_value(transfer.get('signature')),
                    'is_signed': clean_odoo_value(transfer.get('is_signed')),
                    'batch_id': clean_odoo_value(transfer.get('batch_id')),
                    
                    # Informations de dates et utilisateurs
                    'create_date': clean_odoo_value(transfer.get('create_date')),
                    'write_date': clean_odoo_value(transfer.get('write_date')),
                    'create_uid': clean_odoo_value(transfer.get('create_uid')),
                    'write_uid': clean_odoo_value(transfer.get('write_uid')),
                    
                    # Champs de vente et achat
                    'sale_id': clean_odoo_value(transfer.get('sale_id')),
                    'purchase_id': clean_odoo_value(transfer.get('purchase_id')),
                    
                    # Autres champs utiles
                    'json_popover': clean_odoo_value(transfer.get('json_popover')),
                    'activity_ids': clean_odoo_value(transfer.get('activity_ids')),
                    'activity_state': clean_odoo_value(transfer.get('activity_state')),
                    'activity_user_id': clean_odoo_value(transfer.get('activity_user_id')),
                    'activity_type_id': clean_odoo_value(transfer.get('activity_type_id')),
                    'message_needaction': clean_odoo_value(transfer.get('message_needaction')),
                    'message_has_error': clean_odoo_value(transfer.get('message_has_error')),
                    'message_attachment_count': clean_odoo_value(transfer.get('message_attachment_count')),
                    'country_code': clean_odoo_value(transfer.get('country_code')),
                    'has_deadline_issue': clean_odoo_value(transfer.get('has_deadline_issue')),
                    'delay_alert_date': clean_odoo_value(transfer.get('delay_alert_date')),
                    'quality_check_todo': clean_odoo_value(transfer.get('quality_check_todo')),
                    'quality_check_fail': clean_odoo_value(transfer.get('quality_check_fail')),
                    
                    # Détails enrichis
                    'move_details': transfer.get('move_details', []),
                    'move_line_details': transfer.get('move_line_details', []),
                    'carrier_details': transfer.get('carrier_details', {}),
                    'picking_type_details': transfer.get('picking_type_details', {}),
                    
                    # Détails des localisations (source et destination)
                    'location_source_details': transfer.get('location_source_details', None),
                    'location_destination_details': transfer.get('location_destination_details', None),
                    
                    # Détails des acteurs (chauffeur, gérant, etc.)
                    'location_source_actor': clean_odoo_value(transfer.get('location_source_actor')),
                    'location_destination_actor': clean_odoo_value(transfer.get('location_destination_actor')),
                    'related_contacts': transfer.get('related_contacts', []),
                }
                
                formatted_transfers.append(formatted_transfer)
                
            except Exception as e:
                logger.warning(f"Erreur formatage transfert {transfer.get('id', 'unknown')}: {e}")
                # En cas d'erreur, inclure au minimum les champs de base
                formatted_transfer = {
                    'id': transfer['id'],
                    'name': transfer.get('name', ''),
                    'state': transfer.get('state', 'draft'),
                    'error': f"Erreur formatage: {str(e)}"
                }
                formatted_transfers.append(formatted_transfer)
        
        logger.info(f"Récupération de {len(transfers)} transferts pour PDV {pos_config['name']}")
        
        # Calculer le nombre total de pages
        total_pages = (total_count + page_size - 1) // page_size
        
        return ApiResponse(
            success=True,
            data={
                'pos_info': {
                    'id': pos_id,
                    'name': pos_config['name'],
                    'warehouse_id': pos_config.get('warehouse_id'),
                    'company_id': pos_config.get('company_id'),
                },
                'transfers': formatted_transfers,
                'filters_applied': {
                    'state': state,
                    'picking_type_code': picking_type_code,
                    'date_from': date_from,
                    'date_to': date_to,
                    'partner_id': partner_id
                },
                'domain_used': domain,
                'pagination': {
                    'total_count': total_count,
                    'page': page,
                    'page_size': page_size,
                    'total_pages': total_pages,
                    'current_count': len(transfers)
                }
            },
            count=total_count,
            message=f"Trouvé {len(transfers)} transfert(s) sur {total_count} au total pour le PDV '{pos_config['name']}' (page {page}/{total_pages})"
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Erreur lors de la récupération des transferts: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Erreur lors de la récupération: {str(e)}"
        )

@router.get("/inventory/transfers/by-truck", response_model=ApiResponse)
async def get_transfers_by_truck(
    truck_name: str = Query(..., description="Nom du camion (recherche partielle)"),
    transfer_type: Optional[str] = Query(None, description="Type de transfert (internal/incoming/outgoing ou all)"),
    state: Optional[str] = Query(None, description="État du transfert"),
    date_from: Optional[str] = Query(None, description="Date de début (YYYY-MM-DD)"),
    date_to: Optional[str] = Query(None, description="Date de fin (YYYY-MM-DD)"),
    page: int = Query(1, ge=1, description="Numéro de page"),
    page_size: int = Query(50, ge=1, le=200, description="Éléments par page"),
    current_user: dict = Depends(require_scope("pos"))
):
    """
    Récupérer les transferts (internes, livraisons, réceptions) filtrés par nom de camion
    
    Cette route permet de rechercher tous les types de transferts associés à un camion spécifique :
    - **Transferts internes** (internal) : Inventaires/Opérations/Transferts/Interne
    - **Livraisons** (outgoing) : Inventaires/Opérations/Transferts/Livraisons
    - **Réceptions** (incoming) : Inventaires/Opérations/Transferts/Réceptions
    
    **Paramètres :**
    - **truck_name** : Nom du camion (recherche partielle, insensible à la casse)
    - **transfer_type** : Type de transfert à filtrer :
      - `internal` : Transferts internes uniquement
      - `incoming` : Réceptions uniquement
      - `outgoing` : Livraisons uniquement
      - `all` ou null : Tous les types (défaut)
    - **state** : Filtrer par état (draft/waiting/ready/done/cancel)
    - **date_from/date_to** : Période de recherche
    - **page** : Numéro de page (défaut: 1)
    - **page_size** : Éléments par page (défaut: 50, max: 200)
    
    **Note:** La recherche se fait sur plusieurs champs :
    - Champ personnalisé `x_studio_camion` (si disponible)
    - Champs standards `origin` et `name`
    
    **Requires:** Authentification JWT avec scope 'pos'
    """
    try:
        client = get_odoo_client(current_user)
        
        # Déterminer le(s) type(s) de transfert à rechercher
        transfer_types = []
        if transfer_type and transfer_type != 'all':
            # Un seul type spécifique
            if transfer_type in ['internal', 'incoming', 'outgoing']:
                transfer_types = [transfer_type]
            else:
                raise HTTPException(
                    status_code=400,
                    detail=f"Type de transfert invalide: {transfer_type}. Utilisez 'internal', 'incoming', 'outgoing' ou 'all'"
                )
        else:
            # Par défaut, chercher dans tous les types
            transfer_types = ['internal', 'incoming', 'outgoing']
        
        logger.info(f"Recherche transferts de type(s): {transfer_types} pour camion '{truck_name}'")
        
        # STRATÉGIE: Chercher dans plusieurs champs possibles
        # Pour chaque stratégie, on cherche TOUS les types de transferts demandés
        
        # Fonction helper pour créer un domaine multi-types
        def create_multi_type_domain(base_conditions):
            """Crée un domaine qui combine tous les types de transferts avec OU logique"""
            if len(transfer_types) == 1:
                # Un seul type : domaine simple
                return [('picking_type_code', '=', transfer_types[0])] + base_conditions
            else:
                # Plusieurs types : utiliser 'in'
                return [('picking_type_code', 'in', transfer_types)] + base_conditions
        
        # Liste des stratégies à essayer (dans l'ordre de priorité)
        search_strategies = []
        
        # Stratégie 0: Chercher via le champ personnalisé x_studio_camion (many2one vers res.partner)
        try:
            truck_ids_from_partner = client.execute_kw(
                'res.partner',
                'search',
                [[('name', 'ilike', truck_name)]]
            )
            
            if truck_ids_from_partner:
                logger.info(f"Trouvé {len(truck_ids_from_partner)} partenaire(s) correspondant à '{truck_name}': {truck_ids_from_partner}")
                # Essayer d'abord avec x_studio_camion
                try:
                    search_strategies.append(('x_studio_camion', [('x_studio_camion', 'in', truck_ids_from_partner)]))
                except Exception as e:
                    logger.debug(f"Champ x_studio_camion non disponible: {e}")
                # Puis fallback sur partner_id
                search_strategies.append(('partner_id', [('partner_id', 'in', truck_ids_from_partner)]))
        except Exception as e:
            logger.debug(f"Recherche dans res.partner échouée: {e}")
        
        # Stratégie 2: Chercher dans location_id ou location_dest_id (emplacements du camion)
        try:
            # Chercher les emplacements qui contiennent le nom du camion
            location_ids = client.execute_kw(
                'stock.location',
                'search',
                [[('name', 'ilike', truck_name)]]
            )
            
            if location_ids:
                logger.info(f"Trouvé {len(location_ids)} emplacement(s) correspondant à '{truck_name}': {location_ids}")
                search_strategies.append(('location', [
                    '|',
                    ('location_id', 'in', location_ids),
                    ('location_dest_id', 'in', location_ids)
                ]))
        except Exception as e:
            logger.debug(f"Recherche dans stock.location échouée: {e}")
        
        # Stratégie 3: Chercher dans origin (référence du transfert)
        search_strategies.append(('origin', [('origin', 'ilike', truck_name)]))
        
        # Stratégie 4: Chercher dans name (numéro du transfert)
        search_strategies.append(('name', [('name', 'ilike', truck_name)]))
        
        # Essayer chaque stratégie jusqu'à trouver des résultats
        domain = []
        total_count = 0
        
        for strategy_name, base_conditions in search_strategies:
            try:
                # Créer le domaine pour tous les types de transferts
                test_domain = create_multi_type_domain(base_conditions)
                
                # Ajouter les filtres optionnels
                if state:
                    test_domain.append(('state', '=', state))
                
                if date_from:
                    test_domain.append(('date', '>=', f"{date_from} 00:00:00"))
                
                if date_to:
                    test_domain.append(('date', '<=', f"{date_to} 23:59:59"))
                
                # Tester ce domaine
                count = client.execute_kw(
                    'stock.picking',
                    'search_count',
                    [test_domain]
                )
                
                logger.info(f"Stratégie '{strategy_name}': {count} résultat(s)")
                
                if count > 0:
                    domain = test_domain
                    total_count = count
                    logger.info(f"✅ Utilisation de la stratégie '{strategy_name}': {count} transfert(s) trouvé(s)")
                    break
                    
            except Exception as e:
                logger.warning(f"Erreur avec stratégie '{strategy_name}': {e}")
                continue
        
        # Si aucun résultat trouvé avec toutes les options
        if total_count == 0:
            # Construire un domaine de base pour le message (avec tous les types demandés)
            if len(transfer_types) == 1:
                domain = [('picking_type_code', '=', transfer_types[0])]
            else:
                domain = [('picking_type_code', 'in', transfer_types)]
            
            if state:
                domain.append(('state', '=', state))
            if date_from:
                domain.append(('date', '>=', f"{date_from} 00:00:00"))
            if date_to:
                domain.append(('date', '<=', f"{date_to} 23:59:59"))
        
        # Récupérer le nom de la base de données
        from core.security import get_odoo_config_from_user
        db_config = get_odoo_config_from_user(current_user)
        db_name = db_config.get('name', 'Base par défaut') if db_config else 'Base par défaut'
        
        # Créer un message descriptif des types de transferts
        type_labels = {
            'internal': 'Transferts internes',
            'incoming': 'Réceptions',
            'outgoing': 'Livraisons'
        }
        types_str = ' + '.join([type_labels.get(t, t) for t in transfer_types])
        
        logger.info(f"Recherche finale: domaine={domain}, total_count={total_count}, types={types_str}")
        
        if total_count == 0:
            return ApiResponse(
                success=True,
                data={
                    'truck_name': truck_name,
                    'transfer_types': transfer_types,
                    'transfers': [],
                    'pagination': {
                        'total_count': 0,
                        'page': page,
                        'page_size': page_size,
                        'total_pages': 0,
                        'current_count': 0
                    }
                },
                count=0,
                message=f"Aucun transfert ({types_str}) trouvé pour le camion '{truck_name}'"
            )
        
        # Calculer l'offset
        offset = (page - 1) * page_size
        
        # Champs à récupérer (on essaiera avec x_studio_code, sinon sans)
        fields_base = [
            # Champs de base
            'id', 'name', 'origin', 'state', 'picking_type_code', 'partner_id',
            'location_id', 'location_dest_id', 'scheduled_date', 'date_done',
            'user_id', 'company_id', 'products_availability', 'products_availability_state',
            'move_ids', 'pos_session_id', 'pos_order_id', 'note',
            
            # Champs détaillés
            'picking_type_id', 'priority', 'date', 'date_deadline',
            'move_type', 'group_id', 'has_packages', 'is_locked',
            
            # Informations produits
            'move_ids_without_package', 'move_line_ids', 'move_line_ids_without_package',
            
            # Informations de création
            'create_date', 'write_date', 'create_uid', 'write_uid'
        ]
        
        # Essayer d'abord avec le champ personnalisé x_studio_code
        transfers = None
        try:
            fields = fields_base + ['x_studio_code']
            transfers = client.execute_kw(
                'stock.picking',
                'search_read',
                [domain],
                {
                    'fields': fields,
                    'limit': page_size,
                    'offset': offset,
                    'order': 'date desc, id desc'
                }
            )
        except Exception as e:
            # Si x_studio_code n'existe pas, réessayer sans
            if 'x_studio_code' in str(e):
                logger.debug(f"Champ x_studio_code non disponible, récupération sans ce champ")
                transfers = client.execute_kw(
                    'stock.picking',
                    'search_read',
                    [domain],
                    {
                        'fields': fields_base,
                        'limit': page_size,
                        'offset': offset,
                        'order': 'date desc, id desc'
                    }
                )
            else:
                raise
        
        # Enrichir chaque transfert avec les détails des mouvements
        # D'abord, collecter tous les IDs de localisation pour un seul appel Odoo
        all_location_ids = set()
        for transfer in transfers:
            if transfer.get('location_id'):
                loc_id = transfer['location_id'][0] if isinstance(transfer['location_id'], (list, tuple)) else transfer['location_id']
                all_location_ids.add(loc_id)
            if transfer.get('location_dest_id'):
                loc_id = transfer['location_dest_id'][0] if isinstance(transfer['location_dest_id'], (list, tuple)) else transfer['location_dest_id']
                all_location_ids.add(loc_id)
        
        # Récupérer les détails de toutes les localisations (avec champs supplémentaires)
        locations_map = {}
        if all_location_ids:
            try:
                locations_details = client.execute_kw(
                    'stock.location',
                    'read',
                    [list(all_location_ids)],
                    {'fields': ['id', 'name', 'complete_name', 'usage', 'active', 'warehouse_id', 'company_id', 'parent_path', 'barcode', 'location_id', 'comment', 'scrap_location', 'removal_strategy_id']}
                )
                locations_map = {loc['id']: loc for loc in locations_details}
            except Exception as e:
                logger.warning(f"Erreur enrichissement localisations: {e}")
        
        # Collecter tous les IDs de partenaires (depuis transfer)
        all_partner_ids = set()
        
        for transfer in transfers:
            if transfer.get('partner_id'):
                partner_id = transfer['partner_id'][0] if isinstance(transfer['partner_id'], (list, tuple)) else transfer['partner_id']
                all_partner_ids.add(partner_id)
        
        # Récupérer les détails des partenaires et leurs contacts (chauffeurs, gérants)
        partners_map = {}
        drivers_map = {}
        
        if all_partner_ids:
            try:
                partners_details = client.execute_kw(
                    'res.partner',
                    'read',
                    [list(all_partner_ids)],
                    {'fields': ['id', 'name', 'display_name', 'phone', 'mobile', 'email', 'type', 'is_company', 'child_ids', 'category_id', 'commercial_partner_id']}
                )
                partners_map = {p['id']: p for p in partners_details}
                
                # Pour chaque partenaire, récupérer tous ses contacts (chauffeurs, gérants, etc.)
                all_contact_ids = set()
                for partner in partners_details:
                    if partner.get('child_ids'):
                        for contact_id in partner['child_ids']:
                            all_contact_ids.add(contact_id)
                
                if all_contact_ids:
                    contacts_details = client.execute_kw(
                        'res.partner',
                        'read',
                        [list(all_contact_ids)],
                        {'fields': ['id', 'name', 'mobile', 'email', 'phone', 'type', 'function', 'parent_id']}
                    )
                    contacts_map = {c['id']: c for c in contacts_details}
                    
                    # Mapper les contacts par parent
                    for partner in partners_details:
                        if partner.get('child_ids'):
                            partner_contacts = [contacts_map.get(cid) for cid in partner['child_ids'] if cid in contacts_map]
                            drivers_map[partner['id']] = partner_contacts
                            
            except Exception as e:
                logger.warning(f"Erreur enrichissement partenaires: {e}")
        
        # Enrichir chaque transfert avec les détails des localisations et acteurs
        for transfer in transfers:
            # Ajouter les détails des localisations
            source_loc_id = transfer['location_id'][0] if isinstance(transfer.get('location_id'), (list, tuple)) else transfer.get('location_id')
            dest_loc_id = transfer['location_dest_id'][0] if isinstance(transfer.get('location_dest_id'), (list, tuple)) else transfer.get('location_dest_id')
            
            source_loc = locations_map.get(source_loc_id) if source_loc_id else None
            dest_loc = locations_map.get(dest_loc_id) if dest_loc_id else None
            
            transfer['location_source_details'] = source_loc
            transfer['location_destination_details'] = dest_loc
            
            # Enrichir avec les acteurs du transfert
            # Source actor: partenaire/chauffeur du transfert
            source_actor = None
            if transfer.get('partner_id'):
                partner_id = transfer['partner_id'][0] if isinstance(transfer['partner_id'], (list, tuple)) else transfer['partner_id']
                source_actor = partners_map.get(partner_id)
            
            # Destination actor: toujours null pour by-truck (pas de destination spécifique)
            dest_actor = None
            
            transfer['location_source_actor'] = source_actor
            transfer['location_destination_actor'] = dest_actor
            
            # Ajouter les détails du partenaire principal du transfer et du chauffeur si applicable
            if transfer.get('partner_id'):
                partner_id = transfer['partner_id'][0] if isinstance(transfer['partner_id'], (list, tuple)) else transfer['partner_id']
                partner = partners_map.get(partner_id)
                transfer['partner_details'] = partner
                
                # Initialiser les contacts
                transfer['driver_details'] = None
                transfer['related_contacts'] = []
                
                # Si c'est un camion (partenaire), récupérer tous les contacts (chauffeurs, etc.)
                if partner:
                    if drivers_map.get(partner_id):
                        # Si des contacts enfants existent
                        contacts = drivers_map.get(partner_id, [])
                        transfer['driver_details'] = contacts[0] if contacts else None
                        transfer['related_contacts'] = [c for c in contacts if c]  # Tous les contacts associés
                    else:
                        # Si pas de contacts enfants, au moins ajouter le partenaire lui-même
                        transfer['related_contacts'] = [partner]
            else:
                # Si pas de partner_id, initialiser quand même
                transfer['partner_details'] = None
                transfer['driver_details'] = None
                transfer['related_contacts'] = []
            
            # Récupérer les détails des mouvements de stock
            if transfer.get('move_ids'):
                try:
                    move_details = client.execute_kw(
                        'stock.move',
                        'read',
                        [transfer['move_ids']],
                        {
                            'fields': [
                                'id', 'name', 'product_id', 'product_uom_qty', 'product_qty',
                                'product_uom', 'state', 'location_id', 'location_dest_id',
                                'date', 'origin', 'reference', 'description_picking'
                            ]
                        }
                    )
                    
                    # Enrichir avec les infos produits
                    product_ids = [move['product_id'][0] for move in move_details if move.get('product_id')]
                    if product_ids:
                        products_info = client.execute_kw(
                            'product.product',
                            'read',
                            [product_ids],
                            {
                                'fields': [
                                    'id', 'name', 'display_name', 'default_code', 'barcode',
                                    'uom_id', 'type', 'tracking', 'list_price', 'standard_price'
                                ]
                            }
                        )
                        
                        products_map = {p['id']: p for p in products_info}
                        
                        for move in move_details:
                            if move.get('product_id'):
                                product_id = move['product_id'][0]
                                move['product_details'] = products_map.get(product_id, {})
                    
                    transfer['move_details'] = move_details
                    
                except Exception as e:
                    logger.warning(f"Erreur enrichissement mouvements transfert {transfer['id']}: {e}")
                    transfer['move_details'] = []
            else:
                transfer['move_details'] = []
            
            # Récupérer les détails des opérations de stock
            if transfer.get('move_line_ids'):
                try:
                    move_line_details = client.execute_kw(
                        'stock.move.line',
                        'read',
                        [transfer['move_line_ids']],
                        {
                            'fields': [
                                'id', 'move_id', 'product_id', 'product_uom_id', 'qty_done',
                                'quantity', 'lot_id', 'lot_name', 'location_id',
                                'location_dest_id', 'picking_id', 'state', 'reference'
                            ]
                        }
                    )
                    transfer['move_line_details'] = move_line_details
                except Exception as e:
                    logger.warning(f"Erreur enrichissement move_line transfert {transfer['id']}: {e}")
                    transfer['move_line_details'] = []
            else:
                transfer['move_line_details'] = []
            
            # Ajouter les détails du type de picking
            if transfer.get('picking_type_id'):
                try:
                    picking_type_info = client.execute_kw(
                        'stock.picking.type',
                        'read',
                        [transfer['picking_type_id'][0]],
                        {
                            'fields': [
                                'id', 'name', 'code', 'warehouse_id', 'default_location_src_id',
                                'default_location_dest_id', 'sequence_code'
                            ]
                        }
                    )
                    transfer['picking_type_details'] = picking_type_info[0] if picking_type_info else {}
                except Exception as e:
                    logger.warning(f"Erreur enrichissement picking_type transfert {transfer['id']}: {e}")
                    transfer['picking_type_details'] = {}
            else:
                transfer['picking_type_details'] = {}
        
        # Formater les résultats
        def clean_odoo_value(value):
            return None if value is False else value
        
        formatted_transfers = []
        for transfer in transfers:
            try:
                formatted_transfer = {
                    # Champs de base
                    'id': transfer['id'],
                    'name': transfer.get('name', ''),
                    'code': clean_odoo_value(transfer.get('x_studio_code')),
                    'origin': clean_odoo_value(transfer.get('origin')),
                    'state': transfer.get('state', 'draft'),
                    'picking_type_code': clean_odoo_value(transfer.get('picking_type_code')),
                    
                    # Informations de référence (le nom du camion est dans origin)
                    'truck_name': clean_odoo_value(transfer.get('origin')),
                    
                    'partner_id': clean_odoo_value(transfer.get('partner_id')),
                    'partner_details': clean_odoo_value(transfer.get('partner_details')),
                    'driver_details': clean_odoo_value(transfer.get('driver_details')),
                    'related_contacts': clean_odoo_value(transfer.get('related_contacts')),
                    'location_id': clean_odoo_value(transfer.get('location_id')),
                    'location_dest_id': clean_odoo_value(transfer.get('location_dest_id')),
                    'location_source_details': clean_odoo_value(transfer.get('location_source_details')),
                    'location_destination_details': clean_odoo_value(transfer.get('location_destination_details')),
                    'location_source_actor': clean_odoo_value(transfer.get('location_source_actor')),
                    'location_destination_actor': clean_odoo_value(transfer.get('location_destination_actor')),
                    'scheduled_date': clean_odoo_value(transfer.get('scheduled_date')),
                    'date_done': clean_odoo_value(transfer.get('date_done')),
                    'date': clean_odoo_value(transfer.get('date')),
                    'user_id': clean_odoo_value(transfer.get('user_id')),
                    'company_id': clean_odoo_value(transfer.get('company_id')),
                    'products_availability': clean_odoo_value(transfer.get('products_availability')),
                    'products_availability_state': clean_odoo_value(transfer.get('products_availability_state')),
                    'note': clean_odoo_value(transfer.get('note')),
                    
                    # Champs détaillés
                    'picking_type_id': clean_odoo_value(transfer.get('picking_type_id')),
                    'priority': clean_odoo_value(transfer.get('priority')),
                    'date_deadline': clean_odoo_value(transfer.get('date_deadline')),
                    'move_type': clean_odoo_value(transfer.get('move_type')),
                    'group_id': clean_odoo_value(transfer.get('group_id')),
                    'has_packages': clean_odoo_value(transfer.get('has_packages')),
                    'is_locked': clean_odoo_value(transfer.get('is_locked')),
                    
                    # IDs des mouvements
                    'move_ids': transfer.get('move_ids', []) if transfer.get('move_ids') is not False else [],
                    'move_line_ids': clean_odoo_value(transfer.get('move_line_ids')),
                    
                    # Informations de création
                    'create_date': clean_odoo_value(transfer.get('create_date')),
                    'write_date': clean_odoo_value(transfer.get('write_date')),
                    'create_uid': clean_odoo_value(transfer.get('create_uid')),
                    'write_uid': clean_odoo_value(transfer.get('write_uid')),
                    
                    # Détails enrichis
                    'move_details': transfer.get('move_details', []),
                    'move_line_details': transfer.get('move_line_details', []),
                    'picking_type_details': transfer.get('picking_type_details', {}),
                    
                    # Résumé des produits
                    'product_summary': [
                        {
                            'product_name': move.get('product_details', {}).get('name', 'Produit inconnu'),
                            'product_code': move.get('product_details', {}).get('default_code'),
                            'quantity': move.get('product_uom_qty', 0),
                            'uom': move.get('product_uom', [None, 'Unité'])[1] if move.get('product_uom') else 'Unité'
                        }
                        for move in transfer.get('move_details', [])
                    ]
                }
                
                formatted_transfers.append(formatted_transfer)
                
            except Exception as e:
                logger.warning(f"Erreur formatage transfert {transfer.get('id', 'unknown')}: {e}")
                formatted_transfer = {
                    'id': transfer['id'],
                    'name': transfer.get('name', ''),
                    'state': transfer.get('state', 'draft'),
                    'origin': transfer.get('origin', ''),
                    'error': f"Erreur formatage: {str(e)}"
                }
                formatted_transfers.append(formatted_transfer)
        
        # Calculer le nombre total de pages
        total_pages = (total_count + page_size - 1) // page_size
        
        logger.info(f"Trouvé {len(transfers)} transfert(s) ({types_str}) pour le camion '{truck_name}' sur {total_count} au total")
        
        return ApiResponse(
            success=True,
            data={
                'truck_name': truck_name,
                'transfer_types': transfer_types,
                'transfer_types_labels': types_str,
                'database': db_name,
                'transfers': formatted_transfers,
                'filters_applied': {
                    'truck_name': truck_name,
                    'transfer_type': transfer_type or 'all',
                    'state': state,
                    'date_from': date_from,
                    'date_to': date_to
                },
                'pagination': {
                    'total_count': total_count,
                    'page': page,
                    'page_size': page_size,
                    'total_pages': total_pages,
                    'current_count': len(transfers)
                }
            },
            count=total_count,
            message=f"Trouvé {len(transfers)} transfert(s) ({types_str}) sur {total_count} pour le camion '{truck_name}' (page {page}/{total_pages})"
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Erreur lors de la récupération des transferts par camion: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Erreur lors de la récupération: {str(e)}"
        )

@router.post("/inventory/transfers/{transfer_id}/update-state", response_model=ApiResponse)
async def update_inventory_transfer_state(
    transfer_id: int = Path(..., description="ID du transfert de stock"),
    request: StockPickingStateUpdateRequest = Body(...),
    current_user: dict = Depends(require_scope("pos"))
):
    """
    Changer l'état d'un transfert de stock
    
    Cette route permet de faire évoluer l'état d'un transfert de stock selon
    le workflow Odoo standard :
    - **confirm** : Confirmer le transfert (draft → waiting/ready)
    - **assign** : Réserver les produits (waiting → ready)
    - **done** : Marquer comme terminé (ready → done)
    - **cancel** : Annuler le transfert (any → cancel)
    
    **Actions disponibles :**
    - **confirm** : Confirme le transfert en brouillon
    - **assign** : Réserve les quantités disponibles
    - **done** : Valide et termine le transfert
    - **cancel** : Annule le transfert
    
    **Paramètres :**
    - **transfer_id** : ID du transfert (dans l'URL)
    - **action** : Action à effectuer (confirm/assign/done/cancel)
    - **force** : Forcer l'action même si les conditions ne sont pas remplies
    
    **Exemple d'utilisation :**
    ```
    POST /pos/inventory/transfers/82534/update-state
    {
      "action": "done",
      "force": false
    }
    ```
    
    **Requires:** Authentification JWT avec scope 'pos'
    """
    try:
        client = get_odoo_client(current_user)
        
        # Vérifier que le transfert existe
        transfer = client.execute_kw(
            'stock.picking',
            'search_read',
            [[('id', '=', transfer_id)]],
            {'fields': ['id', 'name', 'state', 'picking_type_code'], 'limit': 1}
        )
        
        if not transfer:
            raise HTTPException(status_code=404, detail=f"Transfert {transfer_id} non trouvé")
        
        transfer = transfer[0]
        transfer_name = transfer['name']
        current_state = transfer['state']
        
        logger.info(f"🔄 Mise à jour transfert {transfer_name} (ID: {transfer_id}): {current_state} → action '{request.action}'")
        
        try:
            success = False
            new_state = current_state
            
            if request.action == "confirm":
                # Confirmer le transfert (draft → waiting/ready)
                if current_state == 'draft':
                    client.execute_kw('stock.picking', 'action_confirm', [[transfer_id]])
                    success = True
                    new_state = 'confirmed'
                    logger.info(f"✅ Transfert {transfer_name} confirmé")
                elif request.force:
                    client.execute_kw('stock.picking', 'action_confirm', [[transfer_id]])
                    success = True
                    logger.warning(f"⚠️ Transfert {transfer_name} confirmé en mode forcé (état initial: {current_state})")
                else:
                    raise ValueError(f"Le transfert doit être en état 'draft' pour être confirmé (état actuel: {current_state})")
            
            elif request.action == "assign":
                # Réserver les produits (waiting → ready)
                if current_state in ['confirmed', 'waiting', 'partially_available']:
                    client.execute_kw('stock.picking', 'action_assign', [[transfer_id]])
                    success = True
                    new_state = 'assigned'
                    logger.info(f"✅ Transfert {transfer_name} assigné (produits réservés)")
                elif request.force:
                    client.execute_kw('stock.picking', 'action_assign', [[transfer_id]])
                    success = True
                    logger.warning(f"⚠️ Transfert {transfer_name} assigné en mode forcé (état initial: {current_state})")
                else:
                    raise ValueError(f"Le transfert doit être confirmé pour réserver les produits (état actuel: {current_state})")
            
            elif request.action == "done":
                # Valider le transfert (ready/assigned → done)
                if current_state in ['assigned', 'confirmed']:
                    # Vérifier si des quantités sont définies
                    client.execute_kw('stock.picking', 'button_validate', [[transfer_id]])
                    success = True
                    new_state = 'done'
                    logger.info(f"✅ Transfert {transfer_name} validé et terminé")
                elif request.force:
                    client.execute_kw('stock.picking', 'button_validate', [[transfer_id]])
                    success = True
                    new_state = 'done'
                    logger.warning(f"⚠️ Transfert {transfer_name} validé en mode forcé (état initial: {current_state})")
                else:
                    raise ValueError(f"Le transfert doit être assigné pour être validé (état actuel: {current_state})")
            
            elif request.action == "cancel":
                # Annuler le transfert
                if current_state != 'done':
                    client.execute_kw('stock.picking', 'action_cancel', [[transfer_id]])
                    success = True
                    new_state = 'cancel'
                    logger.info(f"✅ Transfert {transfer_name} annulé")
                elif request.force:
                    client.execute_kw('stock.picking', 'action_cancel', [[transfer_id]])
                    success = True
                    new_state = 'cancel'
                    logger.warning(f"⚠️ Transfert {transfer_name} annulé en mode forcé (état initial: {current_state})")
                else:
                    raise ValueError(f"Impossible d'annuler un transfert terminé (état actuel: {current_state})")
            
            # Récupérer l'état mis à jour
            updated_transfer = client.execute_kw(
                'stock.picking',
                'read',
                [[transfer_id]],
                {'fields': ['id', 'name', 'state']}
            )
            
            if updated_transfer:
                new_state = updated_transfer[0]['state']
            
            logger.info(f"📊 Résultat: {transfer_name} - {current_state} → {new_state} (succès: {success})")
            
            return ApiResponse(
                success=True,
                data={
                    'transfer_id': transfer_id,
                    'transfer_name': transfer_name,
                    'action': request.action,
                    'previous_state': current_state,
                    'new_state': new_state,
                    'state_changed': new_state != current_state
                },
                message=f"Action '{request.action}' effectuée sur le transfert {transfer_name}: {current_state} → {new_state}"
            )
            
        except ValueError as ve:
            logger.error(f"❌ Erreur validation: {ve}")
            raise HTTPException(status_code=400, detail=str(ve))
        except Exception as e:
            logger.error(f"❌ Erreur lors de l'action '{request.action}' sur transfert {transfer_id}: {e}")
            raise HTTPException(
                status_code=500,
                detail=f"Erreur lors de l'action '{request.action}': {str(e)}"
            )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Erreur lors de la mise à jour du transfert {transfer_id}: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Erreur lors de la mise à jour: {str(e)}"
        )

# ===== GESTION DES CAMIONS (FLEET) =====

@router.get("/fleet/debug-user", response_model=ApiResponse)
async def debug_fleet_user(
    current_user: dict = Depends(require_scope("pos"))
):
    """
    Debug: Afficher les informations de l'utilisateur et les IDs liés
    """
    try:
        employee_id = current_user.get('employee_id')
        partner_id = current_user.get('partner_id')
        
        client = get_odoo_client(current_user)
        
        # Récupérer l'employé avec tous ses champs partner
        employee_info = client.execute_kw(
            'hr.employee',
            'search_read',
            [[('id', '=', employee_id)]],
            {
                'fields': [
                    'id', 'name', 'user_partner_id', 'related_partner_id', 
                    'work_contact_id', 'user_id'
                ],
                'limit': 1
            }
        )
        
        # Récupérer le partner actuel
        partner_info = client.execute_kw(
            'res.partner',
            'search_read',
            [[('id', '=', partner_id)]],
            {'fields': ['id', 'name', 'phone', 'mobile', 'email'], 'limit': 1}
        )
        
        # Chercher les camions avec chaque ID possible
        trucks_by_partner = client.execute_kw(
            'fleet.vehicle',
            'search_count',
            [[('driver_id', '=', partner_id), ('active', '=', True)]]
        )
        
        # Essayer avec d'autres IDs de l'employé si disponibles
        debug_data = {
            'jwt_token_info': {
                'employee_id': employee_id,
                'partner_id': partner_id
            },
            'employee_record': employee_info[0] if employee_info else None,
            'partner_record': partner_info[0] if partner_info else None,
            'trucks_found_with_partner_id': trucks_by_partner
        }
        
        # Tester avec les autres partner IDs de l'employé
        if employee_info:
            emp = employee_info[0]
            for field in ['user_partner_id', 'related_partner_id', 'work_contact_id']:
                if emp.get(field):
                    test_id = emp[field][0] if isinstance(emp[field], list) else emp[field]
                    trucks_count = client.execute_kw(
                        'fleet.vehicle',
                        'search_count',
                        [[('driver_id', '=', test_id), ('active', '=', True)]]
                    )
                    debug_data[f'trucks_with_{field}'] = {
                        'partner_id': test_id,
                        'trucks_count': trucks_count
                    }
        
        # Chercher tous les res.partner avec le même nom
        if partner_info:
            partner_name = partner_info[0]['name']
            all_partners_same_name = client.execute_kw(
                'res.partner',
                'search_read',
                [[('name', '=', partner_name)]],
                {'fields': ['id', 'name', 'phone', 'mobile', 'email', 'employee'], 'limit': 10}
            )
            debug_data['all_partners_with_same_name'] = all_partners_same_name
            
            # Tester chaque partner avec le même nom
            for p in all_partners_same_name:
                trucks_count = client.execute_kw(
                    'fleet.vehicle',
                    'search_count',
                    [[('driver_id', '=', p['id']), ('active', '=', True)]]
                )
                if trucks_count > 0:
                    debug_data[f'FOUND_TRUCKS_WITH_PARTNER_{p["id"]}'] = {
                        'partner_id': p['id'],
                        'partner_name': p['name'],
                        'trucks_count': trucks_count,
                        'is_employee': p.get('employee', False)
                    }
        
        # Chercher dans hr.employee avec le même nom
        if employee_info:
            employee_name = employee_info[0]['name']
            all_employees_same_name = client.execute_kw(
                'hr.employee',
                'search_read',
                [[('name', '=', employee_name)]],
                {'fields': ['id', 'name', 'work_contact_id', 'user_partner_id', 'related_partner_id'], 'limit': 10}
            )
            debug_data['all_employees_with_same_name'] = all_employees_same_name
        
        return ApiResponse(
            success=True,
            data=debug_data,
            message="Informations de debug récupérées"
        )
        
    except Exception as e:
        logger.error(f"Erreur lors du debug: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/fleet/my-trucks", response_model=ApiResponse)
async def get_my_trucks(
    current_user: dict = Depends(require_scope("pos"))
):
    """
    Récupérer les camions de l'utilisateur connecté
    
    Cette route récupère tous les camions affectés au chauffeur actuellement connecté.
    Le partner_id est extrait automatiquement du token JWT.
    
    **Note:** Cette route est spécialement conçue pour les chauffeurs authentifiés par PIN.
    Elle utilise le partner_id stocké dans le token JWT lors de l'authentification.
    
    **Informations retournées :**
    - Liste des camions affectés au chauffeur (via fleet.vehicle.driver_id)
    - Informations du chauffeur
    - Détails de chaque camion (modèle, plaque, etc.)
    
    **Requires:** Authentification JWT avec scope 'pos'
    """
    try:
        # Extraire le partner_id du token JWT
        partner_id = current_user.get('partner_id')
        
        if not partner_id:
            raise HTTPException(
                status_code=400,
                detail="Partner ID manquant dans le token. Veuillez vous authentifier avec votre matricule et PIN."
            )
        
        client = get_odoo_client(current_user)
        
        # Récupérer les informations du chauffeur
        driver_info = client.execute_kw(
            'res.partner',
            'search_read',
            [[('id', '=', partner_id)]],
            {'fields': ['id', 'name', 'phone', 'mobile', 'email'], 'limit': 1}
        )
        
        if not driver_info:
            raise HTTPException(status_code=404, detail="Chauffeur non trouvé")
        
        driver_info = driver_info[0]
        driver_name = driver_info['name']
        
        # STRATÉGIE 1: Chercher directement avec le partner_id du token
        trucks = client.execute_kw(
            'fleet.vehicle',
            'search_read',
            [[('driver_id', '=', partner_id), ('active', '=', True)]],
            {
                'fields': [
                    'id', 'name', 'license_plate', 'model_id', 'brand_id', 
                    'vin_sn', 'state_id', 'odometer', 'fuel_type', 
                    'driver_id'
                ],
                'order': 'name asc'
            }
        )
        
        # STRATÉGIE 2: Si aucun camion trouvé, chercher tous les res.partner avec le même nom
        # (car il peut y avoir plusieurs partners pour la même personne dans différentes entreprises)
        if not trucks:
            logger.info(f"Aucun camion trouvé avec partner_id {partner_id}, recherche par nom: {driver_name}")
            
            # Trouver tous les partners avec le même nom
            all_partners = client.execute_kw(
                'res.partner',
                'search_read',
                [[('name', '=', driver_name)]],
                {'fields': ['id', 'name', 'company_id'], 'limit': 10}
            )
            
            # Chercher les camions pour chaque partner trouvé
            for partner in all_partners:
                partner_trucks = client.execute_kw(
                    'fleet.vehicle',
                    'search_read',
                    [[('driver_id', '=', partner['id']), ('active', '=', True)]],
                    {
                        'fields': [
                            'id', 'name', 'license_plate', 'model_id', 'brand_id', 
                            'vin_sn', 'state_id', 'odometer', 'fuel_type', 
                            'driver_id'
                        ],
                        'order': 'name asc'
                    }
                )
                
                if partner_trucks:
                    trucks.extend(partner_trucks)
                    logger.info(f"Trouvé {len(partner_trucks)} camion(s) pour {driver_name} avec partner_id {partner['id']}")
        
        if not trucks:
            return ApiResponse(
                success=True,
                data={
                    'driver': {
                        'id': driver_info['id'],
                        'name': driver_info['name'],
                        'phone': driver_info.get('phone'),
                        'mobile': driver_info.get('mobile'),
                        'email': driver_info.get('email')
                    },
                    'trucks': [],
                    'total_trucks': 0
                },
                count=0,
                message=f"Aucun camion affecté à {driver_info['name']}"
            )
        
        # Formater les données des camions
        trucks_list = []
        for truck in trucks:
            truck_data = {
                'id': truck['id'],
                'name': truck.get('name', 'N/A'),
                'license_plate': truck.get('license_plate', 'N/A'),
                'model': truck['model_id'][1] if truck.get('model_id') and isinstance(truck['model_id'], list) else 'N/A',
                'brand': truck['brand_id'][1] if truck.get('brand_id') and isinstance(truck['brand_id'], list) else 'N/A',
                'chassis_number': truck.get('vin_sn'),
                'state': truck['state_id'][1] if truck.get('state_id') and isinstance(truck['state_id'], list) else 'N/A',
                'odometer': truck.get('odometer', 0),
                'fuel_type': truck.get('fuel_type', 'N/A')
            }
            trucks_list.append(truck_data)
        
        logger.info(f"Trouvé {len(trucks_list)} camion(s) pour le chauffeur {driver_info['name']} (Partner ID: {partner_id})")
        
        return ApiResponse(
            success=True,
            data={
                'driver': {
                    'id': driver_info['id'],
                    'name': driver_info['name'],
                    'phone': driver_info.get('phone'),
                    'mobile': driver_info.get('mobile'),
                    'email': driver_info.get('email')
                },
                'trucks': trucks_list,
                'total_trucks': len(trucks_list)
            },
            count=len(trucks_list),
            message=f"{len(trucks_list)} camion(s) affecté(s) à {driver_info['name']}"
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Erreur lors de la récupération des camions: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Erreur lors de la récupération des camions: {str(e)}"
        )

@router.get("/fleet/trucks/by-driver/{driver_id}", response_model=ApiResponse)
async def get_trucks_by_driver(
    driver_id: int = Path(..., description="ID du partenaire (res.partner) du chauffeur"),
    current_user: dict = Depends(require_scope("pos"))
):
    """
    Récupérer les camions associés à un chauffeur via les transferts
    
    Cette route récupère tous les camions (x_studio_camion) 
    qui ont été utilisés dans des transferts par un chauffeur spécifique.
    
    **Paramètres :**
    - **driver_id** : ID du partenaire (res.partner) du chauffeur
    
    **Note:** Pour les utilisateurs authentifiés par PIN, le partner_id est disponible 
    dans le token JWT (current_user.partner_id). Vous pouvez l'utiliser directement.
    
    **Informations retournées :**
    - Liste des camions uniques utilisés par le chauffeur
    - Informations du chauffeur
    - Nombre de transferts par camion
    
    **Requires:** Authentification JWT avec scope 'pos'
    """
    try:
        client = get_odoo_client(current_user)
        
        # Vérifier que le partenaire existe
        driver_info = client.execute_kw(
            'res.partner',
            'search_read',
            [[('id', '=', driver_id)]],
            {'fields': ['id', 'name', 'phone', 'mobile', 'email'], 'limit': 1}
        )
        
        if not driver_info:
            raise HTTPException(status_code=404, detail="Chauffeur non trouvé (res.partner)")
        
        driver_info = driver_info[0]
        driver_name = driver_info['name']
        
        # STRATÉGIE 1: Chercher directement avec le driver_id fourni
        trucks = client.execute_kw(
            'fleet.vehicle',
            'search_read',
            [[('driver_id', '=', driver_id), ('active', '=', True)]],
            {
                'fields': [
                    'id', 'name', 'license_plate', 'model_id', 'brand_id',
                    'vin_sn', 'state_id', 'odometer', 'fuel_type',
                    'driver_id', 'category_id',
                    'acquisition_date', 'color'
                ],
                'order': 'name asc'
            }
        )
        
        # STRATÉGIE 2: Si aucun camion trouvé, chercher tous les res.partner avec le même nom
        # (car il peut y avoir plusieurs partners pour la même personne dans différentes entreprises)
        if not trucks:
            logger.info(f"Aucun camion trouvé avec driver_id {driver_id}, recherche par nom: {driver_name}")
            
            # Trouver tous les partners avec le même nom
            all_partners = client.execute_kw(
                'res.partner',
                'search_read',
                [[('name', '=', driver_name)]],
                {'fields': ['id', 'name', 'company_id'], 'limit': 10}
            )
            
            # Chercher les camions pour chaque partner trouvé
            for partner in all_partners:
                partner_trucks = client.execute_kw(
                    'fleet.vehicle',
                    'search_read',
                    [[('driver_id', '=', partner['id']), ('active', '=', True)]],
                    {
                        'fields': [
                            'id', 'name', 'license_plate', 'model_id', 'brand_id',
                            'vin_sn', 'state_id', 'odometer', 'fuel_type',
                            'driver_id', 'category_id',
                            'acquisition_date', 'color'
                        ],
                        'order': 'name asc'
                    }
                )
                
                if partner_trucks:
                    trucks.extend(partner_trucks)
                    logger.info(f"Trouvé {len(partner_trucks)} camion(s) pour {driver_name} avec partner_id {partner['id']}")
        
        if not trucks:
            return ApiResponse(
                success=True,
                data={
                    'driver': {
                        'id': driver_info['id'],
                        'name': driver_info['name'],
                        'phone': driver_info.get('phone'),
                        'mobile': driver_info.get('mobile'),
                        'email': driver_info.get('email')
                    },
                    'trucks': [],
                    'total_trucks': 0
                },
                count=0,
                message=f"Aucun camion affecté à {driver_info['name']}"
            )
        
        # Formater les données des camions
        trucks_list = []
        for truck in trucks:
            truck_data = {
                'id': truck['id'],
                'name': truck.get('name', 'N/A'),
                'license_plate': truck.get('license_plate', 'N/A'),
                'model': truck['model_id'][1] if truck.get('model_id') and isinstance(truck['model_id'], list) else 'N/A',
                'brand': truck['brand_id'][1] if truck.get('brand_id') and isinstance(truck['brand_id'], list) else 'N/A',
                'chassis_number': truck.get('vin_sn'),
                'state': truck['state_id'][1] if truck.get('state_id') and isinstance(truck['state_id'], list) else 'N/A',
                'category': truck['category_id'][1] if truck.get('category_id') and isinstance(truck['category_id'], list) else None,
                'odometer': truck.get('odometer', 0),
                'fuel_type': truck.get('fuel_type', 'N/A'),
                'acquisition_date': truck.get('acquisition_date'),
                'color': truck.get('color')
            }
            trucks_list.append(truck_data)
        
        logger.info(f"Trouvé {len(trucks_list)} camion(s) pour le chauffeur {driver_info['name']} (Partner ID: {driver_id})")
        
        return ApiResponse(
            success=True,
            data={
                'driver': {
                    'id': driver_info['id'],
                    'name': driver_info['name'],
                    'phone': driver_info.get('phone'),
                    'mobile': driver_info.get('mobile'),
                    'email': driver_info.get('email')
                },
                'trucks': trucks_list,
                'total_trucks': len(trucks_list)
            },
            count=len(trucks_list),
            message=f"{len(trucks_list)} camion(s) affecté(s) à {driver_info['name']}"
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Erreur lors de la récupération des camions du chauffeur {driver_id}: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Erreur lors de la récupération: {str(e)}"
        )

@router.get("/fleet/trucks", response_model=ApiResponse)
async def get_all_trucks(
    page: int = Query(1, ge=1, description="Numéro de page"),
    page_size: int = Query(50, ge=1, le=200, description="Éléments par page"),
    active_only: bool = Query(True, description="Afficher uniquement les camions actifs"),
    current_user: dict = Depends(require_scope("pos"))
):
    """
    Récupérer tous les camions depuis fleet.vehicle
    
    Cette route liste tous les camions avec leurs informations complètes :
    - Informations du camion (nom, plaque, modèle, marque)
    - Chauffeur affecté
    - État, odomètre, type de carburant
    - Dates d'acquisition, catégorie, couleur
    - Informations techniques (chassis, etc.)
    
    **Paramètres :**
    - **page** : Numéro de page (défaut: 1)
    - **page_size** : Éléments par page (défaut: 50, max: 200)
    - **active_only** : Afficher uniquement les camions actifs (défaut: True)
    
    **Informations retournées :**
    - Liste complète des camions avec toutes leurs informations
    - Informations du chauffeur affecté (si présent)
    - Statistiques d'odomètre, état, etc.
    
    **Requires:** Authentification JWT avec scope 'pos'
    """
    try:
        client = get_odoo_client(current_user)
        
        # Construire le domaine de recherche
        domain = []
        if active_only:
            domain.append(('active', '=', True))
        
        # Compter le total
        total_count = client.execute_kw(
            'fleet.vehicle',
            'search_count',
            [domain]
        )
        
        # Calculer l'offset
        offset = (page - 1) * page_size
        
        # Récupérer les camions avec pagination
        trucks = client.execute_kw(
            'fleet.vehicle',
            'search_read',
            [domain],
            {
                'fields': [
                    'id', 'name', 'license_plate', 'model_id', 'brand_id',
                    'vin_sn', 'state_id', 'odometer', 'fuel_type',
                    'driver_id', 'category_id',
                    'acquisition_date', 'color', 'seats', 'doors',
                    'transmission', 'horsepower', 'power', 'co2',
                    'model_year', 'frame_type', 'frame_size',
                    'car_value', 'residual_value', 'company_id'
                ],
                'order': 'name asc',
                'limit': page_size,
                'offset': offset
            }
        )
        
        if not trucks:
            return ApiResponse(
                success=True,
                data={
                    'trucks': [],
                    'total_trucks': 0,
                    'page': page,
                    'page_size': page_size,
                    'total_pages': 0
                },
                count=0,
                message="Aucun camion trouvé"
            )
        
        # Formater les données des camions
        trucks_list = []
        for truck in trucks:
            truck_data = {
                'id': truck['id'],
                'name': truck.get('name', 'N/A'),
                'license_plate': truck.get('license_plate', 'N/A'),
                'model': truck['model_id'][1] if truck.get('model_id') and isinstance(truck['model_id'], list) else 'N/A',
                'model_id': truck['model_id'][0] if truck.get('model_id') and isinstance(truck['model_id'], list) else None,
                'brand': truck['brand_id'][1] if truck.get('brand_id') and isinstance(truck['brand_id'], list) else 'N/A',
                'brand_id': truck['brand_id'][0] if truck.get('brand_id') and isinstance(truck['brand_id'], list) else None,
                'chassis_number': truck.get('vin_sn'),
                'state': truck['state_id'][1] if truck.get('state_id') and isinstance(truck['state_id'], list) else 'N/A',
                'state_id': truck['state_id'][0] if truck.get('state_id') and isinstance(truck['state_id'], list) else None,
                'category': truck['category_id'][1] if truck.get('category_id') and isinstance(truck['category_id'], list) else None,
                'category_id': truck['category_id'][0] if truck.get('category_id') and isinstance(truck['category_id'], list) else None,
                'odometer': truck.get('odometer', 0),
                'fuel_type': truck.get('fuel_type', 'N/A'),
                'acquisition_date': truck.get('acquisition_date'),
                'color': truck.get('color'),
                'seats': truck.get('seats'),
                'doors': truck.get('doors'),
                'transmission': truck.get('transmission'),
                'horsepower': truck.get('horsepower'),
                'power': truck.get('power'),
                'co2': truck.get('co2'),
                'model_year': truck.get('model_year'),
                'frame_type': truck.get('frame_type'),
                'frame_size': truck.get('frame_size'),
                'car_value': truck.get('car_value'),
                'residual_value': truck.get('residual_value'),
                'company': truck['company_id'][1] if truck.get('company_id') and isinstance(truck['company_id'], list) else None,
                'company_id': truck['company_id'][0] if truck.get('company_id') and isinstance(truck['company_id'], list) else None,
                'driver': None
            }
            
            # Ajouter les informations du chauffeur si présent
            if truck.get('driver_id') and isinstance(truck['driver_id'], list):
                truck_data['driver'] = {
                    'id': truck['driver_id'][0],
                    'name': truck['driver_id'][1]
                }
            
            trucks_list.append(truck_data)
        
        # Calculer le nombre total de pages
        total_pages = (total_count + page_size - 1) // page_size
        
        logger.info(f"Récupération de {len(trucks_list)} camion(s) sur {total_count} au total (page {page}/{total_pages})")
        
        return ApiResponse(
            success=True,
            data={
                'trucks': trucks_list,
                'pagination': {
                    'total_count': total_count,
                    'page': page,
                    'page_size': page_size,
                    'total_pages': total_pages,
                    'current_count': len(trucks_list)
                }
            },
            count=len(trucks_list),
            message=f"Récupéré {len(trucks_list)} camion(s) sur {total_count} au total (page {page}/{total_pages})"
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Erreur lors de la récupération des camions: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Erreur lors de la récupération: {str(e)}"
        )

# ===== GESTION DES PRODUITS POUR POMPES =====

# IDs des product.category pour le filtrage station-service
# produits_blanc  → carburants pompés : ESSENCE, Essence (Cession bac), GASOIL, PETROLE
_CATEG_PRODUITS_BLANC = [23, 93, 95, 98]
# lubrifiants     → LUBRIFIANTS
_CATEG_LUBRIFIANTS = [96]
# gaz_accessoire  → tout le reste (GAZ, ACCESSOIRES, BOUTEILLES, etc.)
_CATEG_POMPE = _CATEG_PRODUITS_BLANC + _CATEG_LUBRIFIANTS  # exclusion pour gaz_accessoire


@router.get("/products/fuel", response_model=ApiResponse)
async def get_fuel_products(
    pos_id: int = Query(..., description="ID du point de vente"),
    filtre: Optional[str] = Query(
        None,
        description="Filtre produit : 'produits_blanc' (carburants pompe), 'lubrifiants', 'gaz_accessoire' (gaz + accessoires). Sans filtre = tous les produits du POS."
    ),
    search: Optional[str] = Query(None, description="Rechercher un produit par nom"),
    current_user: dict = Depends(require_scope("pos"))
):
    """
    Récupérer les produits disponibles pour un point de vente spécifique.

    Respecte la configuration Odoo du POS (iface_available_categ_ids), puis applique
    un filtre métier optionnel par type de produit station-service.

    **Valeurs de filtre :**
    - `produits_blanc` : carburants pris depuis la pompe (ESSENCE, GASOIL, PETROLE…)
    - `lubrifiants` : huiles et lubrifiants
    - `gaz_accessoire` : GAZ, bouteilles, accessoires et tout le reste
    - *(absent)* : tous les produits du POS sans distinction

    **Requires:** Authentification JWT avec scope 'pos'
    """
    VALID_FILTRES = {None, 'produits_blanc', 'lubrifiants', 'gaz_accessoire'}
    if filtre not in VALID_FILTRES:
        raise HTTPException(
            status_code=400,
            detail=f"Valeur de filtre invalide '{filtre}'. Valeurs acceptées : produits_blanc, lubrifiants, gaz_accessoire"
        )

    try:
        client = get_odoo_client(current_user)

        # Récupérer la config du POS pour connaître ses catégories restreintes
        pos_config = client.execute_kw(
            'pos.config', 'search_read',
            [[('id', '=', pos_id)]],
            {'fields': ['id', 'name', 'iface_available_categ_ids'], 'limit': 1}
        )
        if not pos_config:
            raise HTTPException(status_code=404, detail=f"Point de vente {pos_id} non trouvé")

        pos_name = pos_config[0]['name']
        allowed_categ_ids = pos_config[0].get('iface_available_categ_ids') or []

        # Domaine de base
        domain = [
            ('available_in_pos', '=', True),
            ('sale_ok', '=', True),
            ('active', '=', True),
        ]

        # Filtre par catégories POS restreintes (iface_available_categ_ids)
        if allowed_categ_ids:
            try:
                template_ids = client.execute_kw(
                    'product.template',
                    'search',
                    [[('pos_categ_ids', 'in', allowed_categ_ids)]],
                )
                if template_ids:
                    domain.append(('product_tmpl_id', 'in', template_ids))
                    logger.info(f"POS {pos_name}: {len(template_ids)} template(s) dans {len(allowed_categ_ids)} catégorie(s) POS")
                else:
                    logger.warning(f"POS {pos_name}: aucun produit lié aux catégories POS {allowed_categ_ids}, retour de tous les produits available_in_pos")
            except Exception as e:
                logger.warning(f"POS {pos_name}: impossible de filtrer par catégorie POS ({e}), retour de tous les produits disponibles")
        else:
            logger.info(f"POS {pos_name}: aucune restriction de catégorie, retour de tous les produits disponibles")

        # Filtre métier par type de produit station-service
        if filtre == 'produits_blanc':
            domain.append(('categ_id', 'in', _CATEG_PRODUITS_BLANC))
        elif filtre == 'lubrifiants':
            domain.append(('categ_id', 'in', _CATEG_LUBRIFIANTS))
        elif filtre == 'gaz_accessoire':
            domain.append(('categ_id', 'not in', _CATEG_POMPE))

        if search:
            domain.append(('name', 'ilike', search))

        products = client.execute_kw(
            'product.product',
            'search_read',
            [domain],
            {
                'fields': [
                    'id', 'name', 'default_code', 'barcode',
                    'list_price', 'standard_price', 'categ_id',
                    'uom_id', 'type', 'qty_available', 'description_sale'
                ],
                'order': 'name asc',
            }
        )

        if not products:
            return ApiResponse(
                success=True,
                data={'products': []},
                count=0,
                message="Aucun produit trouvé"
            )

        products_list = [
            {
                'id': prod['id'],
                'name': prod.get('name', 'N/A'),
                'code': prod.get('default_code'),
                'barcode': prod.get('barcode'),
                'price': prod.get('list_price', 0.0),
                'cost': prod.get('standard_price', 0.0),
                'category': prod['categ_id'][1] if prod.get('categ_id') and isinstance(prod['categ_id'], list) else 'N/A',
                'category_id': prod['categ_id'][0] if prod.get('categ_id') and isinstance(prod['categ_id'], list) else None,
                'unit': prod['uom_id'][1] if prod.get('uom_id') and isinstance(prod['uom_id'], list) else 'Unité',
                'unit_id': prod['uom_id'][0] if prod.get('uom_id') and isinstance(prod['uom_id'], list) else None,
                'type': prod.get('type', 'product'),
                'stock_quantity': prod.get('qty_available', 0.0),
                'description': prod.get('description_sale')
            }
            for prod in products
        ]

        filtre_label = filtre or 'tous'
        logger.info(f"POS {pos_name} ({pos_id}) [filtre={filtre_label}]: {len(products_list)} produit(s) retourné(s)")

        return ApiResponse(
            success=True,
            data={'products': products_list},
            count=len(products_list),
            message=f"{len(products_list)} produit(s) disponible(s) pour le POS '{pos_name}' [filtre={filtre_label}]"
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Erreur lors de la récupération des produits: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Erreur lors de la récupération: {str(e)}"
        )


@router.get("/products/categories", response_model=ApiResponse)
async def get_product_categories(
    current_user: dict = Depends(require_scope("pos"))
):
    """
    Retourne toutes les catégories de produits (product.category) de la base.

    **Requires:** Authentification JWT avec scope 'pos'
    """
    try:
        client = get_odoo_client(current_user)

        categories = client.execute_kw(
            'product.category',
            'search_read',
            [[]],
            {
                'fields': ['id', 'name', 'parent_id', 'complete_name'],
                'order': 'complete_name asc',
            }
        )

        categories_list = [
            {
                'id': cat['id'],
                'name': cat.get('name', ''),
                'complete_name': cat.get('complete_name', ''),
                'parent_id': cat['parent_id'][0] if cat.get('parent_id') and isinstance(cat['parent_id'], list) else None,
                'parent_name': cat['parent_id'][1] if cat.get('parent_id') and isinstance(cat['parent_id'], list) else None,
            }
            for cat in categories
        ]

        return ApiResponse(
            success=True,
            data={'categories': categories_list},
            count=len(categories_list),
            message=f"{len(categories_list)} catégorie(s) trouvée(s)"
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Erreur lors de la récupération des catégories produits: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Erreur lors de la récupération: {str(e)}"
        )


# ===== GESTION DES SESSIONS POS =====

@router.get("/{pos_id}/suggested-opening-balance", response_model=ApiResponse)
async def get_suggested_opening_balance(
    pos_id: int = Path(..., description="ID du point de vente"),
    current_user: dict = Depends(require_scope("pos"))
):
    """
    Récupérer le solde d'ouverture suggéré pour une nouvelle session
    
    Cette route retourne le solde de fermeture de la dernière session fermée
    comme suggestion pour le starting_balance de la nouvelle session.
    
    **Logique du solde suggéré:**
    1. Si une session est actuellement ouverte → retourne le solde actuel de cette session
    2. Si aucune session n'est ouverte → retourne le solde de fermeture de la dernière session fermée
    3. Si aucune session n'a jamais existé → retourne 0.00
    
    **Informations retournées:**
    - **suggested_balance**: Le solde suggéré pour l'ouverture
    - **last_session_id**: ID de la dernière session (si existante)
    - **last_session_state**: État de la dernière session
    - **last_closing_date**: Date de fermeture de la dernière session
    - **source**: D'où provient le solde suggéré ('current_session', 'last_closed_session', 'default')
    
    **Cas d'utilisation:**
    - Afficher le solde suggéré avant que le gérant n'ouvre une nouvelle session
    - Pré-remplir le champ starting_balance dans le formulaire d'ouverture
    - Vérifier la continuité des soldes entre les sessions
    
    **Requires:** Authentification JWT avec scope 'pos'
    """
    try:
        client = get_odoo_client(current_user)
        
        # Vérifier que le PDV existe
        pos_config = client.execute_kw(
            'pos.config',
            'read',
            [pos_id],
            {'fields': ['name', 'current_session_id', 'cash_control']}
        )
        
        if not pos_config:
            raise HTTPException(status_code=404, detail="Point de vente non trouvé")
        
        pos_config = pos_config[0]
        
        # Initialiser les variables
        suggested_balance = 0.0
        last_session_id = None
        last_session_state = None
        last_closing_date = None
        source = 'default'
        
        # CAS 1: Une session est actuellement ouverte
        if pos_config.get('current_session_id'):
            current_session_id = pos_config['current_session_id'][0] if isinstance(pos_config['current_session_id'], list) else pos_config['current_session_id']
            
            try:
                session = client.execute_kw(
                    'pos.session',
                    'read',
                    [current_session_id],
                    {'fields': ['state', 'cash_register_balance_end_real', 'cash_register_balance_start', 'stop_at']}
                )
                
                if session:
                    session = session[0]
                    last_session_id = current_session_id
                    last_session_state = session.get('state')
                    last_closing_date = session.get('stop_at')
                    
                    # Utiliser le solde actuel de la session ouverte
                    suggested_balance = float(
                        session.get('cash_register_balance_end_real', 0) or 
                        session.get('cash_register_balance_start', 0) or 
                        0
                    )
                    source = 'current_session'
                    
                    logger.info(f"PDV {pos_id}: Session {current_session_id} actuellement {last_session_state}, solde: {suggested_balance}")
            except Exception as e:
                logger.warning(f"Erreur lors de la récupération de la session courante: {e}")
        
        # CAS 2: Aucune session ouverte → chercher la dernière session fermée
        if source == 'default':
            try:
                last_sessions = client.execute_kw(
                    'pos.session',
                    'search_read',
                    [[('config_id', '=', pos_id), ('state', '=', 'closed')]],
                    {
                        'fields': ['id', 'cash_register_balance_end_real', 'stop_at'],
                        'order': 'stop_at desc',  # Trier par date de fermeture décroissante
                        'limit': 1
                    }
                )
                
                if last_sessions:
                    last_session = last_sessions[0]
                    last_session_id = last_session['id']
                    last_session_state = 'closed'
                    last_closing_date = last_session.get('stop_at')
                    
                    # Utiliser le solde de fermeture de la dernière session
                    suggested_balance = float(last_session.get('cash_register_balance_end_real', 0) or 0)
                    source = 'last_closed_session'
                    
                    logger.info(f"PDV {pos_id}: Dernière session fermée {last_session_id}, solde de fermeture: {suggested_balance}")
                else:
                    logger.info(f"PDV {pos_id}: Aucune session précédente trouvée, solde suggéré: 0.00")
            except Exception as e:
                logger.warning(f"Impossible de récupérer la dernière session fermée: {e}")
        
        # CAS 3: Format de réponse selon le contrôle de caisse
        cash_control_enabled = pos_config.get('cash_control', False)
        
        return ApiResponse(
            success=True,
            data={
                'pos_id': pos_id,
                'pos_name': pos_config['name'],
                'suggested_balance': suggested_balance,
                'last_session_id': last_session_id,
                'last_session_state': last_session_state,
                'last_closing_date': last_closing_date,
                'source': source,
                'cash_control_enabled': cash_control_enabled,
                'recommendation': {
                    'message': f"Utilisez {suggested_balance} comme solde de départ" if suggested_balance > 0 else "Aucune session précédente. Comptez votre caisse et entrez le montant réel.",
                    'source_description': {
                        'current_session': "Solde actuel de la session en cours",
                        'last_closed_session': "Solde de fermeture de la dernière session",
                        'default': "Aucune session précédente trouvée"
                    }.get(source, "Solde par défaut")
                }
            },
            message=f"Solde suggéré: {suggested_balance} (source: {source})"
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Erreur lors de la récupération du solde suggéré: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Erreur lors de la récupération du solde suggéré: {str(e)}"
        )

@router.get("/available", response_model=ApiResponse)
async def get_available_pos_shops(
    page: int = Query(1, ge=1, description="Numéro de page (commence à 1)"),
    page_size: int = Query(20, ge=1, le=100, description="Nombre d'éléments par page (max 100)"),
    current_user: dict = Depends(require_scope("pos"))
):
    """
    Récupérer les points de vente affectés à l'employé connecté
    
    Cette route retourne la liste des PDV auxquels l'employé connecté est affecté,
    avec l'état des sessions et les soldes.
    
    **Pagination :**
    - **page** : Numéro de page (défaut: 1)
    - **page_size** : Nombre d'éléments par page (défaut: 20, max: 100)
    
    Requires:
    - Authentification JWT avec scope 'pos'
    """
    try:
        from core.security import get_odoo_config_from_user
        
        client = get_odoo_client(current_user)
        
        # Récupérer la configuration de la base authentifiée
        db_config = get_odoo_config_from_user(current_user)
        db_name = db_config['name'] if db_config else "Base par défaut"
        
        # Récupérer l'ID de l'employé actuel depuis le token
        employee_id = current_user.get("employee_id")
        if not employee_id:
            logger.error("ID d'employé manquant dans le token")
            raise HTTPException(
                status_code=400,
                detail="Informations d'employé manquantes"
            )
        
        # Récupérer les PDV où cet employé a accès
        # Les PDV sont filtrés par les champs basic_employee_ids ou advanced_employee_ids
        pos_search_domain = [
            ('active', '=', True),
            '|',
            ('basic_employee_ids', 'in', [employee_id]),
            ('advanced_employee_ids', 'in', [employee_id])
        ]
        logger.info(f"Recherche des PDV affectés à l'employé {employee_id}")
        
        # Compter le total d'éléments
        total_count = client.execute_kw(
            'pos.config',
            'search_count',
            [pos_search_domain]
        )
        
        # Calculer l'offset pour la pagination
        offset = (page - 1) * page_size
        
        # Récupérer les PDV selon le filtre avec pagination
        pos_configs = client.execute_kw(
            'pos.config',
            'search_read',
            [pos_search_domain],
            {
                'fields': ['id', 'name', 'current_session_id', 'basic_employee_ids', 'advanced_employee_ids', 'company_id'],
                'limit': page_size,
                'offset': offset
            }
        )
        
        logger.info(f"Trouvé {len(pos_configs)} PDV pour l'utilisateur")
        
        available_pos = []
        for pos_config in pos_configs:
            # Log des employés affectés pour debug
            basic_employees = pos_config.get('basic_employee_ids', [])
            advanced_employees = pos_config.get('advanced_employee_ids', [])
            logger.debug(f"PDV {pos_config['name']} (ID: {pos_config['id']}) - Employés basiques: {basic_employees}, Employés avancés: {advanced_employees}")
            
            # Vérifier s'il y a une session active
            session_info = None
            balance = 0.0
            
            if pos_config.get('current_session_id'):
                session_id = pos_config['current_session_id'][0] if isinstance(pos_config['current_session_id'], list) else pos_config['current_session_id']
                session_data = client.execute_kw(
                    'pos.session',
                    'read',
                    [session_id],
                    {'fields': ['state', 'cash_register_balance_end_real', 'cash_register_balance_start']}
                )
                if session_data:
                    session_info = session_data[0]
                    # Récupérer le solde de la session active
                    balance = float(session_info.get('cash_register_balance_end_real', 0) or 
                                  session_info.get('cash_register_balance_start', 0) or 0)
            else:
                # Si pas de session active, récupérer le solde de la dernière session fermée
                try:
                    last_sessions = client.execute_kw(
                        'pos.session',
                        'search_read',
                        [[('config_id', '=', pos_config['id']), ('state', '=', 'closed')]],
                        {'fields': ['cash_register_balance_end_real'], 'order': 'create_date desc', 'limit': 1}
                    )
                    if last_sessions:
                        balance = float(last_sessions[0].get('cash_register_balance_end_real', 0) or 0)
                except Exception as e:
                    logger.warning(f"Impossible de récupérer le dernier solde pour PDV {pos_config['id']}: {e}")
                    balance = 0.0
            
            # Extraire les informations de company
            company_info = None
            if pos_config.get('company_id'):
                company_info = {
                    "id": pos_config['company_id'][0] if isinstance(pos_config['company_id'], list) else pos_config['company_id'],
                    "name": pos_config['company_id'][1] if isinstance(pos_config['company_id'], list) and len(pos_config['company_id']) > 1 else "N/A"
                }
            
            pos_shop = PosShop(
                id=pos_config['id'],
                name=pos_config['name'],
                is_station=False,  # Par défaut, peut être déterminé par d'autres moyens
                current_session_id=pos_config.get('current_session_id')[0] if pos_config.get('current_session_id') else None,
                current_session_state=session_info['state'] if session_info else None,
                balance=balance,
                company=company_info
            )
            available_pos.append(pos_shop)
        
        # Convertir les modèles Pydantic en dictionnaires et ajouter odoo_database
        available_pos_dict = []
        for pos in available_pos:
            pos_dict = pos.model_dump()
            pos_dict['odoo_database'] = db_name
            available_pos_dict.append(pos_dict)
        
        # Calculer le nombre total de pages
        total_pages = (total_count + page_size - 1) // page_size
        
        return {
            "success": True,
            "message": f"{len(available_pos)} PDV disponible(s) sur {total_count} au total",
            "data": available_pos_dict,
            "metadata": {
                "database": db_name,
                "total_count": total_count,
                "page": page,
                "page_size": page_size,
                "total_pages": total_pages
            }
        }
        
    except Exception as e:
        logger.error(f"Erreur lors de la récupération des PDV disponibles: {e}")
        raise HTTPException(status_code=500, detail=f"Erreur lors de la récupération des PDV: {str(e)}")

@router.get("/{pos_id}/session-status", response_model=PosSessionStatus)
async def get_pos_session_status(
    pos_id: int = Path(..., description="ID du point de vente"),
    current_user: dict = Depends(require_scope("pos"))
):
    """
    Vérifier l'état de la session POS pour un point de vente
    
    Cette route vérifie s'il existe une session active et si l'employé peut en ouvrir une nouvelle.
    
    Requires:
    - Authentification JWT avec scope 'pos'
    """
    try:
        client = get_odoo_client(current_user)
        
        # Vérifier si l'employé est gérant (par exemple via le département ou le poste)
        is_manager = False
        if current_user.get("auth_type") == "pin" and current_user.get("employee_id"):
            employee_data = client.execute_kw(
                'hr.employee',
                'read',
                [current_user["employee_id"]],
                {'fields': ['job_id', 'department_id']}
            )
            if employee_data:
                job_name = employee_data[0].get('job_id', [False, ''])[1].lower() if employee_data[0].get('job_id') else ''
                is_manager = 'gérant' in job_name or 'manager' in job_name or 'chef' in job_name
        
        # Vérifier l'état du PDV
        pos_config = client.execute_kw(
            'pos.config',
            'read',
            [pos_id],
            {'fields': ['name', 'current_session_id']}
        )
        
        if not pos_config:
            raise HTTPException(status_code=404, detail="Point de vente non trouvé")
        
        pos_config = pos_config[0]
        
        # Vérifier s'il y a une session active
        has_active_session = bool(pos_config.get('current_session_id'))
        session_id = None
        session_state = None
        
        if has_active_session:
            session_id = pos_config['current_session_id'][0] if isinstance(pos_config['current_session_id'], list) else pos_config['current_session_id']
            session_data = client.execute_kw(
                'pos.session',
                'read',
                [session_id],
                {'fields': ['state']}
            )
            if session_data:
                session_state = session_data[0]['state']
        
        return PosSessionStatus(
            pos_id=pos_id,
            has_active_session=has_active_session,
            session_id=session_id,
            session_state=session_state,
            can_open_session=is_manager,
            is_manager=is_manager
        )
        
    except Exception as e:
        logger.error(f"Erreur lors de la vérification du statut de session: {e}")
        raise HTTPException(status_code=500, detail=f"Erreur lors de la vérification: {str(e)}")

@router.post("/{pos_id}/resume-session", response_model=PosSessionResponse)
async def resume_pos_session(
    pos_id: int = Path(..., description="ID du point de vente"),
    current_user: dict = Depends(require_scope("pos"))
):
    """
    Reprendre une session POS existante
    
    Cette route permet à un employé de reprendre le service sur une caisse déjà ouverte.
    """
    try:
        client = get_odoo_client(current_user)
        
        # Vérifier l'état du PDV et de sa session
        pos_config = client.execute_kw(
            'pos.config',
            'read',
            [pos_id],
            {'fields': ['name', 'current_session_id']}
        )
        
        if not pos_config:
            raise HTTPException(status_code=404, detail="Point de vente non trouvé")
        
        pos_config = pos_config[0]
        
        if not pos_config.get('current_session_id'):
            raise HTTPException(status_code=400, detail="Aucune session active à reprendre")
        
        session_id = pos_config['current_session_id'][0] if isinstance(pos_config['current_session_id'], list) else pos_config['current_session_id']
        
        # Vérifier l'état de la session
        session_data = client.execute_kw(
            'pos.session',
            'read',
            [session_id],
            {'fields': ['state']}
        )
        
        if not session_data or session_data[0]['state'] != 'opened':
            raise HTTPException(status_code=400, detail="La session n'est pas dans un état permettant la reprise")
        
        return PosSessionResponse(
            session_id=session_id,
            pos_id=pos_id,
            pos_name=pos_config['name'],
            is_station=False,  # À déterminer par d'autres moyens si nécessaire
            state='resumed',
            message=f"Session {session_id} reprise avec succès sur {pos_config['name']}"
        )
        
    except Exception as e:
        logger.error(f"Erreur lors de la reprise de session: {e}")
        raise HTTPException(status_code=500, detail=f"Erreur lors de la reprise: {str(e)}")

@router.post("/{pos_id}/initialize-session", response_model=PosSessionResponse)
async def initialize_pos_session(
    pos_id: int = Path(..., description="ID du point de vente"),
    current_user: dict = Depends(require_scope("pos"))
):
    """
    Initialiser une nouvelle session POS (gérants uniquement)
    
    Cette route créé une nouvelle session POS et retourne le numéro de session.
    Seuls les gérants peuvent initialiser une session.
    """
    try:
        client = get_odoo_client(current_user)
        
        # Vérifier si l'employé est gérant
        is_manager = False
        
        # Si l'utilisateur est authentifié par PIN et a des infos additionnelles
        if current_user.get("auth_type") == "pin":
            # Vérifier d'abord dans les additional_info qui contiennent déjà le job
            additional_info = current_user.get("additional_info", {})
            job_title = additional_info.get("job", "").lower() if additional_info.get("job") else ""
            
            logger.info(f"Vérification gérant pour {current_user.get('username')}: job={job_title}")
            is_manager = 'gérant' in job_title or 'manager' in job_title or 'chef' in job_title
            
            # Si pas trouvé dans additional_info, chercher dans Odoo
            if not is_manager and current_user.get("employee_id"):
                try:
                    employee_data = client.execute_kw(
                        'hr.employee',
                        'read',
                        [current_user["employee_id"]],
                        {'fields': ['job_id']}
                    )
                    if employee_data and employee_data[0].get('job_id'):
                        job_name = employee_data[0]['job_id'][1].lower()
                        logger.info(f"Job depuis Odoo: {job_name}")
                        is_manager = 'gérant' in job_name or 'manager' in job_name or 'chef' in job_name
                except Exception as e:
                    logger.warning(f"Erreur lors de la récupération du job depuis Odoo: {e}")
        
        logger.info(f"Résultat vérification gérant: is_manager={is_manager}")
        
        if not is_manager:
            raise HTTPException(status_code=403, detail="Seuls les gérants peuvent initialiser une session")
        
        # Vérifier l'état du PDV
        logger.info(f"Vérification PDV {pos_id}")
        pos_config = client.execute_kw(
            'pos.config',
            'read',
            [pos_id],
            {'fields': ['name', 'current_session_id']}
        )
        
        if not pos_config:
            logger.error(f"PDV {pos_id} non trouvé")
            raise HTTPException(status_code=404, detail="Point de vente non trouvé")
        
        pos_config = pos_config[0]
        logger.info(f"PDV trouvé: {pos_config['name']}, session_id actuelle: {pos_config.get('current_session_id')}")
        
        if pos_config.get('current_session_id'):
            raise HTTPException(status_code=400, detail="Une session est déjà active sur ce point de vente")
        
        # Créer une nouvelle session
        # Dans Odoo, user_id pour une session POS doit correspondre à un utilisateur res.users
        # pas à un employé hr.employee
        session_data = {
            'config_id': pos_id,
            'user_id': 1,  # Utiliser admin par défaut pour l'instant
            'state': 'opening_control'  # État initial
        }
        
        logger.info(f"Création de session avec données: {session_data}")
        session_id = client.execute_kw('pos.session', 'create', [session_data])
        logger.info(f"Session créée avec ID: {session_id}")
        
        return PosSessionResponse(
            session_id=session_id,
            pos_id=pos_id,
            pos_name=pos_config['name'],
            is_station=False,  # À déterminer par d'autres moyens si nécessaire
            state='initialized',
            message=f"Session {session_id} initialisée pour {pos_config['name']}"
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Erreur lors de l'initialisation de session: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Erreur lors de l'initialisation: {str(e)}")


        
    except Exception as e:
        logger.error(f"Erreur lors de la récupération des pompes: {e}")
        raise HTTPException(status_code=500, detail=f"Erreur lors de la récupération des pompes: {str(e)}")

@router.post("/{pos_id}/open-session", response_model=PosSessionResponse)
async def open_pos_session(
    pos_id: int = Path(..., description="ID du point de vente"),
    request: PosUnifiedOpenSessionRequest = Body(...),
    current_user: dict = Depends(require_scope("pos"))
):
    """
    Ouvrir une session POS - Endpoint unifié
    
    Cette route permet d'ouvrir une session POS avec deux modes :
    
    **Mode Station-service (avec pompes):**
    ```json
    {
      "session_id": 123,
      "starting_balance": 1000.00,
      "pump_indexes": [
        {
          "id": "pump_001",
          "name": "J1_E1", 
          "stationId": "station_001",
          "type": "PETROL",
          "start_index": 1234.56
        }
      ]
    }
    ```
    
    **Note:** Le champ `starting_balance` est optionnel en mode station-service.
    Il permet de définir le solde de caisse initial pour le contrôle de trésorerie.
    
    **Mode Standard (caisse normale):**
    ```json
    {
      "starting_balance": 1000.00,
      "opening_notes": "Ouverture matinale"
    }
    ```
    
    Le mode est détecté automatiquement selon les données fournies.
    """
    try:
        client = get_odoo_client(current_user)
        
        # Détecter le mode selon les données fournies
        is_pump_mode = request.pump_indexes is not None and len(request.pump_indexes) > 0
        is_standard_mode = not is_pump_mode and (request.starting_balance is not None or request.opening_notes is not None)
        
        if not is_pump_mode and not is_standard_mode:
            raise HTTPException(
                status_code=400,
                detail="Données manquantes: fournissez pump_indexes pour station-service ou starting_balance/opening_notes pour caisse standard"
            )
        
        # === MODE STATION-SERVICE (avec pompes) ===
        if is_pump_mode:
            if not request.session_id:
                raise HTTPException(
                    status_code=400,
                    detail="session_id requis pour le mode station-service"
                )
            
            # Vérifier que la session existe
            session_data = client.execute_kw(
                'pos.session',
                'read',
                [request.session_id],
                {'fields': ['config_id', 'state', 'name']}
            )
            
            if not session_data:
                raise HTTPException(status_code=404, detail="Session non trouvée")
            
            session = session_data[0]
            
            if session['config_id'][0] != pos_id:
                raise HTTPException(status_code=400, detail="La session ne correspond pas au point de vente")
            
            if session['state'] not in ['opening_control', 'new']:
                logger.warning(f"Session {request.session_id} dans l'état {session['state']}, tentative d'ouverture forcée")
            
            # Traiter et sauvegarder les données des pompes
            try:
                # Sauvegarder les pompes dans la base de données SQLite
                pump_save_success = pump_manager.save_session_pumps(
                    session_id=request.session_id,
                    pos_id=pos_id,
                    pumps=request.pump_indexes
                )
                
                if not pump_save_success:
                    raise HTTPException(
                        status_code=500,
                        detail="Erreur lors de la sauvegarde des données de pompes"
                    )
                
                # Log des pompes sauvegardées
                for pump in request.pump_indexes:
                    logger.info(f"Pompe {pump.name} ({pump.type}): Index de début = {pump.start_index}")
                
                # Mettre à jour la session dans Odoo avec le solde de départ (si fourni)
                session_update = {'state': 'opened'}
                if request.starting_balance is not None:
                    session_update['cash_register_balance_start'] = request.starting_balance
                    logger.info(f"Solde de départ caisse: {request.starting_balance}")
                
                client.execute_kw('pos.session', 'write', [[request.session_id], session_update])
                
                # Récupérer les informations du PDV
                pos_config = client.execute_kw(
                    'pos.config',
                    'read',
                    [pos_id],
                    {'fields': ['name']}
                )[0]
                
                # Message avec infos du solde
                message_parts = [f"{len(request.pump_indexes)} pompes initialisées et sauvegardées"]
                if request.starting_balance is not None:
                    message_parts.append(f"Solde départ: {request.starting_balance}")
                
                logger.info(f"Session {request.session_id} ouverte avec {len(request.pump_indexes)} pompes sauvegardées")
                
                return PosSessionResponse(
                    session_id=request.session_id,
                    pos_id=pos_id,
                    pos_name=pos_config['name'],
                    is_station=True,
                    state='opened',
                    message=f"Session station-service ouverte - {', '.join(message_parts)}"
                )
                
            except HTTPException:
                raise
            except Exception as e:
                logger.error(f"Erreur lors du traitement des pompes: {e}")
                raise HTTPException(
                    status_code=500,
                    detail=f"Erreur lors de la sauvegarde des pompes: {str(e)}"
                )
        
        # === MODE STANDARD (caisse normale) ===
        else:
            # Créer une nouvelle session pour le mode standard
            session_vals = {
                'config_id': pos_id,
                'user_id': current_user.get('employee_id', 1),  # Utiliser l'ID employé ou fallback
            }
            
            # Ajouter le solde de départ si fourni
            if request.starting_balance is not None:
                session_vals['cash_register_balance_start'] = request.starting_balance
            
            # Créer la session
            new_session_id = client.execute_kw(
                'pos.session',
                'create',
                [session_vals]
            )
            
            # Ouvrir la session immédiatement
            client.execute_kw('pos.session', 'write', [[new_session_id], {'state': 'opened'}])
            
            # Récupérer les informations du PDV
            pos_config = client.execute_kw(
                'pos.config',
                'read',
                [pos_id],
                {'fields': ['name']}
            )[0]
            
            # Log des informations d'ouverture
            opening_info = f"Solde: {request.starting_balance or 0}"
            if request.opening_notes:
                opening_info += f", Notes: {request.opening_notes}"
            logger.info(f"Session standard {new_session_id} ouverte - {opening_info}")
            
            return PosSessionResponse(
                session_id=new_session_id,
                pos_id=pos_id,
                pos_name=pos_config['name'],
                is_station=False,
                state='opened',
                message=f"Session standard ouverte - {opening_info}"
            )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Erreur lors de l'ouverture de session: {e}")
        raise HTTPException(status_code=500, detail=f"Erreur lors de l'ouverture: {str(e)}")

@router.get("/{pos_id}/session/{session_id}/pumps", response_model=ApiResponse)
async def get_session_pumps(
    pos_id: int = Path(..., description="ID du point de vente"),
    session_id: int = Path(..., description="ID de la session"),
    current_user: dict = Depends(require_scope("pos"))
):
    """
    Récupérer les pompes sauvegardées pour une session
    
    Cette route retourne les pompes avec leurs index actuels pour les ventes.
    """
    try:
        client = get_odoo_client(current_user)
        
        # Vérifier que la session existe et appartient au bon PDV
        session_data = client.execute_kw(
            'pos.session',
            'read',
            [session_id],
            {'fields': ['config_id', 'state']}
        )
        
        if not session_data or session_data[0]['config_id'][0] != pos_id:
            raise HTTPException(status_code=404, detail="Session non trouvée pour ce point de vente")
        
        # Récupérer les pompes depuis le gestionnaire
        pumps = pump_manager.get_session_pumps(session_id)
        
        if not pumps:
            logger.warning(f"Aucune pompe trouvée pour session {session_id}")
            return ApiResponse(
                success=True,
                data=[],
                count=0,
                message="Aucune pompe configurée pour cette session"
            )
        
        logger.info(f"Session {session_id}: {len(pumps)} pompes récupérées")
        return ApiResponse(
            success=True,
            data=pumps,
            count=len(pumps),
            message=f"{len(pumps)} pompes disponibles"
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Erreur lors de la récupération des pompes pour session {session_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Erreur lors de la récupération des pompes: {str(e)}")
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Erreur lors de la récupération des pompes de session: {e}")
        raise HTTPException(status_code=500, detail=f"Erreur lors de la récupération: {str(e)}")

@router.put("/{pos_id}/session/{session_id}/pump-indexes", response_model=ApiResponse)
async def update_pump_indexes(
    pos_id: int = Path(..., description="ID du point de vente"),
    session_id: int = Path(..., description="ID de la session"),
    pump_data: List[StationPumpData] = Body(..., description="Données des pompes mises à jour"),
    current_user: dict = Depends(require_scope("pos"))
):
    """
    Mettre à jour les index des pompes pendant une session active
    
    Cette route permet de mettre à jour les index actuels des pompes
    pendant qu'une session est en cours.
    """
    try:
        client = get_odoo_client(current_user)
        
        # Vérifier que la session existe et est ouverte
        session_data = client.execute_kw(
            'pos.session',
            'read',
            [session_id],
            {'fields': ['config_id', 'state']}
        )
        
        if not session_data or session_data[0]['config_id'][0] != pos_id:
            raise HTTPException(status_code=404, detail="Session non trouvée")
        
        if session_data[0]['state'] != 'opened':
            raise HTTPException(status_code=400, detail="La session n'est pas ouverte")
        
        # Traiter la mise à jour des index avec le gestionnaire de pompes
        updated_pumps = []
        update_errors = []
        
        for pump in pump_data:
            try:
                # Utiliser le gestionnaire pour mettre à jour l'index
                success = pump_manager.update_pump_index(
                    session_id=session_id,
                    pump_id=pump.id,
                    new_index=pump.start_index,  # L'index actuel est dans start_index
                    order_id=None  # Pas d'order_id pour une mise à jour manuelle
                )
                
                if success:
                    updated_pumps.append({
                        'pump_id': pump.id,
                        'pump_name': pump.name,
                        'fuel_type': pump.type,
                        'new_index': pump.start_index,
                        'status': 'updated'
                    })
                    logger.info(f"Pompe {pump.name}: Index mis à jour à {pump.start_index}")
                else:
                    update_errors.append(f"Échec mise à jour pompe {pump.name}")
                    
            except Exception as e:
                error_msg = f"Erreur pompe {pump.name}: {str(e)}"
                update_errors.append(error_msg)
                logger.error(error_msg)
        
        # Récupérer le résumé mis à jour
        sales_summary = pump_manager.get_session_sales_summary(session_id)
        
        response_data = {
            'session_id': session_id,
            'pumps_updated': len(updated_pumps),
            'update_errors': update_errors,
            'pump_details': updated_pumps,
            'sales_summary': sales_summary
        }
        
        if update_errors:
            logger.warning(f"Session {session_id}: {len(update_errors)} erreurs lors de la mise à jour")
        
        return ApiResponse(
            success=len(update_errors) == 0,
            data=response_data,
            message=f"Index de {len(updated_pumps)} pompes mis à jour avec succès"
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Erreur lors de la mise à jour des index: {e}")
        raise HTTPException(status_code=500, detail=f"Erreur lors de la mise à jour: {str(e)}")

@router.get("/{pos_id}/session/{session_id}/pumps/available", response_model=ApiResponse)
async def get_available_pumps_for_sale(
    pos_id: int = Path(..., description="ID du point de vente"),
    session_id: int = Path(..., description="ID de la session"),
    min_quantity: float = 0.1,
    current_user: dict = Depends(require_scope("pos"))
):
    """
    Récupérer les pompes disponibles pour la vente
    
    Cette route retourne uniquement les pompes qui ont encore du carburant disponible.
    """
    try:
        client = get_odoo_client(current_user)
        
        # Vérifier que la session existe et est ouverte
        session_data = client.execute_kw(
            'pos.session',
            'read',
            [session_id],
            {'fields': ['config_id', 'state']}
        )
        
        if not session_data or session_data[0]['config_id'][0] != pos_id:
            raise HTTPException(status_code=404, detail="Session non trouvée")
        
        if session_data[0]['state'] != 'opened':
            raise HTTPException(status_code=400, detail="La session n'est pas ouverte")
        
        # Récupérer les pompes disponibles pour la vente
        available_pumps = pump_manager.get_available_pumps_for_sale(session_id, min_quantity)
        
        return ApiResponse(
            success=True,
            data=available_pumps,
            count=len(available_pumps),
            message=f"{len(available_pumps)} pompes disponibles pour la vente"
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Erreur lors de la récupération des pompes disponibles: {e}")
        raise HTTPException(status_code=500, detail=f"Erreur lors de la récupération: {str(e)}")

@router.get("/{pos_id}/session/{session_id}/sales-summary", response_model=ApiResponse)
async def get_session_sales_summary(
    pos_id: int = Path(..., description="ID du point de vente"),
    session_id: int = Path(..., description="ID de la session"),
    current_user: dict = Depends(require_scope("pos"))
):
    """
    Récupérer le résumé des ventes par pompe pour une session
    
    Cette route retourne un résumé détaillé des ventes par pompe avec les totaux.
    """
    try:
        client = get_odoo_client(current_user)
        
        # Vérifier que la session existe
        session_data = client.execute_kw(
            'pos.session',
            'read',
            [session_id],
            {'fields': ['config_id', 'state']}
        )
        
        if not session_data or session_data[0]['config_id'][0] != pos_id:
            raise HTTPException(status_code=404, detail="Session non trouvée")
        
        # Récupérer le résumé des ventes
        sales_summary = pump_manager.get_session_sales_summary(session_id)
        
        if not sales_summary:
            return ApiResponse(
                success=True,
                data={},
                message="Aucune donnée de vente trouvée pour cette session"
            )
        
        return ApiResponse(
            success=True,
            data=sales_summary,
            message="Résumé des ventes récupéré avec succès"
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Erreur lors de la récupération du résumé des ventes: {e}")
        raise HTTPException(status_code=500, detail=f"Erreur lors de la récupération: {str(e)}")

@router.post("/{pos_id}/session/{session_id}/pumps/{pump_id}/sale", response_model=ApiResponse)
async def record_pump_sale(
    pos_id: int = Path(..., description="ID du point de vente"),
    session_id: int = Path(..., description="ID de la session"),
    pump_id: str = Path(..., description="ID de la pompe"),
    sale_data: Dict[str, Any] = Body(..., description="Données de la vente"),
    current_user: dict = Depends(require_scope("pos"))
):
    """
    Enregistrer une vente sur une pompe spécifique
    
    Body attendu:
    {
        "end_index": 1234.56,
        "order_id": 123,
        "quantity": 25.5,
        "amount": 35.50
    }
    """
    try:
        client = get_odoo_client(current_user)
        
        # Vérifier que la session existe et est ouverte
        session_data = client.execute_kw(
            'pos.session',
            'read',
            [session_id],
            {'fields': ['config_id', 'state']}
        )
        
        if not session_data or session_data[0]['config_id'][0] != pos_id:
            raise HTTPException(status_code=404, detail="Session non trouvée")
        
        if session_data[0]['state'] != 'opened':
            raise HTTPException(status_code=400, detail="La session n'est pas ouverte")
        
        # Extraire les données de vente
        end_index = sale_data.get('end_index')
        order_id = sale_data.get('order_id')
        
        if not end_index:
            raise HTTPException(status_code=400, detail="end_index requis")
        
        # Mettre à jour l'index de la pompe
        success = pump_manager.update_pump_index(
            session_id=session_id,
            pump_id=pump_id,
            new_index=end_index,
            order_id=order_id
        )
        
        if not success:
            raise HTTPException(status_code=400, detail="Erreur lors de l'enregistrement de la vente")
        
        # Récupérer les informations mises à jour de la pompe
        pumps = pump_manager.get_session_pumps(session_id)
        pump_info = next((p for p in pumps if p['id'] == pump_id), None)
        
        response_data = {
            'pump_id': pump_id,
            'order_id': order_id,
            'sale_recorded': True,
            'pump_info': pump_info
        }
        
        logger.info(f"Vente enregistrée - Pompe {pump_id}, Order {order_id}, Index: {end_index}")
        
        return ApiResponse(
            success=True,
            data=response_data,
            message=f"Vente enregistrée avec succès pour la pompe {pump_id}"
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Erreur lors de l'enregistrement de la vente: {e}")
        raise HTTPException(status_code=500, detail=f"Erreur lors de l'enregistrement: {str(e)}")

@router.post("/{pos_id}/close-session", response_model=PosSessionResponse)
async def close_pos_session(
    pos_id: int = Path(..., description="ID du point de vente"),
    request: PosCloseSessionRequest = Body(...),
    current_user: dict = Depends(require_scope("pos"))
):
    """
    Fermer la session POS active (gérants uniquement)
    
    Cette route ferme la session POS active sur un point de vente avec deux modes :
    
    **Mode Simple** (sans pump_indexes):
    - Fermeture standard pour PDV classiques
    - Validation basique du solde
    
    **Mode Station-Service** (avec pump_indexes):
    - Fermeture avec validation des pompes
    - Contrôle de cohérence index vs ventes
    - Tolérance de 1% ou 1L pour les différences
    
    **Payload unifié (identique à l'ouverture):**
    ```json
    {
      "session_id": 123,
      "starting_balance": 1000.00,
      "ending_balance": 5000.00,
      "forced": false,
      "pump_indexes": [
        {
          "id": "pump_001",
          "name": "J1_E1", 
          "stationId": "station_001",
          "type": "PETROL",
          "start_index": 1234.56,
          "end_index": 2345.67
        }
      ],
      "closing_notes": "Fermeture normale"
    }
    ```
    
    **Vérification de cohérence:**
    Le système vérifie que `ending_balance == starting_balance + total_ventes`.
    Si le solde ne correspond pas, la fermeture est **refusée** avec le détail de l'écart.
    
    Pour forcer la fermeture malgré un écart, envoyez `"forced": true`.
    
    **Paramètres:**
    - **session_id**: ID de la session à fermer (optionnel si détection auto)
    - **starting_balance**: Solde d'ouverture pour vérification de cohérence (optionnel)
    - **ending_balance**: Solde de fermeture déclaré (optionnel)
    - **forced**: Forcer la fermeture même si ending_balance ≠ starting_balance + total ventes (défaut: false)
    - **closing_notes**: Notes de fermeture (optionnel)  
    - **pump_indexes**: Données complètes des pompes avec index de fin (optionnel, active le mode station)
    
    **Requires:** Authentification JWT avec scope 'pos' + Profil gérant
    """
    try:
        client = get_odoo_client(current_user)
        
        # Support du nouveau format pump_indexes et de l'ancien pump_end_indexes
        pump_data_list = request.pump_indexes if request.pump_indexes else request.pump_end_indexes
        
        # Déterminer le mode de fermeture
        is_station_mode = pump_data_list is not None and len(pump_data_list) > 0
        logger.info(f"Mode de fermeture: {'Station-Service' if is_station_mode else 'Standard'}")
        
        # Log des données reçues pour debug
        if request.starting_balance is not None:
            logger.info(f"Solde d'ouverture (vérification): {request.starting_balance}")
        if request.ending_balance is not None:
            logger.info(f"Solde de fermeture déclaré: {request.ending_balance}")
        
        # Vérifier si l'employé est gérant
        if not verify_manager_role(current_user, client):
            raise HTTPException(status_code=403, detail="Seuls les gérants peuvent fermer une session")
        
        # Récupérer la session active du PDV
        logger.info(f"Recherche de session active pour PDV {pos_id}")
        pos_config = client.execute_kw(
            'pos.config',
            'read',
            [pos_id],
            {'fields': ['name', 'current_session_id']}
        )
        
        if not pos_config:
            logger.error(f"PDV {pos_id} non trouvé")
            raise HTTPException(status_code=404, detail="Point de vente non trouvé")
        
        pos_config = pos_config[0]
        
        if not pos_config.get('current_session_id'):
            raise HTTPException(status_code=400, detail="Aucune session active à fermer sur ce point de vente")
        
        session_id = pos_config['current_session_id'][0] if isinstance(pos_config['current_session_id'], list) else pos_config['current_session_id']
        
        # Mode Station-Service : Validation des pompes avec notre gestionnaire
        validation_result = None
        if is_station_mode:
            logger.info(f"Mode station activé - Validation de {len(pump_data_list)} pompe(s)")
            
            try:
                # Mettre à jour les index finaux des pompes
                update_errors = []
                for pump_data in pump_data_list:
                    # Support des deux formats
                    if isinstance(pump_data, dict):
                        pump_id = pump_data.get('pump_id') or pump_data.get('id')
                        end_index = pump_data.get('end_index') or pump_data.get('current_index')
                    else:
                        # Format StationPumpData
                        pump_id = pump_data.id
                        end_index = getattr(pump_data, 'end_index', None) or getattr(pump_data, 'current_index', None)
                    
                    if not pump_id or end_index is None:
                        update_errors.append(f"Données manquantes pour pompe: {pump_data}")
                        continue
                    
                    success = pump_manager.update_pump_index(
                        session_id=session_id,
                        pump_id=pump_id,
                        new_index=end_index,
                        order_id=None  # Fermeture de session
                    )
                    
                    if not success:
                        error_msg = f"Pompe '{pump_id}' non trouvée pour session {session_id}. "
                        error_msg += "Assurez-vous que la pompe a été enregistrée lors de l'ouverture de la session."
                        update_errors.append(error_msg)
                        logger.error(error_msg)
                
                if update_errors:
                    logger.error(f"Erreurs lors de la mise à jour des pompes: {update_errors}")
                    raise HTTPException(
                        status_code=400,
                        detail=f"Erreurs pompes: {'; '.join(update_errors)}"
                    )
                
                # Valider la cohérence des données avec notre gestionnaire
                validation_report = pump_manager.validate_session_closure(session_id)
                
                if not validation_report['valid']:
                    logger.warning(f"Validation des pompes échouée: {validation_report['errors']}")
                    raise HTTPException(
                        status_code=400,
                        detail=f"Validation des pompes échouée: {'; '.join(validation_report['errors'])}"
                    )
                
                if validation_report['warnings']:
                    logger.warning(f"Avertissements validation pompes: {validation_report['warnings']}")
                
                logger.info("✅ Validation des pompes réussie avec notre gestionnaire")
                validation_result = validation_report
                
            except HTTPException:
                raise
            except Exception as e:
                logger.error(f"Erreur lors de la validation des pompes: {e}")
                raise HTTPException(
                    status_code=500,
                    detail=f"Erreur lors de la validation des pompes: {str(e)}"
                )
        
        # Vérifier l'état de la session et récupérer les données financières
        session_data = client.execute_kw(
            'pos.session',
            'read',
            [session_id],
            {'fields': ['state', 'cash_register_balance_start', 'cash_register_total_entry_encoding', 'order_count']}
        )
        
        if not session_data:
            raise HTTPException(status_code=404, detail="Session non trouvée")
        
        session = session_data[0]
        
        # Récupérer le solde d'ouverture depuis Odoo
        odoo_starting_balance = float(session.get('cash_register_balance_start', 0.0) or 0.0)
        
        # Récupérer le total des ventes cash de la session
        # cash_register_total_entry_encoding = total des mouvements cash enregistrés
        odoo_total_cash_entries = float(session.get('cash_register_total_entry_encoding', 0.0) or 0.0)
        order_count = int(session.get('order_count', 0) or 0)
        
        # Calculer aussi le total via les commandes POS de la session
        try:
            pos_orders = client.execute_kw(
                'pos.order',
                'search_read',
                [[['session_id', '=', session_id], ['state', 'in', ['paid', 'done', 'invoiced']]]],
                {'fields': ['amount_total', 'amount_paid']}
            )
            total_sales_from_orders = sum(float(o.get('amount_paid', 0.0) or 0.0) for o in pos_orders)
            order_count = len(pos_orders)
            logger.info(f"Session {session_id}: {order_count} commande(s), total ventes={total_sales_from_orders}")
        except Exception as e:
            logger.warning(f"Impossible de récupérer les commandes POS: {e}")
            total_sales_from_orders = odoo_total_cash_entries
            order_count = session.get('order_count', 0)
        
        # Utiliser le total le plus fiable
        total_sales = total_sales_from_orders if total_sales_from_orders > 0 else odoo_total_cash_entries
        
        # Vérification de cohérence du solde d'ouverture si fourni
        if request.starting_balance is not None:
            if abs(request.starting_balance - odoo_starting_balance) > 0.01:
                logger.warning(
                    f"Incohérence solde d'ouverture: Reçu={request.starting_balance}, "
                    f"Odoo={odoo_starting_balance}"
                )
        
        # === VÉRIFICATION DE COHÉRENCE : ending_balance == starting_balance + total_ventes ===
        if request.ending_balance is not None:
            expected_balance = odoo_starting_balance + total_sales
            difference = abs(request.ending_balance - expected_balance)
            
            logger.info(
                f"Vérification solde: starting={odoo_starting_balance}, "
                f"total_ventes={total_sales}, expected_ending={expected_balance}, "
                f"declared_ending={request.ending_balance}, diff={difference}"
            )
            
            # Tolérance de 0.01 pour les arrondis
            if difference > 0.01:
                if not request.forced:
                    raise HTTPException(
                        status_code=400,
                        detail={
                            "error": "balance_mismatch",
                            "message": (
                                f"Le solde de fermeture déclaré ({request.ending_balance} FCFA) ne correspond pas "
                                f"au solde attendu ({expected_balance} FCFA). "
                                f"Détail: solde ouverture ({odoo_starting_balance}) + total ventes ({total_sales}) "
                                f"= {expected_balance}. Différence: {difference} FCFA. "
                                f"Envoyez forced=true pour forcer la fermeture."
                            ),
                            "starting_balance": odoo_starting_balance,
                            "total_sales": total_sales,
                            "expected_ending_balance": expected_balance,
                            "declared_ending_balance": request.ending_balance,
                            "difference": difference,
                            "order_count": order_count
                        }
                    )
                else:
                    logger.warning(
                        f"⚠️ FERMETURE FORCÉE - Décalage de {difference} FCFA. "
                        f"Attendu={expected_balance}, Déclaré={request.ending_balance}"
                    )
        
        if session['state'] not in ['opened', 'opening_control']:
            raise HTTPException(
                status_code=400, 
                detail=f"La session ne peut pas être fermée. État actuel: {session['state']}"
            )
        
        # Préparer les données de fermeture
        closing_data = {'state': 'closing_control'}
        
        # Ajouter le solde de fermeture s'il est fourni
        if request.ending_balance is not None:
            closing_data['cash_register_balance_end_real'] = request.ending_balance
            logger.info(f"Solde de fermeture déclaré: {request.ending_balance}")
        
        # Ajouter les notes de fermeture s'il y en a
        if request.closing_notes:
            closing_data['note_closing'] = request.closing_notes
            logger.info(f"Notes de fermeture: {request.closing_notes}")
        
        # Fermer la session (passer en closing_control d'abord)
        logger.info(f"Fermeture de la session {session_id}")
        client.execute_kw('pos.session', 'write', [[session_id], closing_data])
        
        # Finaliser la fermeture (passer en closed)
        try:
            # Certaines versions d'Odoo nécessitent un appel de méthode pour finaliser
            client.execute_kw('pos.session', 'action_pos_session_closing_control', [[session_id]])
            final_state = 'closed'
        except Exception as e:
            logger.warning(f"Impossible de finaliser automatiquement la fermeture: {e}")
            # Essayer de passer directement en état 'closed'
            try:
                client.execute_kw('pos.session', 'write', [[session_id], {'state': 'closed'}])
                final_state = 'closed'
            except Exception as e2:
                logger.warning(f"Impossible de passer en état closed: {e2}")
                final_state = 'closing_control'
        
        # Construire le message de réponse
        forced_msg = " (FORCÉE)" if request.forced else ""
        if is_station_mode:
            message = f"Session fermée avec succès{forced_msg} - Mode station-service - {len(pump_data_list)} pompe(s) validée(s)"
            if request.ending_balance is not None:
                message += f" - Solde final: {request.ending_balance} FCFA"
        else:
            message = f"Session fermée avec succès{forced_msg} - Mode standard"
            if request.ending_balance is not None:
                message += f" - Solde final: {request.ending_balance} FCFA"
        
        response_data = {
            'session_id': session_id,
            'pos_id': pos_id,
            'pos_name': pos_config['name'],
            'is_station': is_station_mode,
            'state': final_state,
            'message': message,
            'balance_summary': {
                'starting_balance': odoo_starting_balance,
                'total_sales': total_sales,
                'expected_ending_balance': odoo_starting_balance + total_sales,
                'declared_ending_balance': request.ending_balance,
                'order_count': order_count,
                'forced': request.forced
            }
        }
        
        # Ajouter les résultats de validation si mode station
        if validation_result:
            response_data['validation_summary'] = {
                'total_pumps': len(validation_result.pump_validations),
                'valid_pumps': sum(1 for p in validation_result.pump_validations if p.is_valid),
                'total_sales': validation_result.total_sales
            }
        
        return PosSessionResponse(**response_data)
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Erreur lors de la fermeture de session: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Erreur lors de la fermeture: {str(e)}")
# ===== GESTION DES POMPES ET VENTES =====


@router.post("/{pos_id}/select-pumps")
async def select_pumps_for_sale(
    pos_id: int = Path(..., description="ID du point de vente"),
    request: PumpSelectionRequest = None,
    current_user: dict = Depends(require_scope("pos"))
):
    """
    Sélectionner les pompes pour une vente avec confirmation des produits
    
    Cette route permet à l'agent de sélectionner les pompes qu'il veut utiliser
    avec confirmation du produit associé à chaque pompe.
    
    Requires:
    - Authentification JWT avec scope 'pos'
    """
    try:
        client = get_odoo_client(current_user)
        
        # Vérifier que le PDV a une session active
        pos_config = client.execute_kw(
            'pos.config',
            'read',
            [pos_id],
            {'fields': ['name', 'current_session_id']}
        )
        
        if not pos_config or not pos_config[0].get('current_session_id'):
            raise HTTPException(
                status_code=400, 
                detail="Aucune session active sur ce point de vente"
            )
        
        selected_pumps_details = []
        
        for pump_selection in request.selected_pumps:
            # Récupérer les détails de chaque pompe sélectionnée
            # Dans un vrai système, ceci ferait référence à votre modèle de pompe
            pump_id = pump_selection.pump_id
            
            # Simulation de récupération des détails de pompe
            # Vous devrez adapter ceci à votre modèle Odoo de pompe
            pump_details = {
                'pump_id': pump_id,
                'name': f"Pompe {pump_id}",
                'product_confirmed': pump_selection.product_confirmed,
                'is_ready_for_sale': True,
                'current_index': 1000.0 + (pump_id * 100)  # Index fictif
            }
            
            selected_pumps_details.append(pump_details)
        
        return ApiResponse(
            success=True,
            data={
                'pos_id': pos_id,
                'session_id': pos_config[0]['current_session_id'][0],
                'selected_pumps': selected_pumps_details,
                'total_pumps_selected': len(selected_pumps_details)
            },
            message=f"{len(selected_pumps_details)} pompe(s) sélectionnée(s) et prête(s) pour la vente"
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Erreur lors de la sélection des pompes: {e}")
        raise HTTPException(status_code=500, detail=f"Erreur lors de la sélection: {str(e)}")

@router.get("/{pos_id}/products", response_model=ApiResponse)
async def get_pos_products(
    pos_id: int = Path(..., description="ID du point de vente"),
    limit: int = 50,
    search: Optional[str] = None,
    current_user: dict = Depends(require_scope("pos"))
):
    """
    Récupérer les produits disponibles pour le point de vente
    
    Cette route retourne la liste des produits avec leur ID, nom, prix
    et autres informations utiles pour créer des commandes.
    
    Requires:
    - Authentification JWT avec scope 'pos'
    """
    try:
        client = get_odoo_client(current_user)
        
        # Construire le domaine de recherche
        domain = [
            ('sale_ok', '=', True),
            ('available_in_pos', '=', True)
        ]
        
        # Ajouter la recherche textuelle si fournie
        if search:
            domain.extend([
                '|', '|',
                ('name', 'ilike', search),
                ('default_code', 'ilike', search),
                ('barcode', 'ilike', search)
            ])
        
        # Récupérer les produits
        products = client.execute_kw(
            'product.product',
            'search_read',
            [domain],
            {
                'fields': [
                    'id', 'name', 'default_code', 'barcode', 'list_price',
                    'categ_id', 'uom_id', 'taxes_id', 'available_in_pos'
                ],
                'limit': limit,
                'order': 'name'
            }
        )
        
        # Formater les données pour l'API
        formatted_products = []
        for product in products:
            formatted_product = {
                'id': product['id'],
                'name': product['name'],
                'code': product.get('default_code', ''),
                'barcode': product.get('barcode', ''),
                'price': float(product['list_price']),
                'category': product['categ_id'][1] if product.get('categ_id') else 'Sans catégorie',
                'uom': product['uom_id'][1] if product.get('uom_id') else 'Unité'
            }
            formatted_products.append(formatted_product)
        
        return ApiResponse(
            success=True,
            data=formatted_products,
            message=f"{len(formatted_products)} produit(s) trouvé(s)"
        )
        
    except Exception as e:
        logger.error(f"Erreur lors de la récupération des produits: {e}")
        raise HTTPException(status_code=500, detail=f"Erreur lors de la récupération: {str(e)}")

@router.get("/{pos_id}/payment-methods", response_model=ApiResponse)
async def get_payment_methods(
    pos_id: int = Path(..., description="ID du point de vente"),
    current_user: dict = Depends(require_scope("pos"))
):
    """
    Récupérer les méthodes de paiement disponibles pour le point de vente
    
    Cette route retourne la liste des méthodes de paiement configurées
    pour le point de vente (espèces, carte, etc.).
    
    Requires:
    - Authentification JWT avec scope 'pos'
    """
    try:
        client = get_odoo_client(current_user)
        
        # Récupérer la configuration du PDV
        pos_config = client.execute_kw(
            'pos.config',
            'read',
            [pos_id],
            {'fields': ['payment_method_ids']}
        )
        
        if not pos_config:
            raise HTTPException(status_code=404, detail="Point de vente non trouvé")
        
        payment_method_ids = pos_config[0].get('payment_method_ids', [])
        
        if not payment_method_ids:
            # Si aucune méthode configurée, récupérer les méthodes par défaut
            payment_methods = client.execute_kw(
                'pos.payment.method',
                'search_read',
                [[]],
                {
                    'fields': ['id', 'name', 'type', 'use_payment_terminal'],
                    'limit': 10
                }
            )
        else:
            # Récupérer les méthodes configurées pour ce PDV
            payment_methods = client.execute_kw(
                'pos.payment.method',
                'read',
                [payment_method_ids],
                {'fields': ['id', 'name', 'type', 'use_payment_terminal']}
            )
        
        # Formater les données
        formatted_methods = []
        for method in payment_methods:
            formatted_method = {
                'id': method['id'],
                'name': method['name'],
                'type': method.get('type', 'cash'),
                'is_terminal': method.get('use_payment_terminal', False)
            }
            formatted_methods.append(formatted_method)
        
        return ApiResponse(
            success=True,
            data=formatted_methods,
            message=f"{len(formatted_methods)} méthode(s) de paiement disponible(s)"
        )
        
    except Exception as e:
        logger.error(f"Erreur lors de la récupération des méthodes de paiement: {e}")
        raise HTTPException(status_code=500, detail=f"Erreur lors de la récupération: {str(e)}")


@router.post("/payment-methods", response_model=ApiResponse)
async def create_payment_method(
    request: PosPaymentMethodCreateRequest,
    current_user: dict = Depends(require_scope("pos"))
):
    """
    Créer un nouveau mode de paiement POS dans Odoo.

    - **Cash** : `is_cash_count=true` + `journal_id` requis (journal de caisse)
    - **Externe (KKiaPay, Token, JNPPass)** : `is_cash_count=false`, `journal_id` optionnel

    **Requires:** Authentification JWT avec scope 'pos'
    """
    try:
        client = get_odoo_client(current_user)

        vals = {
            'name': request.name,
            'is_cash_count': request.is_cash_count,
        }
        if request.journal_id:
            vals['journal_id'] = request.journal_id

        method_id = client.execute_kw('pos.payment.method', 'create', [vals])
        logger.info(f"Mode de paiement créé : '{request.name}' (ID: {method_id})")

        created = client.execute_kw(
            'pos.payment.method', 'read', [method_id],
            {'fields': ['id', 'name', 'is_cash_count', 'journal_id']}
        )
        method = created[0]

        return ApiResponse(
            success=True,
            data={
                'id': method['id'],
                'name': method['name'],
                'is_cash_count': method.get('is_cash_count', False),
                'journal_id': method['journal_id'][0] if isinstance(method.get('journal_id'), list) else method.get('journal_id'),
                'journal_name': method['journal_id'][1] if isinstance(method.get('journal_id'), list) else None,
            },
            message=f"Mode de paiement '{request.name}' créé (ID: {method_id})"
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Erreur création mode de paiement: {e}")
        raise HTTPException(status_code=500, detail=f"Erreur lors de la création: {str(e)}")

@router.post("/{pos_id}/orders", response_model=ApiResponse)
async def create_pos_order_only(
    pos_id: int = Path(..., description="ID du point de vente"),
    request: PosOrderCreateSimpleRequest = Body(...),
    current_user: dict = Depends(require_scope("pos"))
):
    """
    Créer une commande POS sans paiement

    Crée une commande en état **draft**, prête à recevoir des paiements.
    Appelez ensuite `POST /{pos_id}/orders/{order_id}/payments` pour enregistrer chaque paiement.

    **Corps de la requête :**
    ```json
    {
      "session_id": 123,
      "lines": [
        {
          "product_id": 42,
          "qty": 2.5,
          "price_unit": 600,
          "discount": 0,
          "note": "note optionnelle"
        }
      ],
      "partner_id": null,
      "note": "note globale optionnelle"
    }
    ```

    **Réponse :**
    - `order_id` : ID Odoo de la commande créée
    - `amount_total` : montant total à payer
    - `amount_due` : montant restant à payer (= amount_total à la création)
    - `payment_status` : `unpaid` | `partial` | `paid`

    **Requires:** Authentification JWT avec scope 'pos'
    """
    try:
        client = get_odoo_client(current_user)

        # Vérifier que la session existe et est ouverte
        session_data = client.execute_kw(
            'pos.session', 'read', [request.session_id],
            {'fields': ['id', 'state', 'config_id', 'user_id']}
        )
        if not session_data:
            raise HTTPException(status_code=404, detail="Session POS non trouvée")

        session = session_data[0]
        if session['config_id'][0] != pos_id:
            raise HTTPException(status_code=400, detail="La session n'appartient pas à ce point de vente")
        if session['state'] != 'opened':
            raise HTTPException(status_code=400, detail=f"La session n'est pas ouverte (état: {session['state']})")

        # Valider les produits et préparer les lignes
        order_lines = []
        amount_total = 0.0

        for line in request.lines:
            product = client.execute_kw(
                'product.product', 'search_read',
                [[('id', '=', line.product_id)]],
                {'fields': ['id', 'name', 'list_price', 'type'], 'limit': 1}
            )
            if not product:
                raise HTTPException(status_code=400, detail=f"Produit {line.product_id} non trouvé dans Odoo")

            product_info = product[0]
            line_total = line.qty * line.price_unit * (1 - (line.discount or 0) / 100)
            amount_total += line_total

            line_vals = {
                'product_id': line.product_id,
                'qty': line.qty,
                'price_unit': line.price_unit,
                'discount': line.discount or 0.0,
                'price_subtotal': line_total,
                'price_subtotal_incl': line_total,
                'full_product_name': product_info['name'],
            }

            # Construire la note de ligne (infos pompe + note manuelle)
            note_parts = []
            if line.pump_id is not None:
                note_parts.append(f"Pompe #{line.pump_id}")
            if line.start_pump_index is not None and line.end_pump_index is not None:
                note_parts.append(f"Index: {line.start_pump_index} → {line.end_pump_index}")
                note_parts.append(f"Volume: {line.end_pump_index - line.start_pump_index:.2f}L")
            if line.note:
                note_parts.append(line.note)
            if note_parts:
                line_vals['note'] = " | ".join(note_parts)

            order_lines.append((0, 0, line_vals))

        # Créer la commande sans paiement (state=draft)
        user_id_val = session['user_id'][0] if isinstance(session.get('user_id'), list) else session.get('user_id', 1)
        order_vals = {
            'session_id': request.session_id,
            'pos_reference': f"Order-{pos_id}-{int(time.time())}",
            'user_id': user_id_val,
            'lines': order_lines,
            'amount_total': amount_total,
            'amount_paid': 0.0,
            'amount_return': 0.0,
            'amount_tax': 0.0,
            'state': 'draft',
            'date_order': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        }

        if request.partner_id:
            order_vals['partner_id'] = request.partner_id
        if current_user.get('employee_id'):
            order_vals['employee_id'] = current_user['employee_id']
        if request.note:
            order_vals['note'] = request.note

        order_id = client.execute_kw('pos.order', 'create', [order_vals])
        logger.info(f"Commande {order_id} créée (draft) - PDV {pos_id} - Montant: {amount_total}")

        return ApiResponse(
            success=True,
            data={
                'order_id': order_id,
                'pos_reference': order_vals['pos_reference'],
                'session_id': request.session_id,
                'partner_id': request.partner_id,
                'amount_total': amount_total,
                'amount_paid': 0.0,
                'amount_due': amount_total,
                'amount_return': 0.0,
                'payment_status': 'unpaid',
                'lines_count': len(request.lines),
                'state': 'draft'
            },
            message=f"Commande créée — Montant à payer: {amount_total}"
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Erreur création commande PDV {pos_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Erreur lors de la création: {str(e)}")


@router.post("/{pos_id}/orders/{order_id}/payments", response_model=ApiResponse)
async def add_payment_to_order(
    pos_id: int = Path(..., description="ID du point de vente"),
    order_id: int = Path(..., description="ID de la commande POS"),
    request: PosAddPaymentRequest = Body(...),
    current_user: dict = Depends(require_scope("pos"))
):
    """
    Ajouter un ou plusieurs paiements à une commande POS existante

    Peut être appelé **plusieurs fois** sur la même commande (paiement partiel),
    et accepte **plusieurs modes de paiement en un seul appel**.

    La commande passe automatiquement en état **paid** quand le total payé ≥ montant total.

    **Exemples de corps :**

    Un seul mode :
    ```json
    {
      "payments": [
        { "payment_method_id": 1, "amount": 1500.0 }
      ]
    }
    ```

    Plusieurs modes simultanés :
    ```json
    {
      "payments": [
        { "payment_method_id": 1, "amount": 500.0 },
        { "payment_method_id": 3, "amount": 1000.0 }
      ]
    }
    ```

    **Réponse :**
    - `payments_added` : liste des paiements créés (avec leur `payment_id`)
    - `total_paid` : cumul de tous les paiements sur la commande
    - `amount_due` : reste à payer (0 si soldée)
    - `amount_return` : monnaie rendue si surpaiement
    - `payment_status` : `unpaid` | `partial` | `paid`
    - `is_complete` : `true` si la commande est soldée

    **Requires:** Authentification JWT avec scope 'pos'
    """
    try:
        client = get_odoo_client(current_user)

        # Vérifier que la commande existe
        order_data = client.execute_kw(
            'pos.order', 'read', [order_id],
            {'fields': ['id', 'session_id', 'state', 'amount_total', 'amount_paid', 'amount_return']}
        )
        if not order_data:
            raise HTTPException(status_code=404, detail=f"Commande {order_id} non trouvée")

        order = order_data[0]

        # Vérifier que la commande appartient au bon PDV
        session_id_val = order['session_id'][0] if isinstance(order['session_id'], list) else order['session_id']
        session_data = client.execute_kw(
            'pos.session', 'read', [session_id_val],
            {'fields': ['config_id', 'state']}
        )
        if not session_data or session_data[0]['config_id'][0] != pos_id:
            raise HTTPException(status_code=400, detail="La commande n'appartient pas à ce point de vente")

        # Vérifier l'état de la commande
        if order['state'] in ('paid', 'done', 'invoiced'):
            raise HTTPException(status_code=400, detail=f"La commande est déjà soldée (état: {order['state']})")
        if order['state'] == 'cancel':
            raise HTTPException(status_code=400, detail="La commande est annulée")

        amount_total = float(order['amount_total'])
        current_paid = float(order['amount_paid'] or 0)
        payment_date = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        # Créer chaque paiement dans Odoo
        payments_added = []
        total_this_call = 0.0

        for p in request.payments:
            payment_id = client.execute_kw('pos.payment', 'create', [{
                'pos_order_id': order_id,
                'payment_method_id': p.payment_method_id,
                'amount': p.amount,
                'payment_date': payment_date,
            }])
            payments_added.append({
                'payment_id': payment_id,
                'payment_method_id': p.payment_method_id,
                'amount': p.amount,
            })
            total_this_call += p.amount
            logger.info(f"Paiement {payment_id} créé — Commande {order_id}: {p.amount} (méthode {p.payment_method_id})")

        # Recalculer les montants
        new_paid = current_paid + total_this_call
        amount_return = max(0.0, new_paid - amount_total)
        amount_due = max(0.0, amount_total - new_paid)
        is_complete = new_paid >= amount_total

        if is_complete:
            client.execute_kw('pos.order', 'write', [[order_id], {
                'state': 'paid',
                'amount_return': amount_return,
            }])
            payment_status = 'paid'
            logger.info(f"Commande {order_id} soldée — payé: {new_paid}, rendu: {amount_return}")

            # Déclencher le mouvement de stock (diminue les quantités en solde)
            try:
                client.execute_kw('pos.order', 'action_pos_order_picking', [[order_id]])
                logger.info(f"Mouvement de stock créé pour commande {order_id}")
            except Exception as stock_err:
                logger.warning(f"Mouvement de stock non créé pour commande {order_id}: {stock_err}")
        else:
            payment_status = 'partial'

        return ApiResponse(
            success=True,
            data={
                'order_id': order_id,
                'payments_added': payments_added,
                'amount_paid_this_call': total_this_call,
                'total_paid': new_paid,
                'amount_total': amount_total,
                'amount_due': amount_due,
                'amount_return': amount_return,
                'payment_status': payment_status,
                'is_complete': is_complete,
            },
            message=(
                f"Commande soldée — Rendu: {amount_return}" if is_complete
                else f"{len(payments_added)} paiement(s) enregistré(s) — Reste à payer: {amount_due}"
            )
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Erreur ajout paiement commande {order_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Erreur lors du paiement: {str(e)}")


@router.get("/{pos_id}/orders/{order_id}/invoice")
async def get_pos_order_invoice(
    pos_id: int = Path(..., description="ID du point de vente"),
    order_id: int = Path(..., description="ID de la commande POS"),
    current_user: dict = Depends(require_scope("pos"))
):
    """
    Récupérer la facture associée à une commande POS.

    Retourne les détails de la facture (account.move) liée à la commande.
    Utilisez l'`invoice_id` retourné avec `GET /accounting/invoice/{invoice_id}/pdf`
    pour télécharger le PDF.

    **Requires:** Authentification JWT avec scope 'pos'
    """
    try:
        client = get_odoo_client(current_user)

        # Lire la commande POS avec le champ account_move
        order_data = client.execute_kw(
            'pos.order', 'read', [order_id],
            {'fields': ['id', 'name', 'state', 'session_id', 'account_move', 'amount_total', 'partner_id']}
        )
        if not order_data:
            raise HTTPException(status_code=404, detail=f"Commande {order_id} non trouvée")

        order = order_data[0]

        # Vérifier que la commande appartient au bon PDV
        session_id_val = order['session_id'][0] if isinstance(order['session_id'], list) else order['session_id']
        session_data = client.execute_kw(
            'pos.session', 'read', [session_id_val],
            {'fields': ['config_id']}
        )
        if not session_data or session_data[0]['config_id'][0] != pos_id:
            raise HTTPException(status_code=400, detail="La commande n'appartient pas à ce point de vente")

        # Récupérer ou générer la facture liée
        account_move = order.get('account_move')
        invoice_id = account_move[0] if isinstance(account_move, list) else account_move
        invoice_generated = False

        if not invoice_id:
            # La commande n'a pas de facture — la générer via action_pos_order_invoice
            if order['state'] not in ('paid', 'done', 'invoiced'):
                raise HTTPException(
                    status_code=400,
                    detail=f"Impossible de facturer une commande en état '{order['state']}'. La commande doit être payée d'abord."
                )
            logger.info(f"Génération de la facture pour la commande {order['name']} (ID: {order_id})")

            # Marquer tous les comptes bancaires non fiables de l'entreprise comme fiables
            untrusted_bank_ids = client.execute_kw(
                'res.partner.bank', 'search',
                [[['allow_out_payment', '=', False]]],
            )
            if untrusted_bank_ids:
                client.execute_kw('res.partner.bank', 'write', [untrusted_bank_ids, {'allow_out_payment': True}])
                logger.info(f"Comptes bancaires marqués fiables : {untrusted_bank_ids}")

            client.execute_kw('pos.order', 'action_pos_order_invoice', [[order_id]])

            # Relire la commande pour récupérer l'account_move créé
            refreshed = client.execute_kw(
                'pos.order', 'read', [order_id],
                {'fields': ['account_move']}
            )
            account_move = refreshed[0].get('account_move') if refreshed else None
            invoice_id = account_move[0] if isinstance(account_move, list) else account_move

            if not invoice_id:
                raise HTTPException(
                    status_code=500,
                    detail="La génération de la facture a échoué — aucun account.move créé"
                )
            invoice_generated = True
            logger.info(f"Facture générée : ID={invoice_id} pour commande {order['name']}")

        # Lire les détails de la facture
        # Récupérer le nom de la facture pour le nom du fichier
        invoice_meta = client.execute_kw(
            'account.move', 'read', [invoice_id],
            {'fields': ['name']}
        )
        if not invoice_meta:
            raise HTTPException(status_code=404, detail=f"Facture {invoice_id} introuvable dans Odoo")

        invoice_name = invoice_meta[0].get('name', f'FAC-{invoice_id}')
        safe_name = invoice_name.replace('/', '_')

        logger.info(f"Génération PDF facture {invoice_name} (ID: {invoice_id})")
        pdf_content = _generate_pdf_via_wizard(client, invoice_id)
        if not pdf_content:
            raise HTTPException(
                status_code=500,
                detail=f"Impossible de générer le PDF pour la facture {invoice_name}"
            )

        return Response(
            content=pdf_content,
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="{safe_name}.pdf"'}
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Erreur récupération facture commande {order_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Erreur lors de la récupération: {str(e)}")


@router.post("/{pos_id}/create-order", response_model=ApiResponse)
async def create_complete_pos_order(
    pos_id: int = Path(..., description="ID du point de vente"),
    request: PosOrderCreateFullRequest = None,
    current_user: dict = Depends(require_scope("pos"))
):
    """
    Créer une commande POS complète avec tous les champs Odoo
    
    Cette route crée une pos.order avec toutes les informations requises :
    produits, quantités, pompes, modes de paiement, etc.
    
    Requires:
    - Authentification JWT avec scope 'pos'
    """
    try:
        client = get_odoo_client(current_user)
        
        # Vérifier que la session existe et est ouverte
        session = client.execute_kw(
            'pos.session',
            'read',
            [request.pos_session_id],
            {'fields': ['id', 'state', 'config_id', 'user_id']}
        )
        
        if not session or session[0]['state'] != 'opened':
            raise HTTPException(
                status_code=400,
                detail="Session POS non trouvée ou non ouverte"
            )
        
        session_data = session[0]
        
        # Préparer les lignes de commande
        order_lines = []
        total_amount = 0.0
        
        for line in request.lines:
            # VALIDATION: Vérifier que le produit existe dans Odoo
            product = client.execute_kw(
                'product.product',
                'search_read',
                [[('id', '=', line.product_id)]],
                {'fields': ['id', 'name', 'list_price', 'type'], 'limit': 1}
            )
            
            if not product:
                raise HTTPException(
                    status_code=400,
                    detail=f"Produit {line.product_id} non trouvé dans Odoo. Vérifiez que le produit existe et est actif."
                )
            
            product_info = product[0]
            logger.info(f"✅ Produit validé: ID={product_info['id']}, Nom={product_info['name']}, Type={product_info['type']}")
            
            line_total = line.qty * line.price_unit * (1 - (line.discount or 0) / 100)
            total_amount += line_total
            
            # Créer la ligne de commande avec tous les champs nécessaires
            line_vals = {
                'product_id': line.product_id,
                'qty': line.qty,
                'price_unit': line.price_unit,
                'discount': line.discount or 0.0,
                'price_subtotal': line_total,
                'price_subtotal_incl': line_total,  # À ajuster selon les taxes
                'full_product_name': product_info['name'],  # ✨ Nom complet du produit
            }
            
            # Ajouter les informations de pompe dans la note (car les champs personnalisés n'existent pas)
            note_parts = []
            if line.pump_id is not None:
                note_parts.append(f"Pompe #{line.pump_id}")
                logger.info(f"  → Pompe ID: {line.pump_id}")
            if line.start_pump_index is not None and line.end_pump_index is not None:
                note_parts.append(f"Index: {line.start_pump_index} → {line.end_pump_index}")
                volume = line.end_pump_index - line.start_pump_index
                note_parts.append(f"Volume: {volume:.2f}L")
                logger.info(f"  → Index début: {line.start_pump_index}, fin: {line.end_pump_index}")
            
            if note_parts:
                line_vals['note'] = " | ".join(note_parts)
            
            logger.info(f"  → Quantité: {line.qty}, Prix unitaire: {line.price_unit}, Total: {line_total}")
            
            order_lines.append((0, 0, line_vals))
        
        # Gérer les paiements (nouveau format ou ancien format pour rétrocompatibilité)
        payments_list = []
        total_paid = 0.0
        
        if request.payments:
            # Nouveau format : liste de paiements
            for payment in request.payments:
                payments_list.append(payment)
                total_paid += payment.amount
            logger.info(f"💳 {len(payments_list)} méthode(s) de paiement")
        elif request.payment_method_id and request.amount_paid:
            # Ancien format (rétrocompatibilité)
            from models.schemas import PosPayment
            payments_list.append(PosPayment(
                payment_method_id=request.payment_method_id,
                amount=request.amount_paid
            ))
            total_paid = request.amount_paid
            logger.info(f"💳 Format legacy : 1 paiement de {total_paid}")
        else:
            raise HTTPException(
                status_code=400,
                detail="Aucun paiement fourni. Utilisez 'payments' ou l'ancien format 'payment_method_id + amount_paid'"
            )
        
        # Créer la commande POS avec tous les champs
        order_vals = {
            'session_id': request.pos_session_id,
            'pos_reference': f"Order-{pos_id}-{int(time.time())}",  # Référence unique
            'user_id': session_data['user_id'][0],
            'lines': order_lines,
            'amount_total': total_amount,
            'amount_paid': total_paid,
            'amount_return': request.amount_return or 0.0,
            'amount_tax': 0.0,  # À calculer selon les taxes
            'state': 'draft',
            'date_order': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        }
        
        # Ajouter les champs optionnels seulement s'ils ne sont pas None ET différent de 0
        if request.partner_id is not None and request.partner_id > 0:
            order_vals['partner_id'] = request.partner_id
            logger.info(f"Client associé: ID={request.partner_id}")
        else:
            logger.info("Vente sans client (anonyme)")
        
        if current_user.get('employee_id'):
            order_vals['employee_id'] = current_user.get('employee_id')
            logger.info(f"Employé associé: ID={current_user.get('employee_id')}")
        
        # Ajouter une note si fournie
        if request.note:
            order_vals['note'] = request.note
        
        logger.info(f"📝 Création de la commande POS avec {len(order_lines)} ligne(s)")
        logger.info(f"   Session: {request.pos_session_id}, Montant total: {total_amount}")
        
        # Créer la commande
        try:
            order_id = client.execute_kw('pos.order', 'create', [order_vals])
            logger.info(f"✅ Commande créée avec succès - ID: {order_id}")
        except Exception as e:
            logger.error(f"❌ Erreur lors de la création de la commande: {e}")
            logger.error(f"   Valeurs envoyées: {order_vals}")
            raise HTTPException(
                status_code=500,
                detail=f"Erreur Odoo lors de la création de la commande: {str(e)}"
            )
        
        # Créer le paiement
        # Créer les paiements (peut être multiple)
        payment_ids = []
        for payment in payments_list:
            payment_vals = {
                'pos_order_id': order_id,
                'payment_method_id': payment.payment_method_id,
                'amount': payment.amount,
                'payment_date': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            }
            
            try:
                payment_id = client.execute_kw('pos.payment', 'create', [payment_vals])
                payment_ids.append(payment_id)
                logger.info(f"✅ Paiement créé: Méthode {payment.payment_method_id}, Montant {payment.amount} (ID: {payment_id})")
            except Exception as e:
                logger.error(f"❌ Erreur création paiement: {e}")
                logger.warning(f"Impossible de créer le paiement automatiquement: {e}")
        
        logger.info(f"💰 Total paiements créés: {len(payment_ids)}/{len(payments_list)}")
        
        # Marquer la commande comme payée et fermée
        try:
            client.execute_kw('pos.order', 'write', [[order_id], {'state': 'paid'}])
            logger.info(f"✅ Commande {order_id} marquée comme payée")
        except Exception as e:
            logger.error(f"❌ Erreur changement d'état: {e}")
            logger.warning(f"Impossible de marquer automatiquement comme payée: {e}")
        
        # Vérifier que la commande a bien été créée avec les lignes
        try:
            created_order = client.execute_kw(
                'pos.order',
                'read',
                [order_id],
                {'fields': ['id', 'name', 'lines', 'amount_total', 'state']}
            )
            if created_order:
                logger.info(f"📊 Commande vérifiée: {created_order[0].get('name')}")
                logger.info(f"   Lignes créées: {len(created_order[0].get('lines', []))} ligne(s)")
                logger.info(f"   Montant: {created_order[0].get('amount_total')}")
                logger.info(f"   État: {created_order[0].get('state')}")
        except Exception as e:
            logger.warning(f"Impossible de vérifier la commande créée: {e}")
        
        return ApiResponse(
            success=True,
            data={
                'order_id': order_id,
                'pos_reference': order_vals['pos_reference'],
                'amount_total': total_amount,
                'amount_paid': total_paid,
                'lines_count': len(order_lines),
                'payments_count': len(payment_ids)
            },
            message="Commande POS créée avec succès"
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Erreur lors de la création de la commande: {e}")
        raise HTTPException(status_code=500, detail=f"Erreur lors de la création: {str(e)}")

@router.get("/{pos_id}/orders/{order_id}/debug", response_model=ApiResponse)
async def debug_pos_order(
    pos_id: int = Path(..., description="ID du point de vente"),
    order_id: int = Path(..., description="ID de la commande POS"),
    current_user: dict = Depends(require_scope("pos"))
):
    """
    Récupérer les détails complets d'une commande POS pour debugging
    """
    try:
        client = get_odoo_client(current_user)
        
        # Récupérer la commande
        order = client.execute_kw(
            'pos.order',
            'read',
            [order_id],
            {
                'fields': [
                    'id', 'name', 'pos_reference', 'date_order', 'state',
                    'session_id', 'partner_id', 'user_id', 'employee_id',
                    'lines', 'amount_total', 'amount_paid', 'amount_return',
                    'amount_tax', 'note'
                ]
            }
        )
        
        if not order:
            raise HTTPException(status_code=404, detail="Commande non trouvée")
        
        order_data = order[0]
        
        # Récupérer les lignes de commande
        line_ids = order_data.get('lines', [])
        lines_details = []
        
        if line_ids:
            lines = client.execute_kw(
                'pos.order.line',
                'read',
                [line_ids],
                {
                    'fields': [
                        'id', 'product_id', 'qty', 'price_unit', 'discount',
                        'price_subtotal', 'price_subtotal_incl', 'full_product_name',
                        'order_id', 'pack_lot_ids', 'note'
                    ]
                }
            )
            
            # Pour chaque ligne, récupérer les lots associés
            for line in lines:
                line_info = dict(line)
                pack_lot_ids = line.get('pack_lot_ids', [])
                
                if pack_lot_ids:
                    # Récupérer les détails des lots
                    lots = client.execute_kw(
                        'pos.pack.operation.lot',
                        'read',
                        [pack_lot_ids],
                        {'fields': ['lot_name', 'product_id', 'pos_order_line_id']}
                    )
                    line_info['lots_details'] = lots
                else:
                    line_info['lots_details'] = []
                
                lines_details.append(line_info)
        
        return ApiResponse(
            success=True,
            data={
                'order': order_data,
                'lines': lines_details,
                'lines_count': len(lines_details),
                'debug_info': {
                    'has_pack_lot_ids': any(line.get('pack_lot_ids') for line in lines_details),
                    'total_lots': sum(len(line.get('pack_lot_ids', [])) for line in lines_details)
                }
            },
            message=f"Commande {order_data.get('name')} - {len(lines_details)} ligne(s)"
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Erreur lors du debug de la commande: {e}")
        raise HTTPException(status_code=500, detail=str(e))

async def validate_pump_indexes(
    client, session_id: int, pump_end_indexes: List[Dict], pos_id: int
) -> CashRegisterValidation:
    """
    Valider les index des pompes contre les quantités vendues
    """
    try:
        # Récupérer toutes les commandes de la session
        orders = client.execute_kw(
            'pos.order',
            'search_read',
            [[('session_id', '=', session_id)]],
            {'fields': ['id', 'lines']}
        )
        
        # Calculer les quantités vendues par pompe
        pump_sales = {}
        for order in orders:
            if order.get('lines'):
                # Récupérer les détails des lignes
                line_ids = order['lines']
                lines = client.execute_kw(
                    'pos.order.line',
                    'read',
                    [line_ids],
                    {'fields': ['product_id', 'qty', 'pump_id']}
                )
                
                for line in lines:
                    pump_id = line.get('pump_id', 0)
                    if pump_id:
                        if pump_id not in pump_sales:
                            pump_sales[pump_id] = 0.0
                        pump_sales[pump_id] += line['qty']
        
        # Valider chaque pompe
        pump_validations = []
        validation_errors = []
        
        for pump_data in pump_end_indexes:
            pump_id = pump_data.get('pump_id')
            end_index = pump_data.get('end_index', 0.0)
            start_index = pump_data.get('start_index', 0.0)
            
            calculated_qty = end_index - start_index
            sold_qty = pump_sales.get(pump_id, 0.0)
            difference = abs(calculated_qty - sold_qty)
            
            # Tolérance de 1% ou 1 litre maximum
            tolerance = max(1.0, calculated_qty * 0.01)
            is_valid = difference <= tolerance
            
            if not is_valid:
                validation_errors.append(
                    f"Pompe {pump_id}: Différence de {difference:.2f}L "
                    f"(calculé: {calculated_qty:.2f}L, vendu: {sold_qty:.2f}L)"
                )
            
            pump_validation = PumpIndexValidation(
                pump_id=pump_id,
                start_index=start_index,
                end_index=end_index,
                calculated_qty=calculated_qty,
                sold_qty=sold_qty,
                difference=difference,
                is_valid=is_valid
            )
            pump_validations.append(pump_validation)
        
        # Calcul du solde global (simplifié)
        total_sales = sum(pump_sales.values()) * 1.5  # Prix moyen fictif
        expected_balance = 1000.0 + total_sales  # Solde initial fictif + ventes
        
        validation = CashRegisterValidation(
            pos_id=pos_id,
            session_id=session_id,
            total_sales=total_sales,
            declared_balance=0.0,  # À remplir par l'appelant
            expected_balance=expected_balance,
            balance_difference=0.0,  # À calculer après
            pump_validations=pump_validations,
            is_valid=len(validation_errors) == 0,
            validation_errors=validation_errors
        )
        
        return validation
        
    except Exception as e:
        logger.error(f"Erreur lors de la validation des pompes: {e}")
        return CashRegisterValidation(
            pos_id=pos_id,
            session_id=session_id,
            total_sales=0.0,
            declared_balance=0.0,
            expected_balance=0.0,
            balance_difference=0.0,
            pump_validations=[],
            is_valid=False,
            validation_errors=[f"Erreur de validation: {str(e)}"]
        )


# ===== GESTION DES ENTREPRISES / COMPANIES =====

@router.get("/companies", response_model=ApiResponse)
async def get_companies(
    page: int = Query(1, ge=1, description="Numéro de page"),
    page_size: int = Query(50, ge=1, le=200, description="Éléments par page"),
    search: Optional[str] = Query(None, description="Recherche par nom, IFU, RCCM, email"),
    is_customer: Optional[bool] = Query(None, description="Filtrer par clients (True) ou non"),
    is_supplier: Optional[bool] = Query(None, description="Filtrer par fournisseurs (True) ou non"),
    current_user: dict = Depends(require_scope("pos"))
):
    """
    Récupérer la liste des entreprises (res.partner avec is_company=True)
    
    Retourne toutes les informations disponibles dans Odoo pour les entreprises.
    
    **Paramètres :**
    - **page** : Numéro de page (défaut: 1)
    - **page_size** : Éléments par page (défaut: 50, max: 200)
    - **search** : Recherche textuelle (nom, IFU, RCCM, email)
    - **is_customer** : Filtrer uniquement les clients
    - **is_supplier** : Filtrer uniquement les fournisseurs
    
    **Requires:** Authentification JWT avec scope 'pos'
    """
    try:
        client = get_odoo_client(current_user)
        
        # Construire le domaine de recherche
        domain = [('is_company', '=', True)]
        
        if search:
            domain.append('|')
            domain.append('|')
            domain.append('|')
            domain.append('|')
            domain.append(('name', 'ilike', search))
            domain.append(('vat', 'ilike', search))  # IFU/NIF
            domain.append(('email', 'ilike', search))
            domain.append(('phone', 'ilike', search))
            domain.append(('ref', 'ilike', search))  # RCCM peut être dans ref
        
        if is_customer is not None:
            domain.append(('customer_rank', '>', 0) if is_customer else ('customer_rank', '=', 0))
        
        if is_supplier is not None:
            domain.append(('supplier_rank', '>', 0) if is_supplier else ('supplier_rank', '=', 0))
        
        # Compter le total
        total_count = client.execute_kw(
            'res.partner',
            'search_count',
            [domain]
        )
        
        if total_count == 0:
            return ApiResponse(
                success=True,
                data={
                    'companies': [],
                    'pagination': {
                        'total_count': 0,
                        'page': page,
                        'page_size': page_size,
                        'total_pages': 0,
                        'current_count': 0
                    }
                },
                count=0,
                message="Aucune entreprise trouvée"
            )
        
        # Calculer l'offset
        offset = (page - 1) * page_size
        total_pages = (total_count + page_size - 1) // page_size
        
        # Champs à récupérer
        fields = [
            'id', 'name', 'display_name', 'ref', 'vat', 'email', 'phone', 'mobile',
            'street', 'street2', 'city', 'state_id', 'country_id', 'zip',
            'website', 'function', 'type', 'is_company', 'company_type',
            'customer_rank', 'supplier_rank', 'user_id', 'category_id',
            'comment', 'parent_id', 'child_ids', 'commercial_partner_id',
            'company_id', 'industry_id', 'active', 'employee',
            'create_date', 'write_date', 'create_uid', 'write_uid',
            # Champs personnalisés possibles
            'property_payment_term_id', 'property_supplier_payment_term_id',
            'property_account_position_id', 'credit', 'lang', 'tz',
            'barcode', 'color', 'image_1920', 'image_512', 'image_256', 'image_128'
        ]
        
        # Récupérer les entreprises
        companies = client.execute_kw(
            'res.partner',
            'search_read',
            [domain],
            {
                'fields': fields,
                'limit': page_size,
                'offset': offset,
                'order': 'name asc'
            }
        )

        if companies:
            partner_ids = [c['id'] for c in companies]

            # Calculer le solde réel depuis account.move.line (bypass le champ calculé
            # res.partner.credit qui est limité à la société active du user API).
            # On somme toutes les écritures receivable non-lettrées de toutes les sociétés.
            try:
                balance_rows = client.execute_kw(
                    'account.move.line',
                    'read_group',
                    [[
                        ('partner_id', 'in', partner_ids),
                        ('account_id.account_type', '=', 'asset_receivable'),
                        ('reconciled', '=', False),
                        ('parent_state', '=', 'posted'),
                    ]],
                    {
                        'groupby': ['partner_id'],
                        'fields': ['partner_id', 'debit:sum', 'credit:sum'],
                        'lazy': False,
                    }
                )
                balance_map = {
                    (row['partner_id'][0] if isinstance(row['partner_id'], list) else row['partner_id']):
                    round(row.get('debit', 0) - row.get('credit', 0), 2)
                    for row in balance_rows
                }
            except Exception as e:
                logger.warning(f"Impossible de calculer les soldes depuis account.move.line: {e}")
                balance_map = {}

            for company in companies:
                # Remplacer le credit calculé par société avec le vrai solde toutes sociétés
                company['credit'] = balance_map.get(company['id'], 0.0)

        return ApiResponse(
            success=True,
            data={
                'companies': companies,
                'pagination': {
                    'total_count': total_count,
                    'page': page,
                    'page_size': page_size,
                    'total_pages': total_pages,
                    'current_count': len(companies)
                },
                'filters_applied': {
                    'search': search,
                    'is_customer': is_customer,
                    'is_supplier': is_supplier
                }
            },
            count=len(companies),
            message=f"Trouvé {len(companies)} entreprise(s) sur {total_count} (page {page}/{total_pages})"
        )
        
    except Exception as e:
        logger.error(f"Erreur lors de la récupération des entreprises: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Erreur lors de la récupération des entreprises: {str(e)}"
        )


@router.get("/companies/formatted", response_model=ApiResponse)
async def get_companies_formatted(
    page: int = Query(1, ge=1, description="Numéro de page"),
    page_size: int = Query(50, ge=1, le=200, description="Éléments par page"),
    search: Optional[str] = Query(None, description="Recherche par nom, IFU, RCCM, email"),
    status: Optional[str] = Query(None, description="Filtrer par statut (PENDING/APPROVED/REJECTED)"),
    current_user: dict = Depends(require_scope("pos"))
):
    """
    Récupérer la liste des entreprises avec format standardisé
    
    Retourne les entreprises dans un format structuré avec mapping des champs Odoo
    vers votre structure personnalisée.
    
    **Mapping des champs:**
    - id → id (converti en string)
    - ref → rccm (Registre de Commerce)
    - vat → ifu (Identifiant Fiscal Unique)
    - name → companyName
    - industry_id → segment
    - email → companyEmail
    - x_rejection_reason → rejectionReason (champ personnalisé si existe)
    - Adresse complète → companyAddress
    - Contact principal → representativeFullname/Email/Phone
    - x_status → status (PENDING/APPROVED/REJECTED)
    - active → enabled
    - create_date → createdAt
    - write_date → updatedAt
    
    **Paramètres :**
    - **page** : Numéro de page (défaut: 1)
    - **page_size** : Éléments par page (défaut: 50, max: 200)
    - **search** : Recherche textuelle
    - **status** : Filtrer par statut (PENDING/APPROVED/REJECTED)
    
    **Requires:** Authentification JWT avec scope 'pos'
    """
    try:
        client = get_odoo_client(current_user)
        
        # Construire le domaine de recherche
        domain = [('is_company', '=', True)]
        
        if search:
            domain.append('|')
            domain.append('|')
            domain.append('|')
            domain.append('|')
            domain.append(('name', 'ilike', search))
            domain.append(('vat', 'ilike', search))
            domain.append(('email', 'ilike', search))
            domain.append(('phone', 'ilike', search))
            domain.append(('ref', 'ilike', search))
        
        # Compter le total
        total_count = client.execute_kw(
            'res.partner',
            'search_count',
            [domain]
        )
        
        if total_count == 0:
            return ApiResponse(
                success=True,
                data={
                    'companies': [],
                    'pagination': {
                        'total_count': 0,
                        'page': page,
                        'page_size': page_size,
                        'total_pages': 0,
                        'current_count': 0
                    }
                },
                count=0,
                message="Aucune entreprise trouvée"
            )
        
        # Calculer l'offset
        offset = (page - 1) * page_size
        total_pages = (total_count + page_size - 1) // page_size
        
        # Champs de base à récupérer
        fields = [
            'id', 'name', 'ref', 'vat', 'email', 'phone', 'mobile',
            'street', 'street2', 'city', 'state_id', 'country_id', 'zip',
            'industry_id', 'active', 'child_ids', 'parent_id',
            'create_date', 'write_date', 'comment'
        ]
        
        # Essayer d'ajouter des champs personnalisés s'ils existent
        try:
            # Tester si les champs personnalisés existent
            test_fields = fields + [
                'x_status', 'x_rejection_reason', 
                'x_file_carte_professionnelle', 'x_file_rccm', 'x_file_ifu'
            ]
            companies_raw = client.execute_kw(
                'res.partner',
                'search_read',
                [domain],
                {
                    'fields': test_fields,
                    'limit': page_size,
                    'offset': offset,
                    'order': 'create_date desc, id desc'
                }
            )
        except Exception as e:
            # Si les champs personnalisés n'existent pas, utiliser seulement les champs de base
            logger.debug(f"Champs personnalisés non disponibles, utilisation des champs de base: {e}")
            companies_raw = client.execute_kw(
                'res.partner',
                'search_read',
                [domain],
                {
                    'fields': fields,
                    'limit': page_size,
                    'offset': offset,
                    'order': 'create_date desc, id desc'
                }
            )
        
        # Formater les données
        companies_formatted = []
        for company in companies_raw:
            # Construire l'adresse complète
            address_parts = []
            if company.get('street'):
                address_parts.append(company['street'])
            if company.get('street2'):
                address_parts.append(company['street2'])
            if company.get('city'):
                address_parts.append(company['city'])
            if company.get('zip'):
                address_parts.append(company['zip'])
            if company.get('state_id') and isinstance(company['state_id'], list):
                address_parts.append(company['state_id'][1])
            if company.get('country_id') and isinstance(company['country_id'], list):
                address_parts.append(company['country_id'][1])
            
            company_address = ', '.join(address_parts) if address_parts else None
            
            # Récupérer les informations du contact principal (premier enfant ou parent)
            representative_fullname = None
            representative_email = None
            representative_phone = None
            
            if company.get('child_ids'):
                # Récupérer le premier contact
                try:
                    contacts = client.execute_kw(
                        'res.partner',
                        'read',
                        [company['child_ids'][:1]],
                        {'fields': ['name', 'email', 'phone', 'mobile', 'function']}
                    )
                    if contacts:
                        contact = contacts[0]
                        representative_fullname = contact.get('name')
                        representative_email = contact.get('email')
                        representative_phone = contact.get('phone') or contact.get('mobile')
                except Exception as e:
                    logger.debug(f"Erreur récupération contact pour {company['id']}: {e}")
            
            # Déterminer le statut (mapper depuis x_status ou utiliser active)
            company_status = company.get('x_status', '').upper() if company.get('x_status') else None
            if not company_status:
                # Mapper depuis active si x_status n'existe pas
                company_status = "APPROVED" if company.get('active', True) else "REJECTED"
            
            # Filtrer par statut si demandé (le paramètre 'status' vient de la requête)
            if status and company_status.upper() != status.upper():
                continue
            
            formatted_company = {
                "id": str(company['id']),
                "rccm": company.get('ref') or "",
                "ifu": company.get('vat') or "",
                "companyName": company.get('name') or "",
                "segment": company['industry_id'][1] if company.get('industry_id') and isinstance(company['industry_id'], list) else "",
                "companyEmail": company.get('email') or "",
                "rejectionReason": company.get('x_rejection_reason') or company.get('comment') or "",
                "companyAddress": company_address or "",
                "representativeFullname": representative_fullname or "",
                "representativeEmail": representative_email or "",
                "representativePhone": representative_phone or "",
                "fileCarteProfessionnelleId": str(company.get('x_file_carte_professionnelle')) if company.get('x_file_carte_professionnelle') else "",
                "fileRccmId": str(company.get('x_file_rccm')) if company.get('x_file_rccm') else "",
                "fileIfuId": str(company.get('x_file_ifu')) if company.get('x_file_ifu') else "",
                "status": company_status,
                "enabled": company.get('active', True),
                "createdAt": company.get('create_date') or datetime.now().isoformat(),
                "updatedAt": company.get('write_date') or company.get('create_date') or datetime.now().isoformat()
            }
            
            companies_formatted.append(formatted_company)
        
        return ApiResponse(
            success=True,
            data={
                'companies': companies_formatted,
                'pagination': {
                    'total_count': len(companies_formatted),
                    'page': page,
                    'page_size': page_size,
                    'total_pages': (len(companies_formatted) + page_size - 1) // page_size if len(companies_formatted) > 0 else 0,
                    'current_count': len(companies_formatted)
                },
                'filters_applied': {
                    'search': search,
                    'status': status
                }
            },
            count=len(companies_formatted),
            message=f"Trouvé {len(companies_formatted)} entreprise(s) formatée(s)"
        )
        
    except Exception as e:
        logger.error(f"Erreur lors de la récupération des entreprises formatées: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Erreur lors de la récupération des entreprises: {str(e)}"
        )
