"""Feedback loop: reviewer decisions re-calibrate rule confidence.

A rejected flag is a false positive for its rule; an accepted or overridden flag is a true
positive. Per-rule precision (Laplace-smoothed) scales the base confidence of future flags,
so rules reviewers keep rejecting drift into the 'ambiguous -> human review' band instead of
blocking auto-approval, and rules reviewers keep confirming get stronger.
"""

from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Flag, ReviewAction, ReviewActionRecord

MIN_SAMPLES = 3  # below this, feedback is too thin to move confidence


@dataclass(frozen=True)
class RuleStats:
    rule_id: str
    accepted: int
    rejected: int

    @property
    def samples(self) -> int:
        return self.accepted + self.rejected

    @property
    def precision(self) -> float:
        return (self.accepted + 1) / (self.samples + 2)  # Laplace smoothing

    @property
    def multiplier(self) -> float:
        if self.samples < MIN_SAMPLES:
            return 1.0
        # precision 0.5 -> x1.0, 0.9 -> x1.4 (capped by clamping to 1.0 later), 0.1 -> x0.6
        return 0.5 + self.precision


def rule_stats(db: Session) -> dict[str, RuleStats]:
    rows = db.execute(
        select(
            Flag.rule_id,
            func.sum(func.iif(ReviewActionRecord.action == ReviewAction.reject.value, 1, 0)) if db.bind.dialect.name == "sqlite"
            else func.sum(func.if_(ReviewActionRecord.action == ReviewAction.reject.value, 1, 0)),
            func.count(ReviewActionRecord.id),
        )
        .join(ReviewActionRecord, ReviewActionRecord.flag_id == Flag.id)
        .group_by(Flag.rule_id)
    ).all()
    out = {}
    for rule_id, rejected, total in rows:
        rejected = int(rejected or 0)
        out[rule_id] = RuleStats(rule_id=rule_id, accepted=int(total) - rejected, rejected=rejected)
    return out


def calibrate(confidence: float, stats: RuleStats | None) -> tuple[float, dict]:
    """Returns (adjusted_confidence, calibration_evidence)."""
    if stats is None or stats.samples < MIN_SAMPLES:
        return confidence, {"applied": False, "samples": stats.samples if stats else 0}
    adjusted = round(min(1.0, confidence * stats.multiplier), 4)
    return adjusted, {
        "applied": True,
        "samples": stats.samples,
        "accepted": stats.accepted,
        "rejected": stats.rejected,
        "precision": round(stats.precision, 3),
        "multiplier": round(stats.multiplier, 3),
        "base_confidence": confidence,
    }
