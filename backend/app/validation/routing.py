"""Confidence-based routing: a pure function of the findings and the pack's policy.

Decision logic (in order):
1. Any finding at a blocking severity (error/critical by default) -> needs_review.
   A confident error is a real defect a human must act on; an unconfident one is ambiguous.
2. Any non-info finding whose confidence is below `auto_approve_confidence` -> needs_review.
   These are the "we are not sure" cases the product exists to route rather than decide.
3. Otherwise compute a score = 1 - sum(severity_weight * confidence); if it falls below
   `min_auto_approve_score` -> needs_review (many confident warnings add up).
4. Else auto_approved.
"""

from dataclasses import dataclass, field

from app.models.enums import RoutingDecision, Severity
from app.rules.context import Finding
from app.rules.schema import RoutingPolicy


@dataclass
class RoutingResult:
    decision: RoutingDecision
    reason: str
    score: float
    blocking: list[str] = field(default_factory=list)  # rule ids
    ambiguous: list[str] = field(default_factory=list)


def compute_score(findings: list[Finding], policy: RoutingPolicy) -> float:
    penalty = sum(policy.severity_weights.get(Severity(f.severity), 0.1) * f.confidence for f in findings)
    return round(max(0.0, 1.0 - penalty), 4)


def decide(findings: list[Finding], policy: RoutingPolicy) -> RoutingResult:
    score = compute_score(findings, policy)
    block = {s.value for s in policy.block_severities}
    blocking = [f.rule_id for f in findings if f.severity in block]
    ambiguous = [
        f.rule_id for f in findings
        if f.severity != Severity.info.value and f.confidence < policy.auto_approve_confidence
    ]

    if blocking:
        n = len(blocking)
        return RoutingResult(
            RoutingDecision.needs_review,
            f"{n} finding{'s' if n > 1 else ''} at blocking severity ({', '.join(sorted(block))}) require human sign-off.",
            score, blocking, ambiguous,
        )
    if ambiguous:
        n = len(ambiguous)
        return RoutingResult(
            RoutingDecision.needs_review,
            f"{n} finding{'s' if n > 1 else ''} below the {policy.auto_approve_confidence:.0%} confidence threshold; routed to a reviewer rather than auto-decided.",
            score, blocking, ambiguous,
        )
    if score < policy.min_auto_approve_score:
        return RoutingResult(
            RoutingDecision.needs_review,
            f"Overall score {score:.2f} is below the {policy.min_auto_approve_score:.2f} auto-approval floor (several confident warnings).",
            score, blocking, ambiguous,
        )
    if findings:
        return RoutingResult(
            RoutingDecision.auto_approved,
            f"Only high-confidence minor findings ({len(findings)}); overall score {score:.2f} clears the auto-approval floor.",
            score,
        )
    return RoutingResult(RoutingDecision.auto_approved, "All rule checks passed and no anomalies were detected.", score)
