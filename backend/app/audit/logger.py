"""Append-only, hash-chained audit logger.

Every row's `hash` = sha256(prev_hash | event_type | target_type | target_id | actor_id |
document_id | canonical(payload) | created_at). Because each hash covers the previous one,
editing or deleting any row invalidates every row after it.

Concurrency: the previous hash is read from a single `audit_chain_head` row that is locked
for update for the remainder of the caller's transaction. Two processes recording at the
same time therefore queue behind each other instead of both chaining onto the same
predecessor (which would make an honest log look tampered with to `verify_chain`).
"""

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.audit import AuditChainHead, AuditLog
from app.models.base import utcnow

GENESIS_HASH = "0" * 64
HEAD_ID = 1


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


def _locked_head(db: Session) -> AuditChainHead:
    """Return the chain-head row, locked until the caller's transaction ends.

    On databases without row locks (SQLite) the write lock on the file plays the same role.
    The head is created lazily on first use; a concurrent first-time creation loses the
    primary-key race and simply re-reads.
    """
    head = db.execute(select(AuditChainHead).where(AuditChainHead.id == HEAD_ID).with_for_update()).scalar_one_or_none()
    if head is not None:
        return head
    # Bootstrap: derive the head from whatever is already in the log (pre-head installs).
    last = db.execute(select(AuditLog).order_by(AuditLog.id.desc()).limit(1)).scalar_one_or_none()
    head = AuditChainHead(id=HEAD_ID, last_hash=last.hash if last else None, last_entry_id=last.id if last else None)
    try:
        with db.begin_nested():
            db.add(head)
            db.flush()
    except IntegrityError:
        pass  # someone else created it between our select and insert
    return db.execute(select(AuditChainHead).where(AuditChainHead.id == HEAD_ID).with_for_update()).scalar_one()


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
    """Append one audit event. The caller owns the transaction (flush only).

    The chain-head lock taken here is held until the caller commits or rolls back, so keep
    the remaining work in that transaction short.
    """
    head = _locked_head(db)
    created_at = utcnow()
    prev_hash = head.last_hash
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
    head.last_hash = entry.hash
    head.last_entry_id = entry.id
    db.flush()
    return entry


def verify_chain(db: Session) -> tuple[bool, int | None]:
    """Recompute every hash in order and check the head points at the final row.
    Returns (ok, first_bad_id); a stale head is reported against the last row."""
    prev: str | None = None
    last: AuditLog | None = None
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
        last = row
    head = db.get(AuditChainHead, HEAD_ID)
    if head is not None and last is not None and head.last_hash != last.hash:
        return False, last.id
    return True, None
