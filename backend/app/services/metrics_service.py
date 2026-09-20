from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Document, DocumentStatus, ExtractedEntity, Flag, FlagStatus, ReviewAction, ReviewActionRecord, RulePack, User, UserRole, ValidationRun

DECIDED = {DocumentStatus.auto_approved, DocumentStatus.needs_review, DocumentStatus.reviewed}


def summary(db: Session, user: User, *, days: int = 14) -> dict:
    doc_q = select(Document)
    if user.role == UserRole.analyst:
        doc_q = doc_q.where(Document.owner_id == user.id)
    docs = db.execute(doc_q).scalars().all()
    doc_ids = [d.id for d in docs]

    by_status = Counter(d.status.value for d in docs)
    decided = [d for d in docs if d.status in DECIDED]

    # Routing outcome comes from the latest completed run so a reviewed document still
    # counts toward whichever bucket the machine put it in.
    latest_runs: dict[int, ValidationRun] = {}
    if doc_ids:
        for run in db.execute(select(ValidationRun).where(ValidationRun.document_id.in_(doc_ids)).order_by(ValidationRun.id)).scalars():
            latest_runs[run.document_id] = run
    auto = sum(1 for d in decided if latest_runs.get(d.id) and latest_runs[d.id].routing_decision and latest_runs[d.id].routing_decision.value == "auto_approved")
    review = len(decided) - auto
    auto_pct = round(100 * auto / len(decided), 1) if decided else 0.0

    durations = []
    for d in decided:
        run = latest_runs.get(d.id)
        if run and run.completed_at:
            created = d.created_at if d.created_at.tzinfo else d.created_at.replace(tzinfo=timezone.utc)
            done = run.completed_at if run.completed_at.tzinfo else run.completed_at.replace(tzinfo=timezone.utc)
            durations.append(max(0.0, (done - created).total_seconds()))
    avg_seconds = round(sum(durations) / len(durations), 2) if durations else None

    flags = db.execute(select(Flag).where(Flag.document_id.in_(doc_ids), Flag.status != FlagStatus.superseded)).scalars().all() if doc_ids else []
    flags_by_severity = Counter(f.severity.value for f in flags)
    flags_by_source = Counter(f.source.value for f in flags)
    per_doc = Counter(f.document_id for f in flags)
    avg_flags = round(sum(per_doc.values()) / len(decided), 2) if decided else 0.0

    actions = db.execute(select(ReviewActionRecord).join(Flag).where(Flag.document_id.in_(doc_ids))).scalars().all() if doc_ids else []
    action_counts = Counter(a.action.value for a in actions)
    accepted_by_rule: dict[str, int] = defaultdict(int)
    rejected_by_rule: dict[str, int] = defaultdict(int)
    flag_rule = {f.id: f.rule_id for f in flags}
    for a in actions:
        rid = flag_rule.get(a.flag_id)
        if rid is None:
            continue
        (rejected_by_rule if a.action == ReviewAction.reject else accepted_by_rule)[rid] += 1
    judged = action_counts.get("accept", 0) + action_counts.get("override", 0) + action_counts.get("reject", 0)
    agreement = round(100 * (action_counts.get("accept", 0) + action_counts.get("override", 0)) / judged, 1) if judged else None

    rule_counts = Counter(f.rule_id for f in flags)
    titles = {}
    for f in flags:
        titles.setdefault(f.rule_id, f.title)
    top_rules = [
        {"rule_id": rid, "title": titles[rid], "count": n, "accepted": accepted_by_rule.get(rid, 0), "rejected": rejected_by_rule.get(rid, 0)}
        for rid, n in rule_counts.most_common(10)
    ]

    week_ago = datetime.now(timezone.utc) - timedelta(days=7)
    def _aware(dt):
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    this_week = [d for d in decided if _aware(d.created_at) >= week_ago]
    flagged_this_week = sum(1 for d in this_week if latest_runs.get(d.id) and latest_runs[d.id].routing_decision and latest_runs[d.id].routing_decision.value == "needs_review")

    # Notional validated: sum of the best notional per decided document, grouped by currency.
    notional_by_ccy: dict[str, float] = defaultdict(float)
    if decided:
        decided_ids = [d.id for d in decided]
        best: dict[int, ExtractedEntity] = {}
        for e in db.execute(select(ExtractedEntity).where(ExtractedEntity.document_id.in_(decided_ids), ExtractedEntity.entity_type == "notional_amount")).scalars():
            if e.document_id not in best or e.confidence > best[e.document_id].confidence:
                best[e.document_id] = e
        for e in best.values():
            nv = e.normalized_value or {}
            if isinstance(nv.get("amount"), (int, float)):
                notional_by_ccy[nv.get("currency") or "???"] += float(nv["amount"])
    active_packs = db.execute(select(func.count(RulePack.id)).where(RulePack.is_active.is_(True))).scalar_one()

    today = datetime.now(timezone.utc).date()
    daily = []
    for i in range(days - 1, -1, -1):
        day = today - timedelta(days=i)
        day_docs = [d for d in docs if d.created_at.date() == day]
        daily.append({
            "day": day.isoformat(),
            "uploaded": len(day_docs),
            "auto_approved": sum(1 for d in day_docs if latest_runs.get(d.id) and latest_runs[d.id].routing_decision and latest_runs[d.id].routing_decision.value == "auto_approved"),
            "needs_review": sum(1 for d in day_docs if latest_runs.get(d.id) and latest_runs[d.id].routing_decision and latest_runs[d.id].routing_decision.value == "needs_review"),
        })

    return {
        "documents_total": len(docs),
        "by_status": dict(by_status),
        "decided_total": len(decided),
        "auto_approved_total": auto,
        "needs_review_total": review,
        "auto_approved_pct": auto_pct,
        "manual_review_reduction_pct": auto_pct,  # every auto-approved doc is one a human did not open
        "avg_processing_seconds": avg_seconds,
        "avg_flags_per_document": avg_flags,
        "flags_by_severity": dict(flags_by_severity),
        "flags_by_source": dict(flags_by_source),
        "top_rules": top_rules,
        "review_actions": dict(action_counts),
        "reviewer_agreement_pct": agreement,
        "daily": daily,
        "decided_this_week": len(this_week),
        "flagged_this_week": flagged_this_week,
        "notional_validated": {k: round(v, 2) for k, v in notional_by_ccy.items()},
        "active_rule_packs": active_packs,
    }
