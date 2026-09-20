"""Local filesystem storage for uploaded originals.

Paths are stored relative to `settings.storage_dir` so the directory can be re-pointed
(e.g. to a mounted volume or later an S3-backed adapter) without touching the database.
"""

import hashlib
import uuid
from pathlib import Path

from app.core.config import get_settings


def sha256_of(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def store_upload(owner_id: int, extension: str, content: bytes) -> tuple[str, str]:
    """Persist bytes; return (relative_path, sha256)."""
    settings = get_settings()
    rel = Path(str(owner_id)) / f"{uuid.uuid4().hex}.{extension}"
    abs_path = settings.storage_dir / rel
    abs_path.parent.mkdir(parents=True, exist_ok=True)
    abs_path.write_bytes(content)
    return rel.as_posix(), sha256_of(content)


def absolute_path(relative_path: str) -> Path:
    settings = get_settings()
    path = (settings.storage_dir / relative_path).resolve()
    # Guard against a tampered storage_path escaping the storage root.
    if settings.storage_dir.resolve() not in path.parents:
        raise ValueError("Storage path escapes storage root.")
    return path
