# Gestion Administrative des Points de Vente (PDV)

## 🎯 Objectif

Endpoints pour créer et gérer les points de vente (PDV) et leurs affectations d'employés.

## 📋 Nouveaux Endpoints

### 1. 🏪 **Création d'un PDV**

```http
POST /pos/create
```

**Body:**
```json
{
  "name": "Station Carburant Nord",
  "company_id": 1,
  "receipt_header": "STATION SERVICE NORD",
  "receipt_footer": "Merci de votre visite !",
  "cash_control": true,
  "module_pos_hr": true,
  "iface_tax_included": "total"
}
```

**Réponse:**
```json
{
  "success": true,
  "data": {
    "pos_id": 15,
    "name": "Station Carburant Nord",
    "company_id": [1, "Ma Société"],
    "active": true,
    "created": true
  },
  "message": "Point de vente 'Station Carburant Nord' créé avec succès"
}
```

### 2. 👥 **Affectation d'employés à un PDV**

```http
POST /pos/{pos_id}/assign-employees
```

**Body:**
```json
{
  "employee_ids": [1183, 1184, 1185],
  "access_level": "basic",
  "replace": false
}
```

**Niveaux d'accès:**
- **`basic`** : Employé standard (peut utiliser le PDV)
- **`advanced`** : Manager/gérant (peut fermer sessions, etc.)

**Modes d'affectation:**
- **`replace: true`** : Remplace toutes les affectations existantes
- **`replace: false`** : Ajoute aux affectations existantes

**Réponse:**
```json
{
  "success": true,
  "data": {
    "pos_id": 15,
    "pos_name": "Station Carburant Nord",
    "access_level": "basic",
    "employees_assigned": [
      {"id": 1183, "name": "Dossi Sylvie LEGBA"},
      {"id": 1184, "name": "Jean MARTIN"},
      {"id": 1185, "name": "Marie DUBOIS"}
    ],
    "total_employees": 5,
    "action": "added"
  },
  "message": "3 employé(s) affecté(s) au PDV 'Station Carburant Nord' avec accès basic"
}
```

### 3. 📋 **Consultation de configuration PDV**

```http
GET /pos/{pos_id}/config
```

**Réponse:**
```json
{
  "success": true,
  "data": {
    "id": 15,
    "name": "Station Carburant Nord",
    "company_id": [1, "Ma Société"],
    "active": true,
    "current_session_id": null,
    "current_session_state": null,
    "employees": {
      "basic": [
        {
          "id": 1183,
          "name": "Dossi Sylvie LEGBA",
          "job": "Employé de Station"
        }
      ],
      "advanced": [
        {
          "id": 1184,
          "name": "Jean MARTIN",
          "job": "Gérant de Station"
        }
      ],
      "total": 2
    },
    "configuration": {
      "cash_control": true,
      "module_pos_hr": true,
      "receipt_header": "STATION SERVICE NORD",
      "receipt_footer": "Merci de votre visite !",
      "journal_id": [5, "Journal Caisse"],
      "currency_id": [1, "EUR"],
      "pricelist_id": [1, "Prix Public"]
    }
  },
  "message": "Configuration du PDV 'Station Carburant Nord' récupérée"
}
```

## 🔧 Schémas de données

### PosCreateRequest
```python
class PosCreateRequest(BaseModel):
    name: str                           # Obligatoire
    company_id: Optional[int] = None    # Auto-détecté si omis
    picking_type_id: Optional[int] = None
    journal_id: Optional[int] = None
    currency_id: Optional[int] = None
    pricelist_id: Optional[int] = None
    receipt_header: Optional[str] = None
    receipt_footer: Optional[str] = None
    iface_tax_included: Optional[str] = "total"
    cash_control: Optional[bool] = True
    module_pos_hr: Optional[bool] = True
```

### PosEmployeeAssignmentRequest
```python
class PosEmployeeAssignmentRequest(BaseModel):
    employee_ids: List[int]     # IDs des employés
    access_level: str           # "basic" ou "advanced"
    replace: bool = False       # Remplacer ou ajouter
```

## 🛡️ Sécurité et Validations

### Validations automatiques
- ✅ **Nom unique** : Vérification que le nom PDV n'existe pas
- ✅ **Employés valides** : Vérification que tous les employés existent et sont actifs
- ✅ **Niveau d'accès** : Validation "basic" ou "advanced" uniquement
- ✅ **PDV existant** : Vérification de l'existence du PDV avant affectation

### Gestion d'erreurs
- **400** : Données invalides (nom existant, employés introuvables)
- **404** : PDV non trouvé
- **403** : Permissions insuffisantes
- **500** : Erreur serveur/Odoo

## 📊 Cas d'usage

### 1. **Création d'une nouvelle station**
```bash
# 1. Créer le PDV
curl -X POST "/pos/create" \
  -d '{"name": "Station Route 66", "receipt_header": "STATION ROUTE 66"}'

# 2. Affecter des employés standards
curl -X POST "/pos/15/assign-employees" \
  -d '{"employee_ids": [1183, 1184], "access_level": "basic", "replace": false}'

# 3. Affecter un gérant
curl -X POST "/pos/15/assign-employees" \
  -d '{"employee_ids": [1185], "access_level": "advanced", "replace": false}'
```

### 2. **Réorganisation des équipes**
```bash
# Remplacer tous les employés basiques
curl -X POST "/pos/15/assign-employees" \
  -d '{"employee_ids": [1186, 1187], "access_level": "basic", "replace": true}'
```

### 3. **Audit des configurations**
```bash
# Vérifier la configuration actuelle
curl -X GET "/pos/15/config"
```

## 🔗 Intégration avec le workflow existant

Ces endpoints s'intègrent parfaitement avec :

1. **`/pos/available`** : Les PDV créés apparaîtront automatiquement pour les employés affectés
2. **Authentification PIN** : Les employés affectés pourront se connecter
3. **Gestion des sessions** : Les PDV créés supportent toutes les fonctionnalités de session
4. **Gestion des pompes** : Compatible avec le système de pompes SQLite

## 🧪 Tests

Exécuter le script de test :
```bash
python test_pos_management.py
```

**Tests inclus :**
1. ✅ Création de PDV avec configuration personnalisée
2. ✅ Affectation d'employés avec niveaux d'accès
3. ✅ Consultation de configuration détaillée
4. ✅ Gestion d'erreurs et validations
5. ✅ Intégration avec employés existants

## 📝 Notes importantes

1. **Champs automatiques** : Si `company_id` ou `picking_type_id` ne sont pas fournis, le système essaie de les détecter automatiquement
2. **Unicité** : Le nom du PDV doit être unique dans Odoo
3. **Employés actifs** : Seuls les employés actifs peuvent être affectés
4. **Permissions** : Les employés affectés peuvent immédiatement utiliser `/pos/available`
5. **Audit** : Toutes les opérations sont loggées pour traçabilité

Ces endpoints permettent une gestion complète du cycle de vie des PDV ! 🚀
