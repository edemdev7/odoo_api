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

class PinResetRequest(BaseModel):
    matricule: str = Field(..., description="Matricule de l'employé", min_length=1)
    new_pin: str = Field(..., description="Nouveau code PIN (4-8 chiffres)", min_length=4, max_length=8)

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

# Modèles pour la gestion des sessions POS
class PosShop(BaseModel):
    id: int
    name: str
    is_station: bool = Field(False, description="Indique si c'est une station service")
    current_session_id: Optional[int] = None
    current_session_state: Optional[str] = None
    balance: Optional[float] = Field(None, description="Solde actuel du point de vente")

class PosSessionStatus(BaseModel):
    pos_id: int
    has_active_session: bool
    session_id: Optional[int] = None
    session_state: Optional[str] = None
    can_open_session: bool = Field(description="L'employé peut-il ouvrir une session")
    is_manager: bool = Field(description="L'employé est-il gérant")

class PosSessionInitializeRequest(BaseModel):
    pos_id: int = Field(..., description="ID du point de vente")

class PosSessionResponse(BaseModel):
    session_id: int
    pos_id: int
    pos_name: str
    is_station: bool
    state: str
    message: str

class PosPump(BaseModel):
    id: int
    name: str
    product_name: str
    last_index: float = Field(description="Dernier index du compteur")
    current_index: Optional[float] = Field(None, description="Index actuel à valider")

class PosOpenSessionRequest(BaseModel):
    session_id: int = Field(..., description="ID de la session à ouvrir")
    pump_indexes: Optional[List[Dict[str, float]]] = Field(None, description="Index des pompes validés")

# Modèles pour les données de pompes spécifiques
class StationPumpData(BaseModel):
    id: str = Field(..., description="ID unique de la pompe")
    name: str = Field(..., description="Nom de la pompe (ex: J1_E1)")
    stationId: str = Field(..., description="ID de la station")
    type: str = Field(..., description="Type de carburant (PETROL, FUEL, etc.)")
    start_index: float = Field(..., description="Index de début de session")

# Nouveau schéma unifié pour l'ouverture de session
class PosUnifiedOpenSessionRequest(BaseModel):
    # Pour ouverture normale (sans pompes)
    starting_balance: Optional[float] = Field(None, description="Solde de départ pour ouverture normale")
    opening_notes: Optional[str] = Field(None, description="Notes d'ouverture")
    
    # Pour ouverture avec pompes (stations-service)
    session_id: Optional[int] = Field(None, description="ID de la session pour ouverture avec pompes")
    pump_indexes: Optional[List[StationPumpData]] = Field(None, description="Données des pompes avec leurs index")

# Anciens modèles (déprécié - à supprimer dans une version future)
class PosOpenSessionRequest(BaseModel):
    session_id: int = Field(..., description="ID de la session à ouvrir")
    pump_indexes: Optional[List[Dict[str, float]]] = Field(None, description="Index des pompes validés")

class PosOpenSessionWithPumpsRequest(BaseModel):
    session_id: int = Field(..., description="ID de la session à ouvrir")
    pump_indexes: List[StationPumpData] = Field(..., description="Données des pompes avec leurs index")

class PosCloseSessionRequest(BaseModel):
    ending_balance: Optional[float] = Field(None, description="Solde de fermeture déclaré")
    closing_notes: Optional[str] = Field(None, description="Notes de fermeture")
    pump_end_indexes: Optional[List[Dict[str, Any]]] = Field(None, description="Index de fin des pompes (pour stations-service)")

# Classe obsolète - utilisez PosCloseSessionRequest à la place
class CashRegisterCloseRequest(BaseModel):
    ending_balance: float = Field(..., description="Solde de fermeture déclaré")
    pump_end_indexes: List[Dict[str, Any]] = Field(..., description="Index de fin des pompes")
    closing_notes: Optional[str] = Field(None, description="Notes de fermeture")

# Modèles pour la gestion des pompes et ventes
class PumpDetails(BaseModel):
    id: int
    name: str
    product_id: int
    product_name: str
    product_code: Optional[str] = None
    unit_price: float
    start_index: Optional[float] = Field(None, description="Index de début de session")
    current_index: Optional[float] = Field(None, description="Index actuel")
    is_available: bool = Field(True, description="Pompe disponible pour vente")

class PumpSelection(BaseModel):
    pump_id: int
    product_confirmed: bool = Field(True, description="Produit confirmé par l'agent")

class PumpSelectionRequest(BaseModel):
    pos_id: int = Field(..., description="ID du point de vente")
    selected_pumps: List[PumpSelection] = Field(..., description="Pompes sélectionnées")

class PosOrderLine(BaseModel):
    product_id: int
    pump_id: Optional[int] = Field(None, description="ID de la pompe utilisée")
    qty: float = Field(..., description="Quantité vendue")
    price_unit: float = Field(..., description="Prix unitaire")
    discount: Optional[float] = Field(0.0, description="Remise en pourcentage")
    start_pump_index: Optional[float] = Field(None, description="Index pompe début")
    end_pump_index: Optional[float] = Field(None, description="Index pompe fin")

class PosOrderCreateFullRequest(BaseModel):
    pos_session_id: int = Field(..., description="ID de la session POS")
    partner_id: Optional[int] = Field(None, description="ID du client")
    lines: List[PosOrderLine] = Field(..., description="Lignes de commande")
    payment_method_id: int = Field(..., description="ID de la méthode de paiement")
    amount_paid: float = Field(..., description="Montant payé")
    amount_return: Optional[float] = Field(0.0, description="Monnaie rendue")
    note: Optional[str] = Field(None, description="Note sur la commande")

class CashRegisterCloseRequest(BaseModel):
    ending_balance: float = Field(..., description="Solde de fermeture déclaré")
    pump_end_indexes: List[Dict[str, Any]] = Field(..., description="Index de fin des pompes")
    closing_notes: Optional[str] = Field(None, description="Notes de fermeture")

class PumpIndexValidation(BaseModel):
    pump_id: int
    start_index: float
    end_index: float
    calculated_qty: float = Field(description="Quantité calculée (fin - début)")
    sold_qty: float = Field(description="Quantité vendue selon les commandes")
    difference: float = Field(description="Différence entre calculée et vendue")
    is_valid: bool = Field(description="Validation conforme")

class CashRegisterValidation(BaseModel):
    pos_id: int
    session_id: int
    total_sales: float
    declared_balance: float
    expected_balance: float
    balance_difference: float
    pump_validations: List[PumpIndexValidation]
    is_valid: bool = Field(description="Validation globale conforme")
    validation_errors: List[str] = Field(default=[], description="Liste des erreurs de validation")
