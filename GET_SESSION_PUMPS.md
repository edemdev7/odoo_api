# 🔧 Récupération des Pompes d'une Session POS

## 📋 Vue d'ensemble

Cette route permet de récupérer toutes les pompes associées à une session POS, avec leurs index actuels et informations de vente.

## 🚀 Endpoint

```
GET /pos/{pos_id}/session/{session_id}/pumps
```

## 🔐 Authentification

**Requise** : Token JWT avec scope `pos`

```bash
Authorization: Bearer <votre_token>
```

## 📥 Paramètres

### Path Parameters

| Paramètre | Type | Obligatoire | Description |
|-----------|------|-------------|-------------|
| `pos_id` | integer | ✅ Oui | ID du point de vente |
| `session_id` | integer | ✅ Oui | ID de la session POS |

### Query Parameters

Aucun

## 📤 Réponse

### Success (200 OK)

```json
{
  "success": true,
  "data": [
    {
      "id": "pump_001",
      "name": "J1_E1",
      "stationId": "station_001",
      "type": "PETROL",
      "start_index": 1234.56,
      "current_index": 2345.67,
      "quantity_available": 1111.11,
      "available": true,
      "product_id": 42,
      "product_name": "Essence Super",
      "raw_data": {
        "id": "pump_001",
        "name": "J1_E1",
        "stationId": "station_001",
        "type": "PETROL",
        "start_index": 1234.56,
        "created_at": "2026-02-23T10:00:00"
      }
    },
    {
      "id": "pump_002",
      "name": "J1_E2",
      "stationId": "station_001",
      "type": "DIESEL",
      "start_index": 5678.90,
      "current_index": 6789.12,
      "quantity_available": 1110.22,
      "available": true,
      "product_id": 43,
      "product_name": "Gasoil",
      "raw_data": {
        "id": "pump_002",
        "name": "J1_E2",
        "stationId": "station_001",
        "type": "DIESEL",
        "start_index": 5678.90,
        "created_at": "2026-02-23T10:00:00"
      }
    }
  ],
  "count": 2,
  "message": "2 pompes disponibles"
}
```

### Structure des données d'une pompe

| Champ | Type | Description |
|-------|------|-------------|
| `id` | string | Identifiant unique de la pompe |
| `name` | string | Nom de la pompe (ex: J1_E1) |
| `stationId` | string | ID de la station-service |
| `type` | string | Type de carburant (PETROL, DIESEL, etc.) |
| `start_index` | float | Index de départ lors de l'ouverture de session (en litres) |
| `current_index` | float | Index actuel après les ventes (en litres) |
| `quantity_available` | float | Quantité vendue = current_index - start_index (en litres) |
| `available` | boolean | Pompe disponible pour vente (toujours true) |
| `product_id` | integer | ID du produit dans Odoo |
| `product_name` | string | Nom du produit |
| `raw_data` | object | Données brutes complètes de la pompe |

### Aucune pompe (200 OK)

```json
{
  "success": true,
  "data": [],
  "count": 0,
  "message": "Aucune pompe configurée pour cette session"
}
```

### Erreurs

#### 404 - Session non trouvée
```json
{
  "detail": "Session non trouvée pour ce point de vente"
}
```

#### 401 - Non authentifié
```json
{
  "detail": "Not authenticated"
}
```

#### 500 - Erreur serveur
```json
{
  "detail": "Erreur lors de la récupération des pompes: <message>"
}
```

## 💡 Cas d'utilisation

### 1. Afficher les pompes disponibles pour une vente

```javascript
// Récupérer les pompes de la session active
const response = await fetch(
  `${API_BASE_URL}/pos/${posId}/session/${sessionId}/pumps`,
  {
    headers: {
      'Authorization': `Bearer ${token}`
    }
  }
);

const result = await response.json();

if (result.success) {
  const pumps = result.data;
  
  // Afficher dans l'interface
  pumps.forEach(pump => {
    console.log(`${pump.name}: ${pump.quantity_available}L vendus`);
  });
}
```

### 2. Vérifier l'état d'une pompe spécifique

```javascript
const pumps = result.data;
const pump001 = pumps.find(p => p.id === 'pump_001');

if (pump001) {
  console.log(`Pompe ${pump001.name}:`);
  console.log(`  - Index départ: ${pump001.start_index}L`);
  console.log(`  - Index actuel: ${pump001.current_index}L`);
  console.log(`  - Quantité vendue: ${pump001.quantity_available}L`);
}
```

### 3. Calculer les ventes totales par type de carburant

```javascript
const pumpsByFuelType = {};

result.data.forEach(pump => {
  if (!pumpsByFuelType[pump.type]) {
    pumpsByFuelType[pump.type] = {
      count: 0,
      totalSold: 0
    };
  }
  
  pumpsByFuelType[pump.type].count++;
  pumpsByFuelType[pump.type].totalSold += pump.quantity_available;
});

// Résultat:
// {
//   "PETROL": { count: 3, totalSold: 5234.56 },
//   "DIESEL": { count: 2, totalSold: 3456.78 }
// }
```

### 4. Workflow complet

```python
import requests

# 1. Authentification
token = login()

headers = {"Authorization": f"Bearer {token}"}
pos_id = 1

# 2. Récupérer la session active
session_response = requests.get(
    f"{API_BASE_URL}/pos/{pos_id}/session-status",
    headers=headers
)
session_id = session_response.json()['session_id']

# 3. Récupérer les pompes de la session
pumps_response = requests.get(
    f"{API_BASE_URL}/pos/{pos_id}/session/{session_id}/pumps",
    headers=headers
)

pumps = pumps_response.json()['data']

# 4. Utiliser les données
for pump in pumps:
    print(f"{pump['name']}: {pump['current_index']}L")
```

## 🔍 Détails techniques

### Stockage des données

Les pompes sont stockées dans une base SQLite locale (`pump_data.db`) via le `PumpManager` :

```python
# Table pump_sessions
CREATE TABLE pump_sessions (
    session_id INTEGER NOT NULL,
    pump_external_id TEXT NOT NULL,
    pump_name TEXT NOT NULL,
    station_id TEXT,
    fuel_type TEXT,
    product_id INTEGER,
    product_name TEXT,
    start_index REAL NOT NULL,
    current_index REAL NOT NULL,
    pump_data TEXT NOT NULL,
    created_at TIMESTAMP,
    updated_at TIMESTAMP,
    UNIQUE(session_id, pump_external_id)
)
```

### Mise à jour des index

Les index (`current_index`) sont mis à jour :
- ✅ Lors de chaque vente via `/pos/{pos_id}/sales`
- ✅ Lors de la fermeture de session via `/pos/{pos_id}/close-session`
- ✅ Manuellement via `/pos/{pos_id}/session/{session_id}/pump-indexes`

### Validation de la session

La route vérifie que :
1. La session existe dans Odoo
2. La session appartient bien au POS spécifié
3. Les pompes ont été enregistrées lors de l'ouverture

## 🧪 Tests

### Script de test fourni

```bash
python test_get_session_pumps.py
```

Le script teste :
- ✅ Récupération des pompes par session_id
- ✅ Affichage détaillé de chaque pompe
- ✅ Récupération via le statut de session active
- ✅ Gestion des erreurs

### Test manuel avec cURL

```bash
# 1. Authentification
TOKEN=$(curl -X POST http://localhost:8002/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"user","password":"pass"}' \
  | jq -r '.access_token')

# 2. Récupérer les pompes
curl -X GET "http://localhost:8002/pos/1/session/123/pumps" \
  -H "Authorization: Bearer $TOKEN" \
  | jq '.'
```

### Test avec Python requests

```python
import requests

# Authentification
response = requests.post(
    "http://localhost:8002/auth/login",
    json={"username": "user", "password": "pass"}
)
token = response.json()["access_token"]

# Récupérer les pompes
response = requests.get(
    "http://localhost:8002/pos/1/session/123/pumps",
    headers={"Authorization": f"Bearer {token}"}
)

pumps = response.json()["data"]
print(f"Nombre de pompes: {len(pumps)}")
```

## 📊 Comparaison avec d'autres routes

### Routes liées aux pompes

| Route | Méthode | Description |
|-------|---------|-------------|
| `/pos/{pos_id}/session/{session_id}/pumps` | GET | **Toutes les pompes** avec index actuels |
| `/pos/{pos_id}/session/{session_id}/pumps/available` | GET | **Pompes disponibles** (quantité > seuil) |
| `/pos/{pos_id}/session/{session_id}/pump-indexes` | PUT | **Mettre à jour** les index manuellement |
| `/pos/{pos_id}/session/{session_id}/sales-summary` | GET | **Résumé des ventes** par pompe |

### Quand utiliser cette route ?

✅ **Utiliser `/pumps`** quand vous voulez :
- Afficher toutes les pompes configurées
- Voir l'état complet de chaque pompe
- Calculer les totaux de vente
- Vérifier les index avant fermeture

✅ **Utiliser `/pumps/available`** quand vous voulez :
- Sélectionner une pompe pour une vente
- Filtrer les pompes avec stock disponible
- Interface de sélection de pompe

✅ **Utiliser `/sales-summary`** quand vous voulez :
- Rapport détaillé des ventes
- Statistiques par produit/pompe
- Validation avant fermeture

## ⚠️ Points importants

1. **Les pompes sont enregistrées à l'ouverture** : Si la session n'a pas été ouverte avec des pompes via `/open-session`, cette route retournera une liste vide.

2. **Index actuels** : Le `current_index` est mis à jour automatiquement lors des ventes.

3. **Persistance** : Les données sont stockées localement dans SQLite, pas dans Odoo directement.

4. **Validation POS** : La route vérifie que la session appartient au POS spécifié.

5. **Sécurité** : Authentification JWT requise avec scope `pos`.

## 🚀 Exemple d'intégration complète

```python
#!/usr/bin/env python3
"""
Exemple d'intégration complète: Affichage des pompes d'une session
"""
import requests
import json

API_BASE_URL = "http://localhost:8002"

def get_token(username, password):
    """Authentification"""
    response = requests.post(
        f"{API_BASE_URL}/auth/login",
        json={"username": username, "password": password}
    )
    return response.json()["access_token"]

def get_active_session(token, pos_id):
    """Récupérer la session active"""
    response = requests.get(
        f"{API_BASE_URL}/pos/{pos_id}/session-status",
        headers={"Authorization": f"Bearer {token}"}
    )
    data = response.json()
    return data['session_id'] if data['has_active_session'] else None

def get_session_pumps(token, pos_id, session_id):
    """Récupérer les pompes d'une session"""
    response = requests.get(
        f"{API_BASE_URL}/pos/{pos_id}/session/{session_id}/pumps",
        headers={"Authorization": f"Bearer {token}"}
    )
    return response.json()

def main():
    # Configuration
    USERNAME = "user"
    PASSWORD = "password"
    POS_ID = 1
    
    # 1. Authentification
    print("🔐 Authentification...")
    token = get_token(USERNAME, PASSWORD)
    print("✅ Token obtenu")
    
    # 2. Récupérer la session active
    print(f"\n📋 Recherche de session active pour POS {POS_ID}...")
    session_id = get_active_session(token, POS_ID)
    
    if not session_id:
        print("❌ Aucune session active")
        return
    
    print(f"✅ Session active: {session_id}")
    
    # 3. Récupérer les pompes
    print(f"\n⛽ Récupération des pompes...")
    result = get_session_pumps(token, POS_ID, session_id)
    
    if not result['success']:
        print("❌ Erreur lors de la récupération")
        return
    
    pumps = result['data']
    print(f"✅ {result['count']} pompe(s) trouvée(s)\n")
    
    # 4. Afficher les détails
    print("=" * 60)
    total_sold = 0
    
    for i, pump in enumerate(pumps, 1):
        print(f"\n🔹 Pompe #{i}: {pump['name']}")
        print(f"   Type: {pump['type']}")
        print(f"   Produit: {pump['product_name']}")
        print(f"   Index départ: {pump['start_index']:.2f} L")
        print(f"   Index actuel: {pump['current_index']:.2f} L")
        print(f"   Quantité vendue: {pump['quantity_available']:.2f} L")
        
        total_sold += pump['quantity_available']
    
    print("\n" + "=" * 60)
    print(f"\n📊 TOTAL VENDU: {total_sold:.2f} L")
    print("=" * 60)

if __name__ == "__main__":
    main()
```

## 📚 Voir aussi

- [Documentation ouverture de session](./ENDPOINT_UNIFIE_OUVERTURE.md)
- [Documentation fermeture de session](./CLOSE_SESSION_UNIFIED.md)
- [Documentation gestion des pompes](./FUEL_MONITOR_README.md)
