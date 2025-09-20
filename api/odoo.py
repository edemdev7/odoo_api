from fastapi import APIRouter, Depends, HTTPException, Query
from typing import Optional

from models.schemas import OdooSearchRequest, OdooCreateRequest, OdooUpdateRequest, OdooDeleteRequest
from models.responses import ApiResponse
from core.security import require_scope
from core.odoo_client import get_odoo_client, default_odoo_client

router = APIRouter(tags=["Odoo"])

# ===== ENDPOINTS ODOO - LECTURE SANS AUTHENTIFICATION =====

@router.get("/public/models", response_model=ApiResponse, tags=["Odoo - Public"])
async def list_public_models():
    """
    Lister les modèles Odoo disponibles (endpoint public)
    
    Cette API permet d'obtenir la liste des modèles (tables) disponibles dans Odoo.
    Cet endpoint est public et ne nécessite pas d'authentification.
    
    Returns:
    - **success**: Indique si la requête a réussi
    - **data**: Liste des modèles Odoo avec leur nom technique et leur libellé
    - **count**: Nombre de modèles retournés
    - **message**: Message informatif sur le résultat de la requête
    
    Note: Cette liste est limitée aux 20 premiers modèles par défaut
    """
    try:
        models = default_odoo_client.execute_kw('ir.model', 'search_read', [[]], {'fields': ['model', 'name'], 'limit': 20})
        
        return ApiResponse(
            success=True,
            data=models,
            count=len(models),
            message=f"Trouvé {len(models)} modèles"
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur lors de la récupération des modèles: {str(e)}")

@router.get("/public/partners", response_model=ApiResponse, tags=["Odoo - Public"])
async def list_public_partners():
    """
    Lister les partenaires publics (endpoint public)
    
    Cette API permet d'obtenir une liste des partenaires (clients/fournisseurs) publics dans Odoo.
    Cet endpoint est public et ne nécessite pas d'authentification.
    
    Returns:
    - **success**: Indique si la requête a réussi
    - **data**: Liste des partenaires avec leurs informations de base (nom, email, téléphone, site web)
    - **count**: Nombre de partenaires retournés
    - **message**: Message informatif sur le résultat de la requête
    
    Note: 
    - Cette liste est limitée aux entreprises (is_company=True)
    - Limité aux 10 premiers partenaires
    """
    try:
        # Domaine pour limiter aux partenaires publics (à adapter selon votre modèle de données)
        domain = [['is_company', '=', True]]
        partners = default_odoo_client.execute_kw('res.partner', 'search_read', [domain], 
                                          {'fields': ['name', 'email', 'phone', 'website'], 'limit': 10})
        
        return ApiResponse(
            success=True,
            data=partners,
            count=len(partners),
            message=f"Trouvé {len(partners)} partenaires publics"
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur lors de la récupération des partenaires: {str(e)}")

@router.get("/public/products", response_model=ApiResponse, tags=["Odoo - Public"])
async def list_public_products():
    """
    Lister les produits publics (endpoint public)
    
    Cette API permet d'obtenir une liste des produits publics disponibles dans Odoo.
    Cet endpoint est public et ne nécessite pas d'authentification.
    
    Returns:
    - **success**: Indique si la requête a réussi
    - **data**: Liste des produits avec leurs informations de base (nom, prix, référence)
    - **count**: Nombre de produits retournés
    - **message**: Message informatif sur le résultat de la requête
    
    Note:
    - Seuls les produits marqués comme "Peut être vendu" (sale_ok=True) sont retournés
    - Limité aux 10 premiers produits
    """
    try:
        # Domaine pour limiter aux produits publics (à adapter selon votre modèle de données)
        domain = [['sale_ok', '=', True]]
        products = default_odoo_client.execute_kw('product.template', 'search_read', [domain], 
                                         {'fields': ['name', 'list_price', 'default_code'], 'limit': 10})
        
        return ApiResponse(
            success=True,
            data=products,
            count=len(products),
            message=f"Trouvé {len(products)} produits publics"
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur lors de la récupération des produits: {str(e)}")

# ===== ENDPOINTS ODOO - LECTURE =====

@router.post("/odoo/search", response_model=ApiResponse, tags=["Odoo - Lecture"])
async def search_records(
    request: OdooSearchRequest,
    current_user: dict = Depends(require_scope("read"))
):
    """
    Rechercher des enregistrements dans Odoo
    
    Cette API permet de rechercher des enregistrements dans n'importe quel modèle Odoo en utilisant un domaine de recherche.
    
    Parameters:
    - **request**: Les critères de recherche incluant:
      - **model**: Le nom technique du modèle Odoo (ex: "res.partner", "product.product")
      - **domain**: Le domaine de recherche Odoo au format liste de listes (ex: [["is_company", "=", true]])
      - **limit**: Nombre maximal de résultats à retourner (optionnel)
    
    Returns:
    - **success**: Indique si la requête a réussi
    - **data**: Liste des IDs des enregistrements correspondants
    - **count**: Nombre d'enregistrements trouvés
    - **message**: Message informatif sur le résultat de la requête
    
    Requires:
    - Authentication avec un token JWT
    - Scope "read"
    """
    try:
        # Obtenir le client Odoo approprié pour cet utilisateur
        client = get_odoo_client(current_user)
        
        kwargs = {}
        if request.limit:
            kwargs['limit'] = request.limit
        
        ids = client.execute_kw(request.model, 'search', [request.domain], kwargs)
        
        return ApiResponse(
            success=True,
            data=ids,
            count=len(ids),
            message=f"Trouvé {len(ids)} enregistrements"
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur lors de la recherche: {str(e)}")

@router.post("/odoo/read", response_model=ApiResponse, tags=["Odoo - Lecture"])
async def read_records(
    model: str = Query(..., description="Nom du modèle Odoo"),
    ids: str = Query(..., description="IDs séparés par des virgules"),
    fields: Optional[str] = Query(None, description="Champs séparés par des virgules"),
    current_user: dict = Depends(require_scope("read"))
):
    """
    Lire des enregistrements par IDs
    
    Cette API permet de lire les détails d'enregistrements spécifiques à partir de leurs IDs.
    
    Parameters:
    - **model**: Le nom technique du modèle Odoo (ex: "res.partner", "product.product")
    - **ids**: Liste des IDs des enregistrements à lire, séparés par des virgules (ex: "1,2,3")
    - **fields**: Liste des champs à retourner, séparés par des virgules (ex: "name,email,phone"). 
                  Si non spécifié, tous les champs sont retournés.
    
    Returns:
    - **success**: Indique si la requête a réussi
    - **data**: Liste des enregistrements avec leurs champs demandés
    - **count**: Nombre d'enregistrements lus
    - **message**: Message informatif sur le résultat de la requête
    
    Requires:
    - Authentication avec un token JWT
    - Scope "read"
    """
    try:
        # Obtenir le client Odoo approprié pour cet utilisateur
        client = get_odoo_client(current_user)
        
        record_ids = [int(id_.strip()) for id_ in ids.split(",")]
        kwargs = {}
        if fields:
            kwargs['fields'] = [field.strip() for field in fields.split(",")]
        
        records = client.execute_kw(model, 'read', [record_ids], kwargs)
        
        return ApiResponse(
            success=True,
            data=records,
            count=len(records),
            message=f"Lu {len(records)} enregistrements"
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur lors de la lecture: {str(e)}")

@router.post("/odoo/search_read", response_model=ApiResponse, tags=["Odoo - Lecture"])
async def search_read_records(
    request: OdooSearchRequest,
    current_user: dict = Depends(require_scope("read"))
):
    """
    Rechercher et lire des enregistrements en une seule opération
    
    Cette API combine les opérations search et read en une seule requête pour une meilleure performance.
    Elle permet de rechercher des enregistrements selon un domaine et de lire leurs valeurs en même temps.
    
    Parameters:
    - **request**: Les critères de recherche incluant:
      - **model**: Le nom technique du modèle Odoo (ex: "res.partner", "product.product")
      - **domain**: Le domaine de recherche Odoo au format liste de listes (ex: [["is_company", "=", true]])
      - **fields**: Liste des champs à retourner (optionnel)
      - **limit**: Nombre maximal de résultats à retourner (optionnel)
    
    Returns:
    - **success**: Indique si la requête a réussi
    - **data**: Liste des enregistrements correspondants avec leurs champs demandés
    - **count**: Nombre d'enregistrements trouvés et lus
    - **message**: Message informatif sur le résultat de la requête
    
    Requires:
    - Authentication avec un token JWT
    - Scope "read"
    """
    try:
        # Obtenir le client Odoo approprié pour cet utilisateur
        client = get_odoo_client(current_user)
        
        kwargs = {}
        if request.fields:
            kwargs['fields'] = request.fields
        if request.limit:
            kwargs['limit'] = request.limit
        
        records = client.execute_kw(request.model, 'search_read', [request.domain], kwargs)
        
        return ApiResponse(
            success=True,
            data=records,
            count=len(records),
            message=f"Trouvé et lu {len(records)} enregistrements"
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur lors de search_read: {str(e)}")

# ===== ENDPOINTS ODOO - ÉCRITURE =====

@router.post("/odoo/create", response_model=ApiResponse, tags=["Odoo - Écriture"])
async def create_record(
    request: OdooCreateRequest,
    current_user: dict = Depends(require_scope("write"))
):
    """
    Créer un nouvel enregistrement
    
    Cette API permet de créer un nouvel enregistrement dans n'importe quel modèle Odoo.
    
    Parameters:
    - **request**: Les données pour la création incluant:
      - **model**: Le nom technique du modèle Odoo (ex: "res.partner", "product.product")
      - **values**: Dictionnaire des valeurs à créer (ex: {"name": "Nouveau Client", "email": "client@example.com"})
    
    Returns:
    - **success**: Indique si la requête a réussi
    - **data**: Contient l'ID du nouvel enregistrement créé
    - **message**: Message informatif sur le résultat de l'opération
    
    Requires:
    - Authentication avec un token JWT
    - Scope "write"
    """
    try:
        # Obtenir le client Odoo approprié pour cet utilisateur
        client = get_odoo_client(current_user)
        
        new_id = client.execute_kw(request.model, 'create', [request.values])
        
        return ApiResponse(
            success=True,
            data={"id": new_id},
            message=f"Enregistrement créé avec l'ID: {new_id}"
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur lors de la création: {str(e)}")

@router.post("/odoo/update", response_model=ApiResponse, tags=["Odoo - Écriture"])
async def update_records(
    request: OdooUpdateRequest,
    current_user: dict = Depends(require_scope("write"))
):
    """
    Mettre à jour des enregistrements existants
    
    Cette API permet de mettre à jour un ou plusieurs enregistrements existants dans n'importe quel modèle Odoo.
    
    Parameters:
    - **request**: Les données pour la mise à jour incluant:
      - **model**: Le nom technique du modèle Odoo (ex: "res.partner", "product.product")
      - **ids**: Liste des IDs des enregistrements à mettre à jour
      - **values**: Dictionnaire des valeurs à mettre à jour (ex: {"name": "Nouveau Nom", "email": "nouveau@example.com"})
    
    Returns:
    - **success**: Indique si la mise à jour a réussi
    - **data**: Contient les IDs des enregistrements mis à jour
    - **count**: Nombre d'enregistrements mis à jour
    - **message**: Message informatif sur le résultat de l'opération
    
    Requires:
    - Authentication avec un token JWT
    - Scope "write"
    """
    try:
        # Obtenir le client Odoo approprié pour cet utilisateur
        client = get_odoo_client(current_user)
        
        success = client.execute_kw(request.model, 'write', [request.ids, request.values])
        
        return ApiResponse(
            success=success,
            data={"updated_ids": request.ids},
            count=len(request.ids),
            message=f"Mis à jour {len(request.ids)} enregistrements"
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur lors de la mise à jour: {str(e)}")

# ===== ENDPOINTS ODOO - SUPPRESSION =====

@router.post("/odoo/delete", response_model=ApiResponse, tags=["Odoo - Suppression"])
async def delete_records(
    request: OdooDeleteRequest,
    current_user: dict = Depends(require_scope("delete"))
):
    """
    Supprimer des enregistrements
    
    Cette API permet de supprimer un ou plusieurs enregistrements dans n'importe quel modèle Odoo.
    
    Parameters:
    - **request**: Les données pour la suppression incluant:
      - **model**: Le nom technique du modèle Odoo (ex: "res.partner", "product.product")
      - **ids**: Liste des IDs des enregistrements à supprimer
    
    Returns:
    - **success**: Indique si la suppression a réussi
    - **data**: Contient les IDs des enregistrements supprimés
    - **count**: Nombre d'enregistrements supprimés
    - **message**: Message informatif sur le résultat de l'opération
    
    Requires:
    - Authentication avec un token JWT
    - Scope "delete"
    
    Attention: Cette opération est irréversible. Les enregistrements supprimés ne peuvent pas être récupérés.
    """
    try:
        # Obtenir le client Odoo approprié pour cet utilisateur
        client = get_odoo_client(current_user)
        
        success = client.execute_kw(request.model, 'unlink', [request.ids])
        
        return ApiResponse(
            success=success,
            data={"deleted_ids": request.ids},
            count=len(request.ids),
            message=f"Supprimé {len(request.ids)} enregistrements"
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur lors de la suppression: {str(e)}")

# ===== ENDPOINTS UTILITAIRES =====

@router.get("/odoo/models", response_model=ApiResponse, tags=["Odoo - Utilitaires"])
async def list_models(
    current_user: dict = Depends(require_scope("read"))
):
    """
    Lister les modèles Odoo disponibles
    
    Cette API permet d'obtenir la liste complète des modèles (tables) disponibles dans Odoo.
    
    Returns:
    - **success**: Indique si la requête a réussi
    - **data**: Liste des modèles Odoo avec leur nom technique et leur libellé
    - **count**: Nombre de modèles retournés
    - **message**: Message informatif sur le résultat de la requête
    
    Requires:
    - Authentication avec un token JWT
    - Scope "read"
    
    Note: Contrairement à l'endpoint public, cette version retourne tous les modèles disponibles
    """
    try:
        # Obtenir le client Odoo approprié pour cet utilisateur
        client = get_odoo_client(current_user)
        
        models = client.execute_kw('ir.model', 'search_read', [[]], {'fields': ['model', 'name']})
        
        return ApiResponse(
            success=True,
            data=models,
            count=len(models),
            message=f"Trouvé {len(models)} modèles"
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur lors de la récupération des modèles: {str(e)}")

@router.get("/odoo/fields/{model}", response_model=ApiResponse, tags=["Odoo - Utilitaires"])
async def get_model_fields(
    model: str,
    current_user: dict = Depends(require_scope("read"))
):
    """
    Obtenir les champs d'un modèle Odoo
    
    Cette API permet d'obtenir la liste des champs disponibles pour un modèle Odoo spécifique,
    avec leurs propriétés (type, libellé, si obligatoire, etc.)
    
    Parameters:
    - **model**: Le nom technique du modèle Odoo (ex: "res.partner", "product.product")
    
    Returns:
    - **success**: Indique si la requête a réussi
    - **data**: Dictionnaire des champs avec leurs propriétés
    - **count**: Nombre de champs retournés
    - **message**: Message informatif sur le résultat de la requête
    
    Requires:
    - Authentication avec un token JWT
    - Scope "read"
    
    Utilisation: Cette API est utile pour découvrir la structure d'un modèle avant d'effectuer
    des opérations de lecture ou d'écriture.
    """
    try:
        # Obtenir le client Odoo approprié pour cet utilisateur
        client = get_odoo_client(current_user)
        
        fields = client.execute_kw(model, 'fields_get', [], {'attributes': ['string', 'help', 'type', 'required']})
        
        return ApiResponse(
            success=True,
            data=fields,
            count=len(fields),
            message=f"Trouvé {len(fields)} champs pour le modèle {model}"
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur lors de la récupération des champs: {str(e)}")
