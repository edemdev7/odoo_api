#!/bin/bash
# Script de test pour l'endpoint /pos/list

echo "🧪 Test de l'endpoint GET /pos/list"
echo "=================================="
echo ""

# Remplacez ce token par votre token actuel
TOKEN="eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJlbXBsb3llZV8zIiwic2NvcGVzIjpbInJlYWQiLCJwb3MiXSwiaWF0IjoxNzYyMjY3MDEzLCJlbXBsb3llZV9pZCI6MywiZW1wbG95ZWVfbmFtZSI6IkdcdTAwZTlyYW50IFNlbmFtaSIsImVtcGxveWVlX21hdHJpY3VsZSI6IjA0MTY4MDk0NTUxMyIsIm9kb29fZGIiOiJmcmFuY2hpc2UiLCJleHAiOjE3NjIyOTU4MTN9.hxZ35OPNzPVHVl9tHxVdUSBeLwjFeDzrL-dI_ZKLDSE"

echo "📡 Requête vers http://127.0.0.1:8001/pos/list"
echo ""

curl -X 'GET' \
  'http://127.0.0.1:8001/pos/list' \
  -H 'accept: application/json' \
  -H "Authorization: Bearer $TOKEN" \
  | python3 -m json.tool

echo ""
echo ""
echo "✅ Test terminé"
