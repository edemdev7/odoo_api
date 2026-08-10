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

# Secret partagé avec le consommateur du webhook (OPEN SI).
# Jamais en dur dans le code : uniquement via variable d'environnement.
ODOO_WEBHOOK_SECRET = os.getenv("ODOO_WEBHOOK_SECRET", "")


def compute_webhook_signature(payload: str, secret: Optional[str] = None) -> Optional[str]:
    """
    Signature HMAC-SHA256 (hex) du payload `x-encrypted-data`.

    Le consommateur recalcule la même signature de son côté et compare : cela
    garantit que la requête provient bien de nous et que le payload n'a pas été
    altéré en transit.

    Retourne None si aucun secret n'est configuré — l'envoi reste possible, mais
    non signé, ce qui sera probablement rejeté par le destinataire.
    """
    key = secret if secret is not None else ODOO_WEBHOOK_SECRET
    if not key:
        return None
    return hmac.new(
        key.encode('utf-8'),
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
        logger.info(f"[WEBHOOK_SENDER] Payload signé (HMAC-SHA256): {signature[:12]}…")
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
