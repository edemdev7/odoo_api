from fastapi import APIRouter, Depends, HTTPException, Path, Body
from typing import List, Dict, Any, Optional
import time
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
    StockPickingStateUpdateRequest, StockPickingListRequest
)
from models.responses import ApiResponse
from core.security import require_scope
from core.odoo_client import get_odoo_client
from core.config import logger
from core.pump_manager import pump_manager

router = APIRouter(prefix="/pos", tags=["Point de Vente"])

# ===== GESTION ADMINISTRATIVE DES PDV =====

@router.post("/create", response_model=ApiResponse)
async def create_pos_config(
    config_data: PosCreateRequest = Body(...),
    current_user: dict = Depends(require_scope("pos"))
):
    """
    Créer un nouveau point de vente (PDV)
    
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
    
    **Requires:** Authentification JWT avec scope 'pos'
    """
    try:
        client = get_odoo_client(current_user)
        
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
    limit: Optional[int] = 50,
    current_user: dict = Depends(require_scope("pos"))
):
    """
    Récupérer les transferts de stock (inventaires) pour un point de vente
    
    Cette route permet de consulter tous les transferts de stock (stock.picking)
    liés à un point de vente spécifique. Utile pour gérer les inventaires,
    réceptions, livraisons et transferts internes.
    
    **Filtres disponibles :**
    - **state** : État du transfert (draft/waiting/ready/done/cancel)
    - **picking_type_code** : Type d'opération (incoming/outgoing/internal)
    - **date_from/date_to** : Période de recherche (YYYY-MM-DD)
    - **partner_id** : Filtrer par partenaire/fournisseur
    - **limit** : Nombre maximum de résultats (défaut: 50)
    
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
        
        # Construire le domaine de recherche de manière simple et robuste
        domain = []
        
        # Filtrer par société du PDV si disponible (plus simple que par entrepôt)
        if pos_config.get('company_id'):
            try:
                company_id = pos_config['company_id'][0] if isinstance(pos_config['company_id'], list) else pos_config['company_id']
                domain.append(('company_id', '=', company_id))
            except Exception as e:
                logger.warning(f"Impossible de filtrer par société: {e}")
        
        # Ajouter les filtres optionnels
        if state:
            domain.append(('state', '=', state))
        
        if picking_type_code:
            domain.append(('picking_type_code', '=', picking_type_code))
        
        if partner_id:
            domain.append(('partner_id', '=', partner_id))
        
        if date_from:
            domain.append(('date', '>=', f"{date_from} 00:00:00"))
        
        if date_to:
            domain.append(('date', '<=', f"{date_to} 23:59:59"))
        
        # Limiter la recherche pour éviter les timeouts
        final_limit = min(limit or 50, 500)
        
        logger.info(f"Recherche transferts avec domaine: {domain}")
        
        # Récupérer les transferts avec tous les détails possibles
        fields = [
            # Champs de base
            'id', 'name', 'origin', 'state', 'picking_type_code', 'partner_id',
            'location_id', 'location_dest_id', 'scheduled_date', 'date_done',
            'user_id', 'company_id', 'products_availability', 'products_availability_state',
            'move_ids', 'pos_session_id', 'pos_order_id', 'note',
            
            # Champs détaillés supplémentaires
            'picking_type_id', 'priority', 'date', 'date_deadline',
            'move_type', 'group_id', 'has_scrap_move', 'has_packages', 
            'show_check_availability', 'is_locked', 'package_level_ids', 
            'package_level_ids_details',
            
            # Informations produits et quantités
            'move_ids_without_package', 'move_line_ids', 'move_line_ids_without_package',
            'move_line_exist', 'show_operations', 'show_reserved',
            
            # Informations de livraison et transport
            'carrier_id', 'carrier_tracking_ref', 'delivery_type',
            'weight', 'carrier_price', 'shipping_weight', 'weight_bulk',
            
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
        
        transfers = client.execute_kw(
            'stock.picking',
            'search_read',
            [domain],
            {
                'fields': fields,
                'limit': final_limit,
                'order': 'date desc, id desc'
            }
        )
        
        # Enrichir chaque transfert avec les détails des mouvements
        for transfer in transfers:
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
                                    'purchase_ok', 'active', 'image_1920', 'description',
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
            
            # Ajouter des informations sur le transporteur
            if transfer.get('carrier_id'):
                try:
                    carrier_info = client.execute_kw(
                        'delivery.carrier',
                        'read',
                        [transfer['carrier_id'][0]],
                        {
                            'fields': [
                                'id', 'name', 'delivery_type', 'product_id', 'website_url',
                                'country_ids', 'state_ids', 'zip_from', 'zip_to',
                                'margin', 'free_over', 'amount', 'fixed_price',
                                'active', 'sequence', 'company_id'
                            ]
                        }
                    )
                    transfer['carrier_details'] = carrier_info[0] if carrier_info else {}
                except Exception as e:
                    logger.warning(f"Erreur récupération transporteur pour transfert {transfer['id']}: {e}")
                    transfer['carrier_details'] = {}
            else:
                transfer['carrier_details'] = {}
            
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
                    
                    # Informations de livraison et transport
                    'carrier_id': clean_odoo_value(transfer.get('carrier_id')),
                    'carrier_tracking_ref': clean_odoo_value(transfer.get('carrier_tracking_ref')),
                    'delivery_type': clean_odoo_value(transfer.get('delivery_type')),
                    'weight': clean_odoo_value(transfer.get('weight')),
                    'carrier_price': clean_odoo_value(transfer.get('carrier_price')),
                    'shipping_weight': clean_odoo_value(transfer.get('shipping_weight')),
                    'weight_bulk': clean_odoo_value(transfer.get('weight_bulk')),
                    
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
                    'picking_type_details': transfer.get('picking_type_details', {})
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
                'domain_used': domain
            },
            count=len(transfers),
            message=f"Trouvé {len(transfers)} transfert(s) pour le PDV '{pos_config['name']}'"
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Erreur lors de la récupération des transferts: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Erreur lors de la récupération: {str(e)}"
        )

@router.post("/{pos_id}/inventory/transfers/update-state", response_model=ApiResponse)
async def update_inventory_transfer_state(
    pos_id: int = Path(..., description="ID du point de vente"),
    request: StockPickingStateUpdateRequest = Body(...),
    current_user: dict = Depends(require_scope("pos"))
):
    """
    Changer l'état des transferts de stock (de prêt à fait, par exemple)
    
    Cette route permet de faire évoluer l'état des transferts de stock selon
    le workflow Odoo standard :
    - **confirm** : Confirmer le transfert (draft → waiting/ready)
    - **assign** : Réserver les produits (waiting → ready)
    - **done** : Marquer comme terminé (ready → done)
    - **cancel** : Annuler le transfert (any → cancel)
    
    **Actions disponibles :**
    - **confirm** : Confirme les transferts en brouillon
    - **assign** : Réserve les quantités disponibles
    - **done** : Valide et termine les transferts
    - **cancel** : Annule les transferts
    
    **Paramètres :**
    - **picking_ids** : Liste des IDs de transferts à traiter
    - **action** : Action à effectuer
    - **force** : Forcer l'action même si les conditions ne sont pas remplies
    
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
        
        # Vérifier que les transferts existent
        existing_transfers = client.execute_kw(
            'stock.picking',
            'search_read',
            [[('id', 'in', request.picking_ids)]],
            {'fields': ['id', 'name', 'state'], 'limit': len(request.picking_ids)}
        )
        
        if len(existing_transfers) != len(request.picking_ids):
            found_ids = [t['id'] for t in existing_transfers]
            missing_ids = set(request.picking_ids) - set(found_ids)
            raise HTTPException(
                status_code=404,
                detail=f"Transferts non trouvés: {list(missing_ids)}"
            )
        
        # Préparer les résultats
        results = []
        errors = []
        
        # Traiter chaque transfert selon l'action demandée
        for transfer in existing_transfers:
            transfer_id = transfer['id']
            transfer_name = transfer['name']
            current_state = transfer['state']
            
            try:
                success = False
                new_state = current_state
                
                if request.action == "confirm":
                    # Confirmer le transfert
                    if current_state == 'draft':
                        client.execute_kw('stock.picking', 'action_confirm', [[transfer_id]])
                        success = True
                        new_state = 'waiting'
                    elif request.force:
                        client.execute_kw('stock.picking', 'action_confirm', [[transfer_id]])
                        success = True
                    else:
                        errors.append(f"{transfer_name}: État '{current_state}' ne permet pas la confirmation")
                
                elif request.action == "assign":
                    # Réserver les produits
                    if current_state in ['waiting', 'confirmed']:
                        client.execute_kw('stock.picking', 'action_assign', [[transfer_id]])
                        success = True
                        new_state = 'assigned'
                    elif request.force:
                        client.execute_kw('stock.picking', 'action_assign', [[transfer_id]])
                        success = True
                    else:
                        errors.append(f"{transfer_name}: État '{current_state}' ne permet pas la réservation")
                
                elif request.action == "done":
                    # Terminer le transfert
                    if current_state in ['assigned', 'confirmed'] or request.force:
                        try:
                            # Étape 1 : Réserver les produits si nécessaire
                            if current_state != 'assigned':
                                client.execute_kw('stock.picking', 'action_assign', [[transfer_id]])
                            
                            # Étape 2 : Définir les quantités réalisées pour toutes les move_lines
                            # D'abord récupérer les mouvements pour connaître les quantités demandées
                            moves = client.execute_kw(
                                'stock.move',
                                'search_read',
                                [[('picking_id', '=', transfer_id)]],
                                {'fields': ['id', 'product_uom_qty', 'state']}
                            )
                            
                            # Créer un mapping des quantités par mouvement
                            move_qty_map = {m['id']: m['product_uom_qty'] for m in moves}
                            
                            # Récupérer les move_lines
                            move_lines = client.execute_kw(
                                'stock.move.line',
                                'search_read',
                                [[('picking_id', '=', transfer_id)]],
                                {'fields': ['id', 'qty_done', 'quantity', 'move_id']}
                            )
                            
                            # Mettre à jour qty_done avec la quantité demandée du mouvement
                            for line in move_lines:
                                if line['qty_done'] == 0:
                                    # Utiliser la quantité du mouvement parent ou la quantité réservée
                                    move_id = line['move_id'][0] if line.get('move_id') else None
                                    target_qty = move_qty_map.get(move_id, line.get('quantity', 0))
                                    
                                    if target_qty > 0:
                                        client.execute_kw(
                                            'stock.move.line',
                                            'write',
                                            [[line['id']], {'qty_done': target_qty}]
                                        )
                                        logger.info(f"Défini qty_done={target_qty} pour move_line {line['id']}")
                            
                            # Étape 3 : Valider le transfert
                            # Utiliser button_validate (méthode standard Odoo)
                            result = client.execute_kw('stock.picking', 'button_validate', [[transfer_id]])
                            
                            # button_validate peut retourner un wizard pour backorder
                            if isinstance(result, dict) and 'res_model' in result:
                                wizard_id = result['res_id']
                                wizard_model = result['res_model']
                                
                                if wizard_model == 'stock.backorder.confirmation':
                                    # Wizard de reliquat - créer un reliquat automatiquement
                                    logger.info(f"Wizard de reliquat détecté pour le transfert {transfer_id}")
                                    try:
                                        # Option 1: Créer un reliquat (bouton "Créer un reliquat")
                                        client.execute_kw('stock.backorder.confirmation', 'process', [[wizard_id]])
                                        logger.info(f"Reliquat créé pour le transfert {transfer_id}")
                                    except Exception as wizard_error:
                                        logger.warning(f"Erreur avec wizard reliquat: {wizard_error}")
                                        # Option 2: Ne pas créer de reliquat (bouton "AUCUN RELIQUAT")
                                        client.execute_kw('stock.backorder.confirmation', 'process_cancel_backorder', [[wizard_id]])
                                        logger.info(f"Transfert validé sans reliquat pour {transfer_id}")
                                
                                elif wizard_model == 'stock.immediate.transfer':
                                    # Wizard de transfert immédiat
                                    logger.info(f"Wizard de transfert immédiat pour {transfer_id}")
                                    client.execute_kw('stock.immediate.transfer', 'process', [[wizard_id]])
                                
                                else:
                                    logger.warning(f"Wizard non géré: {wizard_model} pour le transfert {transfer_id}")
                                    # Essayer process générique
                                    try:
                                        client.execute_kw(wizard_model, 'process', [[wizard_id]])
                                    except:
                                        pass
                            
                            success = True
                            new_state = 'done'
                                
                        except Exception as e:
                            logger.error(f"Erreur lors de la validation du transfert {transfer_id}: {e}")
                            if request.force:
                                try:
                                    # En cas d'erreur, forcer avec action_done si force=True
                                    client.execute_kw('stock.picking', 'write', [[transfer_id], {'state': 'done'}])
                                    success = True
                                    new_state = 'done'
                                    logger.warning(f"Transfert {transfer_id} forcé à l'état 'done'")
                                except Exception as force_error:
                                    errors.append(f"{transfer_name}: Impossible de forcer à 'done': {force_error}")
                            else:
                                errors.append(f"{transfer_name}: Erreur validation: {e}")
                    else:
                        errors.append(f"{transfer_name}: État '{current_state}' ne permet pas la validation (utilisez force=true)")
                
                elif request.action == "cancel":
                    # Annuler le transfert
                    if current_state != 'done':
                        client.execute_kw('stock.picking', 'action_cancel', [[transfer_id]])
                        success = True
                        new_state = 'cancel'
                    elif request.force:
                        client.execute_kw('stock.picking', 'action_cancel', [[transfer_id]])
                        success = True
                        new_state = 'cancel'
                    else:
                        errors.append(f"{transfer_name}: Transfert terminé, impossible d'annuler")
                
                if success:
                    results.append({
                        'id': transfer_id,
                        'name': transfer_name,
                        'previous_state': current_state,
                        'new_state': new_state,
                        'success': True
                    })
                
            except Exception as e:
                error_msg = f"{transfer_name}: Erreur lors de l'action '{request.action}': {str(e)}"
                errors.append(error_msg)
                logger.error(f"Erreur transfert {transfer_id}: {e}")
                
                results.append({
                    'id': transfer_id,
                    'name': transfer_name,
                    'previous_state': current_state,
                    'new_state': current_state,
                    'success': False,
                    'error': str(e)
                })
        
        # Préparer la réponse
        success_count = len([r for r in results if r.get('success', False)])
        error_count = len(errors)
        
        message = f"Action '{request.action}' : {success_count} succès"
        if error_count > 0:
            message += f", {error_count} erreur(s)"
        
        logger.info(f"Mise à jour état transferts PDV {pos_config['name']}: {message}")
        
        return ApiResponse(
            success=error_count == 0,
            data={
                'pos_info': {
                    'id': pos_id,
                    'name': pos_config['name']
                },
                'action': request.action,
                'results': results,
                'summary': {
                    'total_processed': len(request.picking_ids),
                    'success_count': success_count,
                    'error_count': error_count
                },
                'errors': errors if errors else None
            },
            message=message
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Erreur lors de la mise à jour des transferts: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Erreur lors de la mise à jour: {str(e)}"
        )
  
# ===== GESTION DES SESSIONS POS =====
@router.get("/available", response_model=List[PosShop])
async def get_available_pos_shops(current_user: dict = Depends(require_scope("pos"))):
    """
    Récupérer les points de vente affectés à l'employé connecté
    
    Cette route retourne la liste des PDV auxquels l'employé connecté est affecté,
    avec l'état des sessions et les soldes.
    
    Requires:
    - Authentification JWT avec scope 'pos'
    """
    try:
        client = get_odoo_client(current_user)
        
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
        
        # Récupérer les PDV selon le filtre
        pos_configs = client.execute_kw(
            'pos.config',
            'search_read',
            [pos_search_domain],
            {'fields': ['id', 'name', 'current_session_id', 'basic_employee_ids', 'advanced_employee_ids']}
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
            
            pos_shop = PosShop(
                id=pos_config['id'],
                name=pos_config['name'],
                is_station=False,  # Par défaut, peut être déterminé par d'autres moyens
                current_session_id=pos_config.get('current_session_id')[0] if pos_config.get('current_session_id') else None,
                current_session_state=session_info['state'] if session_info else None,
                balance=balance
            )
            available_pos.append(pos_shop)
        
        return available_pos
        
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
        is_standard_mode = request.starting_balance is not None or request.opening_notes is not None
        
        if is_pump_mode and is_standard_mode:
            raise HTTPException(
                status_code=400, 
                detail="Données ambiguës: utilisez soit les données de pompes soit les données standard, pas les deux"
            )
        
        if not is_pump_mode and not is_standard_mode:
            raise HTTPException(
                status_code=400,
                detail="Données manquantes: fournissez soit pump_indexes soit starting_balance/opening_notes"
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
                
                # Ouvrir la session dans Odoo
                client.execute_kw('pos.session', 'write', [[request.session_id], {'state': 'opened'}])
                
                # Récupérer les informations du PDV
                pos_config = client.execute_kw(
                    'pos.config',
                    'read',
                    [pos_id],
                    {'fields': ['name']}
                )[0]
                
                logger.info(f"Session {request.session_id} ouverte avec {len(request.pump_indexes)} pompes sauvegardées")
                
                return PosSessionResponse(
                    session_id=request.session_id,
                    pos_id=pos_id,
                    pos_name=pos_config['name'],
                    is_station=True,
                    state='opened',
                    message=f"Session station-service ouverte - {len(request.pump_indexes)} pompes initialisées et sauvegardées"
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
    
    **Mode Simple** (sans pump_end_indexes):
    - Fermeture standard pour PDV classiques
    - Validation basique du solde
    
    **Mode Station-Service** (avec pump_end_indexes):
    - Fermeture avec validation des pompes
    - Contrôle de cohérence index vs ventes
    - Tolérance de 1% ou 1L pour les différences
    
    **Paramètres:**
    - **ending_balance**: Solde de fermeture déclaré (optionnel)
    - **closing_notes**: Notes de fermeture (optionnel)  
    - **pump_end_indexes**: Index de fin des pompes (optionnel, active le mode station)
    
    **Requires:** Authentification JWT avec scope 'pos' + Profil gérant
    """
    try:
        client = get_odoo_client(current_user)
        
        # Déterminer le mode de fermeture
        is_station_mode = request.pump_end_indexes is not None and len(request.pump_end_indexes) > 0
        logger.info(f"Mode de fermeture: {'Station-Service' if is_station_mode else 'Standard'}")
        
        # Vérifier si l'employé est gérant
        is_manager = False
        
        if current_user.get("auth_type") == "pin":
            # Vérifier d'abord dans les additional_info
            additional_info = current_user.get("additional_info", {})
            job_title = additional_info.get("job", "").lower() if additional_info.get("job") else ""
            
            logger.info(f"Vérification gérant pour fermeture {current_user.get('username')}: job={job_title}")
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
                        logger.info(f"Job depuis Odoo pour fermeture: {job_name}")
                        is_manager = any(keyword in job_name for keyword in ['gérant', 'manager', 'chef', 'responsable'])
                except Exception as e:
                    logger.warning(f"Erreur lors de la récupération du job depuis Odoo: {e}")
        
        logger.info(f"Résultat vérification gérant pour fermeture: is_manager={is_manager}")
        
        if not is_manager:
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
            logger.info(f"Mode station activé - Validation de {len(request.pump_end_indexes)} pompe(s)")
            
            try:
                # Mettre à jour les index finaux des pompes
                update_errors = []
                for pump_data in request.pump_end_indexes:
                    pump_id = pump_data.get('pump_id') or pump_data.get('id')
                    end_index = pump_data.get('end_index') or pump_data.get('current_index')
                    
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
                        update_errors.append(f"Erreur mise à jour pompe {pump_id}")
                
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
        
        # Vérifier l'état de la session
        session_data = client.execute_kw(
            'pos.session',
            'read',
            [session_id],
            {'fields': ['state']}
        )
        
        if not session_data:
            raise HTTPException(status_code=404, detail="Session non trouvée")
        
        session = session_data[0]
        
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
        if is_station_mode:
            message = f"Session fermée avec succès - Mode station-service - {len(request.pump_end_indexes)} pompe(s) validée(s)"
        else:
            message = f"Session fermée avec succès - Mode standard"
        
        response_data = {
            'session_id': session_id,
            'pos_id': pos_id,
            'pos_name': pos_config['name'],
            'is_station': is_station_mode,
            'state': final_state,
            'message': message
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
            }
            
            # Ajouter les informations de pompe si disponibles (non None)
            if line.pump_id is not None:
                line_vals['pump_id'] = line.pump_id  # Champ personnalisé
            if line.start_pump_index is not None:
                line_vals['start_pump_index'] = line.start_pump_index
            if line.end_pump_index is not None:
                line_vals['end_pump_index'] = line.end_pump_index
            
            order_lines.append((0, 0, line_vals))
        
        # Créer la commande POS avec tous les champs
        order_vals = {
            'session_id': request.pos_session_id,
            'pos_reference': f"Order-{pos_id}-{int(time.time())}",  # Référence unique
            'user_id': session_data['user_id'][0],
            'lines': order_lines,
            'amount_total': total_amount,
            'amount_paid': request.amount_paid,
            'amount_return': request.amount_return or 0.0,
            'amount_tax': 0.0,  # À calculer selon les taxes
            'state': 'draft',
            'date_order': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        }
        
        # Ajouter les champs optionnels seulement s'ils ne sont pas None
        if request.partner_id is not None:
            order_vals['partner_id'] = request.partner_id
        
        if current_user.get('employee_id'):
            order_vals['employee_id'] = current_user.get('employee_id')
        
        # Ajouter une note si fournie
        if request.note:
            order_vals['note'] = request.note
        
        # Créer la commande
        order_id = client.execute_kw('pos.order', 'create', [order_vals])
        
        # Créer le paiement
        if request.amount_paid > 0:
            payment_vals = {
                'pos_order_id': order_id,
                'payment_method_id': request.payment_method_id,
                'amount': request.amount_paid,
                'payment_date': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            }
            
            try:
                payment_id = client.execute_kw('pos.payment', 'create', [payment_vals])
                logger.info(f"Paiement créé avec l'ID: {payment_id}")
            except Exception as e:
                logger.warning(f"Impossible de créer le paiement automatiquement: {e}")
        
        # Marquer la commande comme payée et fermée
        try:
            client.execute_kw('pos.order', 'write', [[order_id], {'state': 'paid'}])
        except Exception as e:
            logger.warning(f"Impossible de marquer automatiquement comme payée: {e}")
        
        return ApiResponse(
            success=True,
            data={
                'order_id': order_id,
                'pos_reference': order_vals['pos_reference'],
                'amount_total': total_amount,
                'amount_paid': request.amount_paid,
                'lines_count': len(order_lines)
            },
            message="Commande POS créée avec succès"
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Erreur lors de la création de la commande: {e}")
        raise HTTPException(status_code=500, detail=f"Erreur lors de la création: {str(e)}")

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
