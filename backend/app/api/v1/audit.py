from datetime import datetime

from fastapi import APIRouter, Query
from sqlalchemy.orm import Session

from app.api.deps import DB, AdminOnly, CurrentUser
from app.models import User
from app.schemas.audit import AuditEventOut, ChainVerification
from app.schemas.common import Page
from app.services import audit_service

router = APIRouter(prefix="/audit", tags=["audit"])


@router.get("", response_model=Page[AuditEventOut], summary="Query the immutable audit trail")
def query(
    document_id: int | None = None,
    event_type: str | None = Query(None, description="Exact type, or a glob like 'review.*'"),
    actor_id: int | None = None,
    target_type: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    user: User = CurrentUser,
    db: Session = DB,
):
    items, total = audit_service.query(
        db, user, document_id=document_id, event_type=event_type, actor_id=actor_id, target_type=target_type,
        since=since, until=until, limit=limit, offset=offset,
    )
    return Page(items=items, total=total, limit=limit, offset=offset)


@router.get("/documents/{document_id}", response_model=Page[AuditEventOut], summary="Every decision recorded on one document")
def for_document(document_id: int, limit: int = Query(200, ge=1, le=1000), offset: int = Query(0, ge=0), user: User = CurrentUser, db: Session = DB):
    items, total = audit_service.query(
        db, user, document_id=document_id, event_type=None, actor_id=None, target_type=None, since=None, until=None, limit=limit, offset=offset,
    )
    return Page(items=items, total=total, limit=limit, offset=offset)


@router.get("/event-types", response_model=list[str])
def event_types(user: User = CurrentUser, db: Session = DB):
    return audit_service.event_types(db)


@router.get("/verify", response_model=ChainVerification, summary="Recompute the hash chain to prove the log is untampered")
def verify(user: User = AdminOnly, db: Session = DB):
    return audit_service.verify(db)
