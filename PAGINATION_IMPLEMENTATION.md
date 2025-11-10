# Implémentation de la pagination

## Vue d'ensemble

La pagination a été implémentée sur trois endpoints principaux de l'API POS pour améliorer les performances et permettre une navigation efficace dans les résultats.

## Endpoints modifiés

### 1. `/pos/list` - Liste de tous les points de vente

**Paramètres de pagination :**
- `page` : Numéro de page (défaut: 1, minimum: 1)
- `page_size` : Nombre d'éléments par page (défaut: 20, maximum: 100)

**Métadonnées retournées :**
```json
{
  "metadata": {
    "database": "Nom de la base",
    "total_count": 150,
    "page": 1,
    "page_size": 20,
    "total_pages": 8,
    "active_count": 142,
    "with_open_session": 5
  }
}
```

**Exemple d'utilisation :**
```bash
# Première page avec 20 éléments
GET /pos/list?page=1&page_size=20

# Deuxième page avec 50 éléments
GET /pos/list?page=2&page_size=50

# Toujours filtrer par statut actif
GET /pos/list?active_only=true&page=1&page_size=30
```

---

### 2. `/pos/available` - Points de vente affectés à l'employé

**Paramètres de pagination :**
- `page` : Numéro de page (défaut: 1, minimum: 1)
- `page_size` : Nombre d'éléments par page (défaut: 20, maximum: 100)

**Type de retour modifié :**
- Avant : `List[PosShop]`
- Après : `ApiResponse` avec métadonnées de pagination

**Métadonnées retournées :**
```json
{
  "success": true,
  "message": "5 PDV disponible(s) sur 5 au total",
  "data": [...],
  "metadata": {
    "total_count": 5,
    "page": 1,
    "page_size": 20,
    "total_pages": 1
  }
}
```

**Exemple d'utilisation :**
```bash
# Première page
GET /pos/available?page=1&page_size=10

# Deuxième page
GET /pos/available?page=2&page_size=10
```

**⚠️ Note :** Le type de retour a changé de `List[PosShop]` vers `ApiResponse`. 
Les clients doivent maintenant accéder aux données via `response.data` au lieu de traiter directement le tableau.

---

### 3. `/pos/{pos_id}/inventory/transfers` - Transferts d'inventaire

**Paramètres de pagination :**
- `page` : Numéro de page (défaut: 1, minimum: 1)
- `page_size` : Nombre d'éléments par page (défaut: 50, maximum: 200)

**Métadonnées retournées :**
```json
{
  "success": true,
  "data": {
    "pos_info": {...},
    "transfers": [...],
    "filters_applied": {...},
    "domain_used": [...],
    "pagination": {
      "total_count": 250,
      "page": 1,
      "page_size": 50,
      "total_pages": 5,
      "current_count": 50
    }
  },
  "count": 250,
  "message": "Trouvé 50 transfert(s) sur 250 au total pour le PDV 'Station Nord' (page 1/5)"
}
```

**Exemple d'utilisation :**
```bash
# Première page de 50 transferts
GET /pos/1/inventory/transfers?page=1&page_size=50

# Deuxième page de 100 transferts avec filtres
GET /pos/1/inventory/transfers?page=2&page_size=100&state=done&picking_type_code=incoming

# Filtrer par date avec pagination
GET /pos/1/inventory/transfers?date_from=2024-01-01&date_to=2024-12-31&page=1&page_size=200
```

---

## Optimisations implémentées

### 1. Utilisation de `search_count` pour le total

Au lieu de récupérer tous les enregistrements puis compter, nous utilisons `search_count` d'Odoo qui est beaucoup plus performant :

```python
total_count = client.execute_kw(
    'pos.config',
    'search_count',
    [domain]
)
```

### 2. Calcul de l'offset

L'offset est calculé automatiquement en fonction de la page demandée :

```python
offset = (page - 1) * page_size
```

### 3. Paramètres `limit` et `offset` dans `search_read`

```python
search_params = {
    'fields': [...],
    'limit': page_size,
    'offset': offset,
    'order': 'id asc'
}
```

---

## Bénéfices

1. **Performance améliorée** : Récupération uniquement des données nécessaires
2. **Navigation facile** : Calcul automatique du nombre total de pages
3. **Flexibilité** : Les clients peuvent ajuster la taille de page selon leurs besoins
4. **Limitation des ressources** : Tailles maximales définies pour éviter les surcharges
5. **Métadonnées riches** : Informations complètes sur la pagination dans chaque réponse

---

## Migration pour les clients existants

### Pour `/pos/available`

**Avant :**
```python
pos_list = response.json()  # List[PosShop]
for pos in pos_list:
    print(pos['name'])
```

**Après :**
```python
response_data = response.json()  # ApiResponse
pos_list = response_data['data']
for pos in pos_list:
    print(pos['name'])

# Accès aux métadonnées de pagination
total_pages = response_data['metadata']['total_pages']
```

### Pour `/pos/list` et `/pos/{pos_id}/inventory/transfers`

Ces endpoints retournaient déjà des `ApiResponse`, donc la structure reste compatible. 
Seules les métadonnées de pagination ont été ajoutées.

---

## Valeurs par défaut recommandées

- **Listes de configuration** (`/pos/list`, `/pos/available`) : 
  - `page_size=20` (bon équilibre entre performance et UX)
  
- **Transferts d'inventaire** (`/pos/{pos_id}/inventory/transfers`) : 
  - `page_size=50` (ces objets sont plus volumineux)

---

## Gestion des erreurs

Les validations FastAPI assurent que :
- `page >= 1`
- `page_size >= 1`
- `page_size <= limite_max` (100 ou 200 selon l'endpoint)

Toute valeur invalide retournera une erreur 422 avec détails.
