#!/usr/bin/env python3
"""
secure_value — encryption at rest for Global Integration credentials.

Uses PyNaCl's SecretBox (authenticated XSalsa20-Poly1305). The master key
comes from the GLOBAL_INTEGRATIONS_KEY env var (base64, 32 bytes); if unset,
a key is auto-generated once and persisted to a key file (chmod 600) next
to this module — zero-config for dev, explicit env for production.

Stored format: "enc:v1:<base64(nonce + ciphertext)>" — the version prefix
enables future algorithm migration / key rotation.
"""

import base64
import logging
import os
import secrets
import threading

from nacl.secret import SecretBox

logger = logging.getLogger("secure_value")

_PREFIX = "enc:v1:"
_KEY_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "secure_value.key")

_box: SecretBox | None = None
_lock = threading.Lock()


def _load_or_create_key() -> bytes:
    env_key = os.getenv("GLOBAL_INTEGRATIONS_KEY", "").strip()
    if env_key:
        raw = base64.b64decode(env_key)
        if len(raw) != SecretBox.KEY_SIZE:
            raise ValueError(
                f"GLOBAL_INTEGRATIONS_KEY must be base64 of {SecretBox.KEY_SIZE} bytes "
                f"(got {len(raw)}). Generate with: openssl rand -base64 32")
        return raw

    # Fallback: auto-generated key file (dev / zero-config)
    if os.path.exists(_KEY_FILE):
        with open(_KEY_FILE, "r") as f:
            raw = base64.b64decode(f.read().strip())
        if len(raw) == SecretBox.KEY_SIZE:
            return raw
        logger.warning("secure_value: key file has wrong size — regenerating")

    raw = secrets.token_bytes(SecretBox.KEY_SIZE)
    fd = os.open(_KEY_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(base64.b64encode(raw).decode())
    logger.info("secure_value: generated new key file %s (set GLOBAL_INTEGRATIONS_KEY "
                "in production before storing real credentials)", _KEY_FILE)
    return raw


def _get_box() -> SecretBox:
    global _box
    if _box is None:
        with _lock:
            if _box is None:
                _box = SecretBox(_load_or_create_key())
    return _box


def encrypt_value(plaintext: str) -> str:
    """Encrypt a secret for storage. Fresh nonce per call (SecretBox default)."""
    encrypted = _get_box().encrypt(plaintext.encode("utf-8"))
    return _PREFIX + base64.b64encode(bytes(encrypted)).decode("ascii")


def decrypt_value(stored: str) -> str:
    """Decrypt a stored secret. Raises ValueError on tamper/wrong key/format."""
    if not stored or not stored.startswith(_PREFIX):
        raise ValueError("Value is not in enc:v1: format")
    try:
        raw = base64.b64decode(stored[len(_PREFIX):])
    except Exception as e:
        raise ValueError(f"Corrupted encrypted value: {e}")
    try:
        plaintext = _get_box().decrypt(raw)
    except Exception as e:
        raise ValueError(
            "Decryption failed (wrong GLOBAL_INTEGRATIONS_KEY or tampered data)")
    return plaintext.decode("utf-8")
