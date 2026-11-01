"""STORAGE_BACKEND=db keeps uploads in the stored_files table and restores the disk copy."""

import pytest

from app.core.config import get_settings
from app.ingestion.storage import absolute_path, store_upload
from app.models import StoredFile


@pytest.fixture
def db_backend(monkeypatch):
    monkeypatch.setattr(get_settings(), "storage_backend", "db")
    yield
    monkeypatch.setattr(get_settings(), "storage_backend", "local")


def test_upload_is_mirrored_to_database_and_restored_after_disk_loss(db, db_backend):
    rel, digest = store_upload(owner_id=7, extension="pdf", content=b"%PDF-1.4 demo")
    path = absolute_path(rel)
    assert path.read_bytes() == b"%PDF-1.4 demo"
    assert db.get(StoredFile, rel).size_bytes == len(b"%PDF-1.4 demo")

    path.unlink()  # simulate an ephemeral filesystem being wiped
    restored = absolute_path(rel)
    assert restored.exists() and restored.read_bytes() == b"%PDF-1.4 demo"


def test_local_backend_does_not_touch_database(db):
    rel, _ = store_upload(owner_id=7, extension="pdf", content=b"x")
    assert db.get(StoredFile, rel) is None
    assert absolute_path(rel).exists()


def test_postgres_urls_use_psycopg_driver(monkeypatch):
    from app.core.config import Settings

    assert Settings(database_url="postgres://u:p@h/db").sqlalchemy_url == "postgresql+psycopg://u:p@h/db"
    assert Settings(database_url="postgresql://u:p@h/db").sqlalchemy_url == "postgresql+psycopg://u:p@h/db"
    assert Settings(database_url="sqlite:///x.db").sqlalchemy_url == "sqlite:///x.db"
