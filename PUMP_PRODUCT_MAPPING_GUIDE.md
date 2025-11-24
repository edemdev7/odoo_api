# Guide: Association Produits Odoo aux Pompes

## 📋 Problème résolu

Lorsqu'une vente est créée sur l'application :
- ✅ La vente est enregistrée dans Odoo
- ✅ Le moyen de paiement est enregistré
- ❌ **Le dé-stockage ne fonctionnait pas** car le produit n'était pas correctement identifié

## 🔧 Solutions implémentées

### 1. Validation du product_id lors de la création de vente

**Fichier:** `api/pos.py` - Endpoint `POST /pos/{pos_id}/create-order`

Maintenant, lors de chaque création de commande :
1. ✅ Le `product_id` est **validé** contre la base Odoo
2. ✅ On vérifie que le produit **existe et est actif**
3. ✅ Les logs détaillés sont enregistrés pour le debugging
4. ❌ Si le produit n'existe pas → erreur claire avec message explicite

**Logs générés:**
```
✅ Produit validé: ID=123, Nom=Essence SP95, Type=product
  → Pompe ID: 5
  → Index début: 1000.5
  → Index fin: 1025.3
  → Quantité: 24.8, Prix unitaire: 850, Total: 21080.0
```

### 2. Ajout de product_id dans pump_manager

**Fichier:** `core/pump_manager.py`

La base de données SQLite `pump_sessions` a été enrichie :
```sql
CREATE TABLE pump_sessions (
    ...
    product_id INTEGER,      -- ✨ NOUVEAU: ID du produit Odoo
    product_name TEXT,       -- ✨ NOUVEAU: Nom du produit
    ...
)
```

**Migration automatique:** Si vous avez une base existante, les colonnes seront ajoutées automatiquement au démarrage.

### 3. Schéma de données enrichi

**Fichier:** `models/schemas.py` - Classe `StationPumpData`

```python
class StationPumpData(BaseModel):
    id: str
    name: str
    stationId: str
    type: str
    start_index: float
    product_id: Optional[int]     # ✨ NOUVEAU
    product_name: Optional[str]   # ✨ NOUVEAU
```

### 4. Endpoint pour lister les produits disponibles

**Nouveau endpoint:** `GET /pos/products/fuel`

Permet de récupérer tous les produits disponibles pour associer aux pompes.

**Exemple de réponse:**
```json
{
  "success": true,
  "data": {
    "products": [
      {
        "id": 123,
        "name": "Essence SP95",
        "code": "ESP95",
        "barcode": "1234567890",
        "price": 850.0,
        "cost": 750.0,
        "category": "Carburants",
        "category_id": 10,
        "unit": "Litre",
        "unit_id": 2,
        "type": "product",
        "stock_quantity": 5000.0
      },
      {
        "id": 124,
        "name": "Gasoil",
        "code": "GASOIL",
        "price": 780.0,
        ...
      }
    ]
  },
  "count": 2,
  "message": "2 produit(s) disponible(s)"
}
```

## 📱 Utilisation côté Application

### Étape 1: Configuration des pompes (une fois)

Lors de la création/configuration d'une pompe dans l'admin :

1. **Appeler** `GET /pos/products/fuel` pour obtenir la liste des produits Odoo
2. **Afficher** un sélecteur avec les produits disponibles
3. **Associer** le produit à la pompe
4. **Envoyer** lors de l'ouverture de session :

```json
{
  "session_id": 456,
  "pump_indexes": [
    {
      "id": "pump_1",
      "name": "J1_E1",
      "stationId": "STATION_MAIN",
      "type": "PETROL",
      "start_index": 1000.5,
      "product_id": 123,           // ✨ ID du produit Odoo
      "product_name": "Essence SP95" // ✨ Nom du produit
    }
  ]
}
```

### Étape 2: Création de vente

Lors d'une vente sur une pompe :

```json
{
  "pos_session_id": 456,
  "lines": [
    {
      "product_id": 123,           // ✨ ID du produit Odoo (récupéré de la pompe)
      "pump_id": 1,
      "qty": 24.8,
      "price_unit": 850.0,
      "start_pump_index": 1000.5,
      "end_pump_index": 1025.3
    }
  ],
  "payment_method_id": 1,
  "amount_paid": 21080.0
}
```

**Résultat attendu:**
1. ✅ Validation du product_id
2. ✅ Création de la commande POS
3. ✅ Enregistrement du paiement
4. ✅ **Dé-stockage automatique** du produit dans Odoo

## 🧪 Tests

### Test 1: Lister les produits disponibles

```bash
curl -X 'GET' \
  'http://127.0.0.1:8002/pos/products/fuel' \
  -H 'Authorization: Bearer YOUR_TOKEN'
```

### Test 2: Créer une vente avec validation

```bash
curl -X 'POST' \
  'http://127.0.0.1:8002/pos/123/create-order' \
  -H 'Authorization: Bearer YOUR_TOKEN' \
  -H 'Content-Type: application/json' \
  -d '{
    "pos_session_id": 456,
    "lines": [{
      "product_id": 123,
      "qty": 10,
      "price_unit": 850
    }],
    "payment_method_id": 1,
    "amount_paid": 8500
  }'
```

**Succès:** Commande créée, stock déduit
**Échec:** Message d'erreur clair si product_id invalide

## ⚠️ Points d'attention

1. **Migration des pompes existantes:**
   - Les pompes sans `product_id` continueront de fonctionner
   - Mais il faudra les mettre à jour pour activer le dé-stockage

2. **Validation stricte:**
   - Le `product_id` est maintenant **obligatoire** et **validé**
   - Les ventes avec un product_id inexistant seront **rejetées**

3. **Logs détaillés:**
   - Chaque vente génère des logs pour faciliter le debugging
   - Vérifiez les logs si le dé-stockage ne fonctionne pas

## 📊 Flux complet

```
┌─────────────────┐
│  Configuration  │
│   des pompes    │ → GET /pos/products/fuel
└────────┬────────┘   (Liste des produits Odoo)
         │
         ↓
┌─────────────────┐
│ Association     │
│ Produit → Pompe │ → Stocké dans pump_sessions
└────────┬────────┘   (product_id, product_name)
         │
         ↓
┌─────────────────┐
│ Ouverture       │
│ de session      │ → POST /pos/{pos_id}/open
└────────┬────────┘   (Pump data avec product_id)
         │
         ↓
┌─────────────────┐
│  Vente POS      │ → POST /pos/{pos_id}/create-order
│  avec pompe     │   (product_id validé)
└────────┬────────┘
         │
         ├─→ Validation product_id existe
         ├─→ Création pos.order
         ├─→ Enregistrement paiement
         └─→ ✅ Dé-stockage automatique
```

## 🎯 Résultat final

✅ Le dé-stockage fonctionne automatiquement
✅ Les erreurs sont détectées immédiatement
✅ Les logs permettent de tracer chaque opération
✅ L'association produit/pompe est persistante

---

**Date de mise à jour:** 24 novembre 2025
**Version:** 1.0
