from pydantic import BaseModel, Field, field_validator
from typing import Optional, List, Dict, Any, Union

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
    company: Optional[Dict[str, Any]] = Field(None, description="Informations sur la société")

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
    product_id: Optional[int] = Field(None, description="ID du produit Odoo associé (product.product)")
    product_name: Optional[str] = Field(None, description="Nom du produit Odoo")

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

# ===== NOUVEAUX SCHEMAS POUR GESTION PDV =====

class PosCreateRequest(BaseModel):
    name: str = Field(..., description="Nom du point de vente", min_length=1, max_length=100)
    company_id: Optional[int] = Field(None, description="ID de la société (optionnel, par défaut la société principale)")
    picking_type_id: Optional[int] = Field(None, description="ID du type d'opération (optionnel)")
    journal_id: Optional[int] = Field(None, description="ID du journal comptable (optionnel)")
    currency_id: Optional[int] = Field(None, description="ID de la devise (optionnel)")
    pricelist_id: Optional[int] = Field(None, description="ID de la liste de prix (optionnel)")
    receipt_header: Optional[str] = Field(None, description="En-tête des reçus", max_length=500)
    receipt_footer: Optional[str] = Field(None, description="Pied de page des reçus", max_length=500)
    iface_tax_included: Optional[str] = Field("total", description="Affichage des taxes (total/subtotal)")
    cash_control: Optional[bool] = Field(True, description="Contrôle de caisse avancé")
    module_pos_hr: Optional[bool] = Field(True, description="Connexion par employés")

class PosEmployeeAssignmentRequest(BaseModel):
    employee_ids: List[int] = Field(..., description="Liste des IDs d'employés à affecter", min_items=1)
    access_level: str = Field(..., description="Niveau d'accès (basic/advanced)", pattern="^(basic|advanced)$")
    replace: bool = Field(False, description="Remplacer les affectations existantes (True) ou ajouter (False)")

class PosConfigResponse(BaseModel):
    id: int
    name: str
    company_id: Optional[List[Any]] = None
    active: bool
    basic_employee_ids: List[int] = []
    advanced_employee_ids: List[int] = []
    current_session_id: Optional[List[Any]] = None
    current_session_state: Optional[str] = None

# ===== SCHEMAS POUR GESTION DES PRODUITS =====

class ProductCreateRequest(BaseModel):
    name: str = Field(..., description="Nom du produit", min_length=1, max_length=200)
    default_code: Optional[str] = Field(None, description="Référence interne/code barre", max_length=50)
    list_price: float = Field(..., description="Prix de vente public", ge=0)
    standard_price: Optional[float] = Field(0.0, description="Coût du produit", ge=0)
    type: str = Field("product", description="Type de produit (product/service/consu)", pattern="^(product|service|consu)$")
    categ_id: Optional[int] = Field(None, description="ID de la catégorie de produit")
    uom_id: Optional[int] = Field(None, description="ID de l'unité de mesure")
    uom_po_id: Optional[int] = Field(None, description="ID de l'unité d'achat")
    barcode: Optional[str] = Field(None, description="Code-barres", max_length=50)
    weight: Optional[float] = Field(0.0, description="Poids en kg", ge=0)
    volume: Optional[float] = Field(0.0, description="Volume en m³", ge=0)
    description: Optional[str] = Field(None, description="Description du produit", max_length=1000)
    description_sale: Optional[str] = Field(None, description="Description pour la vente", max_length=500)
    active: bool = Field(True, description="Produit actif")
    sale_ok: bool = Field(True, description="Peut être vendu")
    purchase_ok: bool = Field(True, description="Peut être acheté")
    available_in_pos: bool = Field(True, description="Disponible dans le POS")
    taxes_id: Optional[List[int]] = Field(None, description="IDs des taxes")
    supplier_taxes_id: Optional[List[int]] = Field(None, description="IDs des taxes fournisseur")

class PosProductAssignmentRequest(BaseModel):
    product_ids: List[int] = Field(..., description="Liste des IDs de produits à ajouter au POS", min_items=1)
    replace: bool = Field(False, description="Remplacer les produits existants (True) ou ajouter (False)")

class StockMovementRequest(BaseModel):
    product_id: int = Field(..., description="ID du produit")
    quantity: float = Field(..., description="Quantité à ajouter/retirer (+ pour entrée, - pour sortie)")
    location_id: Optional[int] = Field(None, description="ID de l'emplacement source (optionnel)")
    location_dest_id: Optional[int] = Field(None, description="ID de l'emplacement destination (optionnel)")
    reference: Optional[str] = Field(None, description="Référence du mouvement", max_length=100)
    reason: Optional[str] = Field(None, description="Raison du mouvement", max_length=200)

class StockLevelRequest(BaseModel):
    product_id: int = Field(..., description="ID du produit")
    new_quantity: float = Field(..., description="Nouvelle quantité en stock", ge=0)
    reason: Optional[str] = Field("Mise à jour manuelle", description="Raison de l'ajustement")

class ProductStockResponse(BaseModel):
    product_id: int
    product_name: str
    product_code: Optional[str] = None
    current_stock: float
    reserved_stock: float = 0.0
    available_stock: float
    unit_of_measure: str
    location_name: str
    last_update: Optional[str] = None

# ===== SCHEMAS POUR GESTION DES INVENTAIRES (STOCK.PICKING) =====

class StockMoveDetails(BaseModel):
    """Détails d'un mouvement de stock"""
    id: int
    name: str = Field(description="Description du mouvement")
    product_id: Optional[List[Any]] = Field(None, description="Produit [ID, nom]")
    product_uom_qty: Optional[float] = Field(None, description="Quantité demandée")
    quantity_done: Optional[float] = Field(None, description="Quantité réalisée")
    product_uom: Optional[List[Any]] = Field(None, description="Unité de mesure [ID, nom]")
    state: Optional[str] = Field(None, description="État du mouvement")
    location_id: Optional[List[Any]] = Field(None, description="Emplacement source [ID, nom]")
    location_dest_id: Optional[List[Any]] = Field(None, description="Emplacement destination [ID, nom]")
    date: Optional[str] = Field(None, description="Date du mouvement")
    date_expected: Optional[str] = Field(None, description="Date prévue")
    origin: Optional[str] = Field(None, description="Document source")
    price_unit: Optional[float] = Field(None, description="Prix unitaire")
    product_details: Optional[Dict[str, Any]] = Field(None, description="Détails du produit")
    
    @field_validator('product_id', 'product_uom', 'location_id', 'location_dest_id', mode='before')
    @classmethod
    def validate_many2one_fields(cls, v):
        return None if v is False else v
    
    @field_validator('name', 'state', 'date', 'date_expected', 'origin', mode='before')
    @classmethod
    def validate_string_fields(cls, v):
        return None if v is False else v

class StockPickingTypeDetails(BaseModel):
    """Détails du type de picking"""
    id: int
    name: str = Field(description="Nom du type")
    code: Optional[str] = Field(None, description="Code (incoming/outgoing/internal)")
    warehouse_id: Optional[List[Any]] = Field(None, description="Entrepôt [ID, nom]")
    default_location_src_id: Optional[List[Any]] = Field(None, description="Emplacement source par défaut [ID, nom]")
    default_location_dest_id: Optional[List[Any]] = Field(None, description="Emplacement destination par défaut [ID, nom]")
    use_create_lots: Optional[bool] = Field(None, description="Créer des lots")
    use_existing_lots: Optional[bool] = Field(None, description="Utiliser des lots existants")
    show_entire_packs: Optional[bool] = Field(None, description="Afficher paquets entiers")
    show_reserved: Optional[bool] = Field(None, description="Afficher réservé")
    show_operations: Optional[bool] = Field(None, description="Afficher opérations")
    
    @field_validator('warehouse_id', 'default_location_src_id', 'default_location_dest_id', mode='before')
    @classmethod
    def validate_many2one_fields(cls, v):
        return None if v is False else v
    
    @field_validator('code', mode='before')
    @classmethod
    def validate_string_fields(cls, v):
        return None if v is False else v

class StockPickingResponse(BaseModel):
    # Champs de base
    id: int
    name: str = Field(description="Référence du transfert")
    origin: Optional[str] = Field(None, description="Document source")
    state: str = Field(description="État du transfert (draft/waiting/confirmed/assigned/done/cancel)")
    picking_type_code: Optional[str] = Field(None, description="Type d'opération (incoming/outgoing/internal)")
    partner_id: Optional[List[Any]] = Field(None, description="Contact [ID, nom]")
    location_id: Optional[List[Any]] = Field(None, description="Emplacement source [ID, nom]")
    location_dest_id: Optional[List[Any]] = Field(None, description="Emplacement destination [ID, nom]")
    scheduled_date: Optional[str] = Field(None, description="Date prévue")
    date_done: Optional[str] = Field(None, description="Date de réalisation")
    user_id: Optional[List[Any]] = Field(None, description="Responsable [ID, nom]")
    company_id: Optional[List[Any]] = Field(None, description="Société [ID, nom]")
    products_availability: Optional[str] = Field(None, description="Disponibilité des produits")
    products_availability_state: Optional[str] = Field(None, description="État de disponibilité")
    move_ids: Optional[List[int]] = Field(None, description="IDs des mouvements de stock")
    pos_session_id: Optional[List[Any]] = Field(None, description="Session POS [ID, nom]")
    pos_order_id: Optional[List[Any]] = Field(None, description="Commande POS [ID, nom]")
    note: Optional[str] = Field(None, description="Notes")
    
    # Champs détaillés supplémentaires
    picking_type_id: Optional[List[Any]] = Field(None, description="Type de picking [ID, nom]")
    priority: Optional[str] = Field(None, description="Priorité")
    date: Optional[str] = Field(None, description="Date de création")
    date_deadline: Optional[str] = Field(None, description="Date limite")
    move_type: Optional[str] = Field(None, description="Type de mouvement")
    group_id: Optional[List[Any]] = Field(None, description="Groupe de procurement [ID, nom]")
    has_scrap_move: Optional[bool] = Field(None, description="A des mouvements de rebut")
    has_packages: Optional[bool] = Field(None, description="A des colis")
    is_locked: Optional[bool] = Field(None, description="Est verrouillé")
    is_assigned: Optional[bool] = Field(None, description="Est assigné")
    is_available: Optional[bool] = Field(None, description="Est disponible")
    
    # Informations de livraison
    carrier_id: Optional[List[Any]] = Field(None, description="Transporteur [ID, nom]")
    carrier_tracking_ref: Optional[str] = Field(None, description="Référence de suivi")
    weight: Optional[float] = Field(None, description="Poids")
    carrier_price: Optional[float] = Field(None, description="Prix transport")
    number_of_packages: Optional[int] = Field(None, description="Nombre de colis")
    
    # Informations de workflow
    backorder_id: Optional[List[Any]] = Field(None, description="Commande en retard [ID, nom]")
    immediate_transfer: Optional[bool] = Field(None, description="Transfert immédiat")
    show_operations: Optional[bool] = Field(None, description="Afficher opérations")
    show_lots_text: Optional[bool] = Field(None, description="Afficher texte des lots")
    has_tracking: Optional[bool] = Field(None, description="A un suivi")
    
    # Informations de dates et utilisateurs
    create_date: Optional[str] = Field(None, description="Date de création")
    write_date: Optional[str] = Field(None, description="Date de modification")
    create_uid: Optional[List[Any]] = Field(None, description="Créé par [ID, nom]")
    write_uid: Optional[List[Any]] = Field(None, description="Modifié par [ID, nom]")
    
    # Détails enrichis
    move_details: Optional[List[StockMoveDetails]] = Field(None, description="Détails des mouvements de stock")
    picking_type_details: Optional[StockPickingTypeDetails] = Field(None, description="Détails du type de picking")
    
    @field_validator('partner_id', 'user_id', 'company_id', 'location_id', 'location_dest_id', 'pos_session_id', 'pos_order_id', 'picking_type_id', 'group_id', 'carrier_id', 'backorder_id', 'create_uid', 'write_uid', mode='before')
    @classmethod
    def validate_many2one_fields(cls, v):
        """Convertir False d'Odoo en None pour les champs many2one"""
        return None if v is False else v
    
    @field_validator('origin', 'picking_type_code', 'scheduled_date', 'date_done', 'products_availability', 'products_availability_state', 'note', 'priority', 'date', 'date_deadline', 'move_type', 'carrier_tracking_ref', 'create_date', 'write_date', mode='before')
    @classmethod
    def validate_string_fields(cls, v):
        """Convertir False d'Odoo en None pour les champs string"""
        return None if v is False else v
    
    @field_validator('move_ids', mode='before')
    @classmethod
    def validate_move_ids(cls, v):
        """Convertir False d'Odoo en liste vide pour move_ids"""
        return [] if v is False else v
    
    @field_validator('weight', 'carrier_price', mode='before')
    @classmethod
    def validate_float_fields(cls, v):
        """Convertir False d'Odoo en None pour les champs float"""
        return None if v is False else v
    
    @field_validator('number_of_packages', mode='before')
    @classmethod
    def validate_int_fields(cls, v):
        """Convertir False d'Odoo en None pour les champs int"""
        return None if v is False else v

class StockPickingStateUpdateRequest(BaseModel):
    picking_ids: List[int] = Field(..., description="IDs des transferts à mettre à jour", min_items=1)
    action: str = Field(..., description="Action à effectuer", pattern="^(confirm|assign|done|cancel)$")
    force: bool = Field(False, description="Forcer l'action même si les conditions ne sont pas remplies")

class StockPickingListRequest(BaseModel):
    pos_id: Optional[int] = Field(None, description="Filtrer par point de vente")
    state: Optional[str] = Field(None, description="Filtrer par état (draft/waiting/ready/done/cancel)")
    picking_type_code: Optional[str] = Field(None, description="Type d'opération (incoming/outgoing/internal)")
    date_from: Optional[str] = Field(None, description="Date de début (YYYY-MM-DD)")
    date_to: Optional[str] = Field(None, description="Date de fin (YYYY-MM-DD)")
    partner_id: Optional[int] = Field(None, description="Filtrer par partenaire")
    limit: Optional[int] = Field(50, description="Nombre maximum de résultats", ge=1, le=500)
