#!/bin/bash

# Script de test du système Fuel Monitor
# Ce script teste toutes les fonctionnalités du fuel monitor

set -e  # Arrêter en cas d'erreur

# Couleurs pour l'affichage
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
API_URL="${API_URL:-http://localhost:8001}"
JWT_TOKEN="${JWT_TOKEN:-}"

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}   Test du système Fuel Monitor${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

# Vérifier le token
if [ -z "$JWT_TOKEN" ]; then
    echo -e "${RED}❌ Erreur: JWT_TOKEN non défini${NC}"
    echo -e "${YELLOW}Définissez la variable: export JWT_TOKEN='votre_token'${NC}"
    exit 1
fi

echo -e "${GREEN}✓${NC} Token JWT configuré"
echo -e "${GREEN}✓${NC} API URL: $API_URL"
echo ""

# Fonction pour afficher les résultats
function test_endpoint() {
    local name="$1"
    local method="$2"
    local endpoint="$3"
    local data="$4"
    
    echo -e "${BLUE}Test:${NC} $name"
    echo -e "  ${YELLOW}$method${NC} $endpoint"
    
    if [ "$method" = "GET" ]; then
        response=$(curl -s -w "\n%{http_code}" -X GET "$API_URL$endpoint" \
            -H "Authorization: Bearer $JWT_TOKEN")
    elif [ "$method" = "POST" ]; then
        if [ -z "$data" ]; then
            response=$(curl -s -w "\n%{http_code}" -X POST "$API_URL$endpoint" \
                -H "Authorization: Bearer $JWT_TOKEN")
        else
            response=$(curl -s -w "\n%{http_code}" -X POST "$API_URL$endpoint" \
                -H "Authorization: Bearer $JWT_TOKEN" \
                -H "Content-Type: application/json" \
                -d "$data")
        fi
    elif [ "$method" = "PUT" ]; then
        response=$(curl -s -w "\n%{http_code}" -X PUT "$API_URL$endpoint" \
            -H "Authorization: Bearer $JWT_TOKEN")
    fi
    
    status_code=$(echo "$response" | tail -n1)
    body=$(echo "$response" | head -n-1)
    
    if [ "$status_code" = "200" ] || [ "$status_code" = "201" ]; then
        echo -e "  ${GREEN}✅ Status: $status_code${NC}"
        echo "$body" | python3 -m json.tool 2>/dev/null || echo "$body"
    else
        echo -e "  ${RED}❌ Status: $status_code${NC}"
        echo "$body"
    fi
    
    echo ""
    sleep 1
}

# Health check
echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}1. Health Check${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

curl -s "$API_URL/health" | python3 -m json.tool
echo ""

# Test 1: Initialiser le cache
echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}2. Initialisation du cache${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

test_endpoint \
    "Initialiser le cache" \
    "POST" \
    "/fuel-monitor/initialize-cache"

# Test 2: Vérifier le status du cache
echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}3. Status du cache${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

test_endpoint \
    "Status du cache" \
    "GET" \
    "/fuel-monitor/cache-status"

# Test 3: Configurer le webhook (optionnel)
echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}4. Configuration du webhook${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

WEBHOOK_URL="${WEBHOOK_URL:-http://localhost:3000/api/webhook/fuel-recharge}"
echo -e "URL du webhook: ${GREEN}$WEBHOOK_URL${NC}"

test_endpoint \
    "Configurer webhook" \
    "PUT" \
    "/fuel-monitor/configure-webhook?webhook_url=$WEBHOOK_URL"

# Test 4: Vérifier les changements
echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}5. Vérification des changements${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

test_endpoint \
    "Vérifier changements" \
    "GET" \
    "/fuel-monitor/check-credit-changes?since_minutes=60"

# Test 5: Test manuel du webhook
echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}6. Test manuel du webhook${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

echo -e "${YELLOW}⚠️  Assurez-vous que le webhook receiver est démarré !${NC}"
echo -e "${YELLOW}   python webhook_receiver_example.py${NC}"
echo ""
read -p "Appuyez sur Entrée pour continuer..."

test_endpoint \
    "Trigger manuel" \
    "POST" \
    "/fuel-monitor/manual-trigger?partner_id=123&amount=50000"

# Résumé
echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}   Résumé des tests${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""
echo -e "${GREEN}✓${NC} Health check"
echo -e "${GREEN}✓${NC} Initialisation du cache"
echo -e "${GREEN}✓${NC} Status du cache"
echo -e "${GREEN}✓${NC} Configuration webhook"
echo -e "${GREEN}✓${NC} Vérification changements"
echo -e "${GREEN}✓${NC} Test manuel webhook"
echo ""
echo -e "${BLUE}========================================${NC}"
echo -e "${GREEN}✅ Tous les tests terminés${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""
echo -e "${YELLOW}Prochaines étapes:${NC}"
echo "1. Vérifier les logs: tail -f fuel_monitor.log"
echo "2. Démarrer la surveillance: python fuel_monitor_scheduler.py"
echo "3. Vérifier les webhooks reçus côté receiver"
