# Documentation - Gestion des Produits et Stock

## Vue d'ensemble

Ce module ajoute une gestion complète des produits et du stock au système POS, permettant de :
- ✅ Créer des produits dans Odoo
- ✅ Assigner des produits aux points de vente
- ✅ Gérer les mouvements de stock (entrées/sorties)
- ✅ Consulter les niveaux de stock
- ✅ Effectuer des ajustements d'inventaire

## Endpoints Disponibles

### 1. Création de Produit
**POST** `/pos/products/create`

Crée un nouveau produit dans Odoo avec toutes les informations nécessaires pour le POS.

**Paramètres requis :**
```json
{
  "name": "Nom du produit",
  "list_price": 15.99
}
```

**Paramètres optionnels :**
```json
{
  "default_code": "REF001",
  "barcode": "1234567890",
  "standard_price": 10.50,
  "type": "product",
  "categ_id": 1,
  "uom_id": 1,
  "taxes_id": [1, 2],
  "description": "Description du produit",
  "available_in_pos": true,
  "active": true,
  "sale_ok": true,
  "purchase_ok": true,
  "weight": 0.5,
  "volume": 0.3
}
```

**Réponse :**
```json
{
  "success": true,
  "data": {
    "product_id": 123,
    "name": "Nom du produit",
    "default_code": "REF001",
    "list_price": 15.99,
    "category": [1, "Catégorie"],
    "available_in_pos": true,
    "created": true
  },
  "message": "Produit 'Nom du produit' créé avec succès"
}
```

---

### 2. Affectation de Produits au PDV
**POST** `/pos/{pos_id}/products/assign`

Ajoute ou remplace les produits disponibles dans un point de vente.

**Paramètres :**
```json
{
  "product_ids": [123, 124, 125],
  "replace": false
}
```

- `product_ids` : Liste des IDs de produits à ajouter
- `replace` : `true` pour remplacer tous les produits, `false` pour ajouter

**Réponse :**
```json
{
  "success": true,
  "data": {
    "pos_id": 1,
    "pos_name": "PDV Principal",
    "products_assigned": [
      {"id": 123, "name": "Produit 1"},
      {"id": 124, "name": "Produit 2"}
    ],
    "categories_updated": [1, 2, 3],
    "action": "added"
  },
  "message": "2 produit(s) ajoutés au PDV 'PDV Principal'"
}
```

---

### 3. Mouvement de Stock
**POST** `/pos/{pos_id}/stock/movement`

Crée un mouvement de stock (entrée ou sortie) pour un produit.

**Paramètres :**
```json
{
  "product_id": 123,
  "quantity": 50,
  "reference": "Réapprovisionnement",
  "reason": "Livraison fournisseur",
  "location_id": 8,
  "location_dest_id": 9
}
```

- `quantity` : Quantité positive pour entrée, négative pour sortie
- `location_id` et `location_dest_id` : Optionnels, calculés automatiquement si non fournis

**Réponse :**
```json
{
  "success": true,
  "data": {
    "move_id": 456,
    "product_id": 123,
    "product_name": "Produit Test",
    "quantity": 50,
    "location_src": 8,
    "location_dest": 9,
    "new_stock": 150,
    "reference": "Réapprovisionnement"
  },
  "message": "Mouvement de stock créé: 50 Produit Test"
}
```

---

### 4. Consultation du Stock
**GET** `/pos/{pos_id}/stock/{product_id}`

Récupère le niveau de stock actuel d'un produit pour un PDV.

**Réponse :**
```json
{
  "success": true,
  "data": {
    "product_id": 123,
    "product_name": "Produit Test",
    "product_code": "REF001",
    "current_stock": 150,
    "reserved_stock": 10,
    "available_stock": 140,
    "unit_of_measure": "Unité",
    "location_name": "Stock Principal",
    "last_update": "2024-01-15T10:30:00"
  },
  "message": "Stock de Produit Test: 140 Unité disponible(s)"
}
```

---

### 5. Ajustement de Stock
**POST** `/pos/{pos_id}/stock/{product_id}/adjust`

Ajuste directement le niveau de stock d'un produit à une valeur donnée.

**Paramètres :**
```json
{
  "new_quantity": 200,
  "reason": "Inventaire physique"
}
```

**Réponse :**
```json
{
  "success": true,
  "data": {
    "adjustment": {
      "previous_stock": 150,
      "new_stock": 200,
      "quantity_diff": 50,
      "reason": "Inventaire physique"
    },
    "current_stock_info": {
      "product_id": 123,
      "current_stock": 200,
      "available_stock": 200
    },
    "movement_info": {
      "move_id": 789,
      "reference": "Ajustement stock - Inventaire physique"
    }
  },
  "message": "Stock ajusté: 150 → 200 Unité"
}
```

## Workflow Complet

### 1. Création et Configuration
```bash
# 1. Créer un produit
POST /pos/products/create
{
  "name": "Essence SP95",
  "list_price": 1.65,
  "default_code": "SP95",
  "type": "product",
  "available_in_pos": true
}

# 2. L'assigner à un PDV
POST /pos/1/products/assign
{
  "product_ids": [123],
  "replace": false
}
```

### 2. Gestion du Stock
```bash
# 3. Stock initial
POST /pos/1/stock/movement
{
  "product_id": 123,
  "quantity": 1000,
  "reason": "Stock initial"
}

# 4. Vérifier le stock
GET /pos/1/stock/123

# 5. Réapprovisionnement
POST /pos/1/stock/movement
{
  "product_id": 123,
  "quantity": 500,
  "reason": "Livraison"
}

# 6. Ajustement d'inventaire
POST /pos/1/stock/123/adjust
{
  "new_quantity": 1450,
  "reason": "Inventaire physique"
}
```

## Types de Produits

Le système gère 3 types de produits :

1. **`product`** - Produits stockables
   - Gestion complète du stock
   - Mouvements d'entrée/sortie
   - Réservations

2. **`service`** - Services
   - Stock infini (999999)
   - Pas de gestion physique

3. **`consu`** - Consommables
   - Stock infini (999999)
   - Consommés à la vente

## Gestion des Emplacements

Le système utilise automatiquement :
- **Emplacement de stock** : Stock principal du PDV/entrepôt
- **Emplacement d'inventaire** : Pour les ajustements
- **Calcul automatique** : Si non spécifiés dans les mouvements

## Sécurité

Tous les endpoints requièrent :
- ✅ Authentification JWT valide
- ✅ Scope `pos` dans le token
- ✅ Utilisateur actif dans Odoo

## Intégration Odoo

Le système s'intègre avec les modèles Odoo :
- `product.template` : Informations produit
- `product.product` : Variantes de produit
- `stock.quant` : Quantités en stock
- `stock.move` : Mouvements de stock
- `stock.location` : Emplacements de stock
- `pos.config` : Configuration des PDV

## Codes d'Erreur

| Code | Description |
|------|-------------|
| 400 | Données invalides ou produit non disponible POS |
| 404 | Produit, PDV ou emplacement non trouvé |
| 401 | Non authentifié |
| 403 | Permissions insuffisantes |
| 500 | Erreur serveur ou Odoo |

## Test et Validation

Utilisez le script de test fourni :

```bash
python test_product_management.py
```

Ce script teste automatiquement :
1. ✅ Création de produit
2. ✅ Affectation au PDV
3. ✅ Mouvements de stock
4. ✅ Consultation du stock
5. ✅ Ajustements d'inventaire

## Logs et Monitoring

Les actions sont loggées avec les informations :
- 📝 Type d'opération (création, mouvement, ajustement)
- 👤 Utilisateur concerné
- 📦 Produit et quantités
- 🏪 PDV impliqué
- ⏰ Horodatage des opérations

## Cas d'Usage Typiques

### Station-Service
```bash
# Produits carburant
POST /pos/products/create {"name": "SP95", "type": "product", "list_price": 1.65}
POST /pos/products/create {"name": "Gazole", "type": "product", "list_price": 1.55}

# Boutique
POST /pos/products/create {"name": "Café", "type": "consu", "list_price": 1.20}
POST /pos/products/create {"name": "Lavage auto", "type": "service", "list_price": 8.00}
```

### Commerce de Détail
```bash
# Gestion fine du stock
POST /pos/1/stock/movement {"product_id": 123, "quantity": 100, "reason": "Livraison"}
GET /pos/1/stock/123  # Vérification avant vente
POST /pos/1/stock/123/adjust {"new_quantity": 95, "reason": "Inventaire"}
```

Cette documentation couvre l'ensemble des fonctionnalités de gestion des produits et du stock intégrées à votre système POS.
