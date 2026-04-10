# 🧪 Guide de test - Nouveaux champs d'acteurs

## ⚡ Quick Start (5 minutes)

### 1️⃣ Récupérer un JWT token
```bash
TOKEN=$(curl -s -X POST "http://localhost:8001/auth/login" \
  -H "Content-Type: application/json" \
  -d '{
    "username": "admin@jnpgroupe.com",
    "password": "votre_password"
  }' | jq -r '.data.access_token')

echo "Token: $TOKEN"
```

### 2️⃣ Tester l'endpoint
```bash
curl -X GET "http://localhost:8001/pos/inventory/transfers/by-truck?truck_name=JO70&page_size=5" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" | jq '.'
```

### 3️⃣ Vérifier les nouveaux champs
```bash
curl -X GET "http://localhost:8001/pos/inventory/transfers/by-truck?truck_name=JO70&page_size=1" \
  -H "Authorization: Bearer $TOKEN" | jq '.data.transfers[0] | {
    name,
    location_source_actor,
    location_destination_actor,
    related_contacts
  }'
```

**Résultat attendu:**
```json
{
  "name": "BURWA/OUT/01620",
  "location_source_actor": {
    "id": 1968,
    "name": "Alassane Diallo",
    "mobile": "+221 77 123 4567"
  },
  "location_destination_actor": null,
  "related_contacts": [
    {
      "id": 1968,
      "name": "Alassane Diallo"
    }
  ]
}
```

---

## 🧪 Tests complets

### Test 1: Affichage des acteurs source

```bash
curl -X GET "http://localhost:8001/pos/inventory/transfers/by-truck?truck_name=JO70" \
  -H "Authorization: Bearer $TOKEN" | jq '.data.transfers[] | {
    id: .id,
    name: .name,
    source: .location_source_details.complete_name,
    source_actor: .location_source_actor.name,
    source_mobile: .location_source_actor.mobile
  }'
```

**Vérifier:**
- ✅ `source_actor` n'est pas null
- ✅ `source_mobile` est un vrai numéro
- ✅ ID du `source_actor` existe en base Odoo

### Test 2: Affichage des acteurs destination

```bash
curl -X GET "http://localhost:8001/pos/inventory/transfers/by-truck?truck_name=JO70" \
  -H "Authorization: Bearer $TOKEN" | jq '.data.transfers[] | {
    id: .id,
    name: .name,
    destination: .location_destination_details.complete_name,
    destination_actor: .location_destination_actor,
    destination_actor_name: .location_destination_actor.name
  }'
```

**Vérifier:**
- ✅ `destination_actor` est null OU contient des infos
- ✅ Si POS, c'est le manager
- ✅ Si client, c'est null (location générique)

### Test 3: Tous les contacts

```bash
curl -X GET "http://localhost:8001/pos/inventory/transfers/by-truck?truck_name=JO70" \
  -H "Authorization: Bearer $TOKEN" | jq '.data.transfers[0] | {
    transfer_name: .name,
    contact_count: (.related_contacts | length),
    contacts: .related_contacts[].name
  }'
```

**Vérifier:**
- ✅ `contact_count` >= 1
- ✅ Les noms sont vrais
- ✅ Les IDs sont corrects

### Test 4: Performance

```bash
time curl -X GET "http://localhost:8001/pos/inventory/transfers/by-truck?truck_name=JO70&page_size=50" \
  -H "Authorization: Bearer $TOKEN" > /dev/null

echo "Temps d'exécution: voir 'real' (< 300ms idéal)"
```

**Vérifier:**
- ✅ Temps < 300ms
- ✅ Pas de timeouts
- ✅ Réponse HTTP 200

### Test 5: Vérifier les IDs en base Odoo

```bash
# Une fois la réponse reçue, vérifier qu'un ID d'acteur existe
ACTOR_ID=1968

# Via Odoo, chercher ce partenaire
curl -X GET "http://localhost:8001/api/partners/$ACTOR_ID" \
  -H "Authorization: Bearer $TOKEN" | jq '.data | {
    id,
    name,
    type,
    mobile
  }'
```

**Vérifier:**
- ✅ Le partenaire existe
- ✅ Le nom correspond à celui retourné
- ✅ Le type est correct

---

## 🎯 Cas de test spécifiques

### Test 1: Transfert depuis un camion
```bash
curl -X GET "http://localhost:8001/pos/inventory/transfers/by-truck?truck_name=JO70&transfer_type=outgoing" \
  -H "Authorization: Bearer $TOKEN" | jq '.data.transfers[0] | {
    type: .picking_type_code,
    source_actor: .location_source_actor.name,
    partner: .partner_details.name
  }'
```

**Résultat attendu:**
```json
{
  "type": "outgoing",
  "source_actor": "Alassane Diallo",
  "partner": "Client ABC SARL"
}
```

### Test 2: Réception par un POS
```bash
curl -X GET "http://localhost:8001/pos/inventory/transfers/by-truck?truck_name=JO55&transfer_type=incoming" \
  -H "Authorization: Bearer $TOKEN" | jq '.data.transfers[0] | {
    type: .picking_type_code,
    destination: .location_destination_details.complete_name,
    destination_actor: .location_destination_actor.name
  }'
```

**Résultat attendu:**
```json
{
  "type": "incoming",
  "destination": "BURWA/POS/...",
  "destination_actor": "Ousmane Ba"
}
```

### Test 3: Transfert interne
```bash
curl -X GET "http://localhost:8001/pos/inventory/transfers/by-truck?transfer_type=internal" \
  -H "Authorization: Bearer $TOKEN" | jq '.data.transfers[0] | {
    type: .picking_type_code,
    source_actor: .location_source_actor,
    destination_actor: .location_destination_actor
  }'
```

**Résultat attendu:**
```json
{
  "type": "internal",
  "source_actor": null,
  "destination_actor": null
}
```

---

## 🐛 Troubleshooting

### Problème: `location_source_actor` est null
```bash
# Vérifier que la localisation source est correctement configurée
curl -X GET "http://localhost:8001/pos/inventory/transfers/by-truck?truck_name=JO70&page_size=1" \
  -H "Authorization: Bearer $TOKEN" | jq '.data.transfers[0].location_source_details | {
    id,
    name,
    partner_id,
    pos_config_id
  }'
```

**Attendre:**
- Soit `partner_id` avec une valeur
- Soit `pos_config_id` avec une valeur
- Sinon c'est normal (localisation interne)

### Problème: ID d'acteur incorrect
```bash
# Chercher le partenaire qui devrait être l'acteur
curl -X GET "http://localhost:8001/api/partners?search=JO70" \
  -H "Authorization: Bearer $TOKEN" | jq '.data[] | {id, name, type}'
```

**À vérifier:**
- Le ID retourné par l'endpoint correspond-il?
- Estce un partenaire de type "delivery" (camion)?

### Problème: Performance lente
```bash
# Vérifier le temps de chaque étape
curl -X GET "http://localhost:8001/pos/inventory/transfers/by-truck?truck_name=JO70&page_size=10" \
  -H "Authorization: Bearer $TOKEN" \
  -w "\nStatus: %{http_code}\nTime: %{time_total}s\n" \
  > /tmp/test_response.json

wc -l /tmp/test_response.json
```

**À vérifier:**
- Temps < 1 seconde = OK
- Temps > 5 secondes = Problème Odoo/réseau

---

## ✅ Validation complète

### Checklist de validation

- [ ] Endpoint répond (HTTP 200)
- [ ] `location_source_actor` populé pour outgoing transfers
- [ ] `location_destination_actor` populé pour incoming transfers
- [ ] `related_contacts` contient au moins 1 contact
- [ ] IDs des acteurs existent en base Odoo
- [ ] Performance < 300ms pour 50 transfers
- [ ] Pas d'erreur dans les logs
- [ ] Réponse contient tous les champs (même si null)

### Tester en Python

```python
import requests
import json

TOKEN = "..."  # Votre JWT
BASE_URL = "http://localhost:8001"

# Appel
response = requests.get(
    f"{BASE_URL}/pos/inventory/transfers/by-truck",
    params={"truck_name": "JO70", "page_size": 5},
    headers={"Authorization": f"Bearer {TOKEN}"}
)

# Vérifier
data = response.json()
transfer = data['data']['transfers'][0]

print(f"Transfer: {transfer['name']}")
print(f"Source actor: {transfer.get('location_source_actor', {}).get('name', 'N/A')}")
print(f"Dest actor: {transfer.get('location_destination_actor', {}).get('name', 'N/A')}")
print(f"Contacts: {len(transfer.get('related_contacts', []))}")
print(f"✅ Test réussi!" if transfer.get('location_source_actor') else "❌ Acteur source manquant")
```

---

## 🎬 Démo complète (30 secondes)

```bash
#!/bin/bash

# Setup
TOKEN=$(curl -s -X POST "http://localhost:8001/auth/login" \
  -H "Content-Type: application/json" \
  -d '{"username":"admin@jnpgroupe.com","password":"***"}' \
  | jq -r '.data.access_token')

echo "🔗 Token reçu"

# Test 1: Basic
curl -s -X GET "http://localhost:8001/pos/inventory/transfers/by-truck?truck_name=JO70&page_size=1" \
  -H "Authorization: Bearer $TOKEN" \
  | jq '.data.transfers[0] | {
    name,
    source_actor: .location_source_actor.name,
    dest_actor: .location_destination_actor.name,
    contacts: (.related_contacts | length)
  }'

echo "✅ Test réussi!"
```

---

## 📊 Format des résultats attendus

### Source actor complète
```json
{
  "id": 1968,
  "name": "Alassane Diallo",
  "mobile": "+221 77 123 4567",
  "email": "alassane.diallo@opensi.co",
  "function": "Chauffeur Principal",
  "type": "contact"
}
```

### Destination actor complète
```json
{
  "id": 2045,
  "name": "Ousmane Ba",
  "mobile": "+221 77 666 7777",
  "email": "manager@pos82.opensi.co",
  "function": "Gérant POS-82",
  "type": "contact"
}
```

### Related contacts complètes
```json
[
  {
    "id": 1968,
    "name": "Alassane Diallo",
    "mobile": "+221 77 123 4567",
    "email": "...",
    "function": "Chauffeur Principal"
  },
  {
    "id": 1969,
    "name": "Daouda Sall",
    "mobile": "+221 77 333 2222",
    "email": "...",
    "function": "Assistant"
  }
]
```

---

**Happy testing!** 🚀
