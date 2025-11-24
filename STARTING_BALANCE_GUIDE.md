# Guide du Starting Balance (Solde d'Ouverture)

## 📖 Vue d'ensemble

Le `starting_balance` (solde d'ouverture) est le montant en espèces présent dans la caisse au moment de l'ouverture d'une session POS. C'est une donnée critique pour:
- ✅ Assurer la continuité comptable entre les sessions
- ✅ Détecter les écarts de caisse
- ✅ Faciliter les rapprochements de fin de journée

## 🔄 Logique du Starting Balance

### Principe Fondamental

**Le solde d'ouverture d'une nouvelle session DEVRAIT correspondre au solde de fermeture de la session précédente.**

```
Session N (fermée):
├─ Solde ouverture: 1000 €
├─ Ventes: +2500 €
├─ Dépenses: -200 €
└─ Solde fermeture: 3300 €

Session N+1 (nouvelle):
└─ Solde ouverture: 3300 € ← Provient du solde de fermeture de Session N
```

### Cas Particuliers

#### 1. **Dépôt bancaire entre les sessions**
Si l'argent est déposé à la banque:
```
Session N fermeture: 3300 €
Dépôt bancaire: -3000 €
→ Session N+1 ouverture: 300 € (fonds de caisse minimal)
```

#### 2. **Ajout de monnaie**
Si on ajoute de la monnaie:
```
Session N fermeture: 500 €
Ajout de monnaie: +500 €
→ Session N+1 ouverture: 1000 €
```

#### 3. **Première session du PDV**
Aucune session précédente:
```
→ Session 1 ouverture: 0 € ou montant initial décidé par le gérant
```

## 🎯 Comment Obtenir le Starting Balance Suggéré

### Endpoint: `GET /pos/{pos_id}/suggested-opening-balance`

Cet endpoint calcule automatiquement le solde d'ouverture suggéré selon la logique suivante:

```
┌─────────────────────────────────────┐
│ Une session est-elle ouverte ?      │
└────────────┬────────────────────────┘
             │
     ┌───────┴───────┐
     │ OUI           │ NON
     ▼               ▼
┌─────────────┐  ┌──────────────────────────┐
│ Retourner   │  │ Chercher dernière        │
│ le solde    │  │ session fermée           │
│ actuel      │  └────────┬─────────────────┘
└─────────────┘           │
                  ┌───────┴───────┐
                  │ Trouvée ?     │
                  └───┬───────────┘
                  ┌───┴───┐
                  │ OUI   │ NON
                  ▼       ▼
            ┌─────────┐  ┌─────────┐
            │ Solde   │  │ Retourner│
            │ de      │  │ 0.00     │
            │ fermeture│  └─────────┘
            └─────────┘
```

### Exemple de Requête

```bash
curl -X GET "https://api.example.com/pos/1/suggested-opening-balance" \
  -H "Authorization: Bearer <votre_token>"
```

### Exemple de Réponse

**Scénario 1: Session précédente fermée**
```json
{
  "success": true,
  "message": "Solde suggéré: 3300.50 (source: last_closed_session)",
  "data": {
    "pos_id": 1,
    "pos_name": "Station Service ABC",
    "suggested_balance": 3300.50,
    "last_session_id": 456,
    "last_session_state": "closed",
    "last_closing_date": "2025-11-23 22:30:00",
    "source": "last_closed_session",
    "cash_control_enabled": true,
    "recommendation": {
      "message": "Utilisez 3300.50 comme solde de départ",
      "source_description": "Solde de fermeture de la dernière session"
    }
  }
}
```

**Scénario 2: Aucune session précédente**
```json
{
  "success": true,
  "message": "Solde suggéré: 0.00 (source: default)",
  "data": {
    "pos_id": 2,
    "pos_name": "Nouvelle Caisse",
    "suggested_balance": 0.00,
    "last_session_id": null,
    "last_session_state": null,
    "last_closing_date": null,
    "source": "default",
    "cash_control_enabled": true,
    "recommendation": {
      "message": "Aucune session précédente. Comptez votre caisse et entrez le montant réel.",
      "source_description": "Aucune session précédente trouvée"
    }
  }
}
```

**Scénario 3: Session actuellement ouverte**
```json
{
  "success": true,
  "message": "Solde suggéré: 1250.75 (source: current_session)",
  "data": {
    "pos_id": 1,
    "pos_name": "Station Service ABC",
    "suggested_balance": 1250.75,
    "last_session_id": 457,
    "last_session_state": "opened",
    "last_closing_date": null,
    "source": "current_session",
    "cash_control_enabled": true,
    "recommendation": {
      "message": "Utilisez 1250.75 comme solde de départ",
      "source_description": "Solde actuel de la session en cours"
    }
  }
}
```

## 💼 Workflow Complet d'Ouverture de Session

### 1. Récupérer le Solde Suggéré

```javascript
// Frontend: Avant d'afficher le formulaire d'ouverture
const response = await fetch('/pos/1/suggested-opening-balance', {
  headers: { 'Authorization': `Bearer ${token}` }
});

const { data } = await response.json();
const suggestedBalance = data.suggested_balance;
const recommendation = data.recommendation.message;

// Afficher à l'utilisateur
console.log(`Solde suggéré: ${suggestedBalance} €`);
console.log(`Recommandation: ${recommendation}`);
```

### 2. Afficher le Formulaire Pré-rempli

```html
<form id="openSessionForm">
  <h3>Ouverture de Session</h3>
  
  <div class="info-box">
    <p><strong>Dernière session fermée:</strong> #456 (23/11/2025 22:30)</p>
    <p><strong>Solde de fermeture:</strong> 3300.50 €</p>
  </div>
  
  <label for="startingBalance">Solde d'ouverture (€):</label>
  <input 
    type="number" 
    id="startingBalance" 
    name="starting_balance"
    value="3300.50"
    step="0.01"
    required
  />
  
  <div class="recommendation">
    💡 Utilisez 3300.50 € comme solde de départ
    (solde de fermeture de la dernière session)
  </div>
  
  <label for="openingNotes">Notes d'ouverture (optionnel):</label>
  <textarea id="openingNotes" name="opening_notes"></textarea>
  
  <button type="submit">Ouvrir la Session</button>
</form>
```

### 3. Valider et Ajuster si Nécessaire

```javascript
// Le gérant peut ajuster le montant si nécessaire
document.getElementById('openSessionForm').onsubmit = async (e) => {
  e.preventDefault();
  
  const startingBalance = parseFloat(document.getElementById('startingBalance').value);
  const openingNotes = document.getElementById('openingNotes').value;
  
  // Si le montant diffère du suggéré, demander confirmation
  if (Math.abs(startingBalance - suggestedBalance) > 0.01) {
    const confirmed = confirm(
      `Le montant saisi (${startingBalance} €) diffère du solde suggéré (${suggestedBalance} €). ` +
      `Êtes-vous sûr de vouloir continuer ?`
    );
    
    if (!confirmed) return;
  }
  
  // Ouvrir la session
  await openSession(startingBalance, openingNotes);
};
```

### 4. Ouvrir la Session

```javascript
async function openSession(startingBalance, openingNotes) {
  const response = await fetch('/pos/1/open-session', {
    method: 'POST',
    headers: {
      'Authorization': `Bearer ${token}`,
      'Content-Type': 'application/json'
    },
    body: JSON.stringify({
      starting_balance: startingBalance,
      opening_notes: openingNotes || `Solde suggéré: ${suggestedBalance} €`
    })
  });
  
  const result = await response.json();
  
  if (result.session_id) {
    console.log(`Session ${result.session_id} ouverte avec succès!`);
    console.log(`Solde de départ: ${startingBalance} €`);
  }
}
```

## 📊 Champs Odoo Impliqués

### Modèle: `pos.session`

| Champ | Type | Description |
|-------|------|-------------|
| `cash_register_balance_start` | Float | **Solde d'ouverture** - Montant en caisse au début |
| `cash_register_balance_end_real` | Float | **Solde de fermeture réel** - Montant compté en fin de session |
| `cash_register_balance_end` | Float | Solde théorique calculé (ouverture + ventes - dépenses) |
| `cash_register_difference` | Float | Écart = `end_real` - `end` (calculé automatiquement) |
| `state` | Selection | État: `new`, `opening_control`, `opened`, `closing_control`, `closed` |
| `stop_at` | Datetime | Date/heure de fermeture |

### Exemple de Données

```python
# Session N (fermée)
{
    'id': 456,
    'config_id': [1, 'Station ABC'],
    'state': 'closed',
    'cash_register_balance_start': 1000.00,  # Ouverture
    'cash_register_balance_end': 3305.00,    # Théorique
    'cash_register_balance_end_real': 3300.50, # Compté réellement
    'cash_register_difference': -4.50,        # Écart
    'stop_at': '2025-11-23 22:30:00'
}

# Session N+1 (à ouvrir)
{
    'config_id': [1, 'Station ABC'],
    'state': 'opening_control',
    'cash_register_balance_start': 3300.50,  # ← Provient de end_real de Session N
}
```

## ⚠️ Cas d'Erreurs et Solutions

### Erreur 1: Solde suggéré = 0 alors qu'il devrait y avoir un montant

**Causes possibles:**
1. La session précédente a `cash_register_balance_end_real` = NULL ou 0
2. La session précédente n'a pas été fermée correctement
3. Le champ `stop_at` est NULL (bug connu dans certaines versions Odoo)

**Solution:**
```python
# Vérifier dans Odoo
session = env['pos.session'].browse(456)
print(f"État: {session.state}")
print(f"Solde fermeture: {session.cash_register_balance_end_real}")
print(f"Date fermeture: {session.stop_at}")

# Si manquant, corriger:
session.write({
    'cash_register_balance_end_real': 3300.50,
    'stop_at': fields.Datetime.now()
})
```

### Erreur 2: "Une session est déjà active"

**Cause:** Une session est ouverte mais pas fermée.

**Solution:**
```bash
# Vérifier l'état de la session
GET /pos/1/session-status

# Fermer la session active si nécessaire
POST /pos/1/close-session
{
  "ending_balance": 3300.50,
  "closing_notes": "Fermeture automatique"
}
```

### Erreur 3: Écart important entre suggéré et réel

**Cause:** Dépôt bancaire, vol, erreur de comptage.

**Solution:** Documenter dans `opening_notes`:
```json
{
  "starting_balance": 500.00,
  "opening_notes": "Solde précédent: 3300.50 €. Dépôt bancaire de 2800 € effectué le 23/11."
}
```

## 🔐 Contrôle de Caisse (Cash Control)

### Activation

Le champ `cash_control` sur `pos.config` active/désactive les contrôles:

```python
# Dans Odoo
pos_config.cash_control = True  # Activer les contrôles stricts
```

### Comportement avec Cash Control = True

1. **À l'ouverture:**
   - Le gérant DOIT saisir le `starting_balance`
   - Odoo bloque si le montant n'est pas saisi

2. **À la fermeture:**
   - Le gérant DOIT compter et saisir le `ending_balance`
   - Odoo calcule automatiquement l'écart
   - Si écart > seuil configuré → alerte

3. **Entre sessions:**
   - Le système suggère automatiquement le solde de fermeture précédent

### Comportement avec Cash Control = False

1. Pas de contrôle strict des montants
2. Les champs de solde restent optionnels
3. Aucun calcul d'écart automatique

## 📈 Bonnes Pratiques

### ✅ À Faire

1. **Toujours utiliser le solde suggéré** sauf raison valable
2. **Documenter les écarts** dans `opening_notes`
3. **Vérifier physiquement** la caisse avant d'ouvrir
4. **Former les gérants** sur l'importance de la continuité
5. **Auditer régulièrement** les écarts entre sessions

### ❌ À Éviter

1. Saisir des montants arbitraires sans justification
2. Ignorer les écarts importants
3. Ne pas documenter les opérations exceptionnelles (dépôts, ajouts)
4. Ouvrir plusieurs sessions sans fermer les précédentes

## 🧪 Tests

### Test 1: Première Session

```bash
# Aucune session précédente
GET /pos/1/suggested-opening-balance
# Attendu: suggested_balance = 0.00, source = "default"

POST /pos/1/open-session
{
  "starting_balance": 1000.00,
  "opening_notes": "Première session - Fonds de caisse initial"
}
```

### Test 2: Continuité Normale

```bash
# Session précédente fermée avec 3300.50 €
GET /pos/1/suggested-opening-balance
# Attendu: suggested_balance = 3300.50, source = "last_closed_session"

POST /pos/1/open-session
{
  "starting_balance": 3300.50,
  "opening_notes": "Ouverture normale"
}
```

### Test 3: Dépôt Bancaire

```bash
# Session précédente: 3300.50 €
GET /pos/1/suggested-opening-balance
# Attendu: suggested_balance = 3300.50

POST /pos/1/open-session
{
  "starting_balance": 500.00,
  "opening_notes": "Dépôt bancaire de 2800 € effectué (reçu n°12345)"
}
```

## 📞 Support

Pour toute question sur la gestion du starting_balance:
1. Consultez les logs de l'API pour les détails des calculs
2. Vérifiez l'état des sessions dans Odoo via Menu > Point de Vente > Sessions
3. Contactez l'administrateur système si les données sont incohérentes

---

**Dernière mise à jour:** 24 novembre 2025
**Version:** 1.0.0
