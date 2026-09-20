from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.mysql import LONGTEXT
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.models.base import TimestampMixin, str_enum, utcnow
from app.models.enums import DocumentStatus, DocumentType


class Document(TimestampMixin, Base):
    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)

    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    storage_path: Mapped[str] = mapped_column(String(512), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(100), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), index=True, nullable=False)

    doc_type: Mapped[DocumentType] = mapped_column(
        str_enum(DocumentType), default=DocumentType.term_sheet, nullable=False
    )
    rule_pack_key: Mapped[str | None] = mapped_column(String(32), nullable=True)
    status: Mapped[DocumentStatus] = mapped_column(
        str_enum(DocumentStatus), default=DocumentStatus.uploaded, index=True, nullable=False
    )
    # Term sheet <-> confirmation pairing for cross-document checks.
    related_document_id: Mapped[int | None] = mapped_column(
        ForeignKey("documents.id"), nullable=True
    )

    raw_text: Mapped[str | None] = mapped_column(
        Text().with_variant(LONGTEXT, "mysql"), nullable=True
    )
    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ocr_used: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Final human verdict once a reviewer completes the document (approved / rejected).
    review_outcome: Mapped[str | None] = mapped_column(String(16), nullable=True)

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )

    owner = relationship("User", back_populates="documents", foreign_keys=[owner_id])
    related_document = relationship("Document", remote_side=[id], foreign_keys=[related_document_id])
    entities = relationship(
        "ExtractedEntity", back_populates="document", cascade="all, delete-orphan"
    )
    validation_runs = relationship(
        "ValidationRun", back_populates="document", cascade="all, delete-orphan",
        order_by="ValidationRun.id.desc()",
    )
    flags = relationship("Flag", back_populates="document", cascade="all, delete-orphan")
