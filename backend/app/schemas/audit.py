from datetime import datetime
from typing import Any

from pydantic import BaseModel

from app.schemas.common import ORMModel


class AuditEventOut(ORMModel):
    id: int
    document_id: int | None
    actor_id: int | None
    actor_name: str | None = None
    event_type: str
    target_type: str
    target_id: int | None
    payload: dict[str, Any] | None
    created_at: datetime
    prev_hash: str | None
    hash: str


class ChainVerification(BaseModel):
    ok: bool
    entries: int
    first_bad_id: int | None
