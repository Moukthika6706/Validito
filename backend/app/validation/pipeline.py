"""Validation stage orchestrator: rules + ML + cross-document -> flags -> routing.

Everything persisted here is explainable by construction: each Flag carries the rule (or
model) that raised it, a frozen snapshot of that rule, the evidence values, and a confidence
that reflects both the rule's certainty and the extraction quality.
"""

import logging
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit import events, record
from app.explainability import summarize_flags
from app.extraction.pipeline import set_status
from app.ml import MODEL_VERSION, get_model
from app.ml.feedback import calibrate, rule_stats
from app.models import Document, DocumentStatus, Flag, FlagSource, FlagStatus, RoutingDecision, RunStatus, Severity, ValidationRun
from app.models.base import utcnow
from app.rules import DocumentView, EntityView, Finding, RuleContext, RulePackConfig, active_pack, detect_pack_key, evaluate, rule_snapshot
from app.validation.routing import decide

log = logging.getLogger(__name__)

ML_RULE_ID = "ml.anomaly"


@dataclass
class ValidationOutcome:
    run: ValidationRun
    flags: list[Flag]
    decision: RoutingDecision
    reason: str
    score: float
    summary: str


def to_view(document: Document) -> DocumentView:
    return DocumentView(
        id=document.id,
        doc_type=document.doc_type.value,
        ocr_used=document.ocr_used,
        page_count=document.page_count,
        raw_text=document.raw_text or "",
        entities=[
            EntityView(
                id=e.id, entity_type=e.entity_type, raw_text=e.raw_text,
                normalized_value=e.normalized_value, confidence=e.confidence, page=e.page,
            )
            for e in document.entities
        ],
    )


def resolve_pack(db: Session, document: Document) -> tuple[RulePackConfig, int | None]:
    key = document.rule_pack_key
    if not key:
        key = detect_pack_key(db, document.raw_text or "", [e.raw_text for e in document.entities])
        document.rule_pack_key = key
    cfg, row = active_pack(db, key)
    return cfg, row.id if row else None


def ml_finding(pack: RulePackConfig, view: DocumentView) -> Finding | None:
    if not pack.ml.enabled:
        return None
    try:
        result = get_model(pack.key).score_document(view)
    except Exception:  # noqa: BLE001 -- ML is advisory; never fail validation because of it
        log.exception("Anomaly scoring failed for pack %s", pack.key)
        return None
    if result.score < pack.ml.anomaly_threshold:
        return None
    # Confidence grows with the anomaly score, tempered by extraction quality: an OCR'd
    # document with odd values is as likely to be an OCR error as a real anomaly.
    confidence = round(min(1.0, max(pack.ml.confidence_floor, result.score) * view.quality), 4)
    return Finding(
        rule_id=ML_RULE_ID,
        check="isolation_forest",
        severity=pack.ml.severity.value,
        confidence=confidence,
        title="Unusual combination of terms",
        explanation=result.explanation(),
        evidence={"check": "isolation_forest", **result.to_evidence(), "threshold": pack.ml.anomaly_threshold, "extraction_quality": view.quality},
        entity_id=None,
        source="ml",
    )


def run_validation(db: Session, document: Document) -> ValidationOutcome:
    db.refresh(document)  # drop any stale relationship collections from the extraction stage
    if document.status in (DocumentStatus.uploaded, DocumentStatus.processing) and not document.entities and not document.raw_text:
        raise RuntimeError(f"Document {document.id} has not been extracted yet")

    set_status(db, document, DocumentStatus.processing, stage="validation")
    pack, pack_row_id = resolve_pack(db, document)
    run = ValidationRun(document_id=document.id, rule_pack_id=pack_row_id, ml_model_version=MODEL_VERSION, status=RunStatus.running)
    db.add(run)
    db.flush()
    record(
        db, event_type=events.VALIDATION_STARTED, target_type="validation_run", target_id=run.id, document_id=document.id,
        payload={"rule_pack": pack.key, "rule_pack_version": pack.version, "ml_model_version": MODEL_VERSION,
                 "related_document_id": document.related_document_id},
    )
    db.commit()

    try:
        outcome = _validate(db, document, pack, run)
    except Exception as exc:  # noqa: BLE001
        log.exception("Validation failed for document %s", document.id)
        run.status = RunStatus.failed
        run.completed_at = utcnow()
        document.error_message = f"{type(exc).__name__}: {exc}"[:2000]
        record(db, event_type=events.VALIDATION_FAILED, target_type="validation_run", target_id=run.id, document_id=document.id, payload={"error": document.error_message})
        set_status(db, document, DocumentStatus.failed, stage="validation")
        db.commit()
        raise
    return outcome


def _validate(db: Session, document: Document, pack: RulePackConfig, run: ValidationRun) -> ValidationOutcome:
    view = to_view(document)
    related_view = None
    if document.related_document is not None and document.related_document.entities:
        related_view = to_view(document.related_document)

    engine_result = evaluate(pack, RuleContext(document=view, related=related_view))
    findings = list(engine_result.findings)
    ml = ml_finding(pack, view)
    if ml:
        findings.append(ml)

    # Feedback loop: reviewer history re-calibrates confidence per rule.
    stats = rule_stats(db)
    for f in findings:
        f.confidence, calibration = calibrate(f.confidence, stats.get(f.rule_id))
        f.evidence["calibration"] = calibration

    # Supersede flags from earlier runs so the review queue only shows current findings.
    stale = db.execute(
        select(Flag).where(Flag.document_id == document.id, Flag.status == FlagStatus.open, Flag.validation_run_id != run.id)
    ).scalars().all()
    for old in stale:
        old.status = FlagStatus.superseded
        old.evidence = {**(old.evidence or {}), "superseded_by_run": run.id}

    flags: list[Flag] = []
    for f in findings:
        rule = pack.rule_by_id(f.rule_id)
        flag = Flag(
            validation_run_id=run.id,
            document_id=document.id,
            entity_id=f.entity_id,
            source=FlagSource(f.source),
            rule_id=f.rule_id,
            rule_snapshot=rule_snapshot(rule, pack) if rule else {"pack": pack.key, "pack_version": pack.version, "id": f.rule_id, "check": f.check, "ml": pack.ml.model_dump(mode="json")},
            severity=Severity(f.severity),
            confidence=f.confidence,
            title=f.title,
            explanation=f.explanation,
            evidence=f.evidence,
            status=FlagStatus.open,
        )
        db.add(flag)
        flags.append(flag)
    db.flush()
    for flag in flags:
        record(
            db, event_type=events.FLAG_RAISED, target_type="flag", target_id=flag.id, document_id=document.id,
            payload={"rule_id": flag.rule_id, "source": flag.source.value, "severity": flag.severity.value,
                     "confidence": flag.confidence, "title": flag.title, "explanation": flag.explanation,
                     "entity_id": flag.entity_id, "evidence": flag.evidence},
        )

    routing = decide(findings, pack.routing)
    run.status = RunStatus.completed
    run.overall_score = routing.score
    run.routing_decision = routing.decision
    run.routing_reason = routing.reason
    run.completed_at = utcnow()

    summary = summarize_flags(
        [{"severity": f.severity, "confidence": f.confidence, "title": f.title, "source": f.source} for f in findings],
        decision=routing.decision.value, reason=routing.reason,
    )
    record(
        db, event_type=events.VALIDATION_COMPLETED, target_type="validation_run", target_id=run.id, document_id=document.id,
        payload={"flag_count": len(flags), "rules_evaluated": engine_result.rules_evaluated, "rules_skipped": engine_result.rules_skipped,
                 "rule_errors": engine_result.errors, "score": routing.score, "summary": summary},
    )
    record(
        db, event_type=events.ROUTING_DECIDED, target_type="validation_run", target_id=run.id, document_id=document.id,
        payload={"decision": routing.decision.value, "reason": routing.reason, "score": routing.score,
                 "blocking_rules": routing.blocking, "ambiguous_rules": routing.ambiguous,
                 "policy": pack.routing.model_dump(mode="json")},
    )
    new_status = DocumentStatus.auto_approved if routing.decision == RoutingDecision.auto_approved else DocumentStatus.needs_review
    document.error_message = None
    set_status(db, document, new_status, run_id=run.id, decision=routing.decision.value)
    db.commit()
    return ValidationOutcome(run=run, flags=flags, decision=routing.decision, reason=routing.reason, score=routing.score, summary=summary)
