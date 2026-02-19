"""
Module de gestion de l'encryption RSA pour les webhooks

Utilise les clés RSA pour encrypter les données avant l'envoi
au webhook externe.
"""

import os
import base64
import json
import logging
from typing import Dict, Any
from cryptography.hazmat.primitives import serialization, hashes
from cryptography.hazmat.primitives.asymmetric import rsa, padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.backends import default_backend

logger = logging.getLogger(__name__)


class RSAEncryption:
    """Classe pour gérer l'encryption/decryption RSA"""
    
    def __init__(self, public_key_path: str = None, private_key_path: str = None, load_private: bool = False):
        """
        Initialiser avec les chemins des clés
        
        Args:
            public_key_path: Chemin vers la clé publique (pour encryption)
            private_key_path: Chemin vers la clé privée (pour décryption)
            load_private: Si True, charge aussi la clé privée (nécessaire seulement pour décryption)
        """
        self.public_key = None
        self.private_key = None
        
        # Charger depuis les variables d'environnement si non spécifié
        if public_key_path is None:
            public_key_path = os.getenv("RSA_PUBLIC_KEY_PATH", "public.pem")
        if private_key_path is None:
            private_key_path = os.getenv("RSA_PRIVATE_KEY_PATH", "private.pem")
        
        # Charger les clés si les fichiers existent
        if public_key_path and os.path.exists(public_key_path):
            self.load_public_key(public_key_path)
        
        # Charger la clé privée seulement si demandé (pour décryption)
        if load_private and private_key_path and os.path.exists(private_key_path):
            self.load_private_key(private_key_path)
    
    def load_public_key(self, key_path: str):
        """Charger la clé publique depuis un fichier PEM"""
        try:
            with open(key_path, 'rb') as key_file:
                self.public_key = serialization.load_pem_public_key(
                    key_file.read(),
                    backend=default_backend()
                )
            logger.info(f"✅ Clé publique RSA chargée: {key_path}")
        except Exception as e:
            logger.error(f"❌ Erreur chargement clé publique: {e}")
            raise
    
    def load_private_key(self, key_path: str):
        """Charger la clé privée depuis un fichier PEM"""
        try:
            with open(key_path, 'rb') as key_file:
                self.private_key = serialization.load_pem_private_key(
                    key_file.read(),
                    password=None,
                    backend=default_backend()
                )
            logger.info(f"✅ Clé privée RSA chargée: {key_path}")
        except Exception as e:
            logger.error(f"❌ Erreur chargement clé privée: {e}")
            raise
    
    def encrypt_data(self, data: Dict[str, Any]) -> str:
        """
        Encrypter des données avec chiffrement hybride RSA + AES
        
        Pour contourner la limitation de taille de RSA, on utilise:
        1. AES-256 pour encrypter les données (symétrique, rapide, pas de limite)
        2. RSA pour encrypter la clé AES (seulement 32 bytes)
        
        Args:
            data: Dictionnaire de données à encrypter
            
        Returns:
            String base64 contenant: clé_aes_encryptée + iv + données_encryptées
        """
        if self.public_key is None:
            raise ValueError("Clé publique non chargée")
        
        try:
            # Convertir les données en JSON
            json_data = json.dumps(data, ensure_ascii=False)
            plaintext = json_data.encode('utf-8')
            
            # 1. Générer une clé AES-256 aléatoire (32 bytes)
            aes_key = os.urandom(32)
            
            # 2. Générer un IV aléatoire (16 bytes pour AES)
            iv = os.urandom(16)
            
            # 3. Encrypter les données avec AES
            cipher = Cipher(
                algorithms.AES(aes_key),
                modes.CBC(iv),
                backend=default_backend()
            )
            encryptor = cipher.encryptor()
            
            # Padding PKCS7 pour que la taille soit multiple de 16
            pad_length = 16 - (len(plaintext) % 16)
            padded_plaintext = plaintext + bytes([pad_length] * pad_length)
            
            encrypted_data = encryptor.update(padded_plaintext) + encryptor.finalize()
            
            # 4. Encrypter la clé AES avec RSA
            encrypted_aes_key = self.public_key.encrypt(
                aes_key,
                padding.OAEP(
                    mgf=padding.MGF1(algorithm=hashes.SHA256()),
                    algorithm=hashes.SHA256(),
                    label=None
                )
            )
            
            # 5. Combiner: [longueur_clé_rsa(2 bytes)][clé_aes_encryptée][iv][données_encryptées]
            key_length = len(encrypted_aes_key).to_bytes(2, byteorder='big')
            combined = key_length + encrypted_aes_key + iv + encrypted_data
            
            # 6. Encoder en base64 pour transmission
            encrypted_b64 = base64.b64encode(combined).decode('utf-8')
            
            logger.debug(f"✅ Données encryptées avec AES+RSA (taille: {len(encrypted_b64)} chars)")
            
            return encrypted_b64
            
        except Exception as e:
            logger.error(f"❌ Erreur encryption: {e}")
            raise
    
    def decrypt_data(self, encrypted_data: str) -> Dict[str, Any]:
        """
        Décrypter des données avec chiffrement hybride RSA + AES
        
        Inverse du processus d'encryption:
        1. Extraire et décrypter la clé AES avec RSA
        2. Décrypter les données avec AES
        
        Args:
            encrypted_data: String base64 contenant: clé_aes_encryptée + iv + données_encryptées
            
        Returns:
            Dictionnaire des données décryptées
        """
        if self.private_key is None:
            raise ValueError("Clé privée non chargée")
        
        try:
            # 1. Décoder le base64
            combined = base64.b64decode(encrypted_data)
            
            # 2. Extraire la longueur de la clé RSA encryptée (2 premiers bytes)
            key_length = int.from_bytes(combined[0:2], byteorder='big')
            
            # 3. Extraire les composants
            encrypted_aes_key = combined[2:2+key_length]
            iv = combined[2+key_length:2+key_length+16]
            encrypted_payload = combined[2+key_length+16:]
            
            # 4. Décrypter la clé AES avec RSA
            aes_key = self.private_key.decrypt(
                encrypted_aes_key,
                padding.OAEP(
                    mgf=padding.MGF1(algorithm=hashes.SHA256()),
                    algorithm=hashes.SHA256(),
                    label=None
                )
            )
            
            # 5. Décrypter les données avec AES
            cipher = Cipher(
                algorithms.AES(aes_key),
                modes.CBC(iv),
                backend=default_backend()
            )
            decryptor = cipher.decryptor()
            padded_plaintext = decryptor.update(encrypted_payload) + decryptor.finalize()
            
            # 6. Retirer le padding PKCS7
            pad_length = padded_plaintext[-1]
            plaintext = padded_plaintext[:-pad_length]
            
            # 7. Convertir JSON en dictionnaire
            data = json.loads(plaintext.decode('utf-8'))
            
            logger.debug(f"✅ Données décryptées avec AES+RSA")
            
            return data
            
        except Exception as e:
            logger.error(f"❌ Erreur décryption: {e}")
            raise


# Instances globales
_rsa_encryption = None
_rsa_encryption_with_private = None


def get_rsa_encryption(with_private: bool = False) -> RSAEncryption:
    """
    Obtenir l'instance globale de RSAEncryption
    
    Args:
        with_private: Si True, charge aussi la clé privée pour décryption
    """
    global _rsa_encryption, _rsa_encryption_with_private
    
    if with_private:
        if _rsa_encryption_with_private is None:
            _rsa_encryption_with_private = RSAEncryption(load_private=True)
        return _rsa_encryption_with_private
    else:
        if _rsa_encryption is None:
            _rsa_encryption = RSAEncryption(load_private=False)
        return _rsa_encryption


def encrypt_webhook_data(data: Dict[str, Any]) -> str:
    """
    Fonction helper pour encrypter les données de webhook
    
    Args:
        data: Données à encrypter
        
    Returns:
        String base64 encryptée
    """
    rsa = get_rsa_encryption()
    return rsa.encrypt_data(data)


def decrypt_webhook_data(encrypted_data: str) -> Dict[str, Any]:
    """
    Fonction helper pour décrypter les données de webhook
    
    Args:
        encrypted_data: String base64 encryptée
        
    Returns:
        Données décryptées
    """
    rsa = get_rsa_encryption(with_private=True)  # Charger avec clé privée pour décryption
    return rsa.decrypt_data(encrypted_data)
