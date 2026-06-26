"""
AES-128-CBC encryption / decryption for Hunonic MQTT payloads.

Key derivation:
  1. Pad root_id with PKCS7 to a 16-byte boundary.
  2. Encrypt the padded root_id with AES-CBC using KEY_ZERO / IV_ZERO.
  3. key = encrypted_bytes[4:20]  (16 bytes)
  4. iv  = KEY_ZERO

Requires the ``cryptography`` package:
    pip install cryptography
"""

from __future__ import annotations

import base64

from cryptography.hazmat.primitives import padding as crypto_padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes


# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------

KEY_ZERO: bytes = b"0000000000000000"  # 16 bytes
IV_ZERO: bytes = b"0000000000000000"   # 16 bytes

_BLOCK_SIZE = 128  # AES block size in bits


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _pkcs7_pad(data: bytes, block_size: int = 16) -> bytes:
    """Apply PKCS7 padding so *data* length is a multiple of *block_size*."""
    padder = crypto_padding.PKCS7(block_size * 8).padder()
    return padder.update(data) + padder.finalize()


def _pkcs7_unpad(data: bytes, block_size: int = 16) -> bytes:
    """Remove PKCS7 padding from *data*."""
    unpadder = crypto_padding.PKCS7(block_size * 8).unpadder()
    return unpadder.update(data) + unpadder.finalize()


def _aes_cbc_encrypt(plaintext: bytes, key: bytes, iv: bytes) -> bytes:
    """Encrypt *plaintext* (already padded) with AES-CBC."""
    cipher = Cipher(algorithms.AES(key), modes.CBC(iv))
    encryptor = cipher.encryptor()
    return encryptor.update(plaintext) + encryptor.finalize()


def _aes_cbc_decrypt(ciphertext: bytes, key: bytes, iv: bytes) -> bytes:
    """Decrypt *ciphertext* with AES-CBC (result is still padded)."""
    cipher = Cipher(algorithms.AES(key), modes.CBC(iv))
    decryptor = cipher.decryptor()
    return decryptor.update(ciphertext) + decryptor.finalize()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def derive_key(root_id: str) -> tuple[bytes, bytes]:
    """Derive the AES key and IV from a device *root_id*.

    Algorithm:
      1. Encode root_id to bytes and apply PKCS7 padding to 16-byte boundary.
      2. Encrypt result with AES-CBC(KEY_ZERO, IV_ZERO).
      3. key = encrypted[4:20]
      4. iv  = KEY_ZERO

    Returns:
        (key, iv) — both are 16-byte :class:`bytes` objects.
    """
    root_id_bytes = root_id.encode("utf-8")
    padded = _pkcs7_pad(root_id_bytes)
    encrypted = _aes_cbc_encrypt(padded, KEY_ZERO, IV_ZERO)
    key = encrypted[4:20]
    iv = KEY_ZERO
    return key, iv


def encrypt_payload(payload: str, root_id: str) -> str:
    """Encrypt a string *payload* for MQTT publication to a device with *root_id*.

    Steps:
      1. Derive (key, iv) from *root_id*.
      2. PKCS7-pad the UTF-8 encoded payload.
      3. Encrypt with AES-CBC(key, iv).
      4. Base64-encode and return as a string.

    Args:
        payload: JSON (or any string) payload to encrypt.
        root_id: The device's root_id used for key derivation.

    Returns:
        Base64-encoded ciphertext string.
    """
    key, iv = derive_key(root_id)
    padded = _pkcs7_pad(payload.encode("utf-8"))
    encrypted = _aes_cbc_encrypt(padded, key, iv)
    return base64.b64encode(encrypted).decode("ascii")


def decrypt_payload(encrypted: str, root_id: str) -> str:
    """Decrypt a Base64-encoded MQTT payload received from a device with *root_id*.

    Steps:
      1. Derive (key, iv) from *root_id*.
      2. Base64-decode *encrypted*.
      3. Decrypt with AES-CBC(key, iv).
      4. Strip PKCS7 padding and return the UTF-8 string.

    Args:
        encrypted: Base64-encoded ciphertext (as received from MQTT).
        root_id: The device's root_id used for key derivation.

    Returns:
        Decrypted payload string.
    """
    key, iv = derive_key(root_id)
    ciphertext = base64.b64decode(encrypted)
    padded_plain = _aes_cbc_decrypt(ciphertext, key, iv)
    return _pkcs7_unpad(padded_plain).decode("utf-8")
