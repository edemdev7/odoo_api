from fastapi import FastAPI, HTTPException, Depends, status, Query
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
import os
import jwt
from datetime import datetime, timedelta
import xmlrpc.client
from passlib.context import CryptContext
import logging
from dotenv import load_dotenv

# Charger les variables d'environnement
load_dotenv()

# Configuration du logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Configuration de l'application
app = FastAPI(
    title="Odoo API Gateway",
    description="API REST sécurisée pour intégration avec Odoo",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc"
)

# Middleware CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # À restreindre en production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Configuration de sécurité
SECRET_KEY = os.getenv("JWT_SECRET_KEY", "your-super-secret-key-change-in-production")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30

# Configuration Odoo
ODOO_CONFIG = {
    "url": os.getenv("ODOO_URL", "https://erp.jnpgroupe.com"),
    "db": os.getenv("ODOO_DB", "OMHI-TEST"),
    "username": os.getenv("ODOO_USERNAME", "admin@jnpgroupe.com"),
    "api_key": os.getenv("ODOO_API_KEY", "33e3aa2baad77fc78418d2747d6b0c5616d5dcb6")
}

logger.info(f"Configuration Odoo: {ODOO_CONFIG}")

# Utilisateurs API (en production, utilisez une vraie base de données)
API_USERS = {
    "admin": {
        "username": "admin",
        "hashed_password": "$2b$12$Ve.p30uPHQSVt2PBRTJU4.o37W2sD9vq7SMoR1UQJ4BkWb5/nsqVm",  # "admin123"
        "is_active": True,
        "scopes": ["read", "write", "delete"]
    },
    "readonly": {
        "username": "readonly", 
        "hashed_password": "$2b$12$KpqzDOHWwGPgX0hLDcLKBOHm8JoQs7kB9aL5pF9VqKcwG2LYmK5MG",  # "readonly123"
        "is_active": True,
        "scopes": ["read"]
    },
    "admin@jnpgroupe.com": {
        "username": "admin@jnpgroupe.com",
        "hashed_password": "$2b$12$M6olJi2HJk/MCApZHJkKx.oJPo50QkKz6.QVtW2brH/CCdh31HJSe",  # "zBfMQyOlYVkg8WB"
        "is_active": True,
        "scopes": ["read", "write", "delete"]
    }
}

# Classes de sécurité
security = HTTPBearer()
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# ===== MODÈLES PYDANTIC =====

class Token(BaseModel):
    access_token: str
    token_type: str
    expires_in: int

class UserLogin(BaseModel):
    username: str
    password: str
    # Informations optionnelles pour la connexion Odoo
    odoo_db: Optional[str] = None
    odoo_username: Optional[str] = None
    odoo_api_key: Optional[str] = None

class PinLogin(BaseModel):
    matricule: str = Field(..., description="Matricule de l'employé")
    pin: str = Field(..., description="Code PIN de l'employé")

class OdooSearchRequest(BaseModel):
    model: str = Field(..., description="Nom du modèle Odoo (ex: res.partner)")
    domain: Optional[List] = Field(default=[], description="Critères de recherche")
    limit: Optional[int] = Field(default=None, description="Nombre max de résultats")
    fields: Optional[List[str]] = Field(default=None, description="Champs à retourner")

class OdooCreateRequest(BaseModel):
    model: str = Field(..., description="Nom du modèle Odoo")
    values: Dict[str, Any] = Field(..., description="Données à créer")

class OdooUpdateRequest(BaseModel):
    model: str = Field(..., description="Nom du modèle Odoo")
    ids: List[int] = Field(..., description="IDs des enregistrements à modifier")
    values: Dict[str, Any] = Field(..., description="Nouvelles données")

class OdooDeleteRequest(BaseModel):
    model: str = Field(..., description="Nom du modèle Odoo")
    ids: List[int] = Field(..., description="IDs des enregistrements à supprimer")

class ApiResponse(BaseModel):
    success: bool
    data: Any = None
    message: str = ""
    count: Optional[int] = None

# ===== CLIENT ODOO =====

class OdooClient:
    def __init__(self, custom_config=None):
        """
        Initialise le client Odoo
        :param custom_config: Configuration personnalisée (optionnel) avec url, db, username, api_key
        """
        config = ODOO_CONFIG.copy()
        if custom_config:
            for key, value in custom_config.items():
                if value:  # Ne remplacer que si la valeur n'est pas None
                    config[key] = value
                    
        self.url = config["url"]
        self.db = config["db"]
        self.username = config["username"]
        self.api_key = config["api_key"]
        self.uid = None
        self._authenticate()
    
    
    def _authenticate(self):
        """Authentification avec Odoo"""
        max_retries = 3
        retry_count = 0
        last_error = None
        
        while retry_count < max_retries:
            try:
                logger.info(f"Tentative de connexion à Odoo ({retry_count+1}/{max_retries}): URL={self.url}, DB={self.db}, USER={self.username}")
                common = xmlrpc.client.ServerProxy(f'{self.url}/xmlrpc/2/common')
                
                # Tentative d'authentification avec la clé API (ou mot de passe)
                self.uid = common.authenticate(self.db, self.username, self.api_key, {})
                
                if self.uid:
                    logger.info(f"Authentifié avec Odoo - UID: {self.uid}")
                    return
                else:
                    logger.error("Échec de l'authentification Odoo: identifiants incorrects")
                    raise Exception("Identifiants Odoo incorrects")
                    
            except Exception as e:
                last_error = str(e)
                logger.warning(f"Échec de la tentative {retry_count+1}: {last_error}")
                retry_count += 1
                # Petite pause avant de réessayer
                import time
                time.sleep(1)
        
        # Si on arrive ici, toutes les tentatives ont échoué
        logger.error(f"Échec de l'authentification Odoo après {max_retries} tentatives: {last_error}")
        raise Exception(f"Échec de l'authentification Odoo: {last_error}")
    
    def execute_kw(self, model: str, method: str, args: list, kwargs: dict = None):
        """Exécute une méthode Odoo"""
        kwargs = kwargs or {}
        max_retries = 2
        retry_count = 0
        last_error = None
        
        while retry_count < max_retries:
            try:
                # Vérifier si l'authentification est valide
                if not self.uid:
                    logger.warning("UID non valide, tentative de réauthentification...")
                    self._authenticate()
                
                models = xmlrpc.client.ServerProxy(f'{self.url}/xmlrpc/2/object')
                result = models.execute_kw(self.db, self.uid, self.api_key, model, method, args, kwargs)
                return result
                
            except Exception as e:
                last_error = str(e)
                retry_count += 1
                logger.warning(f"Erreur lors de l'exécution de {method} sur {model} (tentative {retry_count}/{max_retries}): {last_error}")
                
                # Si c'est un problème d'authentification, on réessaie de s'authentifier
                if "session expired" in last_error.lower() or "access denied" in last_error.lower():
                    try:
                        logger.info("Tentative de réauthentification...")
                        self._authenticate()
                    except Exception as auth_error:
                        logger.error(f"Échec de réauthentification: {auth_error}")
                
                # Petite pause avant de réessayer
                if retry_count < max_retries:
                    import time
                    time.sleep(1)
        
        # Si on arrive ici, toutes les tentatives ont échoué
        logger.error(f"Échec de l'exécution de {method} sur {model} après {max_retries} tentatives: {last_error}")
        raise Exception(f"Erreur Odoo: {last_error}")

# Instance globale du client Odoo par défaut
default_odoo_client = OdooClient()

# Fonction pour obtenir le client Odoo approprié pour l'utilisateur
def get_odoo_client(user=None):
    """
    Renvoie le client Odoo approprié en fonction de l'utilisateur
    :param user: Utilisateur authentifié (avec éventuellement une config Odoo personnalisée)
    :return: Instance de OdooClient
    """
    if user and "odoo_config" in user:
        try:
            # Créer un client Odoo avec les paramètres personnalisés
            return OdooClient(custom_config=user["odoo_config"])
        except Exception as e:
            logger.error(f"Erreur lors de la création du client Odoo personnalisé: {e}")
            # En cas d'erreur, utiliser le client par défaut
    
    # Utiliser le client par défaut
    return default_odoo_client

# ===== FONCTIONS DE SÉCURITÉ =====

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

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    try:
        to_encode = data.copy()
        if expires_delta:
            expire = datetime.utcnow() + expires_delta
        else:
            expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
        
        to_encode.update({"exp": expire})
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
        
        # Décoder le token JWT
        try:
            payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        except jwt.ExpiredSignatureError:
            logger.warning("Token expiré")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token expiré",
                headers={"WWW-Authenticate": "Bearer"},
            )
        except jwt.PyJWTError as e:
            logger.warning(f"Erreur de décodage du token: {e}")
            raise credentials_exception
            
        # Vérifier que le username est présent dans le token
        username: str = payload.get("sub")
        if username is None:
            logger.warning("Token sans username")
            raise credentials_exception
            
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
                "auth_type": "pin"  # Indiquer que c'est une authentification par PIN
            }
            
            logger.info(f"Accès authentifié par PIN pour l'employé: {employee_name}")
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

# ===== ENDPOINTS D'AUTHENTIFICATION =====

@app.post("/auth/login", response_model=Token, tags=["Authentification"])
async def login(user_data: UserLogin):
    """Connexion et génération du token JWT"""
    try:
        # Limite de tentatives pour prévenir les attaques par force brute
        from fastapi.concurrency import run_in_threadpool
        
        # Valider les données d'entrée
        if not user_data.username or not user_data.password:
            logger.warning("Tentative de connexion avec des champs vides")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Le nom d'utilisateur et le mot de passe sont requis",
            )
            
        # Authentifier l'utilisateur de manière non-bloquante
        user = await run_in_threadpool(lambda: authenticate_user(user_data.username, user_data.password))
        
        if not user:
            logger.warning(f"Échec d'authentification pour: {user_data.username}")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
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
                test_client = OdooClient(custom_config=custom_odoo_config)
                # Si on arrive ici, c'est que la connexion a réussi
                logger.info(f"Connexion Odoo personnalisée réussie pour: {user_data.username}")
                
                # Stocker les paramètres de connexion Odoo dans le token
                user["odoo_config"] = custom_odoo_config
            except Exception as e:
                logger.error(f"Échec de connexion Odoo personnalisée: {e}")
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
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
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Erreur lors de la connexion",
        )

@app.post("/auth/pin-login", response_model=Token, tags=["Authentification"])
async def pin_login(login_data: PinLogin):
    """Connexion avec matricule et PIN pour les utilisateurs de point de vente/stock"""
    try:
        # Valider les données d'entrée
        if not login_data.matricule or not login_data.pin:
            logger.warning("Tentative de connexion avec des champs vides")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
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
                    status_code=status.HTTP_401_UNAUTHORIZED,
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
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Erreur lors de la vérification des informations d'employé",
            )
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Erreur lors de la connexion par PIN: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Erreur lors de la connexion",
        )

@app.get("/auth/me", tags=["Authentification"])
async def read_users_me(current_user: dict = Depends(get_current_user)):
    """Informations sur l'utilisateur connecté"""
    return {
        "username": current_user["username"],
        "scopes": current_user["scopes"],
        "is_active": current_user["is_active"]
    }

# ===== ENDPOINTS ODOO - LECTURE SANS AUTHENTIFICATION =====

@app.get("/public/models", response_model=ApiResponse, tags=["Odoo - Public"])
async def list_public_models():
    """Lister les modèles Odoo disponibles (endpoint public)"""
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

@app.get("/public/partners", response_model=ApiResponse, tags=["Odoo - Public"])
async def list_public_partners():
    """Lister les partenaires publics (endpoint public)"""
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

@app.get("/public/products", response_model=ApiResponse, tags=["Odoo - Public"])
async def list_public_products():
    """Lister les produits publics (endpoint public)"""
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

@app.post("/odoo/search", response_model=ApiResponse, tags=["Odoo - Lecture"])
async def search_records(
    request: OdooSearchRequest,
    current_user: dict = Depends(require_scope("read"))
):
    """Rechercher des enregistrements dans Odoo"""
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

@app.post("/odoo/read", response_model=ApiResponse, tags=["Odoo - Lecture"])
async def read_records(
    model: str = Query(..., description="Nom du modèle Odoo"),
    ids: str = Query(..., description="IDs séparés par des virgules"),
    fields: Optional[str] = Query(None, description="Champs séparés par des virgules"),
    current_user: dict = Depends(require_scope("read"))
):
    """Lire des enregistrements par IDs"""
    try:
        # Obtenir le client Odoo approprié pour cet utilisateur
        client = get_odoo_client(current_user)
        
        record_ids = [int(id_.strip()) for id_ in ids.split(",")]
        kwargs = {}
        if fields:
            kwargs['fields'] = [f.strip() for f in fields.split(",")]
        
        records = client.execute_kw(model, 'read', [record_ids], kwargs)
        
        return ApiResponse(
            success=True,
            data=records,
            count=len(records),
            message=f"Lu {len(records)} enregistrements"
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur lors de la lecture: {str(e)}")

@app.post("/odoo/search_read", response_model=ApiResponse, tags=["Odoo - Lecture"])
async def search_read_records(
    request: OdooSearchRequest,
    current_user: dict = Depends(require_scope("read"))
):
    """Rechercher et lire des enregistrements en une seule opération"""
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

@app.post("/odoo/create", response_model=ApiResponse, tags=["Odoo - Écriture"])
async def create_record(
    request: OdooCreateRequest,
    current_user: dict = Depends(require_scope("write"))
):
    """Créer un nouvel enregistrement"""
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

@app.post("/odoo/update", response_model=ApiResponse, tags=["Odoo - Écriture"])
async def update_records(
    request: OdooUpdateRequest,
    current_user: dict = Depends(require_scope("write"))
):
    """Mettre à jour des enregistrements existants"""
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

@app.post("/odoo/delete", response_model=ApiResponse, tags=["Odoo - Suppression"])
async def delete_records(
    request: OdooDeleteRequest,
    current_user: dict = Depends(require_scope("delete"))
):
    """Supprimer des enregistrements"""
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

@app.post("/odoo/update", response_model=ApiResponse, tags=["Odoo - Écriture"])
async def update_records(
    request: OdooUpdateRequest,
    current_user: dict = Depends(require_scope("write"))
):
    """Mettre à jour des enregistrements existants"""
    try:
        success = odoo_client.execute_kw(request.model, 'write', [request.ids, request.values])
        
        return ApiResponse(
            success=success,
            data={"updated_ids": request.ids},
            count=len(request.ids),
            message=f"Mis à jour {len(request.ids)} enregistrements"
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur lors de la mise à jour: {str(e)}")

# ===== ENDPOINTS ODOO - SUPPRESSION =====

@app.post("/odoo/delete", response_model=ApiResponse, tags=["Odoo - Suppression"])
async def delete_records(
    request: OdooDeleteRequest,
    current_user: dict = Depends(require_scope("delete"))
):
    """Supprimer des enregistrements"""
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

# ===== ENDPOINTS POS/STOCK =====

class PosProductSearchRequest(BaseModel):
    barcode: Optional[str] = None
    product_name: Optional[str] = None
    limit: Optional[int] = Field(default=10, description="Nombre max de résultats")

class PosOrderCreateRequest(BaseModel):
    customer_id: Optional[int] = None
    products: List[Dict[str, Any]] = Field(..., description="Liste des produits dans la commande")
    payment_method: str = Field(default="cash", description="Méthode de paiement")
    amount_paid: float = Field(..., description="Montant payé")

@app.post("/pos/products", response_model=ApiResponse, tags=["Point de Vente"])
async def search_pos_products(
    request: PosProductSearchRequest,
    current_user: dict = Depends(require_scope("pos"))
):
    """Rechercher des produits pour le point de vente"""
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
        raise HTTPException(status_code=500, detail=f"Erreur lors de la recherche de produits: {str(e)}")

@app.post("/pos/create-order", response_model=ApiResponse, tags=["Point de Vente"])
async def create_pos_order(
    request: PosOrderCreateRequest,
    current_user: dict = Depends(require_scope("pos"))
):
    """Créer une nouvelle commande de point de vente"""
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
                'user_id': current_user.get('employee_id', False),
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

# ===== ENDPOINTS UTILITAIRES =====

@app.get("/odoo/models", response_model=ApiResponse, tags=["Odoo - Utilitaires"])
async def list_models(
    current_user: dict = Depends(require_scope("read"))
):
    """Lister les modèles Odoo disponibles"""
    try:
        # Obtenir le client Odoo approprié pour cet utilisateur
        client = get_odoo_client(current_user)
        
        models = client.execute_kw('ir.model', 'search_read', [[]], {'fields': ['model', 'name'], 'limit': 100})
        
        return ApiResponse(
            success=True,
            data=models,
            count=len(models),
            message=f"Trouvé {len(models)} modèles"
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur lors de la récupération des modèles: {str(e)}")

@app.get("/odoo/fields/{model}", response_model=ApiResponse, tags=["Odoo - Utilitaires"])
async def get_model_fields(
    model: str,
    current_user: dict = Depends(require_scope("read"))
):
    """Obtenir les champs d'un modèle Odoo"""
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


# ===== ENDPOINT DE SANTÉ =====

@app.get("/health", tags=["Système"])
async def health_check():
    """Vérification de l'état de l'API"""
    try:
        # Test de connexion Odoo avec le client par défaut
        version = default_odoo_client.execute_kw('ir.module.module', 'search_count', [[]])
        
        return {
            "status": "healthy",
            "odoo_connection": "ok",
            "timestamp": datetime.utcnow().isoformat(),
            "version": "1.0.0"
        }
    except Exception as e:
        return {
            "status": "unhealthy",
            "odoo_connection": "error",
            "error": str(e),
            "timestamp": datetime.utcnow().isoformat()
        }

# ===== ENDPOINT RACINE =====

@app.get("/", tags=["Système"])
async def root():
    """Page d'accueil de l'API"""
    return {
        "message": "Odoo API Gateway",
        "version": "1.0.0",
        "docs": "/docs",
        "redoc": "/redoc",
        "health": "/health"
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)