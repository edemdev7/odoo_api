#!/bin/bash
# Script pour tester l'écriture comptable

echo "🧾 Test de l'écriture comptable"
echo "================================"
echo ""
echo "📋 Paramètres:"
echo "   Entreprise: 4708"
echo "   Montant: 10000"
echo "   Endpoint: http://localhost:8002/accounting/credit-account"
echo ""
echo "🚀 Lancement du test..."
echo ""

cd /home/edem/Téléchargements/odoo_api
python3 test_accounting_quick.py
