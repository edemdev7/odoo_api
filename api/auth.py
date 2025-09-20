from fastapi import APIRouter, Depends, HTTPException
from fastapi.concurrency import run_in_threadpool
from datetime import datetime, timedelta

from models.schemas import UserLogin, PinLogin, Token
from models.responses import ApiResponse
from core.security import authenticate_user, create_access_token, get_current_user, require_scope
from core.config import ACCESS_TOKEN_EXPIRE_MINUTES, logger
from core.odoo_client import default_odoo_client

router = APIRouter(prefix="/auth", tags=["Authentification"])

@router.post("/login", response_model=Token, summary="Authentification par login/mot de passe")
async def login(user_data: UserLogin):
    """
    **Connexion et génération du token JWT**
    
    Cette route permet à un utilisateur de s'authentifier avec son nom d'utilisateur et mot de passe
    et de recevoir un token JWT pour les appels API ultérieurs.
    
    - **username**: Nom d'utilisateur
    - **password**: Mot de passe
    - **odoo_db** (optionnel): Base de données Odoo personnalisée
    - **odoo_username** (optionnel): Nom d'utilisateur Odoo personnalisé
    - **odoo_api_key** (optionnel): Clé API Odoo personnalisée
    
    **Retourne** un token JWT avec une durée de validité de 30 minutes.
    """
    try:
        # Limite de tentatives pour prévenir les attaques par force brute
        
        # Valider les données d'entrée
        if not user_data.username or not user_data.password:
            logger.warning("Tentative de connexion avec des champs vides")
            raise HTTPException(
                status_code=400,
                detail="Le nom d'utilisateur et le mot de passe sont requis",
            )
            
        # Authentifier l'utilisateur de manière non-bloquante
        user = await run_in_threadpool(lambda: authenticate_user(user_data.username, user_data.password))
        
        if not user:
            logger.warning(f"Échec d'authentification pour: {user_data.username}")
            raise HTTPException(
                status_code=401,
                detail="Nom d'utilisateur ou mot de passe incorrect",
                headers={"WWW-Authenticate": "Bearer"},
            )
        
        # Vérifier si des informations Odoo personnalisées ont été fournies
        custom_odoo_config = None
        if user_data.odoo_db or user_data.odoo_username or user_data.odoo_api_key:
            custom_odoo_config = {
                "db": user_data.odoo_db,
                "username": user_data.odoo_username,
                "api_key": user_data.odoo_api_key
            }
            
            # Tester la connexion Odoo avec les paramètres personnalisés
            try:
                from core.odoo_client import OdooClient
                test_client = OdooClient(custom_config=custom_odoo_config)
                # Si on arrive ici, c'est que la connexion a réussi
                logger.info(f"Connexion Odoo personnalisée réussie pour: {user_data.username}")
                
                # Stocker les paramètres de connexion Odoo dans le token
                user["odoo_config"] = custom_odoo_config
            except Exception as e:
                logger.error(f"Échec de connexion Odoo personnalisée: {e}")
                raise HTTPException(
                    status_code=401,
                    detail="Échec de connexion à Odoo avec les identifiants fournis",
                )
        
        # Générer le token JWT
        access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
        token_data = {
            "sub": user["username"], 
            "scopes": user["scopes"],
            "iat": datetime.utcnow()
        }
        
        # Ajouter les informations Odoo personnalisées au token si présentes
        if "odoo_config" in user:
            token_data["odoo_config"] = {
                "db": user["odoo_config"]["db"],
                "username": user["odoo_config"]["username"],
                # Ne pas inclure la clé API dans le token pour des raisons de sécurité
            }
        
        access_token = create_access_token(
            data=token_data, 
            expires_delta=access_token_expires
        )
        
        logger.info(f"Connexion réussie pour: {user_data.username}")
        return {
            "access_token": access_token,
            "token_type": "bearer",
            "expires_in": ACCESS_TOKEN_EXPIRE_MINUTES * 60
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Erreur lors de la connexion: {e}")
        raise HTTPException(
            status_code=500,
            detail="Erreur lors de la connexion",
        )

@router.post("/pin-login", response_model=Token, summary="Authentification par PIN et matricule")
async def pin_login(login_data: PinLogin):
    """
    **Connexion avec matricule et PIN pour les utilisateurs de point de vente/stock**
    
    Cette route permet à un employé de s'authentifier avec son matricule et son code PIN,
    principalement pour les opérations de point de vente et gestion de stock.
    
    - **matricule**: Matricule de l'employé (champ x_studio_matricule dans Odoo)
    - **pin**: Code PIN de l'employé (utilisé pour le point de vente)
    
    **Retourne** un token JWT avec une durée de validité de 30 minutes et des droits limités aux opérations POS.
    """
    try:
        # Valider les données d'entrée
        if not login_data.matricule or not login_data.pin:
            logger.warning("Tentative de connexion avec des champs vides")
            raise HTTPException(
                status_code=400,
                detail="Le matricule et le PIN sont requis",
            )
        
        # Rechercher l'employé dans Odoo en utilisant le matricule et le PIN
        try:
            domain = [
                ('x_studio_matricule', '=', login_data.matricule),
                ('pin', '=', login_data.pin),
                ('active', '=', True)
            ]
            
            # Utiliser le client Odoo par défaut pour la recherche
            employee = default_odoo_client.execute_kw(
                'hr.employee', 
                'search_read', 
                [domain], 
                {'fields': ['id', 'name', 'work_email', 'job_id', 'department_id'], 'limit': 1}
            )
            
            if not employee:
                logger.warning(f"Aucun employé trouvé avec matricule={login_data.matricule} et PIN fourni")
                raise HTTPException(
                    status_code=401,
                    detail="Matricule ou PIN incorrect",
                )
            
            employee = employee[0]
            logger.info(f"Employé trouvé: {employee['name']}")
            
            # Créer un utilisateur virtuel avec des droits limités pour le POS/stock
            virtual_user = {
                "username": f"employee_{employee['id']}",
                "is_active": True,
                "scopes": ["read", "pos"],  # Limiter aux opérations POS/stock
                "employee_id": employee['id'],
                "employee_name": employee['name'],
                "employee_matricule": login_data.matricule
            }
            
            # Générer le token JWT
            access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
            token_data = {
                "sub": virtual_user["username"],
                "scopes": virtual_user["scopes"],
                "iat": datetime.utcnow(),
                "employee_id": employee['id'],
                "employee_name": employee['name'],
                "employee_matricule": login_data.matricule
            }
            
            access_token = create_access_token(
                data=token_data,
                expires_delta=access_token_expires
            )
            
            logger.info(f"Connexion par PIN réussie pour l'employé: {employee['name']}")
            return {
                "access_token": access_token,
                "token_type": "bearer",
                "expires_in": ACCESS_TOKEN_EXPIRE_MINUTES * 60
            }
            
        except Exception as e:
            logger.error(f"Erreur lors de la vérification de l'employé: {e}")
            raise HTTPException(
                status_code=500,
                detail="Erreur lors de la vérification des informations d'employé",
            )
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Erreur lors de la connexion par PIN: {e}")
        raise HTTPException(
            status_code=500,
            detail="Erreur lors de la connexion",
        )

@router.get("/me", summary="Informations utilisateur")
async def read_users_me(current_user: dict = Depends(get_current_user)):
    """
    **Informations sur l'utilisateur connecté**
    
    Cette route renvoie les informations sur l'utilisateur actuellement authentifié.
    Nécessite un token JWT valide.
    
    **Retourne** les informations de base de l'utilisateur:
    - Nom d'utilisateur
    - Permissions (scopes)
    - Statut d'activité
    """
    return {
        "username": current_user["username"],
        "scopes": current_user["scopes"],
        "is_active": current_user["is_active"]
    }
