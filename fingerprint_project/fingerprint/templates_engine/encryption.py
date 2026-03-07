"""
Template Encryption Module
──────────────────────────
AES-256-CBC encryption and decryption for fingerprint templates.
"""

import os
import logging
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad, unpad
from django.conf import settings

logger = logging.getLogger('fingerprint')

# AES block size
BLOCK_SIZE = 16


def _get_key():
    """
    Get encryption key from settings.
    Key must be 32 bytes (256 bits) as hex string.
    """
    key_hex = settings.FINGERPRINT.get('ENCRYPTION_KEY', '')

    if not key_hex:
        # Generate a default key for development
        logger.warning(
            "No ENCRYPTION_KEY set! Using generated key. "
            "Set ENCRYPTION_KEY in .env for production."
        )
        key_hex = os.urandom(32).hex()

    # Convert hex string to bytes
    key_bytes = bytes.fromhex(key_hex) if len(key_hex) == 64 else key_hex.encode()

    # Ensure 32 bytes
    if len(key_bytes) < 32:
        key_bytes = key_bytes.ljust(32, b'\0')
    elif len(key_bytes) > 32:
        key_bytes = key_bytes[:32]

    return key_bytes


def encrypt_template(template_bytes):
    """
    Encrypt a fingerprint template using AES-256-CBC.

    Args:
        template_bytes: Raw template bytes

    Returns:
        bytes: IV (16 bytes) + encrypted template
    """
    key = _get_key()
    iv = os.urandom(BLOCK_SIZE)

    cipher = AES.new(key, AES.MODE_CBC, iv)
    padded = pad(template_bytes, BLOCK_SIZE)
    encrypted = cipher.encrypt(padded)

    # Prepend IV to ciphertext
    result = iv + encrypted

    logger.info(
        "Template encrypted: input=%d bytes, output=%d bytes",
        len(template_bytes), len(result)
    )

    return result


def decrypt_template(encrypted_bytes):
    """
    Decrypt an AES-256-CBC encrypted fingerprint template.

    Args:
        encrypted_bytes: IV (16 bytes) + encrypted template

    Returns:
        bytes: Decrypted template bytes

    Raises:
        ValueError: If decryption fails (wrong key or corrupt data)
    """
    key = _get_key()

    if len(encrypted_bytes) < BLOCK_SIZE:
        raise ValueError("Encrypted data too short")

    # Extract IV and ciphertext
    iv = encrypted_bytes[:BLOCK_SIZE]
    ciphertext = encrypted_bytes[BLOCK_SIZE:]

    try:
        cipher = AES.new(key, AES.MODE_CBC, iv)
        decrypted = cipher.decrypt(ciphertext)
        unpadded = unpad(decrypted, BLOCK_SIZE)
    except Exception as e:
        raise ValueError(f"Decryption failed: {e}")

    logger.info(
        "Template decrypted: input=%d bytes, output=%d bytes",
        len(encrypted_bytes), len(unpadded)
    )

    return unpadded
