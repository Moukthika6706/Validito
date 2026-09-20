import logging
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.audit import events, record
from app.explainability import confidence_band, describe_source
from app.models import Document, DocumentStatus, Flag, FlagStatus, ReviewAction, ReviewActionRecord, User, ValidationRun
from app.schemas.validation import ReviewActionIn, ReviewCompleteIn

log = logging.getLogger(__name__)

ACTION_TO_STATUS = {
    ReviewAction.accept: FlagStatus.accepted,
    ReviewAction.reject: FlagStatus.rejected,
    ReviewAction.override: FlagStatus.overridden,
}


def flag_to_detail(flag: Flag) -> dict[str, Any]:
    data = {c: getattr(flag, c) for c in Flag.__table__.columns.keys()}
    data["confidence_band"] = confidence_band(flag.confidence)
    data["source_description"] = describe_source(flag.source.value)
    data["entity"] = flag.entity
    data["review_actions"] = flag.review_actions
    return data


def get_flag_or_404(db: Session, flag_id: int) -> Flag:
    flag = db.execute(
        select(Flag).where(Flag.id == flag_id).options(selectinload(Flag.entity), selectinload(Flag.review_actions).selectinload(ReviewActionRecord.reviewer))
    ).scalar_one_or_none()
    if flag is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Flag not found.")
    return flag


def list_flags(db: Session, document_id: int, *, status_filter: FlagStatus | None = None, run_id: int | None = None) -> list[Flag]:
    q = select(Flag).where(Flag.document_id == document_id).options(
        selectinload(Flag.entity), selectinload(Flag.review_actions).selectinload(ReviewActionRecord.reviewer)
    )
    if status_filter:
        q = q.where(Flag.status == status_filter)
    if run_id:
        q = q.where(Flag.validation_run_id == run_id)
    rows = db.execute(q).scalars().all()
    # Most severe, then least confident (most in need of a human) first.
    return sorted(rows, key=lambda f: (-f.severity.rank, f.confidence, f.id))


def review_queue(db: Session, *, limit: int, offset: int) -> tuple[list[dict[str, Any]], int]:
    base = select(Document).where(Document.status == DocumentStatus.needs_review)
    total = db.execute(select(func.count()).select_from(base.subquery())).scalar_one()
    docs = db.execute(
        base.options(selectinload(Document.owner)).order_by(Document.updated_at.asc()).limit(limit).offset(offset)
    ).scalars().all()
    items = []
    for d in docs:
        open_flags = [f for f in db.execute(select(Flag).where(Flag.document_id == d.id, Flag.status == FlagStatus.open)).scalars()]
        run = db.execute(select(ValidationRun).where(ValidationRun.document_id == d.id).order_by(ValidationRun.id.desc()).limit(1)).scalar_one_or_none()
        items.append({
            "document_id": d.id,
            "original_filename": d.original_filename,
            "owner_id": d.owner_id,
            "owner_name": d.owner.full_name if d.owner else "",
            "rule_pack_key": d.rule_pack_key,
            "status": d.status.value,
            "uploaded_at": d.created_at,
            "waiting_since": d.updated_at,
            "open_flags": len(open_flags),
            "max_severity": max((f.severity for f in open_flags), key=lambda s: s.rank, default=None),
            "min_confidence": min((f.confidence for f in open_flags), default=None),
            "routing_reason": run.routing_reason if run else None,
            "overall_score": run.overall_score if run else None,
        })
    return items, total


def act_on_flag(db: Session, flag: Flag, reviewer: User, data: ReviewActionIn) -> Flag:
    if flag.status not in (FlagStatus.open, FlagStatus.accepted, FlagStatus.rejected, FlagStatus.overridden):
        raise HTTPException(status.HTTP_409_CONFLICT, f"Flag is '{flag.status.value}' and can no longer be reviewed.")
    if data.action == ReviewAction.override and data.override_value is None:
        raise HTTPException(422, "An override must include 'override_value'.")

    action = ReviewActionRecord(
        flag_id=flag.id, reviewer_id=reviewer.id, action=data.action, comment=data.comment, override_value=data.override_value
    )
    db.add(action)
    previous = flag.status
    flag.status = ACTION_TO_STATUS[data.action]
    db.flush()
    record(
        db, event_type=events.REVIEW_ACTION, target_type="flag", target_id=flag.id, document_id=flag.document_id, actor_id=reviewer.id,
        payload={"action": data.action.value, "comment": data.comment, "override_value": data.override_value,
                 "rule_id": flag.rule_id, "from_status": previous.value, "to_status": flag.status.value,
                 "flag_confidence": flag.confidence, "flag_severity": flag.severity.value, "review_action_id": action.id},
    )
    db.commit()
    db.refresh(flag)
    return flag


def complete_review(db: Session, document: Document, reviewer: User, data: ReviewCompleteIn) -> Document:
    if document.status not in (DocumentStatus.needs_review, DocumentStatus.auto_approved, DocumentStatus.reviewed):
        raise HTTPException(status.HTTP_409_CONFLICT, f"Document is '{document.status.value}'; only decided documents can be reviewed.")
    open_flags = db.execute(select(Flag).where(Flag.document_id == document.id, Flag.status == FlagStatus.open)).scalars().all()
    if open_flags:
        if data.resolve_remaining is None:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"{len(open_flags)} flag(s) are still open. Resolve them or pass resolve_remaining.",
            )
        for flag in open_flags:
            act_on_flag(db, flag, reviewer, ReviewActionIn(action=data.resolve_remaining, comment=data.comment or "Resolved on review completion", override_value=None))

    previous = document.status
    document.status = DocumentStatus.reviewed
    document.review_outcome = data.outcome
    record(
        db, event_type=events.DOCUMENT_STATUS_CHANGED, target_type="document", target_id=document.id, document_id=document.id, actor_id=reviewer.id,
        payload={"from": previous.value, "to": DocumentStatus.reviewed.value, "outcome": data.outcome, "comment": data.comment, "reason": "review_completed"},
    )
    db.commit()
    return document
