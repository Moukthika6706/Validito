"""Storage for uploaded originals.

Paths are stored relative to `settings.storage_dir` so the directory can be re-pointed
without touching the database. Two backends, chosen with STORAGE_BACKEND:

  local (default)  bytes live only on disk under storage_dir.
  db               bytes are also written to the `stored_files` table; the disk copy is a
                   cache that `absolute_path()` re-creates from the database when missing.
                   Use this on hosts whose filesystem is reset on restart (Render free tier).

Callers always receive a real filesystem path, so PyMuPDF / python-docx / FileResponse work
unchanged.
"""

import hashlib
import logging
import uuid
from pathlib import Path

from app.core.config import get_settings

log = logging.getLogger(__name__)


def sha256_of(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _db_backend() -> bool:
    return get_settings().storage_backend.lower() == "db"


def _write_cache(rel: str, content: bytes) -> Path:
    abs_path = get_settings().storage_dir / rel
    abs_path.parent.mkdir(parents=True, exist_ok=True)
    abs_path.write_bytes(content)
    return abs_path


def _save_to_db(rel: str, content: bytes) -> None:
    from app.core.db import session_scope
    from app.models.stored_file import StoredFile

    with session_scope() as db:
        existing = db.get(StoredFile, rel)
        if existing is None:
            db.add(StoredFile(path=rel, content=content, size_bytes=len(content)))
        else:
            existing.content, existing.size_bytes = content, len(content)


def _load_from_db(rel: str) -> bytes | None:
    from app.core.db import session_scope
    from app.models.stored_file import StoredFile

    with session_scope() as db:
        row = db.get(StoredFile, rel)
        return bytes(row.content) if row is not None else None


def store_upload(owner_id: int, extension: str, content: bytes) -> tuple[str, str]:
    """Persist bytes; return (relative_path, sha256)."""
    rel = (Path(str(owner_id)) / f"{uuid.uuid4().hex}.{extension}").as_posix()
    _write_cache(rel, content)
    if _db_backend():
        _save_to_db(rel, content)
    return rel, sha256_of(content)


def absolute_path(relative_path: str) -> Path:
    settings = get_settings()
    path = (settings.storage_dir / relative_path).resolve()
    # Guard against a tampered storage_path escaping the storage root.
    if settings.storage_dir.resolve() not in path.parents:
        raise ValueError("Storage path escapes storage root.")
    if not path.exists() and _db_backend():
        content = _load_from_db(relative_path)
        if content is not None:
            log.info("Restoring %s from database storage", relative_path)
            _write_cache(relative_path, content)
    return path
