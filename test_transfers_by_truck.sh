#!/bin/bash

# Script de test pour l'endpoint /pos/inventory/transfers/by-truck

# Couleurs
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}Test Endpoint: Transferts par Camion${NC}"
echo -e "${BLUE}========================================${NC}"

# Configuration
BASE_URL="http://localhost:8000"
PIN="1234"  # Remplacer par un PIN valide

echo -e "\n${GREEN}1. Authentification...${NC}"
TOKEN_RESPONSE=$(curl -s -X POST "$BASE_URL/auth/pin-login" \
  -H "Content-Type: application/json" \
  -d "{\"pin\": \"$PIN\"}")

TOKEN=$(echo $TOKEN_RESPONSE | jq -r '.access_token')

if [ "$TOKEN" == "null" ] || [ -z "$TOKEN" ]; then
    echo -e "${RED}❌ Erreur d'authentification${NC}"
    echo $TOKEN_RESPONSE | jq '.'
    exit 1
fi

echo -e "${GREEN}✓ Token obtenu${NC}"

# Liste des camions à tester
declare -a TRUCKS=("BURBO" "CAMION" "TRUCK")

for TRUCK in "${TRUCKS[@]}"
do
    echo -e "\n${BLUE}========================================${NC}"
    echo -e "${YELLOW}Test avec camion: ${TRUCK}${NC}"
    echo -e "${BLUE}========================================${NC}"
    
    RESPONSE=$(curl -s -X GET "$BASE_URL/pos/inventory/transfers/by-truck?truck_name=${TRUCK}&page=1&page_size=5" \
      -H "Authorization: Bearer $TOKEN")
    
    TOTAL_COUNT=$(echo $RESPONSE | jq -r '.count')
    SUCCESS=$(echo $RESPONSE | jq -r '.success')
    MESSAGE=$(echo $RESPONSE | jq -r '.message')
    
    if [ "$SUCCESS" == "true" ]; then
        echo -e "${GREEN}✓ Succès: $MESSAGE${NC}"
        echo -e "${GREEN}  Total: $TOTAL_COUNT transfert(s)${NC}"
        
        # Afficher le résumé des transferts
        echo -e "\n${YELLOW}Transferts trouvés:${NC}"
        echo $RESPONSE | jq -r '.data.transfers[] | "  - ID: \(.id) | Nom: \(.name) | Camion: \(.truck_name) | État: \(.state) | Date: \(.date)"'
        
        # Afficher les produits dans le premier transfert
        FIRST_TRANSFER_PRODUCTS=$(echo $RESPONSE | jq -r '.data.transfers[0].product_summary[]? | "    → \(.product_name) (\(.product_code // "N/A")): \(.quantity) \(.uom)"')
        if [ ! -z "$FIRST_TRANSFER_PRODUCTS" ]; then
            echo -e "\n${YELLOW}Produits du premier transfert:${NC}"
            echo "$FIRST_TRANSFER_PRODUCTS"
        fi
    else
        echo -e "${RED}❌ Échec: $MESSAGE${NC}"
    fi
done

echo -e "\n${BLUE}========================================${NC}"
echo -e "${GREEN}2. Test avec filtres supplémentaires${NC}"
echo -e "${BLUE}========================================${NC}"

# Test avec filtres de date et état
TRUCK_NAME="BURBO"
STATE="done"
DATE_FROM="2024-01-01"

echo -e "${YELLOW}Test: Camion=${TRUCK_NAME}, État=${STATE}, Date depuis=${DATE_FROM}${NC}"

FILTERED_RESPONSE=$(curl -s -X GET "$BASE_URL/pos/inventory/transfers/by-truck?truck_name=${TRUCK_NAME}&state=${STATE}&date_from=${DATE_FROM}&page=1&page_size=10" \
  -H "Authorization: Bearer $TOKEN")

FILTERED_COUNT=$(echo $FILTERED_RESPONSE | jq -r '.count')
FILTERED_MESSAGE=$(echo $FILTERED_RESPONSE | jq -r '.message')

echo -e "${GREEN}Résultat: $FILTERED_MESSAGE${NC}"
echo -e "${GREEN}Total avec filtres: $FILTERED_COUNT${NC}"

echo -e "\n${YELLOW}Pagination:${NC}"
echo $FILTERED_RESPONSE | jq '.data.pagination'

echo -e "\n${BLUE}========================================${NC}"
echo -e "${GREEN}3. Test pagination${NC}"
echo -e "${BLUE}========================================${NC}"

# Test pagination - page 1
PAGE1_RESPONSE=$(curl -s -X GET "$BASE_URL/pos/inventory/transfers/by-truck?truck_name=BURBO&page=1&page_size=2" \
  -H "Authorization: Bearer $TOKEN")

echo -e "${YELLOW}Page 1 (2 éléments):${NC}"
echo $PAGE1_RESPONSE | jq -r '.data.transfers[] | "  - \(.name) | \(.truck_name)"'

# Test pagination - page 2
PAGE2_RESPONSE=$(curl -s -X GET "$BASE_URL/pos/inventory/transfers/by-truck?truck_name=BURBO&page=2&page_size=2" \
  -H "Authorization: Bearer $TOKEN")

echo -e "\n${YELLOW}Page 2 (2 éléments):${NC}"
echo $PAGE2_RESPONSE | jq -r '.data.transfers[] | "  - \(.name) | \(.truck_name)"'

echo -e "\n${BLUE}========================================${NC}"
echo -e "${GREEN}Test terminé !${NC}"
echo -e "${BLUE}========================================${NC}"

# Exemples d'utilisation
echo -e "\n${YELLOW}Exemples d'utilisation:${NC}"
echo -e "${BLUE}# Recherche simple par nom de camion${NC}"
echo "GET /pos/inventory/transfers/by-truck?truck_name=BURBO"
echo ""
echo -e "${BLUE}# Avec état et pagination${NC}"
echo "GET /pos/inventory/transfers/by-truck?truck_name=BURBO&state=done&page=1&page_size=20"
echo ""
echo -e "${BLUE}# Avec période de dates${NC}"
echo "GET /pos/inventory/transfers/by-truck?truck_name=CAMION&date_from=2024-01-01&date_to=2024-12-31"
