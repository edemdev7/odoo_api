# Architecture Multi-Base de Données Odoo

## Vue d'ensemble

L'API FastAPI supporte désormais **deux instances Odoo distinctes** avec une authentification en cascade et un filtrage automatique des types de transferts selon la base de données.

## Configuration des Bases de Données

### Base de Données 1 : JNP Directe
```python
ODOO_DB1_CONFIG = {
    "name": "JNP Directe",
    "url": "https://sandbox-erp.dagbehamiithiel.com",
    "db": "sandbox.dagbehamiithiel.com",
    "username": "admin@jnpdirecte.com",
    "api_key": "JNP_API_KEY",
    "transfer_type_code": "internal"  # Transferts internes uniquement
}
```

### Base de Données 2 : Franchise
```python
ODOO_DB2_CONFIG = {
    "name": "Franchise",
    "url": "https://sandbox.perfect-erp.com",
    "db": "sandbox",
    "username": "admin@perfecterp.com",
    "api_key": "FRANCHISE_API_KEY",
    "transfer_type_code": "incoming"  # Réceptions uniquement
}
```

## Authentification en Cascade

### Principe
Lors de l'authentification par PIN (`POST /api/auth/pin-login`), le système tente de s'authentifier sur **chaque base de données dans l'ordre** défini :

1. **Essai sur JNP Directe** (`ODOO_DB1_CONFIG`)
   - Recherche de l'employé avec matricule + PIN
   - Si trouvé ✅ → authentification réussie sur cette base
   
2. **Si échec, essai sur Franchise** (`ODOO_DB2_CONFIG`)
   - Recherche de l'employé avec matricule + PIN
   - Si trouvé ✅ → authentification réussie sur cette base
   
3. **Si échec sur les deux bases** ❌
   - Retourne une erreur 401 "Matricule ou PIN incorrect"

### Stockage de la Base Authentifiée

Une fois l'authentification réussie, le **nom de la base de données** est inclus dans le token JWT :

```json
{
  "sub": "employee_123",
  "scopes": ["read", "pos"],
  "employee_id": 123,
  "employee_name": "Jean Dupont",
  "employee_matricule": "EMP001",
  "odoo_db": "JNP Directe",  // ← Nom de la DB authentifiée
  "exp": 1234567890
}
```

## Filtrage Automatique par Type de Transfert

### Comportement Automatique

Lorsqu'un utilisateur appelle l'endpoint `/api/pos/{pos_id}/inventory/transfers`, le système :

1. **Lit le token JWT** pour identifier la base de données authentifiée
2. **Récupère la configuration** de cette base (via `get_odoo_config_from_user()`)
3. **Applique automatiquement le filtre** `picking_type_code` selon la configuration :
   - **JNP Directe** → filtre automatique `picking_type_code = "internal"`
   - **Franchise** → filtre automatique `picking_type_code = "incoming"`

### Exemple de Requête

#### Requête sans filtre explicite
```http
GET /api/pos/1/inventory/transfers
Authorization: Bearer <token_jnp_directe>
```

**Résultat** : Seuls les transferts **internes** sont retournés.

#### Requête avec filtre explicite conforme
```http
GET /api/pos/1/inventory/transfers?picking_type_code=internal
Authorization: Bearer <token_jnp_directe>
```

**Résultat** : Transferts internes retournés ✅

#### Requête avec filtre explicite NON conforme
```http
GET /api/pos/1/inventory/transfers?picking_type_code=incoming
Authorization: Bearer <token_jnp_directe>
```

**Résultat** : Erreur 403
```json
{
  "detail": "Cette base de données ne gère que les transferts de type 'internal'"
}
```

## Flux Technique

### 1. Authentification (`api/auth.py`)

```python
@router.post("/pin-login")
async def pin_login(login_data: PinLogin):
    from core.config import ODOO_DATABASES
    from core.odoo_client import OdooClient
    
    # Cascade sur chaque base
    for db_config in ODOO_DATABASES:
        temp_client = OdooClient(custom_config={
            'url': db_config['url'],
            'db': db_config['db'],
            'username': db_config['username'],
            'api_key': db_config['api_key']
        })
        
        employees = temp_client.execute_kw('hr.employee', 'search_read', [domain])
        
        if employees:
            # Employé trouvé ! Créer le token avec odoo_db
            token_data = {
                ...
                "odoo_db": db_config['name']  # ← Essentiel
            }
            access_token = create_access_token(
                data=token_data,
                odoo_db_name=db_config['name']
            )
            return {"access_token": access_token, ...}
    
    # Aucune base n'a authentifié l'employé
    raise HTTPException(status_code=401, detail="Matricule ou PIN incorrect")
```

### 2. Récupération de la Configuration (`core/security.py`)

```python
def get_odoo_config_from_user(user: dict) -> dict:
    """
    Extrait la configuration Odoo depuis le token JWT de l'utilisateur
    """
    from core.config import ODOO_DATABASES
    
    if not user or 'odoo_db' not in user:
        return None
    
    odoo_db_name = user['odoo_db']
    
    # Chercher la config correspondante
    for db_config in ODOO_DATABASES:
        if db_config['name'] == odoo_db_name:
            return db_config
    
    return None
```

### 3. Création du Client Odoo (`core/odoo_client.py`)

```python
def get_odoo_client(user=None):
    """
    Renvoie le client Odoo configuré pour la bonne base de données
    """
    from core.security import get_odoo_config_from_user
    
    if user:
        db_config = get_odoo_config_from_user(user)
        
        if db_config:
            return OdooClient(custom_config={
                'url': db_config['url'],
                'db': db_config['db'],
                'username': db_config['username'],
                'api_key': db_config['api_key']
            })
    
    # Fallback sur le client par défaut
    return default_odoo_client
```

### 4. Filtrage Automatique des Transferts (`api/pos.py`)

```python
@router.get("/pos/{pos_id}/inventory/transfers")
async def get_pos_inventory_transfers(
    pos_id: int,
    picking_type_code: Optional[str] = None,
    current_user: dict = Depends(require_scope("pos"))
):
    from core.security import get_odoo_config_from_user
    
    # Récupérer la config de la DB authentifiée
    db_config = get_odoo_config_from_user(current_user)
    
    if db_config and 'transfer_type_code' in db_config:
        # Aucun code fourni → utiliser celui de la DB
        if not picking_type_code:
            picking_type_code = db_config['transfer_type_code']
        
        # Code fourni mais ne correspond pas → erreur
        elif picking_type_code != db_config['transfer_type_code']:
            raise HTTPException(
                status_code=403,
                detail=f"Cette base ne gère que les transferts '{db_config['transfer_type_code']}'"
            )
    
    # Ajouter au domaine de recherche
    domain.append(('picking_type_code', '=', picking_type_code))
    
    # Rechercher les transferts...
```

## Avantages de l'Architecture

### ✅ Séparation Claire des Responsabilités
- **JNP Directe** : Gestion des transferts internes entre emplacements
- **Franchise** : Gestion des réceptions de marchandises

### ✅ Sécurité Renforcée
- Un utilisateur ne peut accéder qu'aux données de **sa base authentifiée**
- Impossible de "cross-polluer" les types de transferts entre bases
- Token JWT contient l'identité de la base

### ✅ Simplicité pour le Frontend
- Une seule API endpoint → `/api/auth/pin-login`
- Pas de logique côté client pour choisir la base
- Filtrage automatique, pas besoin de spécifier `picking_type_code`

### ✅ Maintenabilité
- Configuration centralisée dans `core/config.py`
- Facile d'ajouter une 3ème base de données
- Logique de filtrage cohérente dans tout le système

## Types de Transferts Odoo

### `picking_type_code = "internal"`
- Transferts **internes** entre emplacements d'un même entrepôt
- Exemples : déplacement de stock, ajustements d'inventaire
- **Base** : JNP Directe

### `picking_type_code = "incoming"`
- **Réceptions** de marchandises depuis des fournisseurs
- Exemples : bons de livraison, réceptions d'achats
- **Base** : Franchise

### `picking_type_code = "outgoing"`
- **Livraisons** vers les clients
- Exemples : bons de livraison, expéditions
- **Non utilisé** dans cette architecture (pourrait être ajouté)

## Ajout d'une Nouvelle Base de Données

### 1. Ajouter la configuration dans `core/config.py`

```python
ODOO_DB3_CONFIG = {
    "name": "Nouvelle Base",
    "url": "https://nouvelle-base.com",
    "db": "nouvelle_db",
    "username": "admin@nouvelle.com",
    "api_key": "NOUVELLE_API_KEY",
    "transfer_type_code": "outgoing"  # Nouveau type
}

# Ajouter à la liste des bases
ODOO_DATABASES = [
    ODOO_DB1_CONFIG,
    ODOO_DB2_CONFIG,
    ODOO_DB3_CONFIG  # ← Ajouter ici
]
```

### 2. Aucune modification de code nécessaire !

Le système d'authentification en cascade et le filtrage automatique fonctionneront immédiatement.

## Tests de Validation

### Test 1 : Authentification sur JNP Directe
```bash
curl -X POST http://localhost:8000/api/auth/pin-login \
  -H "Content-Type: application/json" \
  -d '{"matricule": "EMP001", "pin": "1234"}'
```

**Résultat attendu** : Token avec `"odoo_db": "JNP Directe"`

### Test 2 : Récupération des transferts internes
```bash
curl -X GET http://localhost:8000/api/pos/1/inventory/transfers \
  -H "Authorization: Bearer <token_jnp>"
```

**Résultat attendu** : Uniquement les transferts `picking_type_code = "internal"`

### Test 3 : Tentative de filtrage sur un autre type
```bash
curl -X GET "http://localhost:8000/api/pos/1/inventory/transfers?picking_type_code=incoming" \
  -H "Authorization: Bearer <token_jnp>"
```

**Résultat attendu** : Erreur 403 avec message explicite

## Logs et Debugging

### Logs d'Authentification
```
INFO: Tentative d'authentification sur JNP Directe (https://sandbox-erp.dagbehamiithiel.com)
INFO: ✅ Employé trouvé sur JNP Directe: Jean Dupont
INFO: Authentification réussie sur JNP Directe: Jean Dupont
```

### Logs de Filtrage
```
INFO: Filtrage automatique par type de transfert de la DB: internal
INFO: Filtrage par picking_type_code: internal
INFO: Recherche transferts avec domaine: [('company_id', '=', 1), ('picking_type_code', '=', 'internal')]
```

## Conclusion

Cette architecture multi-base de données offre :
- ✅ **Flexibilité** : Support natif de plusieurs instances Odoo
- ✅ **Sécurité** : Isolation stricte des données entre bases
- ✅ **Simplicité** : Authentification et filtrage automatiques
- ✅ **Évolutivité** : Facile d'ajouter de nouvelles bases

Le système est prêt pour la production et nécessite uniquement la configuration des clés API dans `core/config.py`.
