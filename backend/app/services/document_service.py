import logging

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.api.deps import can_access_document
from app.audit import events, record
from app.core.config import get_settings
from app.ingestion import UploadValidationError, store_upload, validate_upload
from app.models import Document, DocumentStatus, DocumentType, Flag, FlagStatus, User, UserRole, ValidationRun

log = logging.getLogger(__name__)

REPROCESSABLE = {
    DocumentStatus.queued, DocumentStatus.extracted,
    DocumentStatus.auto_approved, DocumentStatus.needs_review, DocumentStatus.reviewed,
    DocumentStatus.failed,
}


def create_document(
    db: Session,
    *,
    owner: User,
    filename: str,
    content: bytes,
    doc_type: DocumentType,
    rule_pack_key: str | None,
    related_document_id: int | None = None,
) -> Document:
    try:
        info = validate_upload(filename, content, max_bytes=get_settings().max_upload_bytes)
    except UploadValidationError as exc:
        raise HTTPException(422, str(exc))

    if related_document_id is not None:
        related = get_document_or_404(db, related_document_id, owner)
        related_document_id = related.id

    rel_path, digest = store_upload(owner.id, info.extension, content)
    document = Document(
        owner_id=owner.id,
        original_filename=info.filename,
        storage_path=rel_path,
        mime_type=info.mime_type,
        size_bytes=info.size_bytes,
        sha256=digest,
        doc_type=doc_type,
        rule_pack_key=rule_pack_key,
        related_document_id=related_document_id,
        status=DocumentStatus.queued,
    )
    db.add(document)
    db.flush()
    record(
        db,
        event_type=events.DOCUMENT_UPLOADED,
        target_type="document",
        target_id=document.id,
        document_id=document.id,
        actor_id=owner.id,
        payload={
            "filename": info.filename, "mime_type": info.mime_type, "size_bytes": info.size_bytes,
            "sha256": digest, "doc_type": doc_type.value, "rule_pack_key": rule_pack_key,
        },
    )
    db.commit()
    _dispatch(document.id)
    return document


def _dispatch(document_id: int) -> None:
    from app.workers.tasks import enqueue_processing

    try:
        enqueue_processing(document_id)
    except Exception:  # noqa: BLE001 -- broker down: the upload is saved; user can retry
        log.exception("Failed to enqueue processing for document %s", document_id)


def reprocess_document(db: Session, document: Document, actor: User) -> Document:
    if document.status not in REPROCESSABLE:
        raise HTTPException(status.HTTP_409_CONFLICT, f"Document is currently '{document.status.value}'.")
    record(
        db, event_type=events.DOCUMENT_STATUS_CHANGED, target_type="document", target_id=document.id,
        document_id=document.id, actor_id=actor.id,
        payload={"from": document.status.value, "to": DocumentStatus.queued.value, "reason": "reprocess", "previous_failed_stage": document.failed_stage},
    )
    document.status = DocumentStatus.queued
    document.error_message = None
    document.failed_stage = None
    document.attempts = 0
    db.commit()
    _dispatch(document.id)
    return document


def create_documents_bulk(
    db: Session, *, owner: User, files: list[tuple[str, bytes]], doc_type: DocumentType, rule_pack_key: str | None
) -> list[dict]:
    """Each file is validated, stored and queued independently; one bad file never rejects the batch."""
    results: list[dict] = []
    for filename, content in files:
        try:
            doc = create_document(db, owner=owner, filename=filename, content=content, doc_type=doc_type, rule_pack_key=rule_pack_key)
            results.append({"filename": filename, "accepted": True, "document_id": doc.id, "status": doc.status.value, "reason": None})
        except HTTPException as exc:
            db.rollback()
            results.append({"filename": filename, "accepted": False, "document_id": None, "status": None, "reason": str(exc.detail)})
    accepted = [r for r in results if r["accepted"]]
    record(
        db, event_type=events.DOCUMENT_BULK_UPLOADED, target_type="user", target_id=owner.id, actor_id=owner.id,
        payload={"accepted": len(accepted), "rejected": len(results) - len(accepted), "document_ids": [r["document_id"] for r in accepted],
                 "rejected_files": [{"filename": r["filename"], "reason": r["reason"]} for r in results if not r["accepted"]]},
    )
    db.commit()
    return results


def status_snapshot(db: Session, user: User, ids: list[int]) -> list[dict]:
    """Lightweight, poll-friendly status for a set of documents (no entity / flag joins)."""
    if not ids:
        return []
    q = select(Document).where(Document.id.in_(ids[:200]))
    if user.role == UserRole.analyst:
        q = q.where(Document.owner_id == user.id)
    docs = {d.id: d for d in db.execute(q).scalars()}
    runs = {}
    if docs:
        for run in db.execute(select(ValidationRun).where(ValidationRun.document_id.in_(list(docs))).order_by(ValidationRun.id)).scalars():
            runs[run.document_id] = run
    out = []
    for doc_id in ids:
        d = docs.get(doc_id)
        if d is None:
            continue  # unknown or not visible: silently omitted, same as a 404 elsewhere
        run = runs.get(d.id)
        out.append({
            "id": d.id, "status": d.status, "terminal": d.status.is_terminal, "failed_stage": d.failed_stage,
            "error_message": d.error_message if d.status == DocumentStatus.failed else None, "attempts": d.attempts,
            "routing_decision": run.routing_decision.value if run and run.routing_decision else None,
            "review_outcome": d.review_outcome, "updated_at": d.updated_at,
        })
    return out


def get_document_or_404(db: Session, document_id: int, user: User) -> Document:
    document = db.get(Document, document_id)
    if document is None or not can_access_document(user, document.owner_id):
        # 404 for both so analysts cannot enumerate other users' document ids.
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found.")
    return document


def list_documents(
    db: Session, user: User, *, status_filter: DocumentStatus | None, limit: int, offset: int
) -> tuple[list[Document], int]:
    q = select(Document)
    if user.role == UserRole.analyst:
        q = q.where(Document.owner_id == user.id)
    if status_filter:
        q = q.where(Document.status == status_filter)
    total = db.execute(select(func.count()).select_from(q.subquery())).scalar_one()
    rows = db.execute(q.order_by(Document.created_at.desc()).limit(limit).offset(offset)).scalars().all()
    return list(rows), total


def link_documents(db: Session, document: Document, related_id: int | None, user: User) -> Document:
    if related_id is not None:
        if related_id == document.id:
            raise HTTPException(422, "A document cannot be linked to itself.")
        related = get_document_or_404(db, related_id, user)
        related_id = related.id
    record(
        db, event_type=events.DOCUMENT_LINKED, target_type="document", target_id=document.id,
        document_id=document.id, actor_id=user.id,
        payload={"from": document.related_document_id, "to": related_id},
    )
    document.related_document_id = related_id
    db.commit()
    return document


def document_detail(db: Session, document: Document) -> dict:
    db.refresh(document, attribute_names=["entities"])
    latest_run = db.execute(
        select(ValidationRun).where(ValidationRun.document_id == document.id).order_by(ValidationRun.id.desc()).limit(1)
    ).scalar_one_or_none()
    open_flags = db.execute(
        select(func.count(Flag.id)).where(Flag.document_id == document.id, Flag.status == FlagStatus.open)
    ).scalar_one()
    return {
        **{c: getattr(document, c) for c in Document.__table__.columns.keys()},
        "entities": sorted(document.entities, key=lambda e: (e.entity_type, -e.confidence)),
        "claimed_by_name": document.claimed_by_name,
        "claim_expires_at": document.claim_expires_at,
        "open_flag_count": open_flags,
        "latest_run_id": latest_run.id if latest_run else None,
        "routing_decision": latest_run.routing_decision.value if latest_run and latest_run.routing_decision else None,
    }
