"""End-to-end: text -> entities -> rules + ML -> flags -> routing, against the in-memory DB."""

import pytest

from app.audit import verify_chain
from app.core.security import hash_password
from app.extraction.ner import extract_entities
from app.extraction.text import ExtractedText, PageText
from app.models import Document, DocumentStatus, DocumentType, ExtractedEntity, Flag, FlagStatus, ReviewAction, ReviewActionRecord, RoutingDecision, User
from app.validation import run_validation
from tests.conftest import ISDA_SAMPLE_TEXT, LMA_SAMPLE_TEXT

FAULTY_ISDA_TEXT = """
Trade Date: 15 March 2026
Effective Date: 17 March 2026
Termination Date: 17 March 2025
Notional Amount: USD 5,000,000,000
Party A: Barclays Bank PLC
Party B: Northwind Industries Ltd
Fixed Rate: 18.5% per annum
Floating Rate Option: 3-month LIBOR plus 45 bps
Payment Frequency: Quarterly
Settlement: To be agreed
Documentation: ISDA 2002 Master Agreement
"""


@pytest.fixture
def user(db):
    u = User(email="u@example.com", password_hash=hash_password("password123"), full_name="U")
    db.add(u)
    db.commit()
    return u


def make_document(db, user, text, *, rule_pack_key=None, ocr=False, related=None) -> Document:
    doc = Document(
        owner_id=user.id, original_filename="x.pdf", storage_path="x", mime_type="application/pdf", size_bytes=1,
        sha256="0" * 64, doc_type=DocumentType.term_sheet, rule_pack_key=rule_pack_key, status=DocumentStatus.extracted,
        raw_text=text, page_count=1, ocr_used=ocr, related_document_id=related.id if related else None,
    )
    db.add(doc)
    db.flush()
    extracted = ExtractedText(pages=[PageText(number=1, text=text, ocr=ocr, ocr_confidence=0.7 if ocr else None)])
    for c in extract_entities(extracted, use_ner=False):
        db.add(ExtractedEntity(document_id=doc.id, entity_type=c.entity_type, raw_text=c.raw_text, normalized_value=c.normalized_value,
                               confidence=c.confidence, extractor=c.extractor, page=c.page, char_start=c.char_start, char_end=c.char_end))
    db.commit()
    db.refresh(doc)
    return doc


def test_clean_isda_auto_approves(db, user):
    doc = make_document(db, user, ISDA_SAMPLE_TEXT, rule_pack_key="isda")
    outcome = run_validation(db, doc)
    assert outcome.decision == RoutingDecision.auto_approved
    assert doc.status == DocumentStatus.auto_approved
    assert [f.rule_id for f in outcome.flags] == []
    assert outcome.run.overall_score == 1.0
    assert verify_chain(db) == (True, None)


def test_faulty_isda_routes_to_review_with_explainable_flags(db, user):
    doc = make_document(db, user, FAULTY_ISDA_TEXT, rule_pack_key="isda")
    outcome = run_validation(db, doc)

    assert outcome.decision == RoutingDecision.needs_review
    assert doc.status == DocumentStatus.needs_review
    ids = {f.rule_id for f in outcome.flags}
    assert {
        "isda.governing_law.present", "isda.dates.effective_before_maturity", "isda.notional.range",
        "isda.fixed_rate.range", "isda.benchmark.discontinued", "isda.settlement.format",
    } <= ids

    for flag in outcome.flags:
        # Explainability contract: every flag says what fired, why, and how sure we are.
        assert flag.rule_id and flag.explanation and 0 <= flag.confidence <= 1
        assert flag.rule_snapshot["pack"] == "isda"
        assert "check" in flag.evidence
        assert "calibration" in flag.evidence

    law = next(f for f in outcome.flags if f.rule_id == "isda.governing_law.present")
    assert law.severity.value == "critical"
    assert law.entity_id is None
    libor = next(f for f in outcome.flags if f.rule_id == "isda.benchmark.discontinued")
    assert libor.entity_id is not None
    assert libor.evidence["entity"]["raw_text"] == "3-month LIBOR plus 45 bps"
    assert "LIBOR" in libor.explanation
    assert "critical" in outcome.summary


def test_ml_anomaly_flag_is_explained(db, user):
    doc = make_document(db, user, FAULTY_ISDA_TEXT, rule_pack_key="isda")
    outcome = run_validation(db, doc)
    ml = next((f for f in outcome.flags if f.rule_id == "ml.anomaly"), None)
    assert ml is not None, "expected the anomaly detector to fire on a 5bn / 18.5% swap"
    assert ml.source.value == "ml"
    assert ml.evidence["model"] == "IsolationForest"
    assert ml.evidence["contributions"], "ML flag must name the deviating features"
    assert "typical" in ml.explanation


def test_pack_is_auto_detected_from_content(db, user):
    doc = make_document(db, user, LMA_SAMPLE_TEXT)
    outcome = run_validation(db, doc)
    assert doc.rule_pack_key == "lma"
    assert outcome.decision == RoutingDecision.auto_approved, [f.title for f in outcome.flags]


def test_cross_document_mismatch_is_flagged(db, user):
    confirmation = make_document(db, user, ISDA_SAMPLE_TEXT.replace("USD 50,000,000", "USD 55,000,000"), rule_pack_key="isda")
    term_sheet = make_document(db, user, ISDA_SAMPLE_TEXT, rule_pack_key="isda", related=confirmation)
    outcome = run_validation(db, term_sheet)
    x = next(f for f in outcome.flags if f.rule_id == "isda.xdoc.notional")
    assert x.source.value == "cross_doc"
    assert x.evidence["related_document_id"] == confirmation.id
    assert outcome.decision == RoutingDecision.needs_review


def test_revalidation_supersedes_old_flags(db, user):
    doc = make_document(db, user, FAULTY_ISDA_TEXT, rule_pack_key="isda")
    first = run_validation(db, doc)
    second = run_validation(db, doc)
    db.refresh(doc)
    open_flags = [f for f in doc.flags if f.status == FlagStatus.open]
    assert {f.validation_run_id for f in open_flags} == {second.run.id}
    old = [f for f in doc.flags if f.validation_run_id == first.run.id]
    assert old and all(f.status == FlagStatus.superseded and f.evidence["superseded_by_run"] == second.run.id for f in old)


def test_reviewer_feedback_recalibrates_confidence(db, user):
    doc = make_document(db, user, FAULTY_ISDA_TEXT, rule_pack_key="isda")
    first = run_validation(db, doc)
    target = next(f for f in first.flags if f.rule_id == "isda.notional.range")
    base = target.confidence
    # Reviewers reject this rule's flags three times -> precision drops -> confidence drops.
    for _ in range(3):
        db.add(ReviewActionRecord(flag_id=target.id, reviewer_id=user.id, action=ReviewAction.reject, comment="fine"))
    db.commit()
    second = run_validation(db, doc)
    again = next(f for f in second.flags if f.rule_id == "isda.notional.range")
    assert again.confidence < base
    assert again.evidence["calibration"]["applied"] is True
    assert again.evidence["calibration"]["rejected"] == 3
