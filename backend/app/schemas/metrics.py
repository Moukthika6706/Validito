from pydantic import BaseModel


class RuleHitCount(BaseModel):
    rule_id: str
    title: str
    count: int
    accepted: int = 0
    rejected: int = 0


class DailyCount(BaseModel):
    day: str
    uploaded: int
    auto_approved: int
    needs_review: int


class MetricsSummary(BaseModel):
    documents_total: int
    by_status: dict[str, int]
    decided_total: int
    auto_approved_total: int
    needs_review_total: int
    auto_approved_pct: float
    manual_review_reduction_pct: float
    avg_processing_seconds: float | None
    avg_flags_per_document: float
    flags_by_severity: dict[str, int]
    flags_by_source: dict[str, int]
    top_rules: list[RuleHitCount]
    review_actions: dict[str, int]
    reviewer_agreement_pct: float | None
    daily: list[DailyCount]
    decided_this_week: int = 0
    flagged_this_week: int = 0
    notional_validated: dict[str, float] = {}
    active_rule_packs: int = 0
