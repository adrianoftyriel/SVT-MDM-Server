"""Filesystem storage for encrypted, content-addressed backup blobs.

Objects live at ``<backup_dir>/<device_id>/<sha[:2]>/<sha>.enc`` — content
addressed by the SHA-256 of the *plaintext*, so identical files are stored once
per device (dedup). Blobs are encrypted on the way in (see app.crypto).
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

from app.config import settings
from app.crypto import StreamEncryptor, decrypt_iter


def object_path(device_id: str, sha256: str) -> Path:
    return Path(settings.backup_dir) / device_id / sha256[:2] / f"{sha256}.enc"


def exists(device_id: str, sha256: str) -> bool:
    return object_path(device_id, sha256).exists()


async def store(device_id: str, sha256: str, stream) -> tuple[bool, int, str]:
    """Encrypt and store a plaintext byte stream, verifying its SHA-256.

    Returns (ok, plaintext_size, message). On hash mismatch nothing is kept.
    ``stream`` is an async iterator of bytes (e.g. request.stream()).
    """
    path = object_path(device_id, sha256)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".enc.tmp")

    hasher = hashlib.sha256()
    size = 0
    try:
        with open(tmp, "wb") as f:
            enc = StreamEncryptor(f)
            async for chunk in stream:
                hasher.update(chunk)
                size += len(chunk)
                enc.update(chunk)
            enc.finalize()
    except Exception:
        tmp.unlink(missing_ok=True)
        raise

    if hasher.hexdigest() != sha256:
        tmp.unlink(missing_ok=True)
        return False, size, "sha256 mismatch"

    os.replace(tmp, path)
    return True, size, "stored"


def open_decrypted(device_id: str, sha256: str):
    """Generator yielding decrypted plaintext chunks for download."""
    path = object_path(device_id, sha256)
    with open(path, "rb") as f:
        yield from decrypt_iter(f)


def delete(device_id: str, sha256: str) -> None:
    object_path(device_id, sha256).unlink(missing_ok=True)
