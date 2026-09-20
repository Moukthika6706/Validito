from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.models.enums import FlagSource, FlagStatus, ReviewAction, RoutingDecision, RunStatus, Severity
from app.schemas.auth import UserOut
from app.schemas.common import ORMModel
from app.schemas.document import EntityOut


class ReviewActionOut(ORMModel):
    id: int
    flag_id: int
    reviewer_id: int
    reviewer: UserOut | None = None
    action: ReviewAction
    comment: str | None
    override_value: dict[str, Any] | None
    created_at: datetime


class FlagOut(ORMModel):
    id: int
    validation_run_id: int
    document_id: int
    entity_id: int | None
    source: FlagSource
    rule_id: str
    severity: Severity
    confidence: float
    confidence_band: str = "high"
    title: str
    explanation: str
    status: FlagStatus
    created_at: datetime


class FlagDetail(FlagOut):
    """Everything a reviewer needs to judge the flag without consulting code."""

    rule_snapshot: dict[str, Any] | None
    evidence: dict[str, Any] | None
    entity: EntityOut | None = None
    source_description: str = ""
    review_actions: list[ReviewActionOut] = []


class ValidationRunOut(ORMModel):
    id: int
    document_id: int
    rule_pack_id: int | None
    rule_pack_key: str | None = None
    ml_model_version: str | None
    status: RunStatus
    overall_score: float | None
    routing_decision: RoutingDecision | None
    routing_reason: str | None
    started_at: datetime
    completed_at: datetime | None


class ValidationRunDetail(ValidationRunOut):
    flags: list[FlagDetail] = []
    summary: str = ""


class ReviewActionIn(BaseModel):
    action: ReviewAction
    comment: str | None = Field(default=None, max_length=4000)
    override_value: dict[str, Any] | None = Field(
        default=None, description="For 'override': the corrected value the reviewer asserts (free-form JSON)."
    )


class ReviewCompleteIn(BaseModel):
    outcome: str = Field(pattern=r"^(approved|rejected)$")
    comment: str | None = Field(default=None, max_length=4000)
    resolve_remaining: ReviewAction | None = Field(
        default=None, description="Apply this action to any still-open flags instead of failing with 409."
    )


class ReviewQueueItem(ORMModel):
    document_id: int
    original_filename: str
    owner_id: int
    owner_name: str
    rule_pack_key: str | None
    status: str
    uploaded_at: datetime
    waiting_since: datetime
    open_flags: int
    max_severity: Severity | None
    min_confidence: float | None
    routing_reason: str | None
    overall_score: float | None
