from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.models.enums import DocumentStatus, DocumentType, Extractor
from app.schemas.common import ORMModel


class EntityOut(ORMModel):
    id: int
    entity_type: str
    raw_text: str
    normalized_value: dict[str, Any] | None
    confidence: float
    extractor: Extractor
    page: int | None
    char_start: int | None
    char_end: int | None


class DocumentOut(ORMModel):
    id: int
    owner_id: int
    original_filename: str
    mime_type: str
    size_bytes: int
    sha256: str
    doc_type: DocumentType
    rule_pack_key: str | None
    status: DocumentStatus
    related_document_id: int | None
    page_count: int | None
    ocr_used: bool
    error_message: str | None
    created_at: datetime
    updated_at: datetime


class DocumentDetail(DocumentOut):
    entities: list[EntityOut] = []
    open_flag_count: int = 0
    latest_run_id: int | None = None
    routing_decision: str | None = None


class DocumentTextOut(BaseModel):
    id: int
    raw_text: str | None
    page_count: int | None
    ocr_used: bool


class DocumentLink(BaseModel):
    related_document_id: int | None = Field(description="Document to compare against (e.g. a confirmation); null to unlink.")
