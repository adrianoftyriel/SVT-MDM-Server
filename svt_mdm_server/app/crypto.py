"""At-rest encryption for backup blobs.

Chunked AES-256-GCM so arbitrarily large files encrypt/decrypt with bounded
memory. File layout on disk:

    MAGIC (5 bytes) then repeated frames of:
        length (4 bytes, big-endian) of (nonce || ciphertext+tag)
        nonce (12 bytes)
        ciphertext + GCM tag

Each plaintext chunk gets a fresh random nonce. The key is resolved once at
import: from the MDM_BACKUP_KEY passphrase (derived via scrypt) if set,
otherwise a random 32-byte key persisted alongside the database. Losing the key
means losing the backups — that is inherent to encryption at rest.
"""

from __future__ import annotations

import base64
import hashlib
import logging
import os
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.config import settings

log = logging.getLogger("mdm.crypto")

MAGIC = b"SVTB1"
CHUNK = 256 * 1024


def _load_key() -> bytes:
    passphrase = os.getenv("MDM_BACKUP_KEY", "").strip()
    if passphrase:
        # Deterministic derivation so the same passphrase reproduces the key
        # across reinstalls. Fixed salt is acceptable for a single-tenant,
        # personal deployment where the passphrase is the secret.
        return hashlib.scrypt(
            passphrase.encode(), salt=b"svt-mdm-backup", n=2**14, r=8, p=1, dklen=32
        )

    key_path = Path(os.path.dirname(settings.db_path) or ".") / "backup.key"
    if key_path.exists():
        return base64.b64decode(key_path.read_text().strip())

    key = os.urandom(32)
    key_path.parent.mkdir(parents=True, exist_ok=True)
    key_path.write_text(base64.b64encode(key).decode())
    log.warning(
        "Generated a random backup encryption key at %s. Keep it safe; without "
        "it, existing backups cannot be decrypted.",
        key_path,
    )
    return key


_key = _load_key()


class StreamEncryptor:
    """Incrementally encrypt plaintext chunks to a binary file object."""

    def __init__(self, out) -> None:
        self._aes = AESGCM(_key)
        self._out = out
        self._buf = bytearray()
        out.write(MAGIC)

    def update(self, data: bytes) -> None:
        self._buf.extend(data)
        while len(self._buf) >= CHUNK:
            self._emit(bytes(self._buf[:CHUNK]))
            del self._buf[:CHUNK]

    def finalize(self) -> None:
        if self._buf:
            self._emit(bytes(self._buf))
            self._buf.clear()

    def _emit(self, chunk: bytes) -> None:
        nonce = os.urandom(12)
        frame = nonce + self._aes.encrypt(nonce, chunk, None)
        self._out.write(len(frame).to_bytes(4, "big"))
        self._out.write(frame)


def decrypt_iter(inp):
    """Yield decrypted plaintext chunks from an encrypted file object."""
    aes = AESGCM(_key)
    if inp.read(len(MAGIC)) != MAGIC:
        raise ValueError("Not an SVT MDM backup blob")
    while True:
        length_bytes = inp.read(4)
        if not length_bytes:
            break
        frame = inp.read(int.from_bytes(length_bytes, "big"))
        yield aes.decrypt(frame[:12], frame[12:], None)
