from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from passlib.context import CryptContext
from datetime import datetime, timedelta
from jose import jwt
from jose.exceptions import ExpiredSignatureError, JWTError

from core.config import (
    SECRET_KEY, ALGORITHM, ACCESS_TOKEN_EXPIRE_MINUTES, API_USERS,
    ODOO_CONFIG, ODOO_DATABASES, logger, REVOKED_TOKENS, ACTIVE_SESSIONS
)

# Classes de sécurité
security = HTTPBearer()
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def verify_password(plain_password: str, hashed_password: str) -> bool:
    try:
        return pwd_context.verify(plain_password, hashed_password)
    except Exception as e:
        logger.error(f"Erreur lors de la vérification du mot de passe: {e}")
        return False

def authenticate_user(username: str, password: str):
    try:
        user = API_USERS.get(username)
        if not user:
            logger.warning(f"Tentative de connexion avec un utilisateur inconnu: {username}")
            return False
            
        if not verify_password(password, user["hashed_password"]):
            logger.warning(f"Mot de passe incorrect pour l'utilisateur: {username}")
            return False
            
        logger.info(f"Authentification réussie pour l'utilisateur: {username}")
        return user
    except Exception as e:
        logger.error(f"Erreur lors de l'authentification de l'utilisateur {username}: {e}")
        return False

def create_access_token(data: dict, expires_delta: timedelta = None, odoo_db_name: str = None):
    """
    Crée un token JWT avec les données utilisateur et l'information de la base de données Odoo
    
    Args:
        data: Données à encoder dans le token
        expires_delta: Durée de validité du token
        odoo_db_name: Nom de la base de données Odoo (jnp_directe ou franchise)
    """
    try:
        to_encode = data.copy()
        if expires_delta:
            expire = datetime.utcnow() + expires_delta
        else:
            expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
        
        to_encode.update({"exp": expire})
        
        # Ajouter l'information de la base de données Odoo si fournie
        if odoo_db_name:
            to_encode.update({"odoo_db": odoo_db_name})
        
        encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
        return encoded_jwt
    except Exception as e:
        logger.error(f"Erreur lors de la création du token JWT: {e}")
        raise

async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Token invalide ou expiré",
        headers={"WWW-Authenticate": "Bearer"},
    )
    
    try:
        # Vérifier que le token est présent
        if not credentials or not credentials.credentials:
            logger.warning("Tentative d'accès sans token")
            raise credentials_exception
            
        token = credentials.credentials
        
        # Vérifier si le token a été révoqué/invalidé (logout)
        if token in REVOKED_TOKENS:
            logger.warning("Tentative d'utilisation d'un token révoqué")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token révoqué. Veuillez vous reconnecter.",
                headers={"WWW-Authenticate": "Bearer"},
            )
        
        # Décoder le token JWT
        try:
            payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        except ExpiredSignatureError:
            logger.warning("Token expiré")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token expiré",
                headers={"WWW-Authenticate": "Bearer"},
            )
        except JWTError as e:
            logger.warning(f"Erreur de décodage du token: {e}")
            raise credentials_exception
            
        # Vérifier que le username est présent dans le token
        username: str = payload.get("sub")
        if username is None:
            logger.warning("Token sans username")
            raise credentials_exception

        # Vérifier que ce token est bien la session active de l'utilisateur
        # (une seule session par compte : une nouvelle connexion ou un
        # changement de PIN/mot de passe invalide les anciens tokens)
        active_token = ACTIVE_SESSIONS.get(username)
        if active_token and active_token != token:
            logger.warning(f"Session obsolète pour {username}: une autre connexion a invalidé ce token")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Session invalidée: une nouvelle connexion a été effectuée sur ce compte. Veuillez vous reconnecter.",
                headers={"WWW-Authenticate": "Bearer"},
            )

        # Vérifier si c'est un employé authentifié par PIN (format employee_ID)
        if username.startswith("employee_"):
            # Pour les authentifications par PIN, créer un utilisateur virtuel avec les données du token
            employee_id = payload.get("employee_id")
            employee_name = payload.get("employee_name")
            employee_matricule = payload.get("employee_matricule")
            
            if not employee_id or not employee_name:
                logger.warning("Token employé invalide - informations manquantes")
                raise credentials_exception
                
            # Créer un utilisateur virtuel avec les informations de l'employé
            virtual_user = {
                "username": username,
                "is_active": True,
                "scopes": payload.get("scopes", ["read", "pos"]),
                "employee_id": employee_id,
                "employee_name": employee_name,
                "employee_matricule": employee_matricule,
                "partner_id": payload.get("partner_id"),  # IMPORTANT: Inclure le partner_id
                "auth_type": "pin",  # Indiquer que c'est une authentification par PIN
                "odoo_db": payload.get("odoo_db")  # IMPORTANT: Inclure le nom de la DB
            }
            
            logger.info(f"Accès authentifié par PIN pour l'employé: {employee_name} (Partner ID: {payload.get('partner_id')})")
            return virtual_user
            
        # Vérifier que l'utilisateur existe pour authentification standard
        user = API_USERS.get(username)
        if user is None:
            logger.warning(f"Utilisateur du token non trouvé: {username}")
            raise credentials_exception
            
        # Vérifier que l'utilisateur est actif
        if not user.get("is_active", False):
            logger.warning(f"Utilisateur inactif: {username}")
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Utilisateur désactivé",
                headers={"WWW-Authenticate": "Bearer"},
            )
        
        # Extraire les informations Odoo personnalisées si elles existent
        if "odoo_config" in payload:
            user["odoo_config"] = payload["odoo_config"]
            # Récupérer la clé API depuis les utilisateurs API (sécurité)
            user["odoo_config"]["api_key"] = ODOO_CONFIG["api_key"]
            
            # Si on est en présence d'un utilisateur qui a ses propres identifiants Odoo
            logger.info(f"Utilisation des identifiants Odoo personnalisés pour: {username}")
            
        logger.info(f"Accès authentifié pour l'utilisateur: {username}")
        return user
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Erreur lors de la validation du token: {e}")
        raise credentials_exception

def invalidate_token(token: str):
    """Invalide un token en l'ajoutant à la liste des tokens révoqués"""
    REVOKED_TOKENS.add(token)
    logger.info("Token invalidé avec succès")
    return True

def register_session(user_key: str, token: str):
    """
    Enregistre `token` comme session active de `user_key`.

    Si une autre session était déjà active pour ce compte (connexion depuis
    un autre appareil/onglet), son token est immédiatement révoqué afin
    qu'une seule session reste valide à la fois.
    """
    old_token = ACTIVE_SESSIONS.get(user_key)
    if old_token and old_token != token:
        REVOKED_TOKENS.add(old_token)
        logger.info(f"Session précédente invalidée pour {user_key} (nouvelle connexion détectée)")
    ACTIVE_SESSIONS[user_key] = token

def invalidate_user_sessions(user_key: str):
    """
    Invalide la session active de `user_key`, par exemple après un
    changement de PIN ou de mot de passe.
    """
    old_token = ACTIVE_SESSIONS.pop(user_key, None)
    if old_token:
        REVOKED_TOKENS.add(old_token)
        logger.info(f"Session invalidée pour {user_key} suite à un changement d'identifiants")
    return old_token is not None

def require_scope(required_scope: str):
    """Décorateur pour vérifier les permissions"""
    def scope_checker(current_user: dict = Depends(get_current_user)):
        if not current_user or "scopes" not in current_user:
            logger.warning(f"Utilisateur sans scopes définis")
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Permissions insuffisantes"
            )
        
        # Gestion spéciale pour les utilisateurs authentifiés par PIN
        if current_user.get("auth_type") == "pin" and required_scope == "pos":
            logger.debug(f"Accès POS autorisé pour l'employé: {current_user.get('employee_name')}")
            return current_user
            
        if required_scope not in current_user["scopes"]:
            user_id = current_user.get("employee_name") if current_user.get("auth_type") == "pin" else current_user["username"]
            logger.warning(f"Accès refusé: {user_id} a tenté d'accéder à {required_scope}")
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Permission insuffisante. Scope requis: {required_scope}"
            )
            
        user_id = current_user.get("employee_name") if current_user.get("auth_type") == "pin" else current_user["username"]
        logger.debug(f"Accès autorisé: {user_id} a accédé à {required_scope}")
        return current_user
    return scope_checker

def get_odoo_config_from_user(current_user: dict) -> dict:
    """
    Récupère la configuration Odoo appropriée selon la base de données de l'utilisateur
    
    Args:
        current_user: Dictionnaire contenant les informations de l'utilisateur (du token JWT)
        
    Returns:
        dict: Configuration Odoo correspondante
    """
    # Récupérer le nom de la DB depuis les infos utilisateur
    odoo_db_name = current_user.get("odoo_db")
    
    # Si pas d'info de DB, utiliser la config par défaut
    if not odoo_db_name:
        logger.warning("Aucune information de base de données dans le token, utilisation de la config par défaut")
        return ODOO_CONFIG
    
    # Trouver la configuration correspondante
    for db_config in ODOO_DATABASES:
        if db_config["name"] == odoo_db_name:
            logger.debug(f"Configuration Odoo trouvée: {db_config['name']} ({db_config['url']})")
            return db_config
    
    # Si la DB n'est pas trouvée, utiliser la config par défaut
    logger.warning(f"Base de données '{odoo_db_name}' non trouvée, utilisation de la config par défaut")
    return ODOO_CONFIG
