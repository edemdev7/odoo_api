# Configuration des affectations PDV dans Odoo

## 🎯 Objectif
Configurer les points de vente auxquels chaque employé a accès dans Odoo pour que l'API retourne uniquement les PDV affectés.

## 📋 Champs utilisés

L'API utilise les champs suivants du modèle `pos.config` :

- **`basic_employee_ids`** : Employés avec accès basique au PDV
- **`advanced_employee_ids`** : Employés avec accès manager au PDV

## 📋 Étapes de configuration

### 1. **Accéder à la configuration des PDV**
```
Point de Vente > Configuration > Points de Vente
```

### 2. **Ouvrir un PDV spécifique**
- Cliquer sur le PDV à configurer
- Aller dans l'onglet "Employés"

### 3. **Affecter des employés**
- **Champ:** `basic_employee_ids` (Employés avec accès basique)
- **Champ:** `advanced_employee_ids` (Employés avec accès manager)
- **Type:** Many2many vers `hr.employee`
- **Action:** Ajouter les employés qui doivent avoir accès à ce PDV

### 4. **Exemple de configuration**

```
PDV "Caisse Principale":
  - Employés basiques: [Louise GBASSI, Jean MARTIN]
  - Employés managers: [Dossi Sylvie LEGBA]

PDV "Station Carburant":  
  - Employés basiques: [Pierre DURAND]
  - Employés managers: [Dossi Sylvie LEGBA]

PDV "Boutique Annexe":
  - Employés basiques: [Louise GBASSI]
```

## 🔍 Vérification

### Depuis l'interface Odoo:
1. Aller dans `Point de Vente > Configuration > Points de Vente`
2. Ouvrir un PDV
3. Vérifier que les employés sont bien listés dans `basic_employee_ids` ou `advanced_employee_ids`

### Via l'API:
```bash
# Test avec employé A
curl -X 'POST' 'http://127.0.0.1:8001/auth/pin-login' \
  -d '{"matricule": "GBASSI", "pin": "0000"}'

curl -X 'GET' 'http://127.0.0.1:8001/pos/available' \
  -H 'Authorization: Bearer TOKEN_A'

# Test avec utilisateur B  
curl -X 'POST' 'http://127.0.0.1:8001/auth/pin-login' \
  -d '{"matricule": "JO125", "pin": "0000"}'

curl -X 'GET' 'http://127.0.0.1:8001/pos/available' \
  -H 'Authorization: Bearer TOKEN_B'
```

## 🐛 Résolution de problèmes

### Problème: Utilisateur ne voit aucun PDV
**Cause:** L'utilisateur n'est affecté à aucun PDV
**Solution:** 
1. Vérifier l'user_id de l'employé dans `hr.employee`
2. S'assurer que cet user_id est dans `user_ids` d'au moins un PDV

### Problème: Utilisateur voit tous les PDV
**Cause:** Impossible de récupérer l'user_id (fallback activé)
**Solution:**
1. Vérifier que l'employé a un `user_id` dans `hr.employee`
2. Vérifier les logs pour les messages d'avertissement

### Problème: Erreur 500
**Cause:** Problème de connexion Odoo ou champs manquants
**Solution:**
1. Vérifier les logs d'erreur
2. S'assurer que les champs `user_ids` existent dans `pos.config`

## 📊 Structure des données

### Table `pos.config`:
```python
{
  'id': 3,
  'name': 'Caisse Principale', 
  'user_ids': [12, 25, 34],  # IDs des utilisateurs affectés
  'active': True,
  'current_session_id': False
}
```

### Table `hr.employee`:
```python
{
  'id': 1183,
  'name': 'Dossi Sylvie LEGBA',
  'user_id': [25, 'sylvie.legba'],  # Lien vers res.users
  'matricule': 'JO125'
}
```

## ✅ Bonnes pratiques

1. **Affectation par rôle:** Affecter les utilisateurs selon leur fonction
2. **Principe du moindre privilège:** Ne donner accès qu'aux PDV nécessaires  
3. **Documentation:** Tenir à jour la liste des affectations
4. **Tests réguliers:** Vérifier que les affectations fonctionnent
5. **Logs de sécurité:** Surveiller les accès aux PDV

## 🔄 Migration

Si vous migrez depuis l'ancien système (tous les PDV):
1. Identifier les utilisateurs actuels
2. Définir les affectations business
3. Configurer les `user_ids` dans Odoo
4. Tester avec l'API
5. Déployer en production
