# 🔄 Système de Surveillance Automatique des Crédits

## Vue d'ensemble

Le système de surveillance automatique détecte en temps réel les changements de crédit des clients et envoie automatiquement des webhooks au serveur Node.js sans nécessiter d'appel manuel.

## 🚀 Fonctionnement

### Démarrage automatique

Le scheduler démarre automatiquement au lancement de l'application FastAPI :

```bash
python3 -m uvicorn main:app --host 0.0.0.0 --port 8002
```

### Cycle de surveillance

1. **Toutes les X secondes** (configurable via `CREDIT_CHECK_INTERVAL`), le scheduler :
   - Se connecte à Odoo
   - Récupère tous les clients actifs
   - Compare le crédit actuel avec le crédit en cache
   - Détecte les augmentations de crédit

2. **Quand un crédit augmente** :
   - Log l'événement
   - Encrypte les données avec RSA-OAEP
   - Envoie le webhook au serveur Node.js
   - Met à jour le cache

3. **Le serveur Node.js reçoit** :
   ```http
   POST https://api-jnp-dev.opensi.co/public/odoo/webhook
   x-encrypted-data: <données_encryptées_base64>
   ```

## ⚙️ Configuration

### Variables d'environnement (.env)

```bash
# Intervalle de vérification (en secondes)
CREDIT_CHECK_INTERVAL=60  # 1 minute par défaut

# URL du webhook
FUEL_WEBHOOK_URL=https://api-jnp-dev.opensi.co/public/odoo/webhook

# Timeout des requêtes webhook (en secondes)
FUEL_WEBHOOK_TIMEOUT=10

# Configuration Odoo (nécessaire pour le scheduler)
ODOO_URL=https://votre-instance.odoo.com
ODOO_DB=votre-database
ODOO_USERNAME=votre-email
ODOO_PASSWORD=votre-mot-de-passe
```

### Ajuster l'intervalle

Pour vérifier plus ou moins souvent :

```bash
# Vérifier toutes les 30 secondes
CREDIT_CHECK_INTERVAL=30

# Vérifier toutes les 5 minutes
CREDIT_CHECK_INTERVAL=300

# Vérifier toutes les 10 secondes (attention à la charge Odoo!)
CREDIT_CHECK_INTERVAL=10
```

## 📡 Endpoints de contrôle

### Vérifier le statut du scheduler

```http
GET /fuel-monitor/scheduler/status
Authorization: Bearer <token>
```

**Réponse :**
```json
{
  "success": true,
  "data": {
    "is_running": true,
    "cache_size": 45,
    "webhook_url": "https://api-jnp-dev.opensi.co/public/odoo/webhook",
    "check_interval_seconds": "60"
  },
  "message": "Scheduler actif"
}
```

### Démarrer le scheduler manuellement

```http
POST /fuel-monitor/scheduler/start
Authorization: Bearer <token>
```

Utile si vous l'avez arrêté précédemment.

### Arrêter le scheduler

```http
POST /fuel-monitor/scheduler/stop
Authorization: Bearer <token>
```

⚠️ **Attention** : Cela désactive la surveillance automatique !

### Forcer une vérification immédiate

```http
POST /fuel-monitor/scheduler/check-now
Authorization: Bearer <token>
```

Lance une vérification sans attendre le prochain cycle.

## 📊 Logs

### Logs du scheduler

Le scheduler produit des logs détaillés :

```
🚀 [SCHEDULER] Démarrage de la surveillance automatique des crédits
⏱️  [SCHEDULER] Intervalle de vérification: 60 secondes
🔗 [SCHEDULER] URL webhook: https://api-jnp-dev.opensi.co/public/odoo/webhook

✅ [SCHEDULER] Vérification terminée: 234 clients, 2 changement(s) détecté(s)

💰 [SCHEDULER] Crédit augmenté: JSI VOYAGES (ID: 4708)
   - Ancien: 789685.0, Nouveau: 794685.0
   - Différence: +5000.0

📤 [SCHEDULER] Préparation webhook pour partner 4708
🔐 [SCHEDULER] Données encryptées (taille: 684 chars)
📤 [SCHEDULER] Envoi webhook: https://api-jnp-dev.opensi.co/public/odoo/webhook
✅ [SCHEDULER] Webhook envoyé avec succès pour partner 4708 - Montant: 5000.0 - Status: 200
```

### Niveaux de log

- **INFO** : Événements importants (démarrage, détections, webhooks envoyés)
- **DEBUG** : Détails de chaque vérification
- **WARNING** : Webhooks rejetés, problèmes mineurs
- **ERROR** : Erreurs de connexion, encryption, etc.

## 🔐 Format des données webhook

### Données envoyées (encryptées)

```json
{
  "action": "COMPANY_RECHARGE",
  "companyExternalId": "4708",
  "amount": 5000.0
}
```

### Encryption

- **Algorithme** : RSA-OAEP avec SHA256
- **Format** : Base64
- **Compression** : Désactivée (compatibilité Node.js)
- **Header** : `x-encrypted-data`

## 🧪 Tests

### Test complet du workflow

```bash
# 1. Vérifier que le scheduler tourne
curl -X GET "http://localhost:8002/fuel-monitor/scheduler/status" \
  -H "Authorization: Bearer $TOKEN"

# 2. Vider le cache pour forcer une détection
curl -X DELETE "http://localhost:8002/fuel-monitor/cache/clear?partner_id=4708" \
  -H "Authorization: Bearer $TOKEN"

# 3. Créer une écriture comptable
python3 test_accounting_quick.py

# 4. Forcer une vérification immédiate
curl -X POST "http://localhost:8002/fuel-monitor/scheduler/check-now" \
  -H "Authorization: Bearer $TOKEN"

# 5. Vérifier les logs pour le webhook envoyé
```

### Test du scheduler seul

```bash
# Démarrer le serveur
python3 -m uvicorn main:app --host 0.0.0.0 --port 8002

# Attendre le premier cycle (60 secondes)
# Observer les logs : [SCHEDULER] Vérification terminée...

# Créer une écriture comptable depuis Odoo ou via l'API
# Attendre le prochain cycle (max 60 secondes)
# Le webhook devrait être envoyé automatiquement
```

## 🔧 Dépannage

### Le scheduler ne démarre pas

**Vérifier :**
1. Les variables d'environnement Odoo sont configurées
2. Les credentials Odoo sont corrects
3. Les logs au démarrage de l'application

```bash
grep "SCHEDULER" /var/log/fastapi/app.log
```

### Les webhooks ne sont pas envoyés

**Vérifier :**
1. Le scheduler est actif : `GET /fuel-monitor/scheduler/status`
2. Les clés RSA sont chargées : logs de démarrage
3. L'URL du webhook est correcte
4. Le cache n'est pas vide (au moins un cycle effectué)

**Forcer une détection :**
```bash
# Vider le cache
curl -X DELETE "http://localhost:8002/fuel-monitor/cache/clear" \
  -H "Authorization: Bearer $TOKEN"

# Attendre un cycle complet ou forcer
curl -X POST "http://localhost:8002/fuel-monitor/scheduler/check-now" \
  -H "Authorization: Bearer $TOKEN"

# Créer une écriture comptable
# Le prochain cycle devrait détecter le changement
```

### Les webhooks sont rejetés (HTTP 401)

**Vérifier :**
1. Le format d'encryption (pas de compression)
2. Les clés RSA correspondent entre Python et Node.js
3. Le serveur Node.js utilise le bon padding (RSA_PKCS1_OAEP_PADDING + SHA256)

**Tester l'encryption :**
```python
from core.encryption import encrypt_webhook_data, get_rsa_encryption

data = {"action": "COMPANY_RECHARGE", "companyExternalId": "4708", "amount": 5000.0}
encrypted = encrypt_webhook_data(data, use_compression=False)
print(f"Taille: {len(encrypted)} chars")
print(f"Données: {encrypted[:100]}...")
```

### Le scheduler consomme trop de ressources

**Solutions :**
1. Augmenter l'intervalle : `CREDIT_CHECK_INTERVAL=300` (5 minutes)
2. Filtrer les partenaires surveillés (modification future)
3. Limiter le nombre de clients récupérés

## 📈 Performances

### Métriques typiques

- **Temps de vérification** : 2-5 secondes pour 200 clients
- **Mémoire** : ~50 MB pour le cache de 1000 clients
- **CPU** : < 5% pendant une vérification
- **Réseau** : 1-2 requêtes Odoo par cycle

### Optimisations

Le système est optimisé pour :
- ✅ Vérifier uniquement les clients actifs
- ✅ Limiter à 1000 clients max par cycle
- ✅ Utiliser un cache en mémoire (pas de base de données)
- ✅ Envoyer les webhooks en async
- ✅ Ne pas bloquer le serveur FastAPI

## 🚦 Workflow complet

```
┌─────────────────────────────────────────────────────────────────┐
│                      Démarrage FastAPI                          │
│                            ↓                                     │
│                  Scheduler démarre auto                         │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│                    Cycle toutes les 60s                         │
│  1. Connexion Odoo                                              │
│  2. Récupération clients actifs (res.partner)                   │
│  3. Comparaison crédit actuel vs cache                          │
│  4. Détection augmentations                                     │
└─────────────────────────────────────────────────────────────────┘
                              ↓
                    Crédit augmenté détecté ?
                              ↓
                            OUI
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│                     Envoi webhook                                │
│  1. Création payload JSON                                       │
│  2. Encryption RSA-OAEP (pas de compression)                    │
│  3. POST vers Node.js avec header x-encrypted-data             │
│  4. Log du résultat (200 = succès, 401 = rejeté)              │
└─────────────────────────────────────────────────────────────────┘
                              ↓
                    Mise à jour du cache
                              ↓
                    Attendre prochain cycle
```

## 📝 Notes importantes

1. **Le scheduler est indépendant** : Il ne nécessite pas d'appel API manuel
2. **Il surveille TOUS les clients** : Pas seulement ceux pour qui on a créé une écriture
3. **Il détecte TOUTE augmentation** : Quelle qu'en soit l'origine (paiement, ajustement, etc.)
4. **Les webhooks sont automatiques** : Envoyés dès qu'une augmentation est détectée
5. **Le système est résilient** : Continue même en cas d'erreurs temporaires

## 🎯 Cas d'usage

### Scénario 1 : Recharge via l'API accounting

```
1. Client crée écriture comptable → +5000 CFA
2. Scheduler détecte dans les 60s max
3. Webhook envoyé automatiquement
4. Node.js reçoit et traite
```

### Scénario 2 : Recharge manuelle dans Odoo

```
1. Comptable crée écriture dans Odoo → +10000 CFA
2. Scheduler détecte dans les 60s max
3. Webhook envoyé automatiquement
4. Node.js reçoit et traite
```

### Scénario 3 : Paiement client

```
1. Client paie facture → Crédit augmente
2. Scheduler détecte dans les 60s max
3. Webhook envoyé automatiquement
4. Node.js reçoit et traite
```

## 🔄 Migration depuis l'ancien système

### Avant (système manuel)

```python
# Il fallait appeler manuellement
GET /fuel-monitor/check-credit-changes?partner_id=4708
```

### Maintenant (système automatique)

```python
# Rien à faire ! Le scheduler s'en charge
# Créer simplement l'écriture comptable
POST /accounting/credit-account

# Le webhook sera envoyé automatiquement dans les 60s
```

## 📞 Support

En cas de problème :
1. Vérifier les logs : `grep "SCHEDULER" app.log`
2. Vérifier le statut : `GET /fuel-monitor/scheduler/status`
3. Forcer un check : `POST /fuel-monitor/scheduler/check-now`
4. Consulter cette documentation

---

**Version** : 1.0  
**Date** : 20 février 2026  
**Compatibilité** : FastAPI, Python 3.8+, Odoo 17
