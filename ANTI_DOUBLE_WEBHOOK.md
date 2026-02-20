# 🔄 Stratégie Anti-Double Webhook

## Problème identifié

Sans protection, il y aurait **double envoi de webhook** :

```
Scénario sans protection:
1. API accounting créée écriture → Crédit passe de 100K à 105K
2. API accounting envoie webhook ✅ (+5K)
3. Scheduler vérifie 60s après → Détecte changement 100K → 105K
4. Scheduler envoie webhook ❌ (+5K encore)  → DOUBLON !
```

## Solution implémentée

### 🎯 Principe

- **L'API accounting** : Envoie le webhook **immédiatement** + met à jour le cache du scheduler
- **Le scheduler** : Surveille uniquement les changements **externes** (faits directement dans Odoo)

### 📝 Comment ça fonctionne

#### 1. Appel API accounting (`POST /accounting/credit-account`)

```python
# 1. Créer l'écriture comptable dans Odoo
move_id = client.execute_kw('account.move', 'create', [move_vals])

# 2. Récupérer le nouveau crédit
new_credit = 105000  # Exemple

# 3. MISE À JOUR DU CACHE SCHEDULER (empêche la double détection)
scheduler = get_scheduler()
scheduler.cache[partner_id] = {
    'credit': new_credit,  # ← Maintenant le scheduler connaît la nouvelle valeur
    'last_check': datetime.now()
}

# 4. ENVOI WEBHOOK IMMÉDIAT
background_tasks.add_task(send_recharge_webhook, partner_id, amount)
```

**Résultat** : Le webhook est envoyé immédiatement, et le cache est à jour.

#### 2. Scheduler vérifie 60s après

```python
# Le scheduler récupère le crédit actuel d'Odoo
current_credit = 105000

# Il compare avec le cache
cached_credit = scheduler.cache[partner_id]['credit']  # 105000

# Différence = 0 → Pas de changement → Pas de webhook ✅
if current_credit - cached_credit > 0.01:
    send_webhook()  # ← Ne sera PAS exécuté
```

**Résultat** : Aucun webhook envoyé par le scheduler (déjà envoyé par l'API).

### 🔄 Cas d'usage

#### Cas 1 : Recharge via API accounting

```
1. POST /accounting/credit-account → +5000 CFA
   ├─ Écriture créée dans Odoo
   ├─ Cache mis à jour : 105000
   └─ Webhook envoyé immédiatement ✅

2. Scheduler vérifie 60s après
   ├─ Crédit Odoo : 105000
   ├─ Cache : 105000
   └─ Différence = 0 → Pas de webhook ✅
```

**Résultat** : 1 seul webhook envoyé ✅

#### Cas 2 : Recharge manuelle dans Odoo

```
1. Comptable crée écriture dans Odoo → +10000 CFA
   └─ Aucun appel API (changement externe)

2. Scheduler vérifie 60s après
   ├─ Crédit Odoo : 115000
   ├─ Cache : 105000 (valeur avant le changement manuel)
   ├─ Différence = +10000
   └─ Webhook envoyé ✅
```

**Résultat** : 1 webhook envoyé par le scheduler ✅

#### Cas 3 : Double recharge (API + Odoo)

```
1. POST /accounting/credit-account → +5000 CFA
   ├─ Cache mis à jour : 105000
   └─ Webhook envoyé (+5000) ✅

2. Comptable ajoute +3000 dans Odoo (30s après)
   └─ Crédit Odoo passe à 108000

3. Scheduler vérifie 60s après l'API
   ├─ Crédit Odoo : 108000
   ├─ Cache : 105000
   ├─ Différence = +3000 (seulement le changement manuel)
   └─ Webhook envoyé (+3000) ✅
```

**Résultat** : 2 webhooks, mais pour 2 opérations différentes ✅

## 📊 Schéma de fonctionnement

```
┌─────────────────────────────────────────────────────────────────┐
│                    API Accounting appelée                        │
│                                                                  │
│  1. Créer écriture dans Odoo                                    │
│  2. Nouveau crédit = 105000                                     │
│  3. Mettre à jour cache[partner_id] = 105000  ← IMPORTANT       │
│  4. Envoyer webhook immédiatement (+5000)                       │
└─────────────────────────────────────────────────────────────────┘
                              ↓
                    ⏱️  60 secondes passent
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│                     Scheduler vérifie                            │
│                                                                  │
│  1. Récupérer crédit Odoo = 105000                              │
│  2. Comparer avec cache = 105000                                │
│  3. Différence = 0                                              │
│  4. Pas de webhook envoyé ✅                                     │
└─────────────────────────────────────────────────────────────────┘
```

## 🔐 Sécurité du cache

### Cache partagé

Le cache est **partagé** entre l'API accounting et le scheduler :

```python
# core/background_scheduler.py
class CreditMonitorScheduler:
    def __init__(self):
        self.cache: Dict[int, Dict[str, Any]] = {}  # Cache partagé

# api/accounting.py
scheduler = get_scheduler()  # Récupère la même instance
scheduler.cache[partner_id] = {...}  # Mise à jour directe
```

### Synchronisation

- **Pas de problème de concurrence** : Python GIL (Global Interpreter Lock)
- **Accès atomique** : Les opérations sur le dict sont thread-safe en CPython
- **Pas de lock nécessaire** : Le scheduler et l'API tournent dans le même processus

## 🧪 Tests

### Test 1 : Vérifier que l'API met à jour le cache

```python
# Avant
scheduler = get_scheduler()
print(f"Cache avant : {scheduler.cache.get(4708)}")

# Créer écriture via API
response = requests.post("/accounting/credit-account", ...)

# Après
print(f"Cache après : {scheduler.cache.get(4708)}")
# Devrait afficher la nouvelle valeur
```

### Test 2 : Vérifier qu'il n'y a pas de doublon

```bash
# 1. Vider le cache
curl -X DELETE "/fuel-monitor/cache/clear?partner_id=4708"

# 2. Créer écriture via API
python3 test_accounting_quick.py

# 3. Observer les logs
grep "Webhook envoyé" logs.txt
# Devrait voir 1 seul webhook

# 4. Attendre 60s pour le scheduler
sleep 65

# 5. Vérifier les logs
grep "Webhook envoyé" logs.txt
# Devrait toujours voir 1 seul webhook (pas de doublon)
```

### Test 3 : Vérifier que le scheduler détecte les changements externes

```bash
# 1. Créer écriture via API
python3 test_accounting_quick.py

# 2. Attendre 30s
sleep 30

# 3. Créer écriture manuellement dans Odoo (+3000)

# 4. Attendre 60s
sleep 60

# 5. Vérifier les logs
grep "Webhook envoyé" logs.txt
# Devrait voir 2 webhooks :
# - 1 de l'API (immédiat)
# - 1 du scheduler (changement manuel détecté)
```

## 📝 Code clé

### API Accounting (mise à jour du cache)

```python
# api/accounting.py ligne ~280

# Récupérer le nouveau crédit
new_credit = updated_partner[0]['credit']

# Mettre à jour le cache du scheduler
scheduler = get_scheduler()
scheduler.cache[partner_id] = {
    'credit': new_credit,
    'last_check': datetime.now()
}

# Envoyer le webhook
background_tasks.add_task(send_recharge_webhook, partner_id, amount)
```

### Scheduler (vérification du cache)

```python
# core/background_scheduler.py ligne ~80

for partner in partners:
    current_credit = float(partner['credit'])
    
    # Comparer avec le cache
    if partner_id in self.cache:
        previous_credit = self.cache[partner_id]['credit']
        credit_increase = current_credit - previous_credit
        
        # Envoyer webhook seulement si augmentation détectée
        if credit_increase > 0.01:
            await self.send_webhook(partner_id, credit_increase)
    
    # Mettre à jour le cache
    self.cache[partner_id] = {
        'credit': current_credit,
        'last_check': datetime.now()
    }
```

## ✅ Avantages de cette approche

1. **Pas de doublon** : Le cache empêche la double détection
2. **Webhooks immédiats** : L'API envoie directement (pas d'attente de 60s)
3. **Détection externe** : Le scheduler surveille quand même les changements manuels
4. **Simple** : Pas besoin de base de données externe
5. **Performant** : Cache en mémoire, très rapide

## ⚠️ Limitations

1. **Redémarrage** : Le cache est perdu au redémarrage (mais se reconstruit au premier cycle)
2. **Multi-instance** : Si plusieurs instances FastAPI, chaque instance a son propre cache
   - Solution : Utiliser Redis pour un cache partagé (amélioration future)

## 🚀 Amélioration future (si nécessaire)

Si vous avez **plusieurs instances FastAPI** (load balancing), utilisez Redis :

```python
import redis

# Cache Redis au lieu de dict Python
redis_client = redis.Redis(host='localhost', port=6379)

# Mise à jour
redis_client.hset(f'credit_cache:{partner_id}', 'credit', new_credit)

# Lecture
cached_credit = redis_client.hget(f'credit_cache:{partner_id}', 'credit')
```

---

**Version** : 1.0  
**Date** : 20 février 2026  
**Status** : ✅ Implémenté et testé
