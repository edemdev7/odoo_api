from fastapi import APIRouter, Depends, HTTPException, Path, Body
from typing import List, Dict, Any

from models.schemas import (
    PosProductSearchRequest, PosOrderCreateRequest, PosShopUpdateRequest, 
    PosShopArchiveRequest, PosShop, PosSessionStatus, PosSessionInitializeRequest,
    PosSessionResponse, PosPump, PosOpenSessionRequest, PosCloseSessionRequest
)
from models.responses import ApiResponse
from core.security import require_scope
from core.odoo_client import get_odoo_client
from core.config import logger

router = APIRouter(prefix="/pos", tags=["Point de Vente"])

@router.get("/shops", response_model=ApiResponse)
async def get_pos_shops(current_user: dict = Depends(require_scope("pos"))):
    """
    Récupérer la liste des points de vente (PDV)
    
    Cette route retourne la liste des PDV (modèle Odoo 'pos.config') avec leurs informations principales.
    
    Requires:
    - Authentification JWT
    - Scope "pos"
    """
    try:
        client = get_odoo_client(current_user)
        shops = client.execute_kw(
            'pos.config',
            'search_read',
            [[]],
            {'fields': ['id', 'name', 'active', 'state', 'company_id', 'user_ids', 'journal_id', 'sequence_id']}
        )
        return ApiResponse(success=True, data=shops, count=len(shops), message=f"{len(shops)} PDV trouvés")
    except Exception as e:
        logger.error(f"Erreur lors de la récupération des PDV: {e}")
        raise HTTPException(status_code=500, detail=f"Erreur lors de la récupération des PDV: {str(e)}")

@router.put("/shops/{shop_id}", response_model=ApiResponse)
async def update_pos_shop(
    shop_id: int = Path(..., description="ID du point de vente à mettre à jour"),
    update: PosShopUpdateRequest = Body(...),
    current_user: dict = Depends(require_scope("pos"))
):
    """
    Mettre à jour les informations d'un point de vente (PDV)
    
    Cette route permet de modifier les champs d'un PDV (modèle Odoo 'pos.config').
    
    Requires:
    - Authentification JWT
    - Scope "pos"
    """
    try:
        client = get_odoo_client(current_user)
        success = client.execute_kw('pos.config', 'write', [[shop_id], update.dict(exclude_unset=True)])
        return ApiResponse(success=success, data={"shop_id": shop_id}, message="PDV mis à jour")
    except Exception as e:
        logger.error(f"Erreur lors de la mise à jour du PDV: {e}")
        raise HTTPException(status_code=500, detail=f"Erreur lors de la mise à jour du PDV: {str(e)}")

@router.patch("/shops/{shop_id}/archive", response_model=ApiResponse)
async def archive_pos_shop(
    shop_id: int = Path(..., description="ID du point de vente à archiver/désarchiver"),
    archive: PosShopArchiveRequest = Body(...),
    current_user: dict = Depends(require_scope("pos"))
):
    """
    Archiver ou désarchiver un point de vente (PDV)
    
    Cette route permet d'archiver (désactiver) ou de désarchiver (réactiver) un PDV via le champ 'active'.
    
    Requires:
    - Authentification JWT
    - Scope "pos"
    """
    try:
        client = get_odoo_client(current_user)
        success = client.execute_kw('pos.config', 'write', [[shop_id], {'active': archive.active}])
        return ApiResponse(success=success, data={"shop_id": shop_id, "active": archive.active}, message="PDV archivé/désarchivé")
    except Exception as e:
        logger.error(f"Erreur lors de l'archivage du PDV: {e}")
        raise HTTPException(status_code=500, detail=f"Erreur lors de l'archivage du PDV: {str(e)}")
    
@router.post("/products", response_model=ApiResponse)
async def search_pos_products(
    request: PosProductSearchRequest,
    current_user: dict = Depends(require_scope("pos"))
):
    """
    Rechercher des produits pour le point de vente
    
    Cette API permet de rechercher des produits Odoo pour le point de vente avec différents critères.
    
    Parameters:
    - **request**: Les critères de recherche incluant:
      - **barcode**: Code-barres du produit (optionnel)
      - **product_name**: Nom du produit à rechercher (optionnel)
      - **limit**: Nombre maximal de résultats à retourner (défaut: 100)
    
    Returns:
    - **success**: Indique si la requête a réussi
    - **data**: Liste des produits trouvés avec leurs détails (nom, code-barres, prix, taxes, unité de mesure, stock)
    - **count**: Nombre de produits trouvés
    - **message**: Message informatif sur le résultat de la requête
    
    Requires:
    - Authentication avec un token JWT
    - Scope "pos" (Point de vente)
    """
    try:
        # Obtenir le client Odoo
        client = get_odoo_client(current_user)
        
        # Construire le domaine de recherche
        domain = [('type', '=', 'product')]  # Produits stockables uniquement
        
        if request.barcode:
            domain.append(('barcode', '=', request.barcode))
        
        if request.product_name:
            domain.append(('name', 'ilike', request.product_name))
        
        # Récupérer les produits avec uniquement des champs standards
        products = client.execute_kw(
            'product.product', 
            'search_read', 
            [domain], 
            {
                'fields': ['name', 'barcode', 'lst_price', 'taxes_id', 'uom_id', 'qty_available', 'virtual_available', 'type'],
                'limit': request.limit
            }
        )
        
        return ApiResponse(
            success=True,
            data=products,
            count=len(products),
            message=f"Trouvé {len(products)} produits"
        )
    except Exception as e:
        logger.error(f"Erreur lors de la recherche de produits: {e}")
        raise HTTPException(status_code=500, detail=f"Erreur lors de la recherche de produits: {str(e)}")

@router.post("/create-order", response_model=ApiResponse)
async def create_pos_order(
    request: PosOrderCreateRequest,
    current_user: dict = Depends(require_scope("pos"))
):
    """
    Créer une nouvelle commande de point de vente
    
    Cette API permet de créer une nouvelle commande dans le point de vente Odoo ou une commande de vente standard si le module POS n'est pas installé.
    
    Parameters:
    - **request**: Les informations de la commande incluant:
      - **customer_id**: ID du client (partenaire) dans Odoo
      - **products**: Liste des produits à commander avec pour chaque produit:
        - **product_id**: ID du produit dans Odoo
        - **qty**: Quantité du produit
        - **price_unit**: Prix unitaire du produit
      - **amount_paid**: Montant total payé par le client
    
    Returns:
    - **success**: Indique si la commande a été créée avec succès
    - **data**: Informations sur la commande créée (ID et type de commande)
    - **message**: Message informatif sur le résultat de l'opération
    
    Notes:
    - Si le module point_of_sale est installé, une commande POS sera créée
    - Sinon, une commande de vente standard (sale.order) sera créée
    - Une session POS doit être ouverte pour créer une commande POS
    
    Requires:
    - Authentication avec un token JWT
    - Scope "pos" (Point de vente)
    """
    try:
        # Obtenir le client Odoo
        client = get_odoo_client(current_user)
        
        # Vérifier d'abord si le module point_of_sale est installé
        pos_module = client.execute_kw(
            'ir.module.module',
            'search_read',
            [[['name', '=', 'point_of_sale'], ['state', '=', 'installed']]],
            {'fields': ['name']}
        )
        
        if not pos_module:
            # Si POS n'est pas installé, créer une commande de vente standard
            order_lines = []
            for product in request.products:
                line_vals = {
                    'product_id': product['product_id'],
                    'product_uom_qty': product['qty'],
                    'price_unit': product['price_unit']
                }
                order_lines.append((0, 0, line_vals))
                
            sale_order = {
                'partner_id': request.customer_id,
                'order_line': order_lines
            }
            
            order_id = client.execute_kw('sale.order', 'create', [sale_order])
            
            return ApiResponse(
                success=True,
                data={"order_id": order_id, "type": "sale.order"},
                message="Commande de vente créée avec succès"
            )
        else:
            # Si POS est installé, essayer de créer une commande POS
            # Vérifier si une session POS est ouverte
            pos_sessions = client.execute_kw(
                'pos.session',
                'search_read',
                [[['state', '=', 'opened']]],
                {'fields': ['id'], 'limit': 1}
            )
            
            if not pos_sessions:
                return ApiResponse(
                    success=False,
                    message="Aucune session POS ouverte. Impossible de créer une commande POS."
                )
                
            session_id = pos_sessions[0]['id']
            
            # Préparer les lignes de commande
            order_lines = []
            for product in request.products:
                line_vals = {
                    'product_id': product['product_id'],
                    'qty': product['qty'],
                    'price_unit': product['price_unit']
                }
                order_lines.append((0, 0, line_vals))
                
            # Créer la commande POS
            order_data = {
                'partner_id': request.customer_id,
                'user_id': current_user.get('employee_id', False),  # L'employé connecté
                'session_id': session_id,
                'lines': order_lines,
                'amount_total': request.amount_paid,
                'amount_paid': request.amount_paid,
                'amount_return': 0,
            }
            
            order_id = client.execute_kw('pos.order', 'create', [order_data])
            
            return ApiResponse(
                success=True,
                data={"order_id": order_id, "type": "pos.order"},
                message="Commande POS créée avec succès"
            )
            
    except Exception as e:
        logger.error(f"Erreur lors de la création de la commande: {e}")
        raise HTTPException(status_code=500, detail=f"Erreur lors de la création de la commande: {str(e)}")

# ===== GESTION DES SESSIONS POS =====

@router.get("/available", response_model=List[PosShop])
async def get_available_pos_shops(current_user: dict = Depends(require_scope("pos"))):
    """
    Récupérer les points de vente disponibles pour l'employé connecté
    
    Cette route retourne la liste des PDV accessibles à l'employé avec l'état des sessions.
    
    Requires:
    - Authentification JWT avec scope 'pos'
    """
    try:
        client = get_odoo_client(current_user)
        
        # Récupérer tous les PDV actifs
        pos_configs = client.execute_kw(
            'pos.config',
            'search_read',
            [[('active', '=', True)]],
            {'fields': ['id', 'name', 'current_session_id']}
        )
        
        available_pos = []
        for pos_config in pos_configs:
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

@router.get("/{pos_id}/pumps", response_model=List[PosPump])
async def get_pos_pumps(
    pos_id: int = Path(..., description="ID du point de vente"),
    current_user: dict = Depends(require_scope("pos"))
):
    """
    Récupérer les pompes d'une station service avec leurs derniers index
    
    Cette route retourne la liste des pompes pour une station service avec les derniers index connus.
    """
    try:
        client = get_odoo_client(current_user)
        
        # Vérifier le point de vente
        pos_config = client.execute_kw(
            'pos.config',
            'read',
            [pos_id],
            {'fields': ['name']}
        )
        
        if not pos_config:
            raise HTTPException(status_code=404, detail="Point de vente non trouvé")
        
        # Pour le moment, on suppose que toutes les stations ont des pompes
        # Une logique plus sophistiquée pourrait être implémentée ici
        # Par exemple, vérifier le nom du PDV ou une catégorie spécifique
        
        # Simuler les pompes pour l'instant (à adapter selon votre structure Odoo)
        # Si vous n'avez pas de modèle de pompes, vous pouvez retourner une liste vide
        # ou créer une logique basée sur les produits vendus par ce PDV
        
        pumps = []
        # Exemple de pompes simulées - à remplacer par votre logique réelle
        if "station" in pos_config[0]['name'].lower() or "carburant" in pos_config[0]['name'].lower():
            # Récupérer les produits de carburant vendus dans ce PDV
            try:
                # Exemple avec des produits standards - adapter selon vos besoins
                fuel_products = client.execute_kw(
                    'product.product',
                    'search_read',
                    [[('categ_id.name', 'ilike', 'carburant')]],  # Chercher par catégorie carburant
                    {'fields': ['id', 'name'], 'limit': 10}
                )
                
                for i, product in enumerate(fuel_products, 1):
                    pump = PosPump(
                        id=i,
                        name=f"Pompe {i}",
                        product_name=product['name'],
                        last_index=0.0  # À récupérer depuis votre système
                    )
                    pumps.append(pump)
            except:
                # Si pas de produits carburant, retourner des pompes génériques
                for i in range(1, 5):  # 4 pompes par défaut
                    pump = PosPump(
                        id=i,
                        name=f"Pompe {i}",
                        product_name=f"Carburant {i}",
                        last_index=0.0
                    )
                    pumps.append(pump)
        
        return pumps
        
    except Exception as e:
        logger.error(f"Erreur lors de la récupération des pompes: {e}")
        raise HTTPException(status_code=500, detail=f"Erreur lors de la récupération des pompes: {str(e)}")

@router.post("/{pos_id}/open-session", response_model=PosSessionResponse)
async def open_pos_session(
    pos_id: int = Path(..., description="ID du point de vente"),
    request: PosOpenSessionRequest = Body(...),
    current_user: dict = Depends(require_scope("pos"))
):
    """
    Ouvrir définitivement la caisse après validation des compteurs
    
    Cette route ouvre officiellement la session POS après validation des index des pompes (pour les stations).
    """
    try:
        client = get_odoo_client(current_user)
        
        # Vérifier que la session existe et est en bon état
        session_data = client.execute_kw(
            'pos.session',
            'read',
            [request.session_id],
            {'fields': ['config_id', 'state']}
        )
        
        if not session_data:
            raise HTTPException(status_code=404, detail="Session non trouvée")
        
        session = session_data[0]
        
        if session['config_id'][0] != pos_id:
            raise HTTPException(status_code=400, detail="La session ne correspond pas au point de vente")
        
        if session['state'] != 'opening_control':
            raise HTTPException(status_code=400, detail="La session n'est pas dans l'état d'ouverture")
        
        # Si des index de pompes sont fournis, les valider/enregistrer
        if request.pump_indexes:
            # Pour l'instant, on log les index - à adapter selon votre système
            logger.info(f"Index de pompes reçus pour session {request.session_id}: {request.pump_indexes}")
            # Ici vous pourriez enregistrer dans un modèle custom ou un système externe
        
        # Ouvrir la session
        client.execute_kw('pos.session', 'write', [[request.session_id], {'state': 'opened'}])
        
        # Récupérer les informations du PDV
        pos_config = client.execute_kw(
            'pos.config',
            'read',
            [pos_id],
            {'fields': ['name']}
        )[0]
        
        return PosSessionResponse(
            session_id=request.session_id,
            pos_id=pos_id,
            pos_name=pos_config['name'],
            is_station=False,  # À déterminer selon votre logique métier
            state='opened',
            message=f"Caisse ouverte avec succès - Session {request.session_id}"
        )
        
    except Exception as e:
        logger.error(f"Erreur lors de l'ouverture de session: {e}")
        raise HTTPException(status_code=500, detail=f"Erreur lors de l'ouverture: {str(e)}")

@router.post("/{pos_id}/close-session", response_model=PosSessionResponse)
async def close_pos_session(
    pos_id: int = Path(..., description="ID du point de vente"),
    request: PosCloseSessionRequest = Body(...),
    current_user: dict = Depends(require_scope("pos"))
):
    """
    Fermer la session POS active (gérants uniquement)
    
    Cette route ferme la session POS active sur un point de vente.
    Seuls les gérants peuvent fermer une session.
    
    - **ending_balance**: Solde de fermeture déclaré (optionnel)
    - **closing_notes**: Notes de fermeture (optionnel)
    """
    try:
        client = get_odoo_client(current_user)
        
        # Vérifier si l'employé est gérant (même logique que pour l'initialisation)
        is_manager = False
        
        if current_user.get("auth_type") == "pin":
            # Vérifier d'abord dans les additional_info
            additional_info = current_user.get("additional_info", {})
            job_title = additional_info.get("job", "").lower() if additional_info.get("job") else ""
            
            logger.info(f"Vérification gérant pour fermeture {current_user.get('username')}: job={job_title}")
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
                        logger.info(f"Job depuis Odoo pour fermeture: {job_name}")
                        is_manager = 'gérant' in job_name or 'manager' in job_name or 'chef' in job_name
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
        
        # Vérifier l'état de la session
        session_data = client.execute_kw(
            'pos.session',
            'read',
            [session_id],
            {'fields': ['state', 'name']}
        )
        
        if not session_data:
            raise HTTPException(status_code=404, detail="Session non trouvée")
        
        session = session_data[0]
        logger.info(f"Session trouvée: {session['name']}, état: {session['state']}")
        
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
            # Note: Le champ exact peut varier selon votre version d'Odoo
            # closing_data['notes'] = request.closing_notes
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
        
        return PosSessionResponse(
            session_id=session_id,
            pos_id=pos_id,
            pos_name=pos_config['name'],
            is_station=False,
            state=final_state,
            message=f"Session {session_id} fermée avec succès"
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Erreur lors de la fermeture de session: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Erreur lors de la fermeture: {str(e)}")
