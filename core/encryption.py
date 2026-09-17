"""
Module de gestion de l'encryption RSA pour les webhooks

Utilise les clés RSA pour encrypter les données avant l'envoi
au webhook externe.
"""

import os
import base64
import json
import logging
import zlib
from typing import Dict, Any
from cryptography.hazmat.primitives import serialization, hashes
from cryptography.hazmat.primitives.asymmetric import rsa, padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives.serialization import load_pem_private_key

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
        """Charger la clé privée depuis un fichier PEM (supporte PKCS#1 et PKCS#8)"""
        try:
            with open(key_path, 'rb') as key_file:
                key_data = key_file.read()
                
            # Essayer de charger comme PKCS#8 (BEGIN PRIVATE KEY)
            try:
                self.private_key = serialization.load_pem_private_key(
                    key_data,
                    password=None,
                    backend=default_backend()
                )
                logger.info(f"✅ Clé privée RSA chargée (PKCS#8): {key_path}")
                return
            except Exception as e1:
                logger.debug(f"Échec chargement PKCS#8: {e1}")
            
            # Si échec, essayer de la convertir de PKCS#1 à PKCS#8
            # Format PKCS#1: BEGIN RSA PRIVATE KEY
            if b'BEGIN RSA PRIVATE KEY' in key_data:
                logger.info("Détection format PKCS#1, conversion en cours...")
                
                # Utiliser openssl pour convertir
                import subprocess
                import tempfile
                
                with tempfile.NamedTemporaryFile(mode='wb', delete=False, suffix='.pem') as tmp_in:
                    tmp_in.write(key_data)
                    tmp_in_path = tmp_in.name
                
                with tempfile.NamedTemporaryFile(mode='rb', delete=False, suffix='.pem') as tmp_out:
                    tmp_out_path = tmp_out.name
                
                try:
                    # Convertir PKCS#1 vers PKCS#8
                    result = subprocess.run(
                        ['openssl', 'pkcs8', '-topk8', '-inform', 'PEM', '-outform', 'PEM', 
                         '-nocrypt', '-in', tmp_in_path, '-out', tmp_out_path],
                        capture_output=True,
                        text=True
                    )
                    
                    if result.returncode == 0:
                        with open(tmp_out_path, 'rb') as f:
                            converted_key = f.read()
                        
                        self.private_key = serialization.load_pem_private_key(
                            converted_key,
                            password=None,
                            backend=default_backend()
                        )
                        logger.info(f"✅ Clé privée RSA chargée (PKCS#1 converti): {key_path}")
                        return
                    else:
                        logger.error(f"Erreur conversion openssl: {result.stderr}")
                finally:
                    # Nettoyer les fichiers temporaires
                    try:
                        os.unlink(tmp_in_path)
                        os.unlink(tmp_out_path)
                    except:
                        pass
            
            raise ValueError(f"Impossible de charger la clé privée. Format non reconnu.")
            
        except Exception as e:
            logger.error(f"❌ Erreur chargement clé privée: {e}")
            raise
    
    def encrypt_data(self, data: Dict[str, Any], use_compression: bool = True) -> str:
        """
        Encrypter des données avec RSA pur + compression optionnelle
        
        Compatible avec Node.js crypto.publicEncrypt avec OAEP padding
        
        Args:
            data: Dictionnaire de données à encrypter
            use_compression: Si True, compresse les données avec zlib avant encryption
            
        Returns:
            String base64 des données encryptées
        """
        if self.public_key is None:
            raise ValueError("Clé publique non chargée")
        
        try:
            # Convertir les données en JSON
            json_data = json.dumps(data, ensure_ascii=False, separators=(',', ':'))
            plaintext = json_data.encode('utf-8')
            
            # Compresser si demandé (réduit la taille pour RSA)
            if use_compression:
                compressed = zlib.compress(plaintext, level=9)
                # Préfixe pour indiquer que c'est compressé
                to_encrypt = b'ZLIB:' + compressed
                logger.debug(f"Compression: {len(plaintext)} bytes -> {len(compressed)} bytes")
            else:
                to_encrypt = plaintext
            
            # Vérifier la taille (RSA 2048 avec OAEP SHA256 = max ~190 bytes)
            max_size = (self.public_key.key_size // 8) - 2 * 32 - 2  # ~190 bytes pour 2048 bits
            if len(to_encrypt) > max_size:
                raise ValueError(
                    f"Données trop grandes pour RSA ({len(to_encrypt)} bytes, max {max_size} bytes). "
                    f"Original: {len(plaintext)} bytes. Activez la compression ou réduisez les données."
                )
            
            # Encrypter avec RSA + OAEP padding (compatible Node.js)
            encrypted = self.public_key.encrypt(
                to_encrypt,
                padding.OAEP(
                    mgf=padding.MGF1(algorithm=hashes.SHA256()),
                    algorithm=hashes.SHA256(),
                    label=None
                )
            )
            
            # Encoder en base64 pour transmission
            encrypted_b64 = base64.b64encode(encrypted).decode('utf-8')
            
            logger.debug(f"✅ Données encryptées avec RSA+OAEP (taille: {len(encrypted_b64)} chars)")
            
            return encrypted_b64
            
        except Exception as e:
            logger.error(f"❌ Erreur encryption: {e}")
            raise
    
    def decrypt_data(self, encrypted_data: str) -> Dict[str, Any]:
        """
        Décrypter des données avec chiffrement hybride RSA + AES
        
        Inverse du processus d'encryption:
        1. Extraire et décrypter la clé AES avec RSA
        Décryptage RSA pur (compatible Node.js)
        
        Args:
            encrypted_data: String base64 contenant les données encryptées avec RSA
            
        Returns:
            Dictionnaire des données décryptées
        """
        if self.private_key is None:
            raise ValueError("Clé privée non chargée")
        
        try:
            # 1. Décoder le base64
            encrypted_bytes = base64.b64decode(encrypted_data)
            
            # 2. Décrypter avec RSA-OAEP
            decrypted = self.private_key.decrypt(
                encrypted_bytes,
                padding.OAEP(
                    mgf=padding.MGF1(algorithm=hashes.SHA256()),
                    algorithm=hashes.SHA256(),
                    label=None
                )
            )
            
            # 3. Vérifier si les données sont compressées (préfixe ZLIB:)
            if decrypted.startswith(b'ZLIB:'):
                compressed = decrypted[5:]  # Retirer le préfixe 'ZLIB:'
                plaintext = zlib.decompress(compressed)
                logger.debug(f"✅ Données décompressées: {len(compressed)} -> {len(plaintext)} bytes")
            else:
                plaintext = decrypted
            
            # 4. Convertir JSON en dictionnaire
            data = json.loads(plaintext.decode('utf-8'))
            
            logger.debug(f"✅ Données décryptées avec RSA pur")
            
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


def encrypt_webhook_data(data: Dict[str, Any], use_compression: bool = False) -> str:
    """
    Fonction helper pour encrypter les données de webhook
    
    Args:
        data: Données à encrypter
        use_compression: Si True, compresse avec zlib (désactivé par défaut pour compatibilité Node.js)
        
    Returns:
        String base64 encryptée
    """
    rsa = get_rsa_encryption()
    return rsa.encrypt_data(data, use_compression=use_compression)


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
