from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.models.enums import Severity
from app.rules.schema import RulePackConfig
from app.schemas.common import ORMModel


class RulePackSummary(ORMModel):
    id: int
    key: str
    name: str
    version: str
    description: str | None
    is_active: bool
    created_by: int | None
    created_at: datetime
    rule_count: int = 0
    cross_document_rule_count: int = 0


class RulePackOut(RulePackSummary):
    config: RulePackConfig


class RulePackCreate(BaseModel):
    config: RulePackConfig


class RuleUpdate(BaseModel):
    """Partial edit of one rule. Produces a new pack version so history is preserved."""

    enabled: bool | None = None
    severity: Severity | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)
    title: str | None = None
    explanation: str | None = None
    params: dict[str, Any] | None = None


class CheckTypeOut(BaseModel):
    name: str
    description: str
