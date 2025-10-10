# Endpoint Unifié - Ouverture de Session POS

## 🎯 Objectif

Unifier les deux endpoints d'ouverture de session en un seul endpoint intelligent qui détecte automatiquement le mode d'ouverture selon les données fournies.

## 🔄 Changements

### Avant (2 endpoints)
- `POST /pos/{pos_id}/open-session` - Ouverture standard
- `POST /pos/{pos_id}/open-session-with-pumps` - Ouverture avec pompes

### Après (1 endpoint unifié)
- `POST /pos/{pos_id}/open-session` - Ouverture intelligente

## 📋 Schémas supportés

### Mode Standard (Caisse normale)
```json
{
  "starting_balance": 1000.00,
  "opening_notes": "Ouverture matinale"
}
```

**Comportement :**
- Crée une nouvelle session POS
- Définit le solde de départ
- Ouvre immédiatement la session
- Retourne `is_station: false`

### Mode Station-service (Avec pompes)
```json
{
  "session_id": 123,
  "pump_indexes": [
    {
      "id": "pump_001",
      "name": "J1_E1",
      "stationId": "station_001", 
      "type": "PETROL",
      "start_index": 1234.56
    }
  ]
}
```

**Comportement :**
- Utilise une session existante
- Enregistre les données des pompes
- Ouvre la session avec validation
- Retourne `is_station: true`

## 🧠 Logique de détection

```python
is_pump_mode = request.pump_indexes is not None and len(request.pump_indexes) > 0
is_standard_mode = request.starting_balance is not None or request.opening_notes is not None

if is_pump_mode and is_standard_mode:
    # Erreur 400 - Données ambiguës
    
if not is_pump_mode and not is_standard_mode:
    # Erreur 400 - Données manquantes
```

## ✅ Validations

### Mode Standard
- ✅ `starting_balance` et/ou `opening_notes` fournis
- ✅ Aucune donnée de pompe
- ✅ PDV valide

### Mode Station-service  
- ✅ `session_id` obligatoire
- ✅ `pump_indexes` non vide
- ✅ Session existante et valide
- ✅ Session appartient au bon PDV

### Cas d'erreur
- ❌ Données mixtes (standard + pompes)
- ❌ Aucune donnée fournie
- ❌ Session inexistante (mode pompes)
- ❌ Session_id manquant (mode pompes)

## 📊 Réponse unifiée

```json
{
  "session_id": 123,
  "pos_id": 1,
  "pos_name": "Caisse Principale",
  "is_station": false,
  "state": "opened",
  "message": "Session standard ouverte - Solde: 1000.0"
}
```

## 🔧 Migration

### Code client existant

**Ancien code :**
```javascript
// Pour station-service
await fetch('/pos/1/open-session-with-pumps', {
  method: 'POST',
  body: JSON.stringify({
    session_id: 123,
    pump_indexes: [...]
  })
});

// Pour caisse standard  
await fetch('/pos/1/open-session', {
  method: 'POST', 
  body: JSON.stringify({
    session_id: 123
  })
});
```

**Nouveau code :**
```javascript
// Pour station-service (aucun changement de schéma)
await fetch('/pos/1/open-session', {
  method: 'POST',
  body: JSON.stringify({
    session_id: 123,
    pump_indexes: [...]
  })
});

// Pour caisse standard (nouveau schéma)
await fetch('/pos/1/open-session', {
  method: 'POST',
  body: JSON.stringify({
    starting_balance: 1000.00,
    opening_notes: "Ouverture"
  })
});
```

## 🧪 Tests

Exécuter le script de test :
```bash
python test_unified_open_session.py
```

**Tests inclus :**
1. ✅ Mode standard avec solde
2. ✅ Mode station-service avec pompes  
3. ❌ Données ambiguës (doit échouer)
4. ❌ Données vides (doit échouer)

## 📝 Notes importantes

1. **Backward compatibility** : L'ancien endpoint `/open-session-with-pumps` est supprimé
2. **Détection automatique** : Plus besoin de choisir l'endpoint selon le mode
3. **Validation stricte** : Impossible de mélanger les modes
4. **Logs détaillés** : Chaque mode produit des logs spécifiques
5. **Gestion d'erreurs** : Messages d'erreur clairs selon le contexte

## 🚀 Avantages

- **Simplicité** : Un seul endpoint à retenir
- **Intelligence** : Détection automatique du mode
- **Maintenance** : Moins de code dupliqué
- **Flexibilité** : Facile d'ajouter de nouveaux modes
- **Validation** : Contrôles stricts des données
