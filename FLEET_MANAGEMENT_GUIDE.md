# Guide de Gestion de la Flotte (Camions & Chauffeurs)

## 📋 Vue d'ensemble

Ce guide explique comment utiliser les endpoints de gestion de la flotte pour récupérer les camions associés aux chauffeurs via les transferts de stock (stock.picking).

## 🔑 Authentification et Partner ID

### Lors de l'authentification par PIN

Quand un employé (chauffeur) s'authentifie avec son matricule et PIN via `/auth/pin-login`, le système:

1. **Recherche l'employé** dans `hr.employee`
2. **Extrait le partner_id** associé (champs: `user_partner_id`, `related_partner_id`, ou `work_contact_id`)
3. **Stocke le partner_id dans le JWT** pour une utilisation ultérieure

**Réponse d'authentification:**
```json
{
  "access_token": "eyJ0eXAiOiJKV1...",
  "token_type": "bearer",
  "expires_in": 1800,
  "user_data": {
    "username": "employee_1023",
    "fullname": "ADITI Urbain",
    "additional_info": {
      "employee_id": 1023,
      "partner_id": 456,  // ⭐ ID du partenaire (res.partner)
      "matricule": "MAT001",
      "odoo_database": "Base Test JNP Directe"
    }
  }
}
```

## 🚚 Endpoints Disponibles

### 1. `/pos/fleet/my-trucks` - Mes Camions (Recommandé)

**Route la plus simple** pour récupérer les camions de l'utilisateur connecté.

**Méthode:** `GET`

**Headers requis:**
```
Authorization: Bearer <votre_jwt_token>
```

**Exemple de requête:**
```bash
curl -X GET "https://api.example.com/pos/fleet/my-trucks" \
  -H "Authorization: Bearer eyJ0eXAiOiJKV1QiLCJhbGc..."
```

**Réponse:**
```json
{
  "success": true,
  "message": "2 camion(s) trouvé(s) avec 15 transfert(s)",
  "data": {
    "driver": {
      "id": 456,
      "name": "ADITI Urbain",
      "phone": "+225 07 00 00 00",
      "mobile": "+225 07 00 00 01",
      "email": "aditi@example.com"
    },
    "trucks": [
      {
        "id": 10,
        "name": "Camion Volvo FH16",
        "transfer_count": 10,
        "last_transfer_date": "2025-11-22 14:30:00",
        "transfers": [
          {
            "id": 123,
            "name": "INT/00015",
            "origin": "Station ABC",
            "state": "done",
            "date": "2025-11-22 14:30:00"
          }
          // ... autres transferts
        ]
      },
      {
        "id": 11,
        "name": "Camion Mercedes Actros",
        "transfer_count": 5,
        "last_transfer_date": "2025-11-20 10:15:00",
        "transfers": [...]
      }
    ],
    "total_trucks": 2,
    "total_transfers": 15
  },
  "count": 2
}
```

**Avantages:**
- ✅ Pas besoin de passer le partner_id manuellement
- ✅ Utilise automatiquement le partner_id du JWT
- ✅ Plus simple pour les applications mobiles/frontend

---

### 2. `/pos/fleet/trucks/by-driver/{driver_id}` - Camions par Chauffeur

**Route flexible** pour récupérer les camions d'un chauffeur spécifique (nécessite le partner_id).

**Méthode:** `GET`

**Paramètres:**
- `driver_id` (path, required): **ID du partenaire** (res.partner), PAS l'employee_id

**Headers requis:**
```
Authorization: Bearer <votre_jwt_token>
```

**Exemple de requête:**
```bash
# CORRECT: Utiliser le partner_id (456)
curl -X GET "https://api.example.com/pos/fleet/trucks/by-driver/456" \
  -H "Authorization: Bearer eyJ0eXAiOiJKV1QiLCJhbGc..."

# ❌ INCORRECT: N'utilisez PAS l'employee_id (1023)
# curl -X GET ".../pos/fleet/trucks/by-driver/1023"
```

**Réponse:** (même format que `/my-trucks`)

**Cas d'utilisation:**
- Gérants qui veulent voir les camions d'un chauffeur spécifique
- Rapports et statistiques par chauffeur
- Administration de la flotte

---

### 3. `/pos/fleet/trucks` - Tous les Camions

Liste tous les camions distincts utilisés dans les transferts.

**Méthode:** `GET`

**Query Parameters:**
- `page` (optionnel, défaut: 1): Numéro de page
- `page_size` (optionnel, défaut: 50, max: 200): Éléments par page

**Exemple de requête:**
```bash
curl -X GET "https://api.example.com/pos/fleet/trucks?page=1&page_size=50" \
  -H "Authorization: Bearer eyJ0eXAiOiJKV1QiLCJhbGc..."
```

**Réponse:**
```json
{
  "success": true,
  "message": "Trouvé 5 camion(s) distinct(s)",
  "data": {
    "trucks": [
      {
        "id": 10,
        "name": "Camion Volvo FH16",
        "usage_count": 25,
        "last_used": "2025-11-22 14:30:00"
      },
      {
        "id": 11,
        "name": "Camion Mercedes Actros",
        "usage_count": 18,
        "last_used": "2025-11-21 09:15:00"
      }
      // ... autres camions
    ]
  },
  "metadata": {
    "total_count": 5,
    "page": 1,
    "page_size": 50,
    "total_pages": 1
  },
  "count": 5
}
```

---

## 🔄 Workflow Typique

### Pour une Application Mobile (Chauffeur)

1. **Authentification:**
```javascript
// Login avec matricule + PIN
const response = await fetch('/auth/pin-login', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({
    matricule: 'MAT001',
    pin: '1234'
  })
});

const { access_token, user_data } = await response.json();
// Sauvegarder access_token pour les requêtes suivantes
// user_data.additional_info.partner_id contient le partner_id
```

2. **Récupérer mes camions:**
```javascript
const trucksResponse = await fetch('/pos/fleet/my-trucks', {
  headers: {
    'Authorization': `Bearer ${access_token}`
  }
});

const { data } = await trucksResponse.json();
console.log(`${data.total_trucks} camions trouvés`);
```

### Pour un Dashboard Administrateur

1. **Liste de tous les camions:**
```javascript
const allTrucks = await fetch('/pos/fleet/trucks?page=1&page_size=100', {
  headers: { 'Authorization': `Bearer ${admin_token}` }
});
```

2. **Camions d'un chauffeur spécifique:**
```javascript
// Obtenir le partner_id du chauffeur (depuis la base de données ou l'interface)
const driverPartnerId = 456;

const driverTrucks = await fetch(`/pos/fleet/trucks/by-driver/${driverPartnerId}`, {
  headers: { 'Authorization': `Bearer ${admin_token}` }
});
```

---

## ⚠️ Points Importants

### 1. Employee ID vs Partner ID

- **Employee ID** (`hr.employee`): Identifiant de l'employé dans le système RH
- **Partner ID** (`res.partner`): Identifiant du contact/partenaire dans Odoo
- **Les endpoints de flotte utilisent le Partner ID**, pas l'Employee ID

### 2. Mapping Employee → Partner

Le système fait automatiquement le mapping lors de l'authentification PIN:
- `user_partner_id` (priorité 1)
- `related_partner_id` (priorité 2)
- `work_contact_id` (priorité 3)

### 3. Champs Odoo Utilisés

Les endpoints recherchent dans `stock.picking`:
- **`x_studio_chauffeur`** (many2one → res.partner): Le chauffeur du transfert
- **`x_studio_camionchauffeur`** (many2one): Le camion utilisé

---

## 🐛 Dépannage

### Erreur: "Partner ID manquant dans le token"

**Cause:** Vous utilisez `/my-trucks` mais votre token ne contient pas de partner_id.

**Solution:** 
- Assurez-vous d'utiliser l'authentification PIN (`/auth/pin-login`)
- Si vous utilisez un autre type d'auth, utilisez `/fleet/trucks/by-driver/{partner_id}` à la place

### Erreur 404: "Chauffeur non trouvé"

**Cause:** Le partner_id fourni n'existe pas dans `res.partner`.

**Solution:**
- Vérifiez que vous utilisez le **partner_id**, pas l'employee_id
- Vérifiez dans Odoo que l'employé a bien un partenaire associé

### Aucun camion trouvé

**Causes possibles:**
1. Le chauffeur n'a aucun transfert avec camion dans `stock.picking`
2. Le champ `x_studio_chauffeur` ne correspond pas au partner_id
3. Le champ `x_studio_camionchauffeur` est vide sur tous les transferts

**Vérifications:**
```python
# Dans Odoo, vérifier les transferts du chauffeur
transfers = env['stock.picking'].search([
    ('x_studio_chauffeur', '=', partner_id),
    ('x_studio_camionchauffeur', '!=', False)
])
```

---

## 📊 Statistiques et Rapports

### Exemple: Top 5 camions les plus utilisés

```python
import requests

response = requests.get(
    'https://api.example.com/pos/fleet/trucks',
    headers={'Authorization': f'Bearer {token}'},
    params={'page_size': 5}
)

trucks = response.json()['data']['trucks']
for truck in trucks:
    print(f"{truck['name']}: {truck['usage_count']} utilisations")
```

### Exemple: Camions par chauffeur

```python
def get_driver_trucks(driver_partner_id, token):
    response = requests.get(
        f'https://api.example.com/pos/fleet/trucks/by-driver/{driver_partner_id}',
        headers={'Authorization': f'Bearer {token}'}
    )
    return response.json()

# Utilisation
trucks_data = get_driver_trucks(456, access_token)
print(f"Chauffeur: {trucks_data['data']['driver']['name']}")
print(f"Camions: {trucks_data['data']['total_trucks']}")
```

---

## 🔐 Sécurité

- ✅ Tous les endpoints nécessitent une authentification JWT
- ✅ Scope requis: `pos`
- ✅ Les chauffeurs ne peuvent voir que leurs propres camions via `/my-trucks`
- ✅ Les gérants peuvent voir tous les camions et ceux de n'importe quel chauffeur

---

## 📝 Changelog

### Version 1.1.0 (23 novembre 2025)
- ✨ Ajout de l'endpoint `/fleet/my-trucks` pour simplifier l'accès aux camions de l'utilisateur connecté
- ✨ Ajout du `partner_id` dans le JWT lors de l'authentification PIN
- 🔄 Simplification de `/fleet/trucks/by-driver` pour utiliser directement le partner_id
- 📚 Ajout de cette documentation complète

### Version 1.0.0
- 🎉 Version initiale avec endpoints de base
