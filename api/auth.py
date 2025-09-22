from fastapi import APIRouter, Depends, HTTPException
from fastapi.concurrency import run_in_threadpool
from datetime import datetime, timedelta

from models.schemas import UserLogin, PinLogin, Token, LogoutRequest, UserData
from models.responses import ApiResponse
from core.security import authenticate_user, create_access_token, get_current_user, require_scope, invalidate_token
from core.config import ACCESS_TOKEN_EXPIRE_MINUTES, logger
from core.odoo_client import default_odoo_client, get_odoo_client

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
        
        # Récupérer des informations supplémentaires sur l'utilisateur depuis Odoo
        user_data = {
            "username": user["username"],
            "scopes": user["scopes"],
            "is_active": user["is_active"],
            "fullname": None,
            "email": user["username"] if "@" in user["username"] else None,
            "image_url": None,
            "phone": None,
            "additional_info": {}
        }
        
        # Si le nom d'utilisateur ressemble à un email, essayer de récupérer les infos utilisateur depuis Odoo
        if "@" in user["username"]:
            try:
                client = get_odoo_client(user)
                user_info = client.execute_kw(
                    'res.users', 
                    'search_read', 
                    [[['login', '=', user["username"]]]], 
                    {'fields': ['name', 'email', 'phone', 'image_1920', 'partner_id'], 'limit': 1}
                )
                
                if user_info:
                    odoo_user = user_info[0]
                    user_data["fullname"] = odoo_user.get('name')
                    user_data["email"] = odoo_user.get('email')
                    
                    # Chercher le téléphone complet à partir du partenaire associé
                    phone = None
                    if odoo_user.get('partner_id'):
                        try:
                            partner_id = odoo_user['partner_id'][0]
                            partner_details = client.execute_kw(
                                'res.partner', 
                                'read', 
                                [partner_id], 
                                {'fields': ['phone', 'mobile']}
                            )
                            if partner_details:
                                # Préférer le mobile s'il existe, sinon utiliser le téléphone fixe
                                phone = partner_details[0].get('mobile') or partner_details[0].get('phone')
                        except Exception as e:
                            logger.warning(f"Impossible de récupérer le téléphone du partenaire: {e}")
                    
                    # Si on n'a pas trouvé de téléphone dans le partenaire, utiliser celui de l'utilisateur
                    if not phone:
                        phone = odoo_user.get('phone')
                    
                    user_data["phone"] = phone
                    
                    # Si l'image est disponible, créer une URL (à adapter selon votre configuration)
                    if odoo_user.get('image_1920'):
                        user_data["image_url"] = f"/api/users/{odoo_user['id']}/image"
                    
                    # Récupérer des informations supplémentaires du partenaire
                    if odoo_user.get('partner_id'):
                        partner_id = odoo_user['partner_id'][0]
                        partner_info = client.execute_kw(
                            'res.partner', 
                            'read', 
                            [partner_id], 
                            {'fields': ['function', 'company_id', 'category_id']}
                        )
                        
                        if partner_info:
                            user_data["additional_info"] = {
                                "function": partner_info[0].get('function'),
                                "company": partner_info[0].get('company_id')[1] if partner_info[0].get('company_id') else None,
                                "tags": [tag[1] for tag in partner_info[0].get('category_id', [])]
                            }
            except Exception as e:
                logger.warning(f"Impossible de récupérer les informations utilisateur depuis Odoo: {e}")
        
        logger.info(f"Connexion réussie pour: {user_data.username}")
        return {
            "access_token": access_token,
            "token_type": "bearer",
            "expires_in": ACCESS_TOKEN_EXPIRE_MINUTES * 60,
            "user_data": user_data
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
            
            # Créer les données utilisateur pour l'employé
            user_data = {
                "username": virtual_user["username"],
                "fullname": employee['name'],
                "email": employee.get('work_email'),
                "scopes": virtual_user["scopes"],
                "is_active": True,
                "phone": None,
                "image_url": None,
                "additional_info": {
                    "employee_id": employee['id'],
                    "matricule": login_data.matricule,
                    "job": employee.get('job_id')[1] if employee.get('job_id') else None,
                    "department": employee.get('department_id')[1] if employee.get('department_id') else None
                }
            }
            
            # Essayer de récupérer plus d'informations sur l'employé
            try:
                employee_details = default_odoo_client.execute_kw(
                    'hr.employee', 
                    'read', 
                    [employee['id']], 
                    {'fields': ['mobile_phone', 'work_phone', 'image_1920']}
                )
                
                if employee_details:
                    user_data["phone"] = employee_details[0].get('mobile_phone') or employee_details[0].get('work_phone')
                    
                    # Si l'image est disponible, créer une URL
                    if employee_details[0].get('image_1920'):
                        user_data["image_url"] = f"/api/employees/{employee['id']}/image"
            except Exception as e:
                logger.warning(f"Impossible de récupérer les détails supplémentaires de l'employé: {e}")
            
            logger.info(f"Connexion par PIN réussie pour l'employé: {employee['name']}")
            return {
                "access_token": access_token,
                "token_type": "bearer",
                "expires_in": ACCESS_TOKEN_EXPIRE_MINUTES * 60,
                "user_data": user_data
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

@router.get("/me", response_model=UserData, summary="Informations utilisateur")
async def read_users_me(current_user: dict = Depends(get_current_user)):
    """
    **Informations sur l'utilisateur connecté**
    
    Cette route renvoie les informations détaillées sur l'utilisateur actuellement authentifié.
    Nécessite un token JWT valide.
    
    **Retourne** les informations complètes de l'utilisateur:
    - Nom d'utilisateur
    - Nom complet
    - Email
    - URL de la photo de profil
    - Numéro de téléphone
    - Permissions (scopes)
    - Statut d'activité
    - Informations additionnelles
    """
    # Vérifier si c'est un employé authentifié par PIN (username commence par "employee_")
    if current_user.get("username", "").startswith("employee_"):
        # Récupérer des données supplémentaires de l'employé
        try:
            employee_id = current_user.get("employee_id")
            if not employee_id and "_" in current_user.get("username", ""):
                # Extraire l'ID de l'employé depuis le username (format: "employee_ID")
                try:
                    employee_id = int(current_user["username"].split("_")[1])
                except:
                    pass
            
            if employee_id:
                employee_details = default_odoo_client.execute_kw(
                    'hr.employee', 
                    'read', 
                    [employee_id], 
                    {'fields': ['name', 'work_email', 'mobile_phone', 'work_phone', 'image_1920', 'job_id', 'department_id']}
                )
                
                if employee_details:
                    employee = employee_details[0]
                    
                    # S'assurer que les champs sont des chaînes de caractères valides
                    work_email = employee.get('work_email') if isinstance(employee.get('work_email'), str) else None
                    mobile_phone = employee.get('mobile_phone') if isinstance(employee.get('mobile_phone'), str) else None
                    work_phone = employee.get('work_phone') if isinstance(employee.get('work_phone'), str) else None
                    
                    # Construire les informations de l'emploi et du département
                    job_info = None
                    if employee.get('job_id') and isinstance(employee.get('job_id'), (list, tuple)) and len(employee.get('job_id')) > 1:
                        job_info = employee.get('job_id')[1]
                    
                    dept_info = None
                    if employee.get('department_id') and isinstance(employee.get('department_id'), (list, tuple)) and len(employee.get('department_id')) > 1:
                        dept_info = employee.get('department_id')[1]
                    
                    return UserData(
                        username=current_user["username"],
                        fullname=employee.get('name') if isinstance(employee.get('name'), str) else None,
                        email=work_email,
                        phone=mobile_phone or work_phone,
                        image_url=f"/api/employees/{employee_id}/image" if employee.get('image_1920') else None,
                        scopes=current_user["scopes"],
                        is_active=current_user.get("is_active", True),
                        additional_info={
                            "employee_id": employee_id,
                            "matricule": current_user.get("employee_matricule"),
                            "job": job_info,
                            "department": dept_info
                        }
                    )
        except Exception as e:
            logger.warning(f"Erreur lors de la récupération des détails de l'employé: {e}")
    
    # Pour un utilisateur standard
    if "@" in current_user["username"]:
        try:
            client = get_odoo_client(current_user)
            user_info = client.execute_kw(
                'res.users', 
                'search_read', 
                [[['login', '=', current_user["username"]]]], 
                {'fields': ['name', 'email', 'phone', 'image_1920', 'partner_id'], 'limit': 1}
            )
            
            if user_info:
                odoo_user = user_info[0]
                additional_info = {}
                
                # S'assurer que les champs sont des chaînes de caractères valides
                email = odoo_user.get('email') if isinstance(odoo_user.get('email'), str) else None
                name = odoo_user.get('name') if isinstance(odoo_user.get('name'), str) else None
                
                # Récupérer le téléphone du partenaire qui est plus complet
                phone = None
                
                # Récupérer des informations supplémentaires du partenaire
                if odoo_user.get('partner_id') and isinstance(odoo_user.get('partner_id'), (list, tuple)) and len(odoo_user.get('partner_id')) > 0:
                    partner_id = odoo_user['partner_id'][0]
                    try:
                        partner_info = client.execute_kw(
                            'res.partner', 
                            'read', 
                            [partner_id], 
                            {'fields': ['function', 'company_id', 'category_id', 'phone', 'mobile']}
                        )
                        
                        if partner_info:
                            # Récupérer le téléphone du partenaire (préférer mobile)
                            if partner_info[0].get('mobile') and isinstance(partner_info[0].get('mobile'), str):
                                phone = partner_info[0].get('mobile')
                            elif partner_info[0].get('phone') and isinstance(partner_info[0].get('phone'), str):
                                phone = partner_info[0].get('phone')
                            
                            # Récupérer les autres informations du partenaire
                            function = partner_info[0].get('function') if isinstance(partner_info[0].get('function'), str) else None
                            
                            company = None
                            if partner_info[0].get('company_id') and isinstance(partner_info[0].get('company_id'), (list, tuple)) and len(partner_info[0].get('company_id')) > 1:
                                company = partner_info[0].get('company_id')[1]
                            
                            tags = []
                            if partner_info[0].get('category_id'):
                                tags = [tag[1] for tag in partner_info[0].get('category_id', []) if isinstance(tag, (list, tuple)) and len(tag) > 1]
                            
                            additional_info = {
                                "function": function,
                                "company": company,
                                "tags": tags
                            }
                    except Exception as e:
                        logger.warning(f"Erreur lors de la récupération des détails du partenaire: {e}")
                
                # Si on n'a pas trouvé de téléphone dans le partenaire, utiliser celui de l'utilisateur
                if not phone and isinstance(odoo_user.get('phone'), str):
                    phone = odoo_user.get('phone')
                
                return UserData(
                    username=current_user["username"],
                    fullname=name,
                    email=email,
                    phone=phone,
                    image_url=f"/api/users/{odoo_user['id']}/image" if odoo_user.get('image_1920') else None,
                    scopes=current_user["scopes"],
                    is_active=current_user.get("is_active", True),
                    additional_info=additional_info
                )
        except Exception as e:
            logger.warning(f"Erreur lors de la récupération des détails utilisateur depuis Odoo: {e}")
    
    # Retour par défaut si aucune information supplémentaire n'est disponible
    return UserData(
        username=current_user["username"],
        scopes=current_user["scopes"],
        is_active=current_user.get("is_active", True)
    )

@router.get("/users/{user_id}/image", summary="Image de profil utilisateur")
async def get_user_image(
    user_id: int,
    current_user: dict = Depends(get_current_user)
):
    """
    **Récupération de l'image de profil d'un utilisateur**
    
    Cette route permet de récupérer l'image de profil d'un utilisateur Odoo.
    
    - **user_id**: L'ID de l'utilisateur Odoo
    
    **Retourne** l'image au format binaire.
    """
    try:
        from fastapi.responses import Response
        import base64
        
        # Récupérer l'image depuis Odoo
        client = get_odoo_client(current_user)
        user_info = client.execute_kw(
            'res.users', 
            'read', 
            [user_id], 
            {'fields': ['image_1920']}
        )
        
        if not user_info or not user_info[0].get('image_1920'):
            raise HTTPException(
                status_code=404,
                detail="Image non trouvée"
            )
        
        # Décoder l'image (Odoo stocke les images en base64)
        image_data = base64.b64decode(user_info[0]['image_1920'])
        
        # Détecter le type d'image (simple vérification)
        content_type = "image/png"  # Par défaut
        if image_data.startswith(b'\xff\xd8'):
            content_type = "image/jpeg"
        elif image_data.startswith(b'\x89\x50\x4E\x47'):
            content_type = "image/png"
        
        # Retourner l'image
        return Response(content=image_data, media_type=content_type)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Erreur lors de la récupération de l'image: {e}")
        raise HTTPException(
            status_code=500,
            detail="Erreur lors de la récupération de l'image"
        )

@router.get("/employees/{employee_id}/image", summary="Image de profil employé")
async def get_employee_image(
    employee_id: int,
    current_user: dict = Depends(get_current_user)
):
    """
    **Récupération de l'image de profil d'un employé**
    
    Cette route permet de récupérer l'image de profil d'un employé Odoo.
    
    - **employee_id**: L'ID de l'employé Odoo
    
    **Retourne** l'image au format binaire.
    """
    try:
        from fastapi.responses import Response
        import base64
        
        # Récupérer l'image depuis Odoo
        employee_details = default_odoo_client.execute_kw(
            'hr.employee', 
            'read', 
            [employee_id], 
            {'fields': ['image_1920']}
        )
        
        if not employee_details or not employee_details[0].get('image_1920'):
            raise HTTPException(
                status_code=404,
                detail="Image non trouvée"
            )
        
        # Décoder l'image (Odoo stocke les images en base64)
        image_data = base64.b64decode(employee_details[0]['image_1920'])
        
        # Détecter le type d'image (simple vérification)
        content_type = "image/png"  # Par défaut
        if image_data.startswith(b'\xff\xd8'):
            content_type = "image/jpeg"
        elif image_data.startswith(b'\x89\x50\x4E\x47'):
            content_type = "image/png"
        
        # Retourner l'image
        return Response(content=image_data, media_type=content_type)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Erreur lors de la récupération de l'image: {e}")
        raise HTTPException(
            status_code=500,
            detail="Erreur lors de la récupération de l'image"
        )

@router.post("/logout", response_model=ApiResponse, summary="Déconnexion")
async def logout(
    logout_data: LogoutRequest,
    current_user: dict = Depends(get_current_user)
):
    """
    **Déconnexion et invalidation du token JWT**
    
    Cette route permet à un utilisateur de se déconnecter en invalidant son token JWT.
    Le token invalidé ne pourra plus être utilisé pour les appels API.
    
    - **token**: Le token JWT à invalider (doit correspondre au token utilisé pour l'authentification)
    
    **Retourne** un message de confirmation si la déconnexion a réussi.
    """
    try:
        # Vérifier que le token fourni correspond au token d'authentification actuel
        from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
        from fastapi import Request
        
        # Valider et invalider le token
        invalidate_token(logout_data.token)
        
        logger.info(f"Déconnexion réussie pour: {current_user['username']}")
        return ApiResponse(
            success=True,
            message="Déconnexion réussie"
        )
    except Exception as e:
        logger.error(f"Erreur lors de la déconnexion: {e}")
        raise HTTPException(
            status_code=500,
            detail="Erreur lors de la déconnexion"
        )
