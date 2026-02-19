# Documentation API - Endpoint Accounting Credit Account

## URL de l'endpoint

```
POST /accounting/credit-account
```

**Base URL**: `https://votre-serveur.com` (à remplacer par l'URL de votre serveur FastAPI)

## Headers requis

```http
Content-Type: application/json
Authorization: Bearer <access_token>
x-encrypted-data: <données_encryptées_en_base64>
```

---

## 🔐 Étape 1 : Authentification

### Obtenir un token d'accès

```http
POST /auth/pin-login
Content-Type: application/json

{
  "pin_code": "0000",
  "database": "jnp_directe"
}
```

### Réponse authentification

```json
{
  "success": true,
  "data": {
    "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
    "token_type": "bearer",
    "employee_id": 9802,
    "employee_name": "AKPAN Marie Elvire",
    "partner_id": 9802
  },
  "message": "Connexion réussie"
}
```

**Conserver le `access_token` pour les requêtes suivantes.**

---

## 📝 Étape 2 : Préparer les données

### Format JSON à encrypter

```json
{
  "partner_id": 4708,
  "amount": 5000.0,
  "reference": "RECHARGE-12345",
  "credit_account": "419101",
  "debit_account": "411100",
  "journal_id": null
}
```

### Description des champs

| Champ | Type | Requis | Description | Défaut |
|-------|------|--------|-------------|--------|
| `partner_id` | integer | ✅ **Oui** | ID du partenaire (client) dans Odoo | - |
| `amount` | float | ✅ **Oui** | Montant de la recharge en CFA (> 0) | - |
| `reference` | string | ❌ Non | Référence unique de la transaction | Auto-généré |
| `credit_account` | string | ❌ Non | Code du compte crédit | `"419101"` |
| `debit_account` | string | ❌ Non | Code du compte débit | `"411100"` |
| `journal_id` | integer/null | ❌ Non | ID du journal comptable | Auto-détecté |

### Valeurs par défaut

- **credit_account** : `"419101"` (Clients, avances et acomptes reçus / Carburant)
- **debit_account** : `"411100"` (Customers - Clients)
- **journal_id** : `null` → Le système détecte automatiquement un journal de vente

### ⚠️ Contraintes

1. Les comptes `credit_account` et `debit_account` doivent :
   - Exister dans Odoo
   - Appartenir à la **même société**
   
2. Le journal (si spécifié) doit :
   - Être de type `general` ou `sale`
   - Appartenir à la même société que les comptes

3. Le partenaire doit exister dans Odoo

---

## 🔒 Étape 3 : Encrypter les données (Node.js)

### Code complet d'encryption

```javascript
const crypto = require('crypto');
const fs = require('fs');

/**
 * Encrypter les données avec RSA-OAEP SHA256
 * Compatible avec le serveur Python/FastAPI
 */
function encryptData(data, publicKeyPath) {
  // 1. Convertir les données en JSON string (minifié)
  const jsonString = JSON.stringify(data);
  
  // 2. Charger la clé publique RSA
  const publicKey = fs.readFileSync(publicKeyPath, 'utf8');
  
  // 3. Encrypter avec RSA-OAEP + SHA256
  const encrypted = crypto.publicEncrypt(
    {
      key: publicKey,
      padding: crypto.constants.RSA_PKCS1_OAEP_PADDING,
      oaepHash: 'sha256',
    },
    Buffer.from(jsonString, 'utf8')
  );
  
  // 4. Encoder en base64
  return encrypted.toString('base64');
}

// Exemple d'utilisation
const data = {
  partner_id: 4708,
  amount: 5000.0,
  reference: 'RECHARGE-12345',
  credit_account: '419101',
  debit_account: '411100',
  journal_id: null
};

const encryptedData = encryptData(data, './public.pem');
console.log('Données encryptées:', encryptedData);
```

### Paramètres d'encryption

- **Algorithme** : RSA 2048-bit
- **Padding** : OAEP (Optimal Asymmetric Encryption Padding)
- **Hash** : SHA256
- **MGF** : MGF1 avec SHA256
- **Compression** : ❌ Désactivée (pour compatibilité Node.js)
- **Encodage** : Base64

### ⚠️ Limite de taille

- **Maximum** : ~190 bytes de données avant encryption
- **Taille actuelle** : ~72 bytes → ✅ OK
- Si vos données dépassent 190 bytes, réduisez-les ou activez la compression côté serveur

---

## 📤 Étape 4 : Envoyer la requête

### Code Node.js complet

```javascript
const axios = require('axios');
const crypto = require('crypto');
const fs = require('fs');

const API_BASE_URL = 'https://votre-serveur.com';

/**
 * Encrypter les données
 */
function encryptData(data, publicKeyPath) {
  const jsonString = JSON.stringify(data);
  const publicKey = fs.readFileSync(publicKeyPath, 'utf8');
  
  const encrypted = crypto.publicEncrypt(
    {
      key: publicKey,
      padding: crypto.constants.RSA_PKCS1_OAEP_PADDING,
      oaepHash: 'sha256',
    },
    Buffer.from(jsonString, 'utf8')
  );
  
  return encrypted.toString('base64');
}

/**
 * Créer une écriture comptable
 */
async function createAccountingEntry() {
  try {
    // 1. S'authentifier
    console.log('📝 Authentification...');
    const authResponse = await axios.post(`${API_BASE_URL}/auth/pin-login`, {
      pin_code: '0000',
      database: 'jnp_directe'
    });
    
    const accessToken = authResponse.data.data.access_token;
    console.log('✅ Token obtenu');
    
    // 2. Préparer les données
    const accountingData = {
      partner_id: 4708,
      amount: 5000.0,
      reference: `RECHARGE-${Date.now()}`,
      credit_account: '419101',
      debit_account: '411100',
      journal_id: null
    };
    
    console.log('📝 Données à encrypter:', accountingData);
    
    // 3. Encrypter les données
    const encryptedData = encryptData(accountingData, './public.pem');
    console.log('🔐 Données encryptées (longueur):', encryptedData.length);
    
    // 4. Envoyer la requête
    console.log('📤 Envoi de la requête...');
    const response = await axios.post(
      `${API_BASE_URL}/accounting/credit-account`,
      {},  // Body vide - les données sont dans le header
      {
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${accessToken}`,
          'x-encrypted-data': encryptedData
        }
      }
    );
    
    // 5. Afficher la réponse
    console.log('✅ Écriture créée avec succès!');
    console.log('Réponse:', JSON.stringify(response.data, null, 2));
    
    return response.data;
    
  } catch (error) {
    console.error('❌ Erreur:', error.response?.data || error.message);
    throw error;
  }
}

// Exécuter
createAccountingEntry()
  .then(() => console.log('✅ Terminé'))
  .catch(err => console.error('❌ Échec:', err));
```

### Requête HTTP brute

```http
POST /accounting/credit-account HTTP/1.1
Host: votre-serveur.com
Content-Type: application/json
Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
x-encrypted-data: aGVsbG8gd29ybGQ=...

```

**Note** : Le body est vide, toutes les données sont dans le header `x-encrypted-data`.

---

## 📥 Réponse de l'API

### ✅ Succès (HTTP 200)

```json
{
  "success": true,
  "data": {
    "move_id": 163644,
    "move_name": "JDV/2026/00028",
    "state": "posted",
    "reference": "RECHARGE-12345",
    "partner_id": 4708,
    "partner_name": "JSI VOYAGES",
    "amount": 5000.0,
    "previous_credit": 789685.0,
    "new_credit": 794685.0,
    "credit_difference": 5000.0,
    "journal_id": 126,
    "journal_name": "JDV - JOURNAL DES VENTES",
    "credit_account": "419101",
    "debit_account": "411100",
    "line_ids": [42578, 42579],
    "created_at": "2026-02-19T14:05:30"
  },
  "message": "Écriture comptable créée et validée avec succès"
}
```

### ❌ Erreurs possibles

#### Erreur 400 - Données invalides

```json
{
  "detail": "Montant invalide : doit être > 0"
}
```

#### Erreur 401 - Non authentifié

```json
{
  "detail": "Not authenticated"
}
```

#### Erreur 403 - Permissions insuffisantes

```json
{
  "detail": "Scope 'pos' requis"
}
```

#### Erreur 404 - Ressource non trouvée

```json
{
  "detail": "Partenaire 4708 non trouvé"
}
```

```json
{
  "detail": "Compte 419101 non trouvé"
}
```

#### Erreur 500 - Erreur serveur

```json
{
  "detail": "Erreur Odoo: Invalid field 'account_id'"
}
```

---

## 📊 Codes de réponse HTTP

| Code | Signification | Action |
|------|---------------|--------|
| **200** | ✅ Succès | Écriture créée et validée |
| **400** | ❌ Requête invalide | Vérifier les données (montant, partner_id, etc.) |
| **401** | ❌ Non authentifié | Obtenir un nouveau token |
| **403** | ❌ Permission refusée | Vérifier les scopes du token |
| **404** | ❌ Non trouvé | Vérifier partner_id, comptes, journal |
| **500** | ❌ Erreur serveur | Vérifier les logs serveur |

---

## 🧪 Test avec curl

### Étape 1 : Obtenir un token

```bash
TOKEN=$(curl -s -X POST "http://localhost:8002/auth/pin-login" \
  -H "Content-Type: application/json" \
  -d '{"pin_code":"0000","database":"jnp_directe"}' \
  | jq -r '.data.access_token')

echo "Token: $TOKEN"
```

### Étape 2 : Encrypter les données (Python)

```bash
python3 << 'EOF'
import sys
sys.path.insert(0, '.')
from core.encryption import encrypt_webhook_data

data = {
    "partner_id": 4708,
    "amount": 5000.0,
    "reference": "TEST-CURL-12345"
}

encrypted = encrypt_webhook_data(data, use_compression=False)
print(encrypted)
EOF
```

### Étape 3 : Envoyer la requête

```bash
# Remplacer ENCRYPTED_DATA par la sortie de l'étape 2
curl -X POST "http://localhost:8002/accounting/credit-account" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -H "x-encrypted-data: ENCRYPTED_DATA" \
  -v
```

---

## 🔑 Fichiers de clés RSA

### Format attendu

Les clés RSA doivent être au format PEM :

**public.pem** :
```
-----BEGIN PUBLIC KEY-----
MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEA...
-----END PUBLIC KEY-----
```

**private.pem** (côté serveur uniquement) :
```
-----BEGIN PRIVATE KEY-----
MIIEvgIBADANBgkqhkiG9w0BAQEFAASCBKgwggSkAgEAAoIBAQC...
-----END PRIVATE KEY-----
```

ou

```
-----BEGIN RSA PRIVATE KEY-----
MIIEpAIBAAKCAQEAz8Z...
-----END RSA PRIVATE KEY-----
```

### Génération des clés (si nécessaire)

```bash
# Générer une paire de clés RSA 2048-bit
openssl genrsa -out private.pem 2048
openssl rsa -in private.pem -pubout -out public.pem
```

---

## 💡 Bonnes pratiques

### 1. Gestion des erreurs

```javascript
try {
  const result = await createAccountingEntry();
  // Traiter le succès
} catch (error) {
  if (error.response) {
    // Erreur de l'API
    console.error('Code:', error.response.status);
    console.error('Message:', error.response.data.detail);
    
    // Gérer selon le code
    if (error.response.status === 401) {
      // Renouveler le token
    } else if (error.response.status === 404) {
      // Partenaire non trouvé
    }
  } else {
    // Erreur réseau
    console.error('Erreur réseau:', error.message);
  }
}
```

### 2. Validation avant envoi

```javascript
function validateAccountingData(data) {
  if (!data.partner_id || data.partner_id <= 0) {
    throw new Error('partner_id invalide');
  }
  
  if (!data.amount || data.amount <= 0) {
    throw new Error('amount doit être > 0');
  }
  
  if (data.reference && data.reference.length > 100) {
    throw new Error('reference trop longue (max 100 caractères)');
  }
  
  return true;
}
```

### 3. Retry en cas d'échec temporaire

```javascript
async function createWithRetry(maxRetries = 3) {
  for (let i = 0; i < maxRetries; i++) {
    try {
      return await createAccountingEntry();
    } catch (error) {
      if (i === maxRetries - 1) throw error;
      if (error.response?.status >= 500) {
        // Erreur serveur, retry
        await new Promise(r => setTimeout(r, 1000 * (i + 1)));
        continue;
      }
      throw error; // Autres erreurs, pas de retry
    }
  }
}
```

---

## 📞 Support et débogage

### Vérifications en cas de problème

1. **Encryption échoue** :
   - ✅ Vérifier que `public.pem` existe et est lisible
   - ✅ Vérifier le format de la clé (BEGIN PUBLIC KEY)
   - ✅ Taille des données < 190 bytes

2. **HTTP 401** :
   - ✅ Token valide et non expiré
   - ✅ Format du header : `Authorization: Bearer <token>`

3. **HTTP 404** :
   - ✅ `partner_id` existe dans Odoo
   - ✅ Comptes `419101` et `411100` existent
   - ✅ Comptes dans la même société

4. **HTTP 500** :
   - ✅ Consulter les logs du serveur
   - ✅ Vérifier la connexion à Odoo
   - ✅ Vérifier les permissions Odoo

### Logs serveur

Pour voir les détails des erreurs, consultez les logs FastAPI :

```bash
# Si lancé avec uvicorn
tail -f /var/log/fastapi/app.log

# Ou si lancé en console
# Les logs s'affichent directement
```

---

## 📝 Résumé rapide

```javascript
// 1. Authentification
const auth = await axios.post('/auth/pin-login', {...});
const token = auth.data.data.access_token;

// 2. Encryption des données
const data = { partner_id: 4708, amount: 5000.0, reference: 'REF-123' };
const encrypted = crypto.publicEncrypt({
  key: publicKey,
  padding: crypto.constants.RSA_PKCS1_OAEP_PADDING,
  oaepHash: 'sha256'
}, Buffer.from(JSON.stringify(data))).toString('base64');

// 3. Envoi
const response = await axios.post('/accounting/credit-account', {}, {
  headers: {
    'Authorization': `Bearer ${token}`,
    'x-encrypted-data': encrypted
  }
});

// 4. Résultat
console.log('Écriture:', response.data.data.move_name);
console.log('Nouveau crédit:', response.data.data.new_credit);
```

---

**Version** : 1.0  
**Date** : 19 février 2026  
**Compatibilité** : Node.js 12+, Python 3.8+
