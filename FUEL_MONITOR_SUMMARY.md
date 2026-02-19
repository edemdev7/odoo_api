# 📦 Résumé du Module Fuel Monitor

## ✅ Ce qui a été créé

### 1. Module API (`api/fuel_monitor.py`)
Module FastAPI qui surveille les changements du champ `credit` dans `res.partner`.

**Fonctionnalités** :
- ✅ Détection des augmentations de crédit
- ✅ Cache en mémoire pour comparaison
- ✅ Envoi automatique de webhooks
- ✅ Endpoints de gestion et monitoring

### 2. Scheduler Python (`fuel_monitor_scheduler.py`)
Script de surveillance automatique avec APScheduler.

**Fonctionnalités** :
- ✅ Vérification périodique (configurable)
- ✅ Initialisation automatique du cache
- ✅ Health checks
- ✅ Logging complet

### 3. Service Systemd (`fuel-monitor.service`)
Configuration pour exécution en tant que service système.

### 4. Documentation
- ✅ `FUEL_MONITOR_README.md` - Documentation technique
- ✅ `INSTALLATION_FUEL_MONITOR.md` - Guide d'installation

### 5. Configuration
- ✅ Variables d'environnement dans `.env`
- ✅ Dependencies dans `requirements.txt`

## 🎯 Workflow

```
┌─────────────────────────────────────────────────────────────┐
│  1. Client paie via Kkiapay ou autre                        │
└──────────────────────┬──────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────────┐
│  2. Odoo met à jour le champ 'credit' de res.partner       │
│     (Total Receivable augmente)                             │
└──────────────────────┬──────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────────┐
│  3. Scheduler appelle /fuel-monitor/check-credit-changes    │
│     (toutes les 2 minutes par défaut)                       │
└──────────────────────┬──────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────────┐
│  4. Le module compare avec le cache                         │
│     Détecte : ancien=450000, nouveau=503155                 │
│     Différence : +53155 CFA                                 │
└──────────────────────┬──────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────────┐
│  5. Webhook envoyé automatiquement :                        │
│     POST https://votre-api.com/webhook                      │
│     {                                                        │
│       "action": "COMPANY_RECHARGE",                         │
│       "companyExternalId": "123",                           │
│       "amount": 53155.0                                     │
│     }                                                        │
└──────────────────────┬──────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────────┐
│  6. Votre API traite la notification                        │
│     - Mettre à jour votre base de données                   │
│     - Envoyer notification au client                        │
│     - Déclencher autres actions métier                      │
└─────────────────────────────────────────────────────────────┘
```

## 🚀 Démarrage rapide

### 1. Configuration

```bash
# Dans .env
FUEL_WEBHOOK_URL=https://votre-api.com/api/webhook/fuel-recharge
```

### 2. Installation

```bash
pip install -r requirements.txt
```

### 3. Démarrer l'API

```bash
python main.py
# ou
uvicorn main:app --host 0.0.0.0 --port 8001
```

### 4. Initialiser le cache

```bash
curl -X POST "http://localhost:8001/fuel-monitor/initialize-cache" \
  -H "Authorization: Bearer YOUR_TOKEN"
```

### 5. Démarrer la surveillance

**Option A : Python Scheduler**
```bash
export JWT_TOKEN="your_token"
python fuel_monitor_scheduler.py
```

**Option B : Systemd**
```bash
sudo systemctl start fuel-monitor
```

**Option C : Cron**
```bash
*/2 * * * * curl -X GET "http://localhost:8001/fuel-monitor/check-credit-changes" -H "Authorization: Bearer YOUR_TOKEN"
```

## 📊 Endpoints disponibles

| Endpoint | Méthode | Description |
|----------|---------|-------------|
| `/fuel-monitor/check-credit-changes` | GET | Vérifier les changements et envoyer webhooks |
| `/fuel-monitor/initialize-cache` | POST | Initialiser le cache |
| `/fuel-monitor/cache-status` | GET | État du cache |
| `/fuel-monitor/manual-trigger` | POST | Test manuel du webhook |
| `/fuel-monitor/configure-webhook` | PUT | Configurer l'URL du webhook |

## 📝 Format du webhook

```json
{
  "action": "COMPANY_RECHARGE",
  "companyExternalId": "123",
  "amount": 50000.0
}
```

## 🔍 Monitoring

```bash
# Voir le cache
curl -X GET "http://localhost:8001/fuel-monitor/cache-status" \
  -H "Authorization: Bearer YOUR_TOKEN"

# Tester le webhook
curl -X POST "http://localhost:8001/fuel-monitor/manual-trigger?partner_id=123&amount=1000" \
  -H "Authorization: Bearer YOUR_TOKEN"
```

## 📋 Prochaines étapes

1. **Configurer l'URL du webhook** dans `.env`
2. **Créer votre endpoint** qui recevra les webhooks
3. **Tester** avec `manual-trigger`
4. **Déployer** en production avec systemd ou supervisor

## ⚠️ Notes importantes

- Le cache est **en mémoire** - perdu au redémarrage
- **Initialiser le cache** avant la première utilisation
- Le webhook est appelé **en arrière-plan** (non bloquant)
- Les erreurs de webhook sont **loggées** mais ne bloquent pas le système

## 📚 Documentation complète

- `FUEL_MONITOR_README.md` - Documentation technique détaillée
- `INSTALLATION_FUEL_MONITOR.md` - Guide d'installation pas à pas
