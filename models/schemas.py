from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any

class PosShopUpdateRequest(BaseModel):
    name: Optional[str] = Field(None, description="Nom du point de vente")
    state: Optional[str] = Field(None, description="État du PDV")
    company_id: Optional[int] = Field(None, description="ID de la société")
    user_ids: Optional[List[int]] = Field(None, description="IDs des utilisateurs du PDV")
    journal_id: Optional[int] = Field(None, description="ID du journal")
    sequence_id: Optional[int] = Field(None, description="ID de la séquence")

class PosShopArchiveRequest(BaseModel):
    active: bool = Field(..., description="True pour désarchiver, False pour archiver le PDV")

class Token(BaseModel):
    access_token: str
    token_type: str
    expires_in: int
    user_data: Optional[Dict[str, Any]] = Field(None, description="Données de l'utilisateur connecté")

class UserData(BaseModel):
    username: str
    fullname: Optional[str] = None
    email: Optional[str] = None
    image_url: Optional[str] = None
    phone: Optional[str] = None
    scopes: List[str]
    is_active: bool
    additional_info: Optional[Dict[str, Any]] = None

class LogoutRequest(BaseModel):
    token: str = Field(..., description="Token JWT à invalider")

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

class PosProductSearchRequest(BaseModel):
    barcode: Optional[str] = None
    product_name: Optional[str] = None
    limit: Optional[int] = Field(default=10, description="Nombre max de résultats")

class PosOrderCreateRequest(BaseModel):
    customer_id: Optional[int] = None
    products: List[Dict[str, Any]] = Field(..., description="Liste des produits dans la commande")
    payment_method: str = Field(default="cash", description="Méthode de paiement")
    amount_paid: float = Field(..., description="Montant payé")
