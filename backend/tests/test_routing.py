import pytest

from app.models.enums import RoutingDecision
from app.rules.context import Finding
from app.rules.schema import RoutingPolicy
from app.validation.routing import compute_score, decide


def f(rule_id="r", severity="warning", confidence=0.9):
    return Finding(rule_id=rule_id, check="c", severity=severity, confidence=confidence, title="t", explanation="e")


@pytest.fixture
def policy():
    return RoutingPolicy()


def test_clean_document_auto_approves(policy):
    r = decide([], policy)
    assert r.decision == RoutingDecision.auto_approved
    assert r.score == 1.0


def test_blocking_severity_forces_review(policy):
    r = decide([f(severity="critical", confidence=0.99)], policy)
    assert r.decision == RoutingDecision.needs_review
    assert r.blocking == ["r"]
    assert "blocking severity" in r.reason


def test_ambiguous_warning_forces_review(policy):
    r = decide([f(severity="warning", confidence=0.6)], policy)
    assert r.decision == RoutingDecision.needs_review
    assert r.ambiguous == ["r"]
    assert "confidence threshold" in r.reason


def test_confident_warning_auto_approves(policy):
    r = decide([f(severity="warning", confidence=0.9)], policy)
    assert r.decision == RoutingDecision.auto_approved
    assert r.score == pytest.approx(1 - 0.1 * 0.9)


def test_low_confidence_info_does_not_block(policy):
    r = decide([f(severity="info", confidence=0.3)], policy)
    assert r.decision == RoutingDecision.auto_approved


def test_many_confident_warnings_drop_score_below_floor(policy):
    findings = [f(rule_id=f"r{i}", severity="warning", confidence=0.95) for i in range(4)]
    r = decide(findings, policy)
    assert compute_score(findings, policy) < policy.min_auto_approve_score
    assert r.decision == RoutingDecision.needs_review
    assert "auto-approval floor" in r.reason


def test_policy_is_tunable():
    strict = RoutingPolicy(block_severities=["warning", "error", "critical"])
    assert decide([f(severity="warning", confidence=0.99)], strict).decision == RoutingDecision.needs_review
