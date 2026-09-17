"""
Helper to send encrypted webhook payloads to multiple endpoints in parallel.
"""
import asyncio
import hashlib
import hmac
import logging
import os
from typing import List, Dict, Any, Tuple, Optional
import httpx

from core.encryption import encrypt_webhook_data

logger = logging.getLogger(__name__)

# Le secret et son encodage sont lus À CHAQUE APPEL, jamais figés à l'import.
#
# Figer la valeur au niveau module créait un piège : si `load_dotenv()` s'exécute
# après l'import de ce module, ou si la variable est déjà présente dans
# l'environnement du service (systemd), le processus conserve une valeur périmée
# malgré la modification du fichier .env.


def _secret_to_key(secret: str) -> bytes:
    """
    Convertit le secret en clé HMAC selon l'encodage configuré.

    ODOO_WEBHOOK_SECRET_ENCODING :
      "raw" → la chaîne telle quelle (défaut, correspond au createHmac de Node)
      "hex" → les octets obtenus en décodant l'hexadécimal
    """
    encoding = os.getenv("ODOO_WEBHOOK_SECRET_ENCODING", "raw").lower()
    if encoding == "hex":
        try:
            return bytes.fromhex(secret)
        except ValueError:
            logger.error(
                "[WEBHOOK_SENDER] ODOO_WEBHOOK_SECRET_ENCODING=hex mais le secret "
                "n'est pas de l'hexadécimal valide — repli sur l'encodage brut"
            )
    return secret.encode('utf-8')


def verify_inbound_signature(payload: bytes, signature: str, secret: str) -> bool:
    """
    Vérifie la signature HMAC-SHA256 d'un contenu reçu.

    Pendant entrant de `compute_webhook_signature` : l'émetteur signe le contenu
    binaire avec le secret partagé, on recalcule et on compare.

    La comparaison utilise `compare_digest`, dont le temps d'exécution ne dépend
    pas de l'endroit où les deux valeurs divergent. Un `==` classique permettrait
    de deviner la signature attendue octet par octet en mesurant les temps de
    réponse.
    """
    if not signature or not secret:
        return False
    attendue = hmac.new(secret.encode('utf-8'), payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(attendue, signature.strip().lower())


def secret_fingerprint(secret: str) -> str:
    """
    Empreinte du secret réellement utilisé, sans jamais l'exposer.

    C'est le HMAC de la chaîne 'test' avec ce secret : la même sonde peut être
    calculée de l'autre côté pour vérifier que les deux parties utilisent bien
    la même valeur, sans avoir à se la réenvoyer.
    """
    if not secret:
        return "<vide>"
    return hmac.new(secret.encode('utf-8'), b'test', hashlib.sha256).hexdigest()[:16]


def compute_webhook_signature(payload: str, secret: Optional[str] = None) -> Optional[str]:
    """
    Signature HMAC-SHA256 (hex) du payload `x-encrypted-data`.

    Le consommateur recalcule la même signature de son côté et compare : cela
    garantit que la requête provient bien de nous et que le payload n'a pas été
    altéré en transit.

    Retourne None si aucun secret n'est configuré — l'envoi reste possible, mais
    non signé, ce qui sera probablement rejeté par le destinataire.
    """
    key = secret if secret is not None else os.getenv("ODOO_WEBHOOK_SECRET", "")
    if not key:
        return None
    return hmac.new(
        _secret_to_key(key),
        payload.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()


async def send_encrypted_webhook(
    urls: List[str],
    webhook_data: Dict[str, Any],
    timeout: int = 10,
    use_compression: bool = False,
) -> List[Tuple[str, int, str]]:
    """Encrypt webhook_data once and POST to all urls in parallel.

    Returns a list of tuples: (url, status_code, response_text_or_error).
    """
    # Normalize and deduplicate URLs while preserving order
    urls = [u for u in dict.fromkeys(urls) if u]
    if not urls:
        logger.warning("[WEBHOOK_SENDER] No webhook URLs provided")
        return []

    try:
        encrypted = encrypt_webhook_data(webhook_data, use_compression=use_compression)
    except Exception as e:
        logger.error(f"[WEBHOOK_SENDER] Error encrypting webhook data: {e}")
        return [(u, 0, f"encryption_error:{e}") for u in urls]

    headers = {
        'Content-Type': 'application/json',
        'x-encrypted-data': encrypted,
    }

    signature = compute_webhook_signature(encrypted)
    if signature:
        headers['x-odoo-signature'] = signature
        current_secret = os.getenv("ODOO_WEBHOOK_SECRET", "")
        logger.info(
            f"[WEBHOOK_SENDER] Payload signé (HMAC-SHA256): {signature[:12]}… | "
            f"empreinte du secret utilisé: {secret_fingerprint(current_secret)} | "
            f"encodage: {os.getenv('ODOO_WEBHOOK_SECRET_ENCODING', 'raw')} | "
            f"longueur payload signé: {len(encrypted)}"
        )
    else:
        logger.warning(
            "[WEBHOOK_SENDER] ODOO_WEBHOOK_SECRET absent — webhook envoyé sans "
            "signature, il sera probablement rejeté par le destinataire"
        )

    async with httpx.AsyncClient(timeout=timeout) as client:
        async def _post(u: str):
            try:
                resp = await client.post(u, headers=headers)
                text = resp.text[:1000] if resp.text else ''
                if resp.status_code in (200, 201, 204):
                    logger.info(f"✅ [WEBHOOK_SENDER] Webhook envoyé vers {u} - Status {resp.status_code}")
                else:
                    logger.warning(f"⚠️ [WEBHOOK_SENDER] Webhook rejeté par {u} - Status {resp.status_code}: {text}")
                return (u, resp.status_code, text)
            except Exception as e:
                logger.error(f"❌ [WEBHOOK_SENDER] Exception lors de l'envoi vers {u}: {e}")
                return (u, 0, str(e))

        tasks = [_post(u) for u in urls]
        results = await asyncio.gather(*tasks, return_exceptions=False)

    return results
