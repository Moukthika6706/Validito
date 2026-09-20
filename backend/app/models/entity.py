from typing import Any

from sqlalchemy import JSON, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.models.base import TimestampMixin, str_enum
from app.models.enums import Extractor


class ExtractedEntity(TimestampMixin, Base):
    __tablename__ = "extracted_entities"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    document_id: Mapped[int] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), index=True, nullable=False
    )

    entity_type: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    raw_text: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_value: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    extractor: Mapped[Extractor] = mapped_column(str_enum(Extractor), nullable=False)

    page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    char_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    char_end: Mapped[int | None] = mapped_column(Integer, nullable=True)

    document = relationship("Document", back_populates="entities")
