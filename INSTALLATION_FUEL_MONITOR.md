# 🚀 Installation et Configuration du Fuel Monitor

## Installation des dépendances

```bash
pip install -r requirements.txt
```

Cela installera notamment :
- `httpx` : pour les appels HTTP asynchrones
- `APScheduler` : pour la surveillance automatique

## Configuration

### 1. Variables d'environnement (.env)

Ajoutez dans votre fichier `.env` :

```bash
# URL du webhook à appeler quand un compte est crédité
FUEL_WEBHOOK_URL=https://votre-api.com/api/webhook/fuel-recharge

# Timeout pour les appels webhook (en secondes)
FUEL_WEBHOOK_TIMEOUT=10
```

### 2. Token JWT

Créez un token JWT pour l'authentification :

```bash
# Se connecter à l'API
curl -X POST "http://localhost:8001/auth/login" \
  -H "Content-Type: application/json" \
  -d '{
    "username": "admin",
    "password": "votre_password"
  }'
```

Copiez le `access_token` retourné.

## Utilisation

### Option 1 : Surveillance manuelle (API REST)

#### 1. Initialiser le cache

```bash
curl -X POST "http://localhost:8001/fuel-monitor/initialize-cache" \
  -H "Authorization: Bearer YOUR_JWT_TOKEN"
```

#### 2. Vérifier les changements

```bash
curl -X GET "http://localhost:8001/fuel-monitor/check-credit-changes" \
  -H "Authorization: Bearer YOUR_JWT_TOKEN"
```

#### 3. Tester le webhook

```bash
curl -X POST "http://localhost:8001/fuel-monitor/manual-trigger?partner_id=123&amount=50000" \
  -H "Authorization: Bearer YOUR_JWT_TOKEN"
```

### Option 2 : Surveillance automatique (Python Scheduler)

#### 1. Configurer le token

```bash
export JWT_TOKEN="votre_jwt_token_ici"
export API_BASE_URL="http://localhost:8001"
export CHECK_INTERVAL_SECONDS="120"  # 2 minutes
```

#### 2. Lancer le scheduler

```bash
python fuel_monitor_scheduler.py
```

Le scheduler va :
- Initialiser le cache au démarrage
- Vérifier les changements toutes les 2 minutes
- Envoyer automatiquement les webhooks
- Logger toutes les actions dans `fuel_monitor.log`

### Option 3 : Surveillance automatique (Systemd Service)

Pour une utilisation en production :

#### 1. Modifier le service

Éditez `fuel-monitor.service` et remplacez :
- `YOUR_JWT_TOKEN_HERE` par votre token JWT
- Les chemins si nécessaire

#### 2. Installer le service

```bash
sudo cp fuel-monitor.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable fuel-monitor
sudo systemctl start fuel-monitor
```

#### 3. Vérifier le status

```bash
sudo systemctl status fuel-monitor
sudo journalctl -u fuel-monitor -f  # Logs en temps réel
```

### Option 4 : Cron Job (Simple)

Ajoutez dans votre crontab :

```bash
# Vérifier toutes les 2 minutes
*/2 * * * * curl -X GET "http://localhost:8001/fuel-monitor/check-credit-changes" -H "Authorization: Bearer YOUR_TOKEN" >> /var/log/fuel-monitor-cron.log 2>&1
```

## Endpoints disponibles

### GET /fuel-monitor/check-credit-changes
Vérifier les changements et envoyer les webhooks.

**Paramètres** :
- `partner_id` (optionnel) : ID spécifique
- `since_minutes` (optionnel) : Période de vérification

### POST /fuel-monitor/initialize-cache
Initialiser le cache avec les valeurs actuelles.

### GET /fuel-monitor/cache-status
Afficher l'état du cache.

### POST /fuel-monitor/manual-trigger
Déclencher manuellement un webhook (test).

**Paramètres** :
- `partner_id` (requis)
- `amount` (requis)

### PUT /fuel-monitor/configure-webhook
Configurer l'URL du webhook.

**Paramètres** :
- `webhook_url` (requis)

## Format du webhook envoyé

```json
{
  "action": "COMPANY_RECHARGE",
  "companyExternalId": "123",
  "amount": 50000.0
}
```

**Champs** :
- `action` : Toujours "COMPANY_RECHARGE"
- `companyExternalId` : ID de l'entreprise dans Odoo (res.partner)
- `amount` : Montant ajouté au crédit (en CFA ou devise configurée)

## Logs

### Logs du scheduler Python
```bash
tail -f fuel_monitor.log
```

### Logs du service systemd
```bash
sudo journalctl -u fuel-monitor -f
```

### Logs de l'API FastAPI
```bash
# Selon votre configuration uvicorn
tail -f /var/log/odoo-api.log
```

## Dépannage

### Le webhook n'est pas envoyé

1. Vérifier que le cache est initialisé :
```bash
curl -X GET "http://localhost:8001/fuel-monitor/cache-status" \
  -H "Authorization: Bearer YOUR_TOKEN"
```

2. Vérifier l'URL du webhook :
```bash
echo $FUEL_WEBHOOK_URL
```

3. Tester manuellement :
```bash
curl -X POST "http://localhost:8001/fuel-monitor/manual-trigger?partner_id=123&amount=1000" \
  -H "Authorization: Bearer YOUR_TOKEN"
```

### Le crédit change mais pas de détection

- Vérifier que le cache est initialisé
- S'assurer que l'intervalle de vérification couvre la période du changement
- Vérifier les logs pour voir si le changement est détecté

### Erreur 401 (Unauthorized)

- Token JWT expiré → Se reconnecter
- Token invalide → Vérifier le token

### Erreur de connexion à Odoo

- Vérifier les credentials dans `.env`
- Tester la connexion Odoo via `/health`

## Monitoring

Pour surveiller l'état du système :

```bash
# Status du cache
curl -X GET "http://localhost:8001/fuel-monitor/cache-status" \
  -H "Authorization: Bearer YOUR_TOKEN"

# Health check de l'API
curl -X GET "http://localhost:8001/health"
```

## Sécurité

⚠️ **Important** :
- Ne commitez JAMAIS les tokens JWT dans Git
- Utilisez des variables d'environnement pour les secrets
- Protégez l'endpoint webhook avec HTTPS
- Validez les données reçues côté webhook

## Production

Pour la production, il est recommandé de :
1. Utiliser le service systemd
2. Configurer un reverse proxy (Nginx)
3. Activer HTTPS
4. Mettre en place un système de monitoring (Prometheus, Grafana)
5. Configurer des alertes en cas d'erreur
