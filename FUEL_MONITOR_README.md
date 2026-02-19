# 🔔 Module de Surveillance des Comptes Fuel

Ce module surveille automatiquement les changements du champ `credit` (Total Receivable) des entreprises clientes dans Odoo et envoie un webhook lorsqu'une recharge est détectée.

## 📋 Fonctionnement

### 1. Champ surveillé
- **Modèle Odoo**: `res.partner`
- **Champ**: `credit` (Total Receivable / Créances totales)
- **Type**: monetary

Quand un client paie via Kkiapay ou autre moyen, Odoo met à jour le champ `credit` du partenaire.

### 2. Détection des changements
Le système compare périodiquement les valeurs actuelles de `credit` avec un cache en mémoire pour détecter les augmentations.

### 3. Webhook envoyé
Quand une augmentation est détectée, un webhook est envoyé à votre endpoint avec ce format :

```json
{
  "action": "COMPANY_RECHARGE",
  "companyExternalId": "123",
  "amount": 50000.0
}
```

## 🚀 Utilisation

### Configuration

1. **Définir l'URL du webhook dans `.env`** :
```bash
FUEL_WEBHOOK_URL=https://votre-api.com/api/webhook/fuel-recharge
FUEL_WEBHOOK_TIMEOUT=10
```

2. **Ou configurer via l'API** :
```bash
curl -X PUT "http://localhost:8001/fuel-monitor/configure-webhook?webhook_url=https://votre-api.com/webhook" \
  -H "Authorization: Bearer YOUR_TOKEN"
```

### Initialisation

**Avant la première utilisation**, initialisez le cache avec les valeurs actuelles :

```bash
curl -X POST "http://localhost:8001/fuel-monitor/initialize-cache" \
  -H "Authorization: Bearer YOUR_TOKEN"
```

### Surveillance manuelle

Pour vérifier les changements :

```bash
curl -X GET "http://localhost:8001/fuel-monitor/check-credit-changes" \
  -H "Authorization: Bearer YOUR_TOKEN"
```

**Paramètres optionnels** :
- `partner_id`: ID d'un client spécifique
- `since_minutes`: Période de vérification (défaut: 5 minutes)

### Surveillance automatique (Cron)

Pour une surveillance continue, configurez un cron qui appelle l'endpoint toutes les X minutes :

```bash
# Exemple de cron toutes les 2 minutes
*/2 * * * * curl -X GET "http://localhost:8001/fuel-monitor/check-credit-changes" -H "Authorization: Bearer YOUR_TOKEN" > /dev/null 2>&1
```

Ou utilisez un scheduler Python (APScheduler, Celery, etc.)

### Test manuel

Pour tester le webhook sans attendre un vrai paiement :

```bash
curl -X POST "http://localhost:8001/fuel-monitor/manual-trigger?partner_id=123&amount=50000" \
  -H "Authorization: Bearer YOUR_TOKEN"
```

## 📡 Endpoints disponibles

### `GET /fuel-monitor/check-credit-changes`
Vérifier les changements récents et envoyer les webhooks si nécessaire.

**Paramètres** :
- `partner_id` (optionnel) : ID du partenaire à vérifier
- `since_minutes` (optionnel) : Période de vérification (défaut: 5)

**Réponse** :
```json
{
  "success": true,
  "data": {
    "changes_detected": [
      {
        "partner_id": 123,
        "partner_name": "CORIS BANK POOL",
        "vat": "3201502709216",
        "previous_credit": 450000.0,
        "current_credit": 503155.0,
        "amount_added": 53155.0,
        "detected_at": "2026-02-18T10:30:00"
      }
    ],
    "total_partners_checked": 45,
    "cache_size": 45
  },
  "count": 1,
  "message": "1 changement(s) de crédit détecté(s)"
}
```

### `POST /fuel-monitor/initialize-cache`
Initialiser le cache avec les valeurs actuelles de crédit.

**Paramètres** :
- `partner_ids` (optionnel) : Liste des IDs à surveiller

### `GET /fuel-monitor/cache-status`
Afficher l'état actuel du cache de surveillance.

### `POST /fuel-monitor/manual-trigger`
Déclencher manuellement un webhook (pour tests).

**Paramètres** :
- `partner_id` (requis) : ID du partenaire
- `amount` (requis) : Montant de la recharge

### `PUT /fuel-monitor/configure-webhook`
Configurer l'URL du webhook dynamiquement.

**Paramètres** :
- `webhook_url` (requis) : Nouvelle URL du webhook

## 🔄 Workflow complet

```
1. Client paie via Kkiapay
   ↓
2. Kkiapay notifie Odoo (ou mise à jour manuelle)
   ↓
3. Odoo met à jour le champ 'credit' du res.partner
   ↓
4. Votre cron appelle /fuel-monitor/check-credit-changes
   ↓
5. Le système détecte l'augmentation du crédit
   ↓
6. Webhook envoyé à votre API :
   {
     "action": "COMPANY_RECHARGE",
     "companyExternalId": "123",
     "amount": 53155.0
   }
   ↓
7. Votre API traite la notification
```

## ⚠️ Important

1. **Initialiser le cache** avant la première utilisation
2. **Configurer l'URL du webhook** dans `.env` ou via l'API
3. **Mettre en place un cron** pour la surveillance automatique
4. Le cache est **en mémoire** - il sera perdu au redémarrage de l'API

## 🐛 Debugging

### Vérifier le cache
```bash
curl -X GET "http://localhost:8001/fuel-monitor/cache-status" \
  -H "Authorization: Bearer YOUR_TOKEN"
```

### Logs
Les logs affichent :
- ✅ Webhooks envoyés avec succès
- ❌ Erreurs de webhook
- 💰 Changements de crédit détectés
- ⏱️ Timeouts

### Test du webhook
```bash
curl -X POST "http://localhost:8001/fuel-monitor/manual-trigger?partner_id=123&amount=1000" \
  -H "Authorization: Bearer YOUR_TOKEN"
```

## 📝 TODO / Améliorations futures

- [ ] Persister le cache dans une base de données (Redis/PostgreSQL)
- [ ] Ajouter un système de retry pour les webhooks échoués
- [ ] Supporter plusieurs URLs de webhook
- [ ] Ajouter une interface de monitoring
- [ ] Implémenter un système de queue (RabbitMQ/Celery)
- [ ] Ajouter des alertes en cas d'erreur répétée
