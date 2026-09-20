"""Append-only, hash-chained audit logger.

Every row's `hash` = sha256(prev_hash | event_type | target_type | target_id | actor_id |
document_id | canonical(payload) | created_at). Because each hash covers the previous one,
editing or deleting any row invalidates every row after it.
"""

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.audit import AuditLog
from app.models.base import utcnow

GENESIS_HASH = "0" * 64


def _canonical(payload: dict[str, Any] | None) -> str:
    return json.dumps(payload or {}, sort_keys=True, separators=(",", ":"), default=str)


def _canonical_ts(value: datetime) -> str:
    """Timestamp as stored: UTC, naive, whole seconds. MySQL DATETIME drops fractional
    seconds and SQLite drops tzinfo, so the hash must not depend on either."""
    if value.tzinfo is not None:
        value = value.astimezone(timezone.utc).replace(tzinfo=None)
    return value.replace(microsecond=0).isoformat()


def compute_hash(
    *,
    prev_hash: str | None,
    event_type: str,
    target_type: str,
    target_id: int | None,
    actor_id: int | None,
    document_id: int | None,
    payload: dict[str, Any] | None,
    created_at: datetime,
) -> str:
    material = "|".join(
        [
            prev_hash or GENESIS_HASH,
            event_type,
            target_type,
            str(target_id),
            str(actor_id),
            str(document_id),
            _canonical(payload),
            _canonical_ts(created_at),
        ]
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _last_hash(db: Session) -> str | None:
    row = db.execute(
        select(AuditLog.hash).order_by(AuditLog.id.desc()).limit(1)
    ).scalar_one_or_none()
    return row


def record(
    db: Session,
    *,
    event_type: str,
    target_type: str,
    target_id: int | None = None,
    payload: dict[str, Any] | None = None,
    actor_id: int | None = None,
    document_id: int | None = None,
) -> AuditLog:
    """Append one audit event. The caller owns the transaction (flush only)."""
    created_at = utcnow()
    prev_hash = _last_hash(db)
    entry = AuditLog(
        document_id=document_id,
        actor_id=actor_id,
        event_type=event_type,
        target_type=target_type,
        target_id=target_id,
        payload=payload,
        prev_hash=prev_hash,
        created_at=created_at,
        hash=compute_hash(
            prev_hash=prev_hash,
            event_type=event_type,
            target_type=target_type,
            target_id=target_id,
            actor_id=actor_id,
            document_id=document_id,
            payload=payload,
            created_at=created_at,
        ),
    )
    db.add(entry)
    db.flush()
    return entry


def verify_chain(db: Session) -> tuple[bool, int | None]:
    """Recompute every hash in order. Returns (ok, first_bad_id)."""
    prev: str | None = None
    for row in db.execute(select(AuditLog).order_by(AuditLog.id)).scalars():
        expected = compute_hash(
            prev_hash=prev,
            event_type=row.event_type,
            target_type=row.target_type,
            target_id=row.target_id,
            actor_id=row.actor_id,
            document_id=row.document_id,
            payload=row.payload,
            created_at=row.created_at,
        )
        if row.prev_hash != prev or row.hash != expected:
            return False, row.id
        prev = row.hash
    return True, None
