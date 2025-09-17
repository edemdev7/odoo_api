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
    "url": os.getenv("ODOO_URL", "http://34.89.40.140"),
    "db": os.getenv("ODOO_DB", "jnpdb"),
    "username": os.getenv("ODOO_USERNAME", "admin"),
    "api_key": os.getenv("ODOO_API_KEY", "524b562f73048e5ad0f5248a29fb22584b6254d1")
}

logger.info(f"Configuration Odoo: {ODOO_CONFIG}")

# Utilisateurs API (en production, utilisez une vraie base de données)
API_USERS = {
    "admin": {
        "username": "admin",
        "hashed_password": "$2b$12$vVswhtAQBoTursFoUkyKyOU2UJ9kKNZ8KZYDc4bz1MjNL86r48fiO",  # "admin123"
        "is_active": True,
        "scopes": ["read", "write", "delete"]
    },
    "readonly": {
        "username": "readonly", 
        "hashed_password": "$2b$12$KpqzDOHWwGPgX0hLDcLKBOHm8JoQs7kB9aL5pF9VqKcwG2LYmK5MG",  # "readonly123"
        "is_active": True,
        "scopes": ["read"]
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
    def __init__(self):
        self.url = ODOO_CONFIG["url"]
        self.db = ODOO_CONFIG["db"]
        self.username = ODOO_CONFIG["username"]
        self.api_key = ODOO_CONFIG["api_key"]
        self.uid = None
        self._authenticate()
    
    def _authenticate(self):
        """Authentification avec Odoo"""
        try:
            logger.info(f"Tentative de connexion à Odoo: URL={self.url}, DB={self.db}, USER={self.username}")
            common = xmlrpc.client.ServerProxy(f'{self.url}/xmlrpc/2/common')
            
            # Tentative avec clé API
            self.uid = common.authenticate(self.db, self.username, self.api_key, {})
            
            # Si échec, essayer avec le mot de passe comme 'api_key'
            if not self.uid:
                logger.warning("Échec d'authentification avec clé API, tentative avec mot de passe...")
                self.uid = common.authenticate(self.db, self.username, self.api_key, {})
            
            if not self.uid:
                logger.error(f"Échec de l'authentification Odoo: UID={self.uid}")
                raise Exception("Échec de l'authentification Odoo")
            
            logger.info(f"Authentifié avec Odoo - UID: {self.uid}")
        except Exception as e:
            logger.error(f"Erreur d'authentification Odoo: {str(e)}")
            raise
    
    def execute_kw(self, model: str, method: str, args: list, kwargs: dict = None):
        """Exécute une méthode Odoo"""
        kwargs = kwargs or {}
        try:
            models = xmlrpc.client.ServerProxy(f'{self.url}/xmlrpc/2/object')
            return models.execute_kw(self.db, self.uid, self.api_key, model, method, args, kwargs)
        except Exception as e:
            logger.error(f"Erreur lors de l'exécution de {method} sur {model}: {e}")
            raise

# Instance globale du client Odoo
odoo_client = OdooClient()

# ===== FONCTIONS DE SÉCURITÉ =====

def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)

def authenticate_user(username: str, password: str):
    user = API_USERS.get(username)
    if not user or not verify_password(password, user["hashed_password"]):
        return False
    return user

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Token invalide",
        headers={"WWW-Authenticate": "Bearer"},
    )
    
    try:
        token = credentials.credentials
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise credentials_exception
    except jwt.PyJWTError:
        raise credentials_exception
    
    user = API_USERS.get(username)
    if user is None:
        raise credentials_exception
    return user

def require_scope(required_scope: str):
    """Décorateur pour vérifier les permissions"""
    def scope_checker(current_user: dict = Depends(get_current_user)):
        if required_scope not in current_user["scopes"]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Permission insuffisante. Scope requis: {required_scope}"
            )
        return current_user
    return scope_checker

# ===== ENDPOINTS D'AUTHENTIFICATION =====

@app.post("/auth/login", response_model=Token, tags=["Authentification"])
async def login(user_data: UserLogin):
    """Connexion et génération du token JWT"""
    user = authenticate_user(user_data.username, user_data.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Nom d'utilisateur ou mot de passe incorrect",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user["username"], "scopes": user["scopes"]}, 
        expires_delta=access_token_expires
    )
    
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "expires_in": ACCESS_TOKEN_EXPIRE_MINUTES * 60
    }

@app.get("/auth/me", tags=["Authentification"])
async def read_users_me(current_user: dict = Depends(get_current_user)):
    """Informations sur l'utilisateur connecté"""
    return {
        "username": current_user["username"],
        "scopes": current_user["scopes"],
        "is_active": current_user["is_active"]
    }

# ===== ENDPOINTS ODOO - LECTURE =====

@app.post("/odoo/search", response_model=ApiResponse, tags=["Odoo - Lecture"])
async def search_records(
    request: OdooSearchRequest,
    current_user: dict = Depends(require_scope("read"))
):
    """Rechercher des enregistrements dans Odoo"""
    try:
        kwargs = {}
        if request.limit:
            kwargs['limit'] = request.limit
        
        ids = odoo_client.execute_kw(request.model, 'search', [request.domain], kwargs)
        
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
        record_ids = [int(id_.strip()) for id_ in ids.split(",")]
        kwargs = {}
        if fields:
            kwargs['fields'] = [f.strip() for f in fields.split(",")]
        
        records = odoo_client.execute_kw(model, 'read', [record_ids], kwargs)
        
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
        kwargs = {}
        if request.fields:
            kwargs['fields'] = request.fields
        if request.limit:
            kwargs['limit'] = request.limit
        
        records = odoo_client.execute_kw(request.model, 'search_read', [request.domain], kwargs)
        
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
        new_id = odoo_client.execute_kw(request.model, 'create', [request.values])
        
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
        success = odoo_client.execute_kw(request.model, 'unlink', [request.ids])
        
        return ApiResponse(
            success=success,
            data={"deleted_ids": request.ids},
            count=len(request.ids),
            message=f"Supprimé {len(request.ids)} enregistrements"
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur lors de la suppression: {str(e)}")

# ===== ENDPOINTS UTILITAIRES =====

@app.get("/odoo/models", response_model=ApiResponse, tags=["Odoo - Utilitaires"])
async def list_models(
    current_user: dict = Depends(require_scope("read"))
):
    """Lister les modèles Odoo disponibles"""
    try:
        models = odoo_client.execute_kw('ir.model', 'search_read', [[]], {'fields': ['model', 'name'], 'limit': 100})
        
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
        fields = odoo_client.execute_kw(model, 'fields_get', [], {'attributes': ['string', 'help', 'type', 'required']})
        
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
        # Test de connexion Odoo
        version = odoo_client.execute_kw('ir.module.module', 'search_count', [[]])
        
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