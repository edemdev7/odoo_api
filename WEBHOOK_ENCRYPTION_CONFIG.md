# 🔐 Configuration Webhook avec Encryption RSA

## ✅ Modifications effectuées

### 1. URL du Webhook
```bash
FUEL_WEBHOOK_URL=https://api-jnp-dev.opensi.co/public/odoo/webhook
```

### 2. Format du Webhook avec Encryption

**Requête HTTP envoyée** :
```http
POST https://api-jnp-dev.opensi.co/public/odoo/webhook
Content-Type: application/json
x-encrypted-data: <base64_encrypted_data>
```

**Données encryptées** (JSON avant encryption) :
```json
{
  "action": "COMPANY_RECHARGE",
  "companyExternalId": "123",
  "amount": 50000.0
}
```

### 3. Clés RSA
- **Clé publique** : `public.pem` (encryption)
- **Clé privée** : `private.pem` (décryption côté serveur)

### 4. Algorithme
- RSA-OAEP
- SHA-256
- Base64 encoding

## 🧪 Test

```bash
# Tester l'encryption
python3 test_encryption.py

# Tester le webhook
curl -X POST "http://localhost:8001/fuel-monitor/manual-trigger?partner_id=123&amount=50000" \
  -H "Authorization: Bearer YOUR_TOKEN"
```

## 🔓 Décryption côté OpenSI

Le header `x-encrypted-data` contient les données encryptées.
Utilisez `private.pem` pour décrypter avec RSA-OAEP + SHA256.

Voir le document complet pour les exemples de code Python/Node.js.
