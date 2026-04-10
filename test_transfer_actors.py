#!/usr/bin/env python3
"""
Exemple d'utilisation des nouveaux champs d'acteurs sur les transferts
"""
import json

# Exemple de réponse complète avec les nouveaux champs
example_transfer = {
    "id": 95290,
    "name": "BURWA/OUT/01620",
    "state": "done",
    "picking_type_code": "outgoing",
    "date": "2026-04-08",
    
    # Localisations
    "location_source_details": {
        "id": 38,
        "name": "IMMO",
        "complete_name": "BURWA/IMMO",
        "usage": "internal",
        "warehouse_id": [4, "JNP SA - BUREAUX WANSIROU"],
        "partner_id": False  # Localisation interne
    },
    
    "location_destination_details": {
        "id": 5,
        "name": "Customers",
        "complete_name": "Partners/Customers",
        "usage": "customer",
        "warehouse_id": False,
        "partner_id": False
    },
    
    # 🆕 NOUVEAUX: Acteurs/responsables
    "location_source_actor": {
        "id": 1968,
        "name": "Alassane Diallo",
        "mobile": "+221 77 123 4567",
        "email": "alassane.diallo@opensi.co",
        "function": "Chauffeur Principal",
        "type": "contact"
    },
    
    "location_destination_actor": None,  # Pas de responsable spécifique côté client
    
    # Partenaire principal du transfert
    "partner_details": {
        "id": 456,
        "name": "Client ABC SARL",
        "type": "delivery",
        "phone": "+221 77 555 1234",
        "mobile": "+221 77 555 1234",
        "email": "contact@abc.sn",
        "is_company": True
    },
    
    # Premier contact (pour compat avec ancien code)
    "driver_details": {
        "id": 1968,
        "name": "Alassane Diallo",
        "mobile": "+221 77 123 4567"
    },
    
    # 🆕 NOUVEAU: Tous les contacts associés
    "related_contacts": [
        {
            "id": 1968,
            "name": "Alassane Diallo",
            "mobile": "+221 77 123 4567",
            "email": "alassane.diallo@opensi.co",
            "function": "Chauffeur Principal",
            "type": "contact"
        },
        {
            "id": 1969,
            "name": "Daouda Sall",
            "mobile": "+221 77 333 2222",
            "email": "assistant@jo70.opensi.co",
            "function": "Assistant",
            "type": "contact"
        }
    ]
}


def display_transfer_details(transfer):
    """Affiche les détails d'un transfert de manière lisible"""
    
    print("\n" + "="*80)
    print(f"📦 Transfert: {transfer['name']} ({transfer['state'].upper()})")
    print(f"   Type: {transfer['picking_type_code']} | Date: {transfer.get('date', 'N/A')}")
    print("="*80)
    
    # Source
    print(f"\n📤 SOURCE: {transfer['location_source_details']['complete_name']}")
    if transfer.get('location_source_actor'):
        actor = transfer['location_source_actor']
        print(f"   Responsable: {actor['name']}")
        if actor.get('function'):
            print(f"   Fonction: {actor['function']}")
        if actor.get('mobile'):
            print(f"   Mobile: {actor['mobile']}")
        if actor.get('email'):
            print(f"   Email: {actor['email']}")
    else:
        print(f"   Aucun responsable spécifique")
    
    # Destination
    print(f"\n📥 DESTINATION: {transfer['location_destination_details']['complete_name']}")
    if transfer.get('location_destination_actor'):
        actor = transfer['location_destination_actor']
        print(f"   Responsable: {actor['name']}")
        if actor.get('function'):
            print(f"   Fonction: {actor['function']}")
        if actor.get('mobile'):
            print(f"   Mobile: {actor['mobile']}")
    else:
        print(f"   Aucun responsable spécifique")
    
    # Partenaire principal
    if transfer.get('partner_details'):
        partner = transfer['partner_details']
        print(f"\n🤝 PARTENAIRE: {partner['name']}")
        print(f"   Type: {partner.get('type', 'N/A')}")
        if partner.get('phone'):
            print(f"   Tel: {partner['phone']}")
        if partner.get('email'):
            print(f"   Email: {partner['email']}")
    
    # Contacts associés
    if transfer.get('related_contacts') and len(transfer['related_contacts']) > 0:
        print(f"\n👥 CONTACTS ASSOCIÉS ({len(transfer['related_contacts'])}):")
        for contact in transfer['related_contacts']:
            print(f"   • {contact['name']}")
            if contact.get('function'):
                print(f"     - {contact['function']}")
            if contact.get('mobile'):
                print(f"     - {contact['mobile']}")


def get_responsible_for_action(transfer, action_type):
    """
    Retourne le contact à contacter selon l'action requise.
    
    Args:
        transfer: Le transfert
        action_type: 'send', 'receive', 'urgent', etc.
    
    Returns:
        dict: Contact à contacter ou None
    """
    
    if action_type == 'send':
        # Qui a envoyé? → location_source_actor
        return transfer.get('location_source_actor')
    
    elif action_type == 'receive':
        # Qui doit recevoir? → location_destination_actor ou manager
        return transfer.get('location_destination_actor')
    
    elif action_type == 'urgent':
        # En cas d'urgence: essayer le chauffeur d'abord
        if transfer.get('location_source_actor'):
            return transfer['location_source_actor']
        elif transfer.get('driver_details'):
            return transfer['driver_details']
        else:
            return transfer.get('partner_details')
    
    elif action_type == 'all_contacts':
        # Tous les contacts disponibles
        contacts = []
        if transfer.get('location_source_actor'):
            contacts.append(transfer['location_source_actor'])
        if transfer.get('location_destination_actor'):
            contacts.append(transfer['location_destination_actor'])
        if transfer.get('related_contacts'):
            contacts.extend(transfer['related_contacts'])
        return contacts
    
    return None


def extract_contact_list(transfer):
    """Extrait une liste de numéros à contacter"""
    
    numbers = []
    
    # Source
    source = transfer.get('location_source_actor') or {}
    if source.get('mobile'):
        numbers.append(source['mobile'])
    
    # Destination
    dest = transfer.get('location_destination_actor') or {}
    if dest.get('mobile'):
        numbers.append(dest['mobile'])
    
    # Tous les autres contacts
    for contact in transfer.get('related_contacts', []) or []:
        if contact and contact.get('mobile') and contact['mobile'] not in numbers:
            numbers.append(contact['mobile'])
    
    return numbers


# ============================================================
# TESTS
# ============================================================

if __name__ == "__main__":
    print("\n🧪 Tests des nouveaux champs d'acteurs de transfert\n")
    
    # Test 1: Affichage lisible
    print("\n[TEST 1] Affichage formaté du transfert:")
    display_transfer_details(example_transfer)
    
    # Test 2: Récupérer le responsable de l'envoi
    print("\n[TEST 2] Qui a envoyé?")
    sender = get_responsible_for_action(example_transfer, 'send')
    if sender:
        print(f"✅ {sender['name']} ({sender.get('mobile', 'N/A')})")
    else:
        print("❌ Pas de responsable trouvé")
    
    # Test 3: Récupérer le responsable de la réception
    print("\n[TEST 3] Qui reçoit?")
    receiver = get_responsible_for_action(example_transfer, 'receive')
    if receiver:
        print(f"✅ {receiver['name']} ({receiver.get('mobile', 'N/A')})")
    else:
        print("⚠️ Pas de responsable spécifique (réception générique)")
    
    # Test 4: Cas d'urgence
    print("\n[TEST 4] En cas d'urgence, qui contacter?")
    urgent_contact = get_responsible_for_action(example_transfer, 'urgent')
    if urgent_contact:
        print(f"✅ {urgent_contact['name']} ({urgent_contact.get('mobile', 'N/A')})")
    else:
        print("❌ Aucun contact trouvé")
    
    # Test 5: Tous les contacts
    print("\n[TEST 5] Tous les contacts disponibles:")
    all_contacts = get_responsible_for_action(example_transfer, 'all_contacts')
    for i, contact in enumerate(all_contacts, 1):
        print(f"  {i}. {contact.get('name', 'N/A')} - {contact.get('mobile', 'N/A')}")
    
    # Test 6: Liste de numéros à notifier
    print("\n[TEST 6] Numéros à notifier (SMS/appel):")
    numbers = extract_contact_list(example_transfer)
    for num in numbers:
        print(f"  • {num}")
    
    # Test 7: Export JSON
    print("\n[TEST 7] Export JSON des champs importants:")
    important_fields = {
        "transfer_id": example_transfer['id'],
        "transfer_name": example_transfer['name'],
        "source_actor": example_transfer.get('location_source_actor'),
        "destination_actor": example_transfer.get('location_destination_actor'),
        "related_contacts": example_transfer.get('related_contacts'),
        "contact_numbers": extract_contact_list(example_transfer)
    }
    print(json.dumps(important_fields, indent=2, ensure_ascii=False))
    
    print("\n✅ Tests terminés!\n")
