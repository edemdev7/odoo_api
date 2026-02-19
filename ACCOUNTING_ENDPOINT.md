# 📝 Endpoint de Crédit Comptable

## Endpoint créé

### POST `/accounting/credit-account`

Crée une écriture comptable de **crédit sur le compte 419101**.

## 🔐 Sécurité

**Toutes les données doivent être encryptées avec RSA** et envoyées dans le header `x-encrypted-data`.

## 📤 Format de la requête

```http
POST /accounting/credit-account
Content-Type: application/json
x-encrypted-data: <données_encryptées_base64>
```

### Données à encrypter (JSON)

```json
{
  "partner_id": 123,
  "amount": 50000,
  "reference": "KKIAPAY-TRX-12345",
  "date": "2026-02-19",
  "description": "Recharge compte fuel via Kkiapay"
}
```

**Champs** :
- `partner_id` (requis) : ID de l'entreprise dans Odoo
- `amount` (requis) : Montant à créditer (> 0)
- `reference` (requis) : Référence de transaction (ex: ID transaction Kkiapay)
- `date` (optionnel) : Date de l'écriture (défaut: aujourd'hui)
- `description` (optionnel) : Description (défaut: "Recharge compte - {reference}")

## 📥 Réponse

### Succès (200)

```json
{
  "success": true,
  "data": {
    "move_id": 456,
    "move_name": "MISC/2026/0123",
    "move_state": "posted",
    "partner_id": 123,
    "partner_name": "CORIS BANK POOL",
    "amount": 50000.0,
    "reference": "KKIAPAY-TRX-12345",
    "date": "2026-02-19",
    "accounts": {
      "debit": "512000 - Banque",
      "credit": "419101 - Clients - Dettes provisionnées"
    },
    "old_balance": 450000.0,
    "new_balance": 500000.0
  },
  "message": "Écriture comptable créée avec succès pour CORIS BANK POOL - Montant: 50000.0"
}
```

### Erreur (401)

```json
{
  "detail": "Données encryptées requises dans le header x-encrypted-data"
}
```

### Erreur (404)

```json
{
  "detail": "Partenaire 123 non trouvé"
}
```

ou

```json
{
  "detail": "Compte comptable 419101 non trouvé dans Odoo"
}
```

## 💡 Ce qui se passe en arrière-plan

1. **Décryption** des données du header
2. **Validation** des paramètres
3. **Vérification** que le partenaire existe
4. **Recherche** des comptes comptables :
   - Compte crédit : **419101**
   - Compte débit : **512000** (ou premier compte banque trouvé)
5. **Création** de l'écriture comptable (`account.move`) avec 2 lignes :
   - Ligne débit : Banque +50000
   - Ligne crédit : Client 419101 +50000
6. **Validation** automatique de l'écriture (état: posted)
7. **Mise à jour** automatique du solde client

## 🧪 Test

### Avec Python

```python
from core.encryption import encrypt_webhook_data
import requests

# Préparer les données
data = {
    "partner_id": 123,
    "amount": 50000,
    "reference": "KKIAPAY-TRX-12345"
}

# Encrypter
encrypted = encrypt_webhook_data(data)

# Envoyer
response = requests.post(
    "http://localhost:8001/accounting/credit-account",
    headers={
        "Content-Type": "application/json",
        "x-encrypted-data": encrypted
    }
)

print(response.json())
```

### Avec le script de test

```bash
python3 test_accounting.py
```

## 📋 Configuration par défaut

Dans `api/accounting.py` :

```python
DEFAULT_CREDIT_ACCOUNT = "419101"  # Compte client à créditer
DEFAULT_DEBIT_ACCOUNT = "512000"   # Compte banque
DEFAULT_JOURNAL_ID = 1              # Journal de banque
```

⚠️ **À adapter** selon votre plan comptable Odoo !

## 🔧 Modifier les comptes par défaut

Si vos comptes sont différents, éditez `api/accounting.py` :

```python
DEFAULT_CREDIT_ACCOUNT = "VOTRE_COMPTE_CLIENT"
DEFAULT_DEBIT_ACCOUNT = "VOTRE_COMPTE_BANQUE"
DEFAULT_JOURNAL_ID = VOTRE_JOURNAL_ID
```

## 🔍 Vérifier un compte

### GET `/accounting/accounts/{account_code}`

Vérifie qu'un compte comptable existe.

**Requête** :
```http
GET /accounting/accounts/419101
x-encrypted-data: <données_encryptées>
```

**Réponse** :
```json
{
  "success": true,
  "data": {
    "id": 789,
    "code": "419101",
    "name": "Clients - Dettes provisionnées",
    "account_type": "asset_receivable",
    "currency_id": [1, "XOF"]
  },
  "message": "Compte 419101 trouvé"
}
```

## 🚀 Exemple d'utilisation complète

### Depuis votre système externe

```javascript
// Node.js exemple
const crypto = require('crypto');
const axios = require('axios');
const fs = require('fs');

// 1. Préparer les données
const data = {
  partner_id: 123,
  amount: 50000,
  reference: 'KKIAPAY-TRX-' + Date.now()
};

// 2. Encrypter
const publicKey = fs.readFileSync('public.pem', 'utf8');
const encrypted = crypto.publicEncrypt(
  {
    key: publicKey,
    padding: crypto.constants.RSA_PKCS1_OAEP_PADDING,
    oaepHash: 'sha256'
  },
  Buffer.from(JSON.stringify(data))
);
const encryptedB64 = encrypted.toString('base64');

// 3. Envoyer
const response = await axios.post(
  'http://localhost:8001/accounting/credit-account',
  {},
  {
    headers: {
      'Content-Type': 'application/json',
      'x-encrypted-data': encryptedB64
    }
  }
);

console.log('Écriture créée:', response.data);
```

## ⚠️ Notes importantes

1. **Pas d'authentification JWT** - L'endpoint utilise uniquement l'encryption RSA
2. **Client Odoo par défaut** - Utilise les credentials du `.env`
3. **Validation automatique** - L'écriture est validée (posted) automatiquement
4. **Idempotence** - Utilisez des références uniques pour éviter les doublons
5. **Journal** - Assurez-vous que le journal ID existe dans Odoo
6. **Comptes** - Vérifiez que les codes de compte existent dans votre plan comptable

## 🔄 Workflow avec Kkiapay

```
1. Client paie via Kkiapay
   ↓
2. Kkiapay webhook vers votre système
   ↓
3. Votre système valide le paiement
   ↓
4. Votre système appelle /accounting/credit-account
   (données encryptées avec RSA)
   ↓
5. API Odoo crée l'écriture comptable
   Débit: Compte banque
   Crédit: Compte 419101
   ↓
6. Écriture validée automatiquement
   ↓
7. Solde client mis à jour
   ↓
8. Fuel Monitor détecte le changement
   ↓
9. Webhook envoyé vers OpenSI
```

## 📊 Logs

L'endpoint logge toutes les étapes :

```
🔓 Décryption des données...
✅ Données décryptées: partner_id=123, amount=50000
✅ Partenaire trouvé: CORIS BANK POOL (crédit actuel: 450000)
✅ Compte crédit: 419101 - Clients - Dettes provisionnées
✅ Compte débit: 512000 - Banque
📝 Création de l'écriture comptable...
   Débit: 512000 - 50000
   Crédit: 419101 - 50000
✅ Écriture créée: ID=456
✅ Écriture validée (posted)
✅ Écriture créée: MISC/2026/0123
   État: posted
   Référence: KKIAPAY-TRX-12345
💰 Nouveau solde client: 500000
```
