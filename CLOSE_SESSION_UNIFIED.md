# Endpoint de Fermeture de Session POS - Payload Unifié

## 📋 Vue d'ensemble

L'endpoint `/pos/{pos_id}/close-session` a été mis à jour pour accepter un **payload unifié** identique à celui utilisé lors de l'ouverture de session, facilitant ainsi l'intégration et la cohérence des données.

## 🔄 Changements apportés

### 1. Modèle `PosCloseSessionRequest` mis à jour

**Nouveaux champs ajoutés:**
- `session_id` : ID de la session à fermer (optionnel si détection automatique)
- `starting_balance` : Solde d'ouverture pour vérification de cohérence
- `pump_indexes` : Format unifié avec `StationPumpData` (remplace `pump_end_indexes`)

**Anciens champs conservés (rétrocompatibilité):**
- `ending_balance` : Solde de fermeture
- `closing_notes` : Notes de fermeture
- `pump_end_indexes` : Format obsolète (toujours supporté)

### 2. Structure du payload

```python
class PosCloseSessionRequest(BaseModel):
    session_id: Optional[int]                      # NOUVEAU
    starting_balance: Optional[float]              # NOUVEAU
    ending_balance: Optional[float]
    closing_notes: Optional[str]
    pump_indexes: Optional[List[StationPumpData]]  # NOUVEAU (format unifié)
    pump_end_indexes: Optional[List[Dict]]         # OBSOLÈTE (rétrocompat.)
```

## 📝 Exemples d'utilisation

### Mode Station-Service (avec pompes)

```json
POST /pos/1/close-session
{
  "session_id": 123,
  "starting_balance": 1000.00,
  "ending_balance": 5432.10,
  "pump_indexes": [
    {
      "id": "pump_001",
      "name": "J1_E1", 
      "stationId": "station_001",
      "type": "PETROL",
      "start_index": 1234.56,
      "end_index": 2345.67
    },
    {
      "id": "pump_002",
      "name": "J1_E2",
      "stationId": "station_001",
      "type": "DIESEL",
      "start_index": 5678.90,
      "end_index": 6789.12
    }
  ],
  "closing_notes": "Fermeture normale"
}
```

### Mode Standard (caisse normale)

```json
POST /pos/1/close-session
{
  "starting_balance": 500.00,
  "ending_balance": 1234.56,
  "closing_notes": "Fermeture caisse"
}
```

## ✨ Fonctionnalités

### 1. Vérification de cohérence

Si `starting_balance` est fourni, le système compare avec le solde enregistré dans Odoo lors de l'ouverture :

```python
# Log warning si incohérence détectée (mais ne bloque pas la fermeture)
if abs(request.starting_balance - odoo_starting_balance) > 0.01:
    logger.warning(f"Incohérence solde d'ouverture: Reçu={request.starting_balance}, Odoo={odoo_starting_balance}")
```

### 2. Support dual format pompes

Le système supporte à la fois le nouveau format (`pump_indexes`) et l'ancien (`pump_end_indexes`) :

```python
pump_data_list = request.pump_indexes if request.pump_indexes else request.pump_end_indexes
```

### 3. Validation automatique des pompes

Pour les stations-service :
- Mise à jour des index finaux de chaque pompe
- Validation de la cohérence index vs ventes
- Tolérance de 1% ou 1L pour les différences
- Rapport de validation détaillé

### 4. Enregistrement des notes

Les notes de fermeture sont maintenant enregistrées dans Odoo :

```python
if request.closing_notes:
    closing_data['note_closing'] = request.closing_notes
```

## 📊 Réponse API

```json
{
  "session_id": 123,
  "pos_id": 1,
  "pos_name": "Station 001",
  "is_station": true,
  "state": "closed",
  "message": "Session fermée avec succès - Mode station-service - 2 pompe(s) validée(s) - Solde final: 5432.10 FCFA",
  "validation_summary": {
    "total_pumps": 2,
    "valid_pumps": 2,
    "total_sales": 25000.50
  }
}
```

## 🔍 Détails techniques

### Logique de détection du mode

```python
# Nouveau format prioritaire
pump_data_list = request.pump_indexes if request.pump_indexes else request.pump_end_indexes

# Mode station si des pompes sont présentes
is_station_mode = pump_data_list is not None and len(pump_data_list) > 0
```

### Traitement des pompes

```python
for pump_data in pump_data_list:
    # Support des deux formats
    if isinstance(pump_data, dict):
        pump_id = pump_data.get('pump_id') or pump_data.get('id')
        end_index = pump_data.get('end_index') or pump_data.get('current_index')
    else:
        # Format StationPumpData
        pump_id = pump_data.id
        end_index = getattr(pump_data, 'end_index', None) or getattr(pump_data, 'current_index', None)
```

### Données écrites dans Odoo

```python
closing_data = {
    'state': 'closing_control',
    'cash_register_balance_end_real': request.ending_balance,  # Si fourni
    'note_closing': request.closing_notes  # Si fourni
}
```

## 🧪 Tests

Utilisez le script de test fourni :

```bash
python test_close_session_unified.py
```

Le script teste :
1. ✅ Fermeture station-service avec payload unifié complet
2. ✅ Fermeture standard sans pompes
3. ✅ Vérification de cohérence des soldes
4. ✅ Validation des pompes

## 🔒 Sécurité

- **Authentification requise** : Token JWT avec scope `pos`
- **Autorisation** : Seuls les gérants peuvent fermer une session
- **Validation** : Vérification de l'état de la session avant fermeture

## 📌 Points importants

1. **Rétrocompatibilité** : L'ancien format `pump_end_indexes` continue de fonctionner
2. **Optionalité** : Tous les champs sont optionnels sauf l'authentification
3. **Cohérence** : Le format est maintenant identique entre ouverture et fermeture
4. **Validation non bloquante** : L'incohérence du solde d'ouverture génère un warning mais ne bloque pas
5. **Notes persistées** : Les notes de fermeture sont maintenant enregistrées dans Odoo

## 🚀 Migration

### Avant (ancien format)
```json
{
  "ending_balance": 5432.10,
  "pump_end_indexes": [
    {"pump_id": "pump_001", "end_index": 2345.67}
  ]
}
```

### Après (nouveau format unifié)
```json
{
  "session_id": 123,
  "starting_balance": 1000.00,
  "ending_balance": 5432.10,
  "pump_indexes": [
    {
      "id": "pump_001",
      "name": "J1_E1",
      "stationId": "station_001",
      "type": "PETROL",
      "start_index": 1234.56,
      "end_index": 2345.67
    }
  ],
  "closing_notes": "Fermeture normale"
}
```

## 📚 Fichiers modifiés

1. **`models/schemas.py`** : Modèle `PosCloseSessionRequest` enrichi
2. **`api/pos.py`** : Endpoint `close_pos_session` mis à jour
3. **`test_close_session_unified.py`** : Nouveau script de test

## ✅ Avantages

1. **Cohérence** : Même structure de données ouverture/fermeture
2. **Traçabilité** : Solde d'ouverture inclus pour vérification
3. **Complétude** : Toutes les informations de session disponibles
4. **Flexibilité** : Support de l'ancien et du nouveau format
5. **Intégration facile** : Moins de transformations côté client
