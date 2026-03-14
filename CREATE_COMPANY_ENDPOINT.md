# Endpoint Création d'Entreprise (`/odoo/companies`)

Ce document décrit l'endpoint REST permettant de créer une nouvelle entreprise dans Odoo via le modèle `res.partner`.

## 🔒 Sécurité & Authentification

- **URL** : `POST /odoo/companies`
- **Scopes requis** : `write`
- **Authentification** : JWT via `/auth/login` ou `/auth/pin-login`
- **Headers** :
  ```http
  Authorization: Bearer <access_token>
  Content-Type: application/json
  ```

## 🧾 Payload JSON

```json
{
  "name": "ACME Logistics",
  "email": "contact@acme-logistics.com",
  "phone": "+2250102030405",
  "street": "Treichville, Rue du Commerce",
  "city": "Abidjan",
  "zip": "00225",
  "country_id": 45,
  "vat": "CI123456789",
  "company_registry": "CI-ABJ-2024-B-12345",
  "category_ids": [12, 21],
  "salesperson_id": 78,
  "payment_term_id": 4,
  "note": "Livraison en 24h",
  "customer_rank": 1,
  "supplier_rank": 0
}
```

### Champs supportés

| Champ | Type | Requis | Description |
| --- | --- | --- | --- |
| `name` | string | ✅ | Nom légal de l'entreprise (min 2, max 255 caractères)
| `email` | string | ❌ | Email principal
| `phone` / `mobile` | string | ❌ | Numéros de téléphone
| `street` / `street2` | string | ❌ | Adresse complète
| `zip` / `city` | string | ❌ | Code postal et ville
| `state_id` | int | ❌ | ID `res.country.state`
| `country_id` | int | ❌ | ID `res.country`
| `vat` | string | ❌ | Numéro fiscal / TVA
| `company_registry` | string | ❌ | Numéro RCCM / registre de commerce
| `website` | string | ❌ | Site web
| `category_ids` | int[] | ❌ | Tags (modèle `res.partner.category`)
| `salesperson_id` | int | ❌ | Commercial (`res.users`)
| `payment_term_id` | int | ❌ | Conditions de paiement (`account.payment.term`)
| `note` | string | ❌ | Notes internes (stockées dans `comment`)
| `customer_rank` | int | ❌ | Rang client (par défaut 1)
| `supplier_rank` | int | ❌ | Rang fournisseur (par défaut 0)

> ℹ️ L'endpoint force toujours `is_company = True` et `company_type = "company"`.

## ✅ Réponse

```json
{
  "success": true,
  "data": {
    "id": 9999,
    "partner": {
      "name": "ACME Logistics",
      "email": "contact@acme-logistics.com",
      "phone": "+2250102030405",
      "vat": "CI123456789",
      "website": null,
      "company_registry": "CI-ABJ-2024-B-12345",
      "customer_rank": 1,
      "supplier_rank": 0,
      "category_id": [[12, "Transport"], [21, "VIP"]]
    }
  },
  "message": "Entreprise créée avec succès (ID 9999)"
}
```

## 🚨 Règles métier

1. `salesperson_id` est injecté dans `user_id`
2. `payment_term_id` est injecté dans `property_payment_term_id`
3. `category_ids` utilise la commande Odoo `(6, 0, <ids>)`
4. `note` est stocké dans `comment`
5. Les `customer_rank` / `supplier_rank` sont initialisés à 1 / 0 par défaut

## 🧪 Test rapide

Un test de fumée (`test_create_company_endpoint.py`) valide que l'endpoint :
- construit correctement le payload envoyé à Odoo
- renvoie un `ApiResponse` avec l'ID de la société créée

```bash
DISABLE_UPDATE_PROMPT=true python3 test_create_company_endpoint.py
```

## 🧭 Étapes suivantes

- Mettre en place un test d'intégration qui cible directement un serveur Odoo de staging
- Ajouter une vérification anti-doublon (ex: même `vat` ou `company_registry`)
- Étendre l'endpoint pour créer automatiquement les contacts enfants (facturation / livraison)
