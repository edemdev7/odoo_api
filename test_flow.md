il faut d'abord savoir quels `move_line_id` sont dans le transfert. On les trouve via l'endpoint existant :

**Étape 0 — récupérer les move_line_ids du transfert**
```
GET /pos/32/inventory/transfers?page=1&page_size=10
```
Dans la réponse, chaque transfert a un champ `move_line_details` avec les lignes et leurs IDs.

---

**Étape 1 — valider partiellement (ex: 30 000 L sur 50 000 L commandés)**

```
POST /inventory/transfers/82534/validate-partial
Authorization: Bearer <token>
Content-Type: application/json
```
```json
{
  "lines": [
    { "move_line_id": 1234, "qty_done": 30000 }
  ],
  "create_backorder": true
}
```

**Réponse — livraison partielle, reliquat créé :**
```json
{
  "success": true,
  "message": "Livraison partielle validée (WH/OUT/00042). Reliquat créé : WH/OUT/00042/001.",
  "data": {
    "transfer": {
      "id": 82534,
      "name": "WH/OUT/00042",
      "previous_state": "assigned",
      "state": "done",
      "date_done": "2026-07-14 10:23:11"
    },
    "backorder": {
      "id": 82600,
      "name": "WH/OUT/00042/001",
      "state": "assigned",
      "scheduled_date": "2026-07-15 08:00:00",
      "move_line_count": 1
    },
    "is_partial": true,
    "lines_validated": 1
  }
}
```

---

**Étape 2 — valider le reliquat (les 20 000 L restants)**

```
POST /inventory/transfers/82600/validate-partial
```
```json
{
  "lines": [
    { "move_line_id": 1301, "qty_done": 20000 }
  ],
  "create_backorder": true
}
```

**Réponse — livraison complète, pas de reliquat :**
```json
{
  "success": true,
  "message": "Livraison partielle validée (WH/OUT/00042/001). Livraison complète.",
  "data": {
    "transfer": {
      "id": 82600,
      "name": "WH/OUT/00042/001",
      "previous_state": "assigned",
      "state": "done",
      "date_done": "2026-07-16 09:05:44"
    },
    "backorder": null,
    "is_partial": false,
    "lines_validated": 1
  }
}
```

---

**Cas avec plusieurs produits sur le même transfert**
```json
{
  "lines": [
    { "move_line_id": 1234, "qty_done": 30000 },
    { "move_line_id": 1235, "qty_done": 500 }
  ],
  "create_backorder": true
}
```

**Cas sans reliquat (valider sans générer de backorder)**
```json
{
  "lines": [
    { "move_line_id": 1234, "qty_done": 30000 }
  ],
  "create_backorder": false
}
```
→ Les 20 000 L restants sont abandonnés, pas de reliquat créé.