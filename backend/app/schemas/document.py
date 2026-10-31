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
    bbox: list[dict[str, Any]] | None = None


class PageInfo(BaseModel):
    number: int
    width: float
    height: float


class PagesOut(BaseModel):
    document_id: int
    renderable: bool
    render_source: str | None = Field(default=None, description="pdf | image | libreoffice | null when no page render is possible (e.g. DOCX without LibreOffice)")
    page_count: int
    pages: list[PageInfo]
    note: str | None = None


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
    review_outcome: str | None = None
    failed_stage: str | None = None
    attempts: int = 0
    claimed_by_id: int | None = None
    claimed_by_name: str | None = None
    claimed_at: datetime | None = None
    claim_expires_at: datetime | None = None
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


class DocumentStatusOut(ORMModel):
    id: int
    status: DocumentStatus
    terminal: bool
    failed_stage: str | None
    error_message: str | None
    attempts: int
    routing_decision: str | None
    review_outcome: str | None
    updated_at: datetime


class BulkFileResult(BaseModel):
    filename: str
    accepted: bool
    document_id: int | None
    status: str | None
    reason: str | None


class BulkUploadResult(BaseModel):
    accepted: int
    rejected: int
    results: list[BulkFileResult]


class DocumentLink(BaseModel):
    related_document_id: int | None = Field(description="Document to compare against (e.g. a confirmation); null to unlink.")
