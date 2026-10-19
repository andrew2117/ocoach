"""Application-level encryption for BYOK API keys stored in Supabase.

Hosted Supabase does not grant the SQL editor / postgres role permission to
call `pgsodium.crypto_aead_det_encrypt`, so we encrypt in the FastAPI backend
before writing and decrypt after reading. Ciphertext is stored in
`profiles.anthropic_api_key`; only the backend (Secret Key) can read it.
"""

from __future__ import annotations

import base64
import hashlib
import logging

from cryptography.fernet import Fernet, InvalidToken

from core.config import settings

logger = logging.getLogger(__name__)


def _fernet_key_material() -> bytes:
    """Derive a stable 32-byte Fernet key from server-only configuration."""
    source = settings.profile_encryption_key or settings.supabase_secret_key
    if not source:
        raise RuntimeError(
            "PROFILE_ENCRYPTION_KEY or SUPABASE_SECRET_KEY must be set to encrypt BYOK keys"
        )
    return base64.urlsafe_b64encode(hashlib.sha256(source.encode()).digest())


def encrypt_api_key(plaintext: str) -> str:
    return Fernet(_fernet_key_material()).encrypt(plaintext.encode()).decode()


def decrypt_api_key(ciphertext: str) -> str | None:
    try:
        return Fernet(_fernet_key_material()).decrypt(ciphertext.encode()).decode()
    except InvalidToken:
        logger.warning("Could not decrypt stored API key (invalid or legacy ciphertext)")
        return None
