# 🚀 Architecture Multi-Base de Données - Guide de Démarrage Rapide

## ✨ Nouveautés

Cette version de l'API FastAPI supporte désormais **deux instances Odoo distinctes** avec :

- ✅ **Authentification en cascade** : Essai automatique sur JNP Directe puis Franchise
- ✅ **Filtrage automatique** : Les transferts sont filtrés selon le type autorisé pour chaque base
- ✅ **Sécurité renforcée** : Impossible d'accéder à des types de transferts non autorisés
- ✅ **Token JWT enrichi** : Contient le nom de la base de données authentifiée

## 🔧 Configuration Requise

### 1. Variables d'Environnement

Ajoutez les clés API dans votre fichier `.env` ou définissez-les dans `core/config.py` :

```python
# Base de données 1 : JNP Directe
ODOO_DB1_URL = "https://sandbox-erp.dagbehamiithiel.com"
ODOO_DB1_DATABASE = "sandbox.dagbehamiithiel.com"
ODOO_DB1_USERNAME = "admin@jnpdirecte.com"
ODOO_DB1_API_KEY = "votre_cle_api_jnp"

# Base de données 2 : Franchise
ODOO_DB2_URL = "https://sandbox.perfect-erp.com"
ODOO_DB2_DATABASE = "sandbox"
ODOO_DB2_USERNAME = "admin@perfecterp.com"
ODOO_DB2_API_KEY = "votre_cle_api_franchise"
```

### 2. Types de Transferts par Base

| Base de Données | Type Autorisé | Description |
|----------------|---------------|-------------|
| **JNP Directe** | `internal` | Transferts internes entre emplacements |
| **Franchise** | `incoming` | Réceptions de marchandises |

## 🎯 Fichiers Modifiés

### Fichiers de Configuration

1. **`core/config.py`** ✏️
   - Ajout de `ODOO_DB1_CONFIG` et `ODOO_DB2_CONFIG`
   - Création de `ODOO_DATABASES` pour la cascade
   - Configuration des `transfer_type_code` par base

2. **`core/security.py`** ✏️
   - Fonction `create_access_token()` : Ajout du paramètre `odoo_db_name`
   - Nouvelle fonction `get_odoo_config_from_user()` : Récupère la config depuis le token

### Fichiers d'Authentification

3. **`api/auth.py`** ✏️
   - Endpoint `/pin-login` : Authentification en cascade sur les deux bases
   - Inclusion de `odoo_db` dans le token JWT
   - Utilisation du client authentifié pour récupérer les détails de l'employé

### Fichiers API

4. **`api/pos.py`** ✏️
   - Endpoint `/pos/{pos_id}/inventory/transfers` : Filtrage automatique par type
   - Validation du type de transfert demandé vs autorisé
   - Logs enrichis pour le debugging

5. **`core/odoo_client.py`** ✏️
   - Fonction `get_odoo_client()` : Utilise la config depuis le token utilisateur
   - Support natif du multi-database

### Documentation

6. **`MULTI_DATABASE_ARCHITECTURE.md`** ✅ NOUVEAU
   - Architecture complète du système multi-base
   - Exemples de code et flux techniques
   - Guide d'ajout d'une nouvelle base

7. **`test_multi_database.py`** ✅ NOUVEAU
   - Script de test automatisé
   - 4 suites de tests complètes
   - Validation de tous les scénarios

8. **`MULTI_DB_QUICK_START.md`** ✅ NOUVEAU (ce fichier)
   - Guide de démarrage rapide

## 🧪 Tests

### Lancer l'API

```bash
# Installer les dépendances
pip install -r requirements.txt

# Lancer l'API
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

### Tester l'Authentification

#### Test 1 : Authentification sur JNP Directe

```bash
curl -X POST http://localhost:8000/api/auth/pin-login \
  -H "Content-Type: application/json" \
  -d '{
    "matricule": "EMP_JNP_001",
    "pin": "1234"
  }'
```

**Résultat attendu** :
```json
{
  "access_token": "eyJ...",
  "token_type": "bearer",
  "user_data": {
    "additional_info": {
      "odoo_database": "JNP Directe"
    }
  }
}
```

#### Test 2 : Authentification sur Franchise

```bash
curl -X POST http://localhost:8000/api/auth/pin-login \
  -H "Content-Type: application/json" \
  -d '{
    "matricule": "EMP_FRAN_001",
    "pin": "5678"
  }'
```

**Résultat attendu** :
```json
{
  "access_token": "eyJ...",
  "token_type": "bearer",
  "user_data": {
    "additional_info": {
      "odoo_database": "Franchise"
    }
  }
}
```

### Tester le Filtrage Automatique

#### Test 3 : Transferts internes (JNP Directe)

```bash
# Récupérer le token JNP Directe
TOKEN_JNP="<votre_token_jnp>"

curl -X GET "http://localhost:8000/api/pos/1/inventory/transfers" \
  -H "Authorization: Bearer $TOKEN_JNP"
```

**Résultat** : Uniquement les transferts avec `picking_type_code = "internal"`

#### Test 4 : Réceptions (Franchise)

```bash
# Récupérer le token Franchise
TOKEN_FRAN="<votre_token_franchise>"

curl -X GET "http://localhost:8000/api/pos/1/inventory/transfers" \
  -H "Authorization: Bearer $TOKEN_FRAN"
```

**Résultat** : Uniquement les transferts avec `picking_type_code = "incoming"`

### Tester le Rejet des Types Non Autorisés

#### Test 5 : Type non autorisé sur JNP Directe

```bash
curl -X GET "http://localhost:8000/api/pos/1/inventory/transfers?picking_type_code=incoming" \
  -H "Authorization: Bearer $TOKEN_JNP"
```

**Résultat attendu** : Erreur 403
```json
{
  "detail": "Cette base de données ne gère que les transferts de type 'internal'"
}
```

### Script de Test Automatisé

```bash
# Rendre le script exécutable
chmod +x test_multi_database.py

# Lancer tous les tests
python test_multi_database.py
```

## 📊 Logs de Débogage

L'API génère des logs détaillés pour suivre le flux d'authentification et de filtrage :

```
INFO: Tentative d'authentification sur JNP Directe (https://sandbox-erp.dagbehamiithiel.com)
INFO: ✅ Employé trouvé sur JNP Directe: Jean Dupont
INFO: Authentification réussie sur JNP Directe: Jean Dupont
INFO: Connexion par PIN réussie pour l'employé: Jean Dupont sur JNP Directe

INFO: Filtrage automatique par type de transfert de la DB: internal
INFO: Filtrage par picking_type_code: internal
INFO: Recherche transferts avec domaine: [('company_id', '=', 1), ('picking_type_code', '=', 'internal')]
```

## 🔍 Vérification de la Configuration

### Vérifier les bases de données configurées

```python
from core.config import ODOO_DATABASES

for db in ODOO_DATABASES:
    print(f"✓ {db['name']}: {db['url']} (Type: {db['transfer_type_code']})")
```

**Sortie attendue** :
```
✓ JNP Directe: https://sandbox-erp.dagbehamiithiel.com (Type: internal)
✓ Franchise: https://sandbox.perfect-erp.com (Type: incoming)
```

### Tester la connexion à chaque base

```python
from core.odoo_client import OdooClient
from core.config import ODOO_DATABASES

for db_config in ODOO_DATABASES:
    try:
        client = OdooClient(custom_config={
            'url': db_config['url'],
            'db': db_config['db'],
            'username': db_config['username'],
            'api_key': db_config['api_key']
        })
        
        # Test simple
        result = client.execute_kw('res.partner', 'search', [[]], {'limit': 1})
        print(f"✅ {db_config['name']}: Connexion OK")
        
    except Exception as e:
        print(f"❌ {db_config['name']}: Erreur - {e}")
```

## 🐛 Troubleshooting

### Erreur : "Matricule ou PIN incorrect" alors que les identifiants sont corrects

**Cause** : L'employé n'existe dans aucune des deux bases de données.

**Solution** :
1. Vérifier que l'employé existe dans Odoo
2. Vérifier que le champ `x_studio_matricule` est renseigné
3. Vérifier que le champ `pin` est renseigné et correspond

### Erreur : "Cette base de données ne gère que les transferts de type 'internal'"

**Cause** : Vous essayez de filtrer un type de transfert non autorisé pour cette base.

**Solution** :
- Sur JNP Directe : utilisez uniquement `picking_type_code=internal` ou aucun filtre
- Sur Franchise : utilisez uniquement `picking_type_code=incoming` ou aucun filtre

### Erreur : "Configuration Odoo non trouvée pour l'utilisateur"

**Cause** : Le token JWT ne contient pas le champ `odoo_db`.

**Solution** :
1. Se ré-authentifier via `/api/auth/pin-login`
2. Vérifier que le token inclut bien le champ `odoo_db`

### Aucun transfert retourné

**Causes possibles** :
1. Aucun transfert n'existe pour ce PDV
2. Le PDV n'existe pas
3. Le filtre est trop restrictif

**Solutions** :
1. Créer des transferts de test dans Odoo
2. Vérifier l'ID du PDV
3. Enlever les filtres optionnels (date, état, etc.)

## 📝 Notes Importantes

### Sécurité

- ⚠️ Les clés API ne doivent **JAMAIS** être commitées dans Git
- ⚠️ Utilisez des variables d'environnement ou un fichier `.env` (gitignored)
- ⚠️ Les tokens JWT expirent après 30 minutes (configurable via `ACCESS_TOKEN_EXPIRE_MINUTES`)

### Performance

- Les recherches sont limitées à 500 transferts maximum par défaut
- Utilisez les filtres (date, état) pour réduire la charge
- Les logs peuvent être ajustés dans `core/config.py`

### Évolution

Pour ajouter une 3ème base de données :

1. Ajouter la configuration dans `core/config.py`
2. Ajouter à `ODOO_DATABASES`
3. Définir le `transfer_type_code` approprié

**Aucune modification de code n'est nécessaire** ✅

## 📚 Documentation Complète

Pour plus de détails sur l'architecture, consultez :

- **`MULTI_DATABASE_ARCHITECTURE.md`** : Architecture technique complète
- **Swagger UI** : `http://localhost:8000/docs` (une fois l'API lancée)
- **ReDoc** : `http://localhost:8000/redoc`

## ✅ Checklist de Validation

Avant la mise en production, vérifiez :

- [ ] Les clés API sont correctement configurées
- [ ] Les deux bases Odoo sont accessibles
- [ ] Des employés de test existent dans chaque base
- [ ] Le script `test_multi_database.py` passe tous les tests
- [ ] Les logs de l'API sont cohérents
- [ ] La documentation Swagger est à jour

## 🆘 Support

En cas de problème :

1. Consulter les logs de l'API
2. Vérifier la configuration dans `core/config.py`
3. Tester la connexion à chaque base Odoo manuellement
4. Lancer le script de test automatisé

---

**Version** : 2.0.0 (Multi-Database Support)  
**Date** : Janvier 2025  
**Auteur** : Équipe API Odoo
