# Test: Récupération des Transferts avec Détails des Localisations

## Description
L'endpoint `/pos/{pos_id}/inventory/transfers` a été enrichi pour afficher automatiquement les **détails complets des deux parties** (source et destination) de chaque transfert.

## Champs Ajoutés

Chaque transfert retourné contient maintenant:

### `location_source_details`
Détails complets de la localisation **source** (d'où ça quitte):
```json
{
  "id": 12,
  "name": "Entrepôt/Stock",
  "complete_name": "MY_WH/Stock/Entrepôt",
  "usage": "internal",
  "active": true,
  "warehouse_id": [1, "WH"],
  "company_id": [1, "JNP"],
  "partner_id": false,
  "barcode": "WH-STOCK-12",
  "comment": "Stock principal",
  "scrap_location": false
}
```

### `location_destination_details`
Détails complets de la localisation **destination** (où ça va):
```json
{
  "id": 45,
  "name": "Chambre Froide",
  "complete_name": "MY_WH/Stock/Chambre Froide",
  "usage": "internal",
  "active": true,
  "warehouse_id": [1, "WH"],
  "company_id": [1, "JNP"],
  "partner_id": false,
  "barcode": "WH-CF-45",
  "comment": "Stockage froid",
  "scrap_location": false
}
```

## Exemple d'Appel

```bash
curl -X GET 'http://localhost:8001/api/pos/1/inventory/transfers?page=1&page_size=10' \
  -H 'Authorization: Bearer YOUR_JWT_TOKEN'
```

## Structure de Réponse

Chaque transfert dans `data.transfers` contiendra:

```json
{
  "id": 123,
  "name": "PICK/001",
  "state": "done",
  "picking_type_code": "internal",
  "location_id": [12, "Entrepôt/Stock"],
  "location_dest_id": [45, "Chambre Froide"],
  
  // ✅ NOUVEAU: Détails complets des deux parties
  "location_source_details": {
    "id": 12,
    "name": "Entrepôt/Stock",
    "complete_name": "MY_WH/Stock/Entrepôt",
    "usage": "internal",
    "warehouse_id": [1, "WH"],
    "company_id": [1, "JNP"],
    "partner_id": false,
    "active": true
  },
  "location_destination_details": {
    "id": 45,
    "name": "Chambre Froide",
    "complete_name": "MY_WH/Stock/Chambre Froide",
    "usage": "internal",
    "warehouse_id": [1, "WH"],
    "company_id": [1, "JNP"],
    "partner_id": false,
    "active": true
  },
  
  // ... autres champs
}
```

## Cas d'Usage

### 1. Afficher qui envoie et qui reçoit
```javascript
// Frontend JavaScript
const transfer = transfers[0];
console.log(`Transfert depuis: ${transfer.location_source_details.complete_name}`);
console.log(`Vers: ${transfer.location_destination_details.complete_name}`);
// Output:
// Transfert depuis: MY_WH/Stock/Entrepôt
// Vers: MY_WH/Stock/Chambre Froide
```

### 2. Filtrer par type de location (livraisons vs réceptions)
```javascript
// Identifier les transferts avec partenaire (livraisons/réceptions)
const shipments = transfers.filter(t => 
  t.location_destination_details?.partner_id && t.location_destination_details.partner_id[0]
);
```

### 3. Afficher les codes barres des localisations
```javascript
// Barcode scanning
const sourceBarcode = transfer.location_source_details.barcode;
const destBarcode = transfer.location_destination_details.barcode;
```

## Comportement en Cas d'Erreur

Si une erreur survient lors de la récupération des détails de localisation:
- `location_source_details` et `location_destination_details` seront à `null`
- Le transfert sera quand même retourné avec les autres champs disponibles
- Un avertissement sera enregistré dans les logs

## Champs Disponibles par Location

Chaque localisation détaillée contient:
- `id` : Identifiant Odoo
- `name` : Nom court de la localisation
- `complete_name` : Chemin complet (avec hiérarchie)
- `usage` : Type d'usage (internal, customer, supplier, inventory loss, production, transit)
- `active` : Si la localisation est active
- `warehouse_id` : Entrepôt associé
- `company_id` : Société
- `partner_id` : Partenaire (fournisseur/client) si applicable
- `barcode` : Code-barres
- `comment` : Notes additionnelles
- `scrap_location` : Si c'est un endroit pour la casse
- `parent_path` : Chemin de la hiérarchie
- `location_id` : Location parent
- `removal_strategy_id` : Stratégie de prélèvement

## Performance

- Les appels aux `stock.location` sont faits une fois par page de transferts
- Les IDs de localisation sont dédupliqués pour minimiser les requêtes Odoo
- En cas de transferts sans localisation (cas rare), aucun appel supplémentaire n'est fait
