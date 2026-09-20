from datetime import datetime

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import can_access_document
from app.audit import verify_chain
from app.models import AuditLog, Document, User, UserRole


def query(
    db: Session,
    user: User,
    *,
    document_id: int | None,
    event_type: str | None,
    actor_id: int | None,
    target_type: str | None,
    since: datetime | None,
    until: datetime | None,
    limit: int,
    offset: int,
) -> tuple[list[dict], int]:
    q = select(AuditLog)
    if user.role == UserRole.analyst:
        # Analysts may only query the trail of their own documents (and their own actions).
        if document_id is None:
            q = q.where(AuditLog.actor_id == user.id)
        else:
            doc = db.get(Document, document_id)
            if doc is None or not can_access_document(user, doc.owner_id):
                raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found.")
    if document_id is not None:
        q = q.where(AuditLog.document_id == document_id)
    if event_type:
        q = q.where(AuditLog.event_type == event_type) if "*" not in event_type else q.where(AuditLog.event_type.like(event_type.replace("*", "%")))
    if actor_id is not None:
        q = q.where(AuditLog.actor_id == actor_id)
    if target_type:
        q = q.where(AuditLog.target_type == target_type)
    if since:
        q = q.where(AuditLog.created_at >= since)
    if until:
        q = q.where(AuditLog.created_at <= until)

    total = db.execute(select(func.count()).select_from(q.subquery())).scalar_one()
    rows = db.execute(q.order_by(AuditLog.id.desc()).limit(limit).offset(offset)).scalars().all()
    actor_ids = {r.actor_id for r in rows if r.actor_id}
    names = {u.id: u.full_name for u in db.execute(select(User).where(User.id.in_(actor_ids))).scalars()} if actor_ids else {}
    out = []
    for r in rows:
        d = {c: getattr(r, c) for c in AuditLog.__table__.columns.keys()}
        d["actor_name"] = names.get(r.actor_id) if r.actor_id else "system"
        out.append(d)
    return out, total


def event_types(db: Session) -> list[str]:
    return [t for (t,) in db.execute(select(AuditLog.event_type).distinct().order_by(AuditLog.event_type))]


def verify(db: Session) -> dict:
    ok, bad = verify_chain(db)
    total = db.execute(select(func.count(AuditLog.id))).scalar_one()
    return {"ok": ok, "entries": total, "first_bad_id": bad}
