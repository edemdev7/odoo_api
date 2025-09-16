# ===== test_client.py - Client de test pour l'API =====

import requests
import json
from typing import Optional

class OdooAPIClient:
    """Client Python pour tester l'API Odoo FastAPI"""

    def __init__(self, base_url: str = "http://localhost:8001"):
        self.base_url = base_url
        self.session = requests.Session()
        self.token = None
    
    def login(self, username: str, password: str) -> bool:
        """Se connecter à l'API"""
        try:
            response = self.session.post(
                f"{self.base_url}/auth/login",
                json={"username": username, "password": password}
            )
            
            if response.status_code == 200:
                data = response.json()
                self.token = data["access_token"]
                self.session.headers.update({
                    "Authorization": f"Bearer {self.token}"
                })
                print(f"✅ Connexion réussie ! Token expire dans {data['expires_in']} secondes")
                return True
            else:
                print(f"❌ Échec de la connexion: {response.json()}")
                return False
                
        except Exception as e:
            print(f"❌ Erreur de connexion: {e}")
            return False
    
    def get_me(self):
        """Obtenir les infos de l'utilisateur connecté"""
        response = self.session.get(f"{self.base_url}/auth/me")
        return self._handle_response(response)
    
    def search_partners(self, limit: int = 5):
        """Rechercher des partenaires"""
        data = {
            "model": "res.partner",
            "domain": [],
            "limit": limit
        }
        response = self.session.post(f"{self.base_url}/odoo/search", json=data)
        return self._handle_response(response)
    
    def read_partners(self, partner_ids: list, fields: list = None):
        """Lire les détails des partenaires"""
        fields_str = ",".join(fields) if fields else ""
        ids_str = ",".join(map(str, partner_ids))
        
        params = {"model": "res.partner", "ids": ids_str}
        if fields_str:
            params["fields"] = fields_str
            
        response = self.session.post(f"{self.base_url}/odoo/read", params=params)
        return self._handle_response(response)
    
    def search_read_companies(self, limit: int = 3):
        """Rechercher et lire les entreprises"""
        data = {
            "model": "res.partner",
            "domain": [["is_company", "=", True]],
            "fields": ["name", "email", "phone"],
            "limit": limit
        }
        response = self.session.post(f"{self.base_url}/odoo/search_read", json=data)
        return self._handle_response(response)
    
    def create_partner(self, name: str, email: str, phone: str = None):
        """Créer un nouveau partenaire"""
        values = {
            "name": name,
            "email": email,
            "is_company": False
        }
        if phone:
            values["phone"] = phone
            
        data = {"model": "res.partner", "values": values}
        response = self.session.post(f"{self.base_url}/odoo/create", json=data)
        return self._handle_response(response)
    
    def update_partner(self, partner_id: int, values: dict):
        """Mettre à jour un partenaire"""
        data = {
            "model": "res.partner",
            "ids": [partner_id],
            "values": values
        }
        response = self.session.post(f"{self.base_url}/odoo/update", json=data)
        return self._handle_response(response)
    
    def delete_partner(self, partner_id: int):
        """Supprimer un partenaire"""
        data = {
            "model": "res.partner",
            "ids": [partner_id]
        }
        response = self.session.post(f"{self.base_url}/odoo/delete", json=data)
        return self._handle_response(response)
    
    def get_models(self):
        """Lister les modèles Odoo"""
        response = self.session.get(f"{self.base_url}/odoo/models")
        return self._handle_response(response)
    
    def get_model_fields(self, model: str):
        """Obtenir les champs d'un modèle"""
        response = self.session.get(f"{self.base_url}/odoo/fields/{model}")
        return self._handle_response(response)
    
    def health_check(self):
        """Vérifier l'état de l'API"""
        response = self.session.get(f"{self.base_url}/health")
        return response.json() if response.status_code == 200 else None
    
    def _handle_response(self, response):
        """Gérer les réponses de l'API"""
        if response.status_code == 200:
            return response.json()
        elif response.status_code == 401:
            print("❌ Non autorisé - Token expiré ou invalide")
            return None
        elif response.status_code == 403:
            print("❌ Accès interdit - Permissions insuffisantes")
            return None
        else:
            print(f"❌ Erreur {response.status_code}: {response.text}")
            return None

def test_api_complete():
    """Test complet de l'API"""
    print("=== Test de l'API Odoo FastAPI ===\n")
    
    # Initialiser le client
    client = OdooAPIClient()
    
    # Tester la santé de l'API
    print("1. 🏥 Test de santé de l'API...")
    health = client.health_check()
    if health:
        print(f"✅ API en bonne santé: {health['status']}")
    else:
        print("❌ API indisponible")
        return
    
    # Se connecter avec admin (droits complets)
    print("\n2. 🔐 Connexion en tant qu'admin...")
    if not client.login("admin", "secret"):
        print("❌ Impossible de se connecter")
        return
    
    # Vérifier l'utilisateur connecté
    print("\n3. 👤 Vérification utilisateur...")
    user_info = client.get_me()
    if user_info:
        print(f"✅ Connecté en tant que: {user_info['username']}")
        print(f"   Permissions: {user_info['scopes']}")
    
    # Rechercher des partenaires
    print("\n4. 🔍 Recherche de partenaires...")
    search_result = client.search_partners(limit=5)
    if search_result and search_result['success']:
        partner_ids = search_result['data']
        print(f"✅ Trouvé {len(partner_ids)} partenaires: {partner_ids}")
        
        # Lire les détails
        print("\n5. 📖 Lecture des détails...")
        partners = client.read_partners(partner_ids[:3], ['name', 'email', 'phone'])
        if partners and partners['success']:
            for partner in partners['data']:
                print(f"   - {partner['name']} | {partner.get('email', 'Pas d\'email')}")
    
    # Rechercher et lire les entreprises
    print("\n6. 🏢 Entreprises...")
    companies = client.search_read_companies(limit=3)
    if companies and companies['success']:
        for company in companies['data']:
            print(f"   - {company['name']} | {company.get('email', 'Pas d\'email')}")
    
    # Créer un nouveau partenaire
    print("\n7. ➕ Création d'un nouveau partenaire...")
    new_partner = client.create_partner(
        name="Test API Client",
        email="test.api@example.com",
        phone="+229 12 34 56 78"
    )
    
    if new_partner and new_partner['success']:
        partner_id = new_partner['data']['id']
        print(f"✅ Partenaire créé avec l'ID: {partner_id}")
        
        # Mettre à jour le partenaire
        print("\n8. ✏️ Mise à jour...")
        update_result = client.update_partner(partner_id, {"phone": "+229 87 65 43 21"})
        if update_result and update_result['success']:
            print("✅ Partenaire mis à jour")
        
        # Supprimer le partenaire de test
        print("\n9. 🗑️ Suppression...")
        delete_result = client.delete_partner(partner_id)
        if delete_result and delete_result['success']:
            print("✅ Partenaire supprimé")
    
    print("\n✅ Test complet terminé avec succès!")

def test_readonly_user():
    """Tester avec un utilisateur en lecture seule"""
    print("\n=== Test utilisateur lecture seule ===\n")
    
    client = OdooAPIClient()
    
    print("1. 🔐 Connexion en tant qu'utilisateur readonly...")
    if client.login("readonly", "readonly123"):
        print("✅ Connexion réussie")
        
        # Tenter de lire (devrait marcher)
        print("\n2. 📖 Test de lecture (autorisé)...")
        partners = client.search_partners(limit=2)
        if partners and partners['success']:
            print(f"✅ Lecture réussie: {len(partners['data'])} partenaires")
        
        # Tenter de créer (devrait échouer)
        print("\n3. ➕ Test de création (interdit)...")
        result = client.create_partner("Test Readonly", "readonly@test.com")
        if not result:
            print("✅ Création correctement bloquée (permissions insuffisantes)")

if __name__ == "__main__":
    # Test complet avec admin
    test_api_complete()
    
    # Test avec utilisateur readonly
    test_readonly_user()

