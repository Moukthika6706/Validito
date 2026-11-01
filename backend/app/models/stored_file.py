"""Uploaded originals kept inside the database (STORAGE_BACKEND=db).

Used on hosts whose filesystem is wiped on every restart (e.g. Render's free tier). The
local `storage_dir` then acts only as a cache that is re-filled from this table on demand.
"""

from datetime import datetime

from sqlalchemy import DateTime, Integer, LargeBinary, String
from sqlalchemy.dialects.mysql import LONGBLOB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.base import utcnow


class StoredFile(Base):
    __tablename__ = "stored_files"

    # Same relative path that Document.storage_path holds.
    path: Mapped[str] = mapped_column(String(512), primary_key=True)
    content: Mapped[bytes] = mapped_column(LargeBinary().with_variant(LONGBLOB, "mysql"), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
