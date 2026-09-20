"""Extraction stage: file -> text -> entities, persisted with an audit trail."""

import logging

from sqlalchemy.orm import Session

from app.audit import events, record
from app.extraction.ner import extract_entities
from app.extraction.text import extract_text
from app.ingestion.storage import absolute_path
from app.models import Document, DocumentStatus, ExtractedEntity

log = logging.getLogger(__name__)


def set_status(db: Session, document: Document, status: DocumentStatus, *, actor_id: int | None = None, **payload) -> None:
    previous = document.status
    document.status = status
    record(
        db,
        event_type=events.DOCUMENT_STATUS_CHANGED,
        target_type="document",
        target_id=document.id,
        document_id=document.id,
        actor_id=actor_id,
        payload={"from": previous.value, "to": status.value, **payload},
    )


def run_extraction(db: Session, document: Document) -> list[ExtractedEntity]:
    """Extract text + entities for one document. Raises on failure after recording it."""
    set_status(db, document, DocumentStatus.processing, stage="extraction")
    db.commit()

    try:
        extracted = extract_text(absolute_path(document.storage_path), document.mime_type)
        candidates = extract_entities(extracted)
    except Exception as exc:  # noqa: BLE001
        log.exception("Extraction failed for document %s", document.id)
        document.error_message = f"{type(exc).__name__}: {exc}"[:2000]
        record(
            db,
            event_type=events.EXTRACTION_FAILED,
            target_type="document",
            target_id=document.id,
            document_id=document.id,
            payload={"error": document.error_message},
        )
        set_status(db, document, DocumentStatus.failed, stage="extraction")
        db.commit()
        raise

    # Re-extraction replaces prior entities; the audit log keeps the history.
    for old in list(document.entities):
        db.delete(old)
    db.flush()

    document.raw_text = extracted.text
    document.page_count = extracted.page_count
    document.ocr_used = extracted.ocr_used
    document.error_message = None

    entities: list[ExtractedEntity] = []
    for c in candidates:
        entity = ExtractedEntity(
            document_id=document.id,
            entity_type=c.entity_type,
            raw_text=c.raw_text,
            normalized_value=c.normalized_value,
            confidence=c.confidence,
            extractor=c.extractor,
            page=c.page,
            char_start=c.char_start,
            char_end=c.char_end,
        )
        db.add(entity)
        entities.append(entity)
    db.flush()

    for entity in entities:
        record(
            db,
            event_type=events.ENTITY_EXTRACTED,
            target_type="entity",
            target_id=entity.id,
            document_id=document.id,
            payload={
                "entity_type": entity.entity_type,
                "raw_text": entity.raw_text,
                "normalized_value": entity.normalized_value,
                "confidence": entity.confidence,
                "extractor": entity.extractor.value,
                "page": entity.page,
            },
        )
    record(
        db,
        event_type=events.EXTRACTION_COMPLETED,
        target_type="document",
        target_id=document.id,
        document_id=document.id,
        payload={
            "entity_count": len(entities),
            "page_count": extracted.page_count,
            "ocr_used": extracted.ocr_used,
            "entity_types": sorted({e.entity_type for e in entities}),
        },
    )
    set_status(db, document, DocumentStatus.extracted, entity_count=len(entities))
    db.commit()
    return entities
