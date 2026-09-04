# Dette technique — note interne

> **Ne pas inclure dans la documentation partagée.**
> Ce fichier reste dans le dépôt et ne fait pas partie de `docs/`, qui est
> transmis au client.

---

## 1. Identifiants Odoo en dur dans le code

**Où** — `core/config.py`, dans `ODOO_DB1_CONFIG` et `ODOO_DB2_CONFIG`.

Les URL, noms de base, comptes de service et **clés API** des deux instances
figurent en valeurs par défaut des appels `os.getenv()`. Les variables
d'environnement les surchargent, mais les valeurs restent lisibles dans le code.

**Portée** — Toute personne ayant accès au dépôt dispose d'un accès
administrateur aux deux ERP. Les clés sont également présentes dans l'historique
Git, donc dans tous les clones existants.

**Correction**

1. Faire tourner les deux clés API dans Odoo. C'est le seul geste qui règle
   réellement le problème : retirer les valeurs du code ne les efface pas de
   l'historique.
2. Retirer les valeurs par défaut, et faire échouer le démarrage si une variable
   obligatoire manque — un échec explicite vaut mieux qu'une connexion silencieuse
   à la mauvaise instance.
3. Renseigner les nouvelles clés dans le `.env` du serveur.

**Effort** — Environ une heure, rotation comprise.

---

## 2. Base des index de pompes versionnée

**Où** — `pump_data.db`, à la racine du dépôt.

Ce fichier SQLite contient les relevés de pompes des sessions en cours. C'est une
donnée d'exploitation produite en production, et elle est suivie par Git.

**Portée** — Un `git pull` ou un déploiement peut écraser les relevés en cours par
la version figée du dépôt. La perte serait silencieuse et ne se manifesterait
qu'à la clôture de session, quand le calcul des volumes deviendrait impossible.

**Correction**

```bash
git rm --cached pump_data.db
printf 'pump_data.db\n' >> .gitignore
git commit -m "chore: sortir la base des index de pompes du suivi Git"
```

Le fichier se recrée seul au démarrage — `pump_manager.py` contient les
instructions de création des tables — donc l'opération est sans risque.

Prévoir en revanche une **sauvegarde** de ce fichier sur le serveur : il n'est
répliqué nulle part.

**Effort** — Quelques minutes, plus la mise en place de la sauvegarde.

---

## 3. Cache Python versionné

**Où** — Répertoires `__pycache__/` suivis par Git.

Sans conséquence de sécurité, mais source de conflits à chaque `git pull` et
risque qu'un `.pyc` obsolète soit chargé à la place du source modifié.

**Correction**

```bash
git ls-files | grep '__pycache__' | xargs -r git rm --cached
printf '\n__pycache__/\n*.pyc\n' >> .gitignore
git commit -m "chore: exclure le cache Python du suivi Git"
```

---

## 4. Webhooks envoyés vers deux environnements

**Où** — `FUEL_WEBHOOK_URL` et `FUEL_WEBHOOK_URL_STG`.

Chaque notification part vers la production et la préproduction. Les identifiants
métier n'existant que dans une base à la fois, l'un des deux appels échoue
systématiquement en 403, et l'erreur est journalisée au niveau `ERROR`.

**Portée** — Bruit permanent dans les journaux. Une vraie panne s'y noierait.

**Correction** — Trois options, à arbitrer : ne notifier qu'un environnement,
abaisser le niveau de journalisation de ces rejets attendus, ou router selon la
base Odoo d'origine de l'opération.

---

## 5. Fichiers résiduels à la racine

`pos.py` (copie ancienne de `api/pos.py`), `accounting.py.bak`, et une dizaine de
scripts ponctuels non maintenus.

Sans gravité, mais `pos.py` à la racine peut induire en erreur : c'est une
version périmée du routeur principal, et rien n'indique laquelle fait foi.

**Correction** — Supprimer les copies mortes, déplacer les scripts ponctuels dans
un répertoire clairement identifié comme non maintenu.
