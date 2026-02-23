#!/bin/bash

# Script pour récupérer les pompes d'une session POS
# Usage: ./test_get_pumps.sh [pos_id] [session_id]

API_BASE_URL="http://localhost:8002"
USERNAME="admin@jnpdirecte.com"
PASSWORD="your_password_here"

# Couleurs pour l'affichage
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo "=========================================="
echo "  Récupération des pompes d'une session"
echo "=========================================="

# 1. Authentification
echo -e "\n${BLUE}🔐 Authentification...${NC}"
TOKEN=$(curl -s -X POST "$API_BASE_URL/auth/login" \
  -H "Content-Type: application/json" \
  -d "{\"username\":\"$USERNAME\",\"password\":\"$PASSWORD\"}" \
  | jq -r '.access_token')

if [ "$TOKEN" == "null" ] || [ -z "$TOKEN" ]; then
  echo -e "${RED}❌ Erreur d'authentification${NC}"
  exit 1
fi

echo -e "${GREEN}✅ Token obtenu${NC}"

# 2. Configuration
POS_ID=${1:-1}
SESSION_ID=${2}

# Si pas de session_id fourni, récupérer la session active
if [ -z "$SESSION_ID" ]; then
  echo -e "\n${BLUE}📋 Récupération de la session active pour POS $POS_ID...${NC}"
  
  SESSION_RESPONSE=$(curl -s -X GET "$API_BASE_URL/pos/$POS_ID/session-status" \
    -H "Authorization: Bearer $TOKEN")
  
  HAS_SESSION=$(echo "$SESSION_RESPONSE" | jq -r '.has_active_session')
  
  if [ "$HAS_SESSION" != "true" ]; then
    echo -e "${RED}❌ Aucune session active pour ce POS${NC}"
    exit 1
  fi
  
  SESSION_ID=$(echo "$SESSION_RESPONSE" | jq -r '.session_id')
  echo -e "${GREEN}✅ Session active trouvée: $SESSION_ID${NC}"
fi

# 3. Récupérer les pompes
echo -e "\n${BLUE}⛽ Récupération des pompes de la session $SESSION_ID...${NC}"

PUMPS_RESPONSE=$(curl -s -X GET "$API_BASE_URL/pos/$POS_ID/session/$SESSION_ID/pumps" \
  -H "Authorization: Bearer $TOKEN")

SUCCESS=$(echo "$PUMPS_RESPONSE" | jq -r '.success')

if [ "$SUCCESS" != "true" ]; then
  echo -e "${RED}❌ Erreur lors de la récupération${NC}"
  echo "$PUMPS_RESPONSE" | jq '.'
  exit 1
fi

# 4. Afficher les résultats
PUMP_COUNT=$(echo "$PUMPS_RESPONSE" | jq -r '.count')
MESSAGE=$(echo "$PUMPS_RESPONSE" | jq -r '.message')

echo -e "${GREEN}✅ $MESSAGE${NC}\n"

if [ "$PUMP_COUNT" -eq 0 ]; then
  echo -e "${YELLOW}⚠️ Aucune pompe configurée pour cette session${NC}"
  exit 0
fi

echo "=========================================="
echo "  Détail des pompes ($PUMP_COUNT)"
echo "=========================================="

# Parcourir chaque pompe
PUMPS=$(echo "$PUMPS_RESPONSE" | jq -c '.data[]')

COUNTER=1
TOTAL_SOLD=0

while IFS= read -r pump; do
  NAME=$(echo "$pump" | jq -r '.name')
  TYPE=$(echo "$pump" | jq -r '.type')
  PRODUCT=$(echo "$pump" | jq -r '.product_name')
  START_INDEX=$(echo "$pump" | jq -r '.start_index')
  CURRENT_INDEX=$(echo "$pump" | jq -r '.current_index')
  QUANTITY=$(echo "$pump" | jq -r '.quantity_available')
  
  echo -e "\n${BLUE}🔹 Pompe #$COUNTER: $NAME${NC}"
  echo "   Type: $TYPE"
  echo "   Produit: $PRODUCT"
  printf "   Index départ: %.2f L\n" "$START_INDEX"
  printf "   Index actuel: %.2f L\n" "$CURRENT_INDEX"
  printf "   ${GREEN}Quantité vendue: %.2f L${NC}\n" "$QUANTITY"
  
  # Calculer le total (utiliser bc si disponible)
  if command -v bc &> /dev/null; then
    TOTAL_SOLD=$(echo "$TOTAL_SOLD + $QUANTITY" | bc)
  fi
  
  COUNTER=$((COUNTER + 1))
done <<< "$PUMPS"

echo -e "\n=========================================="
if command -v bc &> /dev/null; then
  printf "${GREEN}📊 TOTAL VENDU: %.2f L${NC}\n" "$TOTAL_SOLD"
fi
echo "=========================================="

# 5. Afficher le JSON brut (optionnel)
echo -e "\n${YELLOW}📄 JSON brut (pour développement):${NC}"
echo "$PUMPS_RESPONSE" | jq '.'

exit 0
