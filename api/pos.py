from fastapi import APIRouter, Depends, HTTPException
from typing import List, Dict, Any

from models.schemas import PosProductSearchRequest, PosOrderCreateRequest
from models.responses import ApiResponse
from core.security import require_scope
from core.odoo_client import get_odoo_client
from core.config import logger

router = APIRouter(prefix="/pos", tags=["Point de Vente"])

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
