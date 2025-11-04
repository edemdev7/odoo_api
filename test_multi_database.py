#!/usr/bin/env python3
"""
Script de test pour l'architecture multi-base de données Odoo

Ce script teste :
1. L'authentification en cascade sur les deux bases
2. Le filtrage automatique par type de transfert
3. La gestion des erreurs de type non autorisé
"""

import requests
import json
from typing import Dict, Optional

# Configuration
BASE_URL = "http://localhost:8000"

# Codes couleur pour l'affichage
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
BLUE = "\033[94m"
RESET = "\033[0m"


def print_test(title: str):
    """Affiche le titre d'un test"""
    print(f"\n{BLUE}{'='*60}{RESET}")
    print(f"{BLUE}🧪 {title}{RESET}")
    print(f"{BLUE}{'='*60}{RESET}")


def print_success(message: str):
    """Affiche un message de succès"""
    print(f"{GREEN}✅ {message}{RESET}")


def print_error(message: str):
    """Affiche un message d'erreur"""
    print(f"{RED}❌ {message}{RESET}")


def print_warning(message: str):
    """Affiche un avertissement"""
    print(f"{YELLOW}⚠️  {message}{RESET}")


def print_info(message: str):
    """Affiche une information"""
    print(f"ℹ️  {message}")


def authenticate(matricule: str, pin: str) -> Optional[Dict]:
    """
    Tente de s'authentifier avec un matricule et un PIN
    
    Returns:
        Dict contenant le token et les données utilisateur, ou None en cas d'échec
    """
    print_info(f"Tentative d'authentification avec matricule={matricule}, pin={pin}")
    
    try:
        response = requests.post(
            f"{BASE_URL}/api/auth/pin-login",
            json={"matricule": matricule, "pin": pin},
            headers={"Content-Type": "application/json"}
        )
        
        if response.status_code == 200:
            data = response.json()
            user_data = data.get('user_data', {})
            additional_info = user_data.get('additional_info', {})
            
            print_success(f"Authentification réussie !")
            print_info(f"  👤 Utilisateur: {user_data.get('fullname')}")
            print_info(f"  🏢 Base de données: {additional_info.get('odoo_database')}")
            print_info(f"  🔑 Token: {data['access_token'][:30]}...")
            
            return data
        
        elif response.status_code == 401:
            print_error("Authentification échouée : Matricule ou PIN incorrect")
            return None
        
        else:
            print_error(f"Erreur inattendue : {response.status_code}")
            print_info(f"Détails : {response.text}")
            return None
            
    except Exception as e:
        print_error(f"Exception lors de l'authentification : {e}")
        return None


def get_transfers(pos_id: int, token: str, picking_type_code: Optional[str] = None) -> Optional[Dict]:
    """
    Récupère les transferts de stock pour un PDV
    
    Args:
        pos_id: ID du point de vente
        token: Token JWT d'authentification
        picking_type_code: Type de transfert (internal/incoming/outgoing) ou None
    
    Returns:
        Réponse JSON ou None en cas d'échec
    """
    url = f"{BASE_URL}/api/pos/{pos_id}/inventory/transfers"
    
    params = {}
    if picking_type_code:
        params['picking_type_code'] = picking_type_code
        print_info(f"Récupération des transferts avec filtre picking_type_code={picking_type_code}")
    else:
        print_info(f"Récupération des transferts sans filtre (filtrage automatique)")
    
    try:
        response = requests.get(
            url,
            params=params,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json"
            }
        )
        
        if response.status_code == 200:
            data = response.json()
            transfers = data.get('data', [])
            
            print_success(f"{len(transfers)} transfert(s) récupéré(s)")
            
            # Afficher les types de transferts trouvés
            if transfers:
                types = set(t.get('picking_type_code') for t in transfers)
                print_info(f"  Types de transferts : {', '.join(types)}")
                
                # Afficher le premier transfert
                first = transfers[0]
                print_info(f"  Premier transfert : {first.get('name')} - {first.get('state')}")
            
            return data
        
        elif response.status_code == 403:
            error = response.json()
            print_error(f"Accès refusé : {error.get('detail')}")
            return None
        
        elif response.status_code == 404:
            print_error("Point de vente non trouvé")
            return None
        
        else:
            print_error(f"Erreur inattendue : {response.status_code}")
            print_info(f"Détails : {response.text}")
            return None
            
    except Exception as e:
        print_error(f"Exception lors de la récupération des transferts : {e}")
        return None


def test_authentication_cascade():
    """Test l'authentification en cascade sur les deux bases"""
    print_test("TEST 1 : Authentification en Cascade")
    
    # Test avec un matricule qui devrait être sur JNP Directe
    print("\n📍 Test 1.1 : Authentification sur JNP Directe")
    auth_data = authenticate("EMP_JNP_001", "1234")
    
    if auth_data:
        db = auth_data['user_data']['additional_info'].get('odoo_database')
        if db == "JNP Directe":
            print_success("Authentification sur la bonne base (JNP Directe)")
        else:
            print_warning(f"Authentification réussie mais sur {db} au lieu de JNP Directe")
    
    # Test avec un matricule qui devrait être sur Franchise
    print("\n📍 Test 1.2 : Authentification sur Franchise")
    auth_data = authenticate("EMP_FRAN_001", "5678")
    
    if auth_data:
        db = auth_data['user_data']['additional_info'].get('odoo_database')
        if db == "Franchise":
            print_success("Authentification sur la bonne base (Franchise)")
        else:
            print_warning(f"Authentification réussie mais sur {db} au lieu de Franchise")
    
    # Test avec des identifiants invalides
    print("\n📍 Test 1.3 : Authentification échouée (identifiants invalides)")
    auth_data = authenticate("INVALID_MAT", "9999")
    
    if not auth_data:
        print_success("Rejet correct des identifiants invalides")


def test_automatic_filtering():
    """Test le filtrage automatique par type de transfert"""
    print_test("TEST 2 : Filtrage Automatique par Type de Transfert")
    
    # Authentification sur JNP Directe
    print("\n📍 Test 2.1 : Filtrage automatique pour JNP Directe (internal)")
    auth_data = authenticate("EMP_JNP_001", "1234")
    
    if auth_data:
        token = auth_data['access_token']
        
        # Sans filtre explicite → devrait retourner uniquement les transferts internes
        transfers = get_transfers(pos_id=1, token=token)
        
        if transfers:
            # Vérifier que tous les transferts sont de type "internal"
            data = transfers.get('data', [])
            if all(t.get('picking_type_code') == 'internal' for t in data):
                print_success("Tous les transferts sont de type 'internal' ✓")
            else:
                types = set(t.get('picking_type_code') for t in data)
                print_error(f"Certains transferts ne sont pas de type 'internal' : {types}")
    
    # Authentification sur Franchise
    print("\n📍 Test 2.2 : Filtrage automatique pour Franchise (incoming)")
    auth_data = authenticate("EMP_FRAN_001", "5678")
    
    if auth_data:
        token = auth_data['access_token']
        
        # Sans filtre explicite → devrait retourner uniquement les réceptions
        transfers = get_transfers(pos_id=1, token=token)
        
        if transfers:
            # Vérifier que tous les transferts sont de type "incoming"
            data = transfers.get('data', [])
            if all(t.get('picking_type_code') == 'incoming' for t in data):
                print_success("Tous les transferts sont de type 'incoming' ✓")
            else:
                types = set(t.get('picking_type_code') for t in data)
                print_error(f"Certains transferts ne sont pas de type 'incoming' : {types}")


def test_forbidden_type_filtering():
    """Test le rejet des types de transferts non autorisés"""
    print_test("TEST 3 : Rejet des Types de Transferts Non Autorisés")
    
    # Authentification sur JNP Directe
    print("\n📍 Test 3.1 : Tentative de filtrage 'incoming' sur JNP Directe")
    auth_data = authenticate("EMP_JNP_001", "1234")
    
    if auth_data:
        token = auth_data['access_token']
        
        # Tenter de filtrer par "incoming" alors que JNP Directe ne gère que "internal"
        transfers = get_transfers(pos_id=1, token=token, picking_type_code="incoming")
        
        if not transfers:
            print_success("Rejet correct du type non autorisé ✓")
        else:
            print_error("Le type 'incoming' n'aurait pas dû être autorisé sur JNP Directe")
    
    # Authentification sur Franchise
    print("\n📍 Test 3.2 : Tentative de filtrage 'internal' sur Franchise")
    auth_data = authenticate("EMP_FRAN_001", "5678")
    
    if auth_data:
        token = auth_data['access_token']
        
        # Tenter de filtrer par "internal" alors que Franchise ne gère que "incoming"
        transfers = get_transfers(pos_id=1, token=token, picking_type_code="internal")
        
        if not transfers:
            print_success("Rejet correct du type non autorisé ✓")
        else:
            print_error("Le type 'internal' n'aurait pas dû être autorisé sur Franchise")


def test_explicit_correct_filtering():
    """Test le filtrage explicite avec le type correct"""
    print_test("TEST 4 : Filtrage Explicite avec le Type Correct")
    
    # Authentification sur JNP Directe
    print("\n📍 Test 4.1 : Filtrage explicite 'internal' sur JNP Directe")
    auth_data = authenticate("EMP_JNP_001", "1234")
    
    if auth_data:
        token = auth_data['access_token']
        
        # Filtrer explicitement par "internal" (devrait fonctionner)
        transfers = get_transfers(pos_id=1, token=token, picking_type_code="internal")
        
        if transfers:
            print_success("Filtrage explicite 'internal' autorisé ✓")
        else:
            print_error("Le filtrage explicite 'internal' aurait dû fonctionner sur JNP Directe")
    
    # Authentification sur Franchise
    print("\n📍 Test 4.2 : Filtrage explicite 'incoming' sur Franchise")
    auth_data = authenticate("EMP_FRAN_001", "5678")
    
    if auth_data:
        token = auth_data['access_token']
        
        # Filtrer explicitement par "incoming" (devrait fonctionner)
        transfers = get_transfers(pos_id=1, token=token, picking_type_code="incoming")
        
        if transfers:
            print_success("Filtrage explicite 'incoming' autorisé ✓")
        else:
            print_error("Le filtrage explicite 'incoming' aurait dû fonctionner sur Franchise")


def main():
    """Fonction principale"""
    print(f"\n{BLUE}{'='*60}{RESET}")
    print(f"{BLUE}🚀 Test de l'Architecture Multi-Base de Données Odoo{RESET}")
    print(f"{BLUE}{'='*60}{RESET}")
    
    print(f"\n{YELLOW}⚠️  PRÉREQUIS :{RESET}")
    print("1. L'API FastAPI doit être lancée (uvicorn main:app)")
    print("2. Les deux bases Odoo doivent être configurées dans core/config.py")
    print("3. Des employés de test doivent exister dans chaque base")
    print("\nAppuyez sur Entrée pour continuer...")
    input()
    
    try:
        # Test 1 : Authentification en cascade
        test_authentication_cascade()
        
        # Test 2 : Filtrage automatique
        test_automatic_filtering()
        
        # Test 3 : Rejet des types non autorisés
        test_forbidden_type_filtering()
        
        # Test 4 : Filtrage explicite correct
        test_explicit_correct_filtering()
        
        # Résumé
        print(f"\n{BLUE}{'='*60}{RESET}")
        print(f"{GREEN}✅ Tous les tests sont terminés !{RESET}")
        print(f"{BLUE}{'='*60}{RESET}")
        
    except KeyboardInterrupt:
        print(f"\n\n{YELLOW}⚠️  Tests interrompus par l'utilisateur{RESET}")
    except Exception as e:
        print(f"\n\n{RED}❌ Erreur inattendue : {e}{RESET}")


if __name__ == "__main__":
    main()
