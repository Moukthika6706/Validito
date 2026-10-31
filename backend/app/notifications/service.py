"""Decide when to notify, build the message, and hand delivery to the Celery task.

Triggers (per validation run, merged into one message):
  needs_review   - the routing decision sent the document to the human queue
  high_severity  - at least one open flag at or above NOTIFY_SEVERITY_THRESHOLD

Per-document dedupe (NOTIFY_DEDUPE_PER_DOCUMENT) uses the audit log as the ledger: if a
`notification.sent` event already exists for the document, later runs are skipped. That
keeps the behaviour queryable and avoids a table nobody else needs.
"""

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit import events
from app.core.config import Settings, get_settings
from app.models import AuditLog, Document, Flag, FlagStatus, RoutingDecision, Severity, ValidationRun
from app.notifications.channels import Message, enabled_channels

log = logging.getLogger(__name__)

SEV_RANK = {s.value: s.rank for s in Severity}


def triggers_for_run(decision: RoutingDecision, flags: list[Flag], settings: Settings | None = None) -> list[str]:
    s = settings or get_settings()
    kinds: list[str] = []
    if decision == RoutingDecision.needs_review:
        kinds.append("needs_review")
    threshold = SEV_RANK.get(s.notify_severity_threshold, Severity.error.rank)
    if any(f.status == FlagStatus.open and f.severity.rank >= threshold for f in flags):
        kinds.append("high_severity")
    return kinds


def already_notified(db: Session, document_id: int, channel: str | None = None, run_id: int | None = None) -> bool:
    rows = db.execute(select(AuditLog).where(AuditLog.document_id == document_id, AuditLog.event_type == events.NOTIFICATION_SENT)).scalars().all()
    for r in rows:
        p = r.payload or {}
        if channel and p.get("channel") != channel:
            continue
        if run_id and p.get("run_id") != run_id:
            continue
        return True
    return False


def enqueue_for_run(db: Session, document: Document, run: ValidationRun, flags: list[Flag], decision: RoutingDecision) -> list[str]:
    """Called by the validation pipeline after routing. Never raises."""
    try:
        s = get_settings()
        kinds = triggers_for_run(decision, flags, s)
        if not kinds or not enabled_channels(s):
            return []
        if s.notify_dedupe_per_document and already_notified(db, document.id):
            log.info("notification for document %s suppressed by per-document dedupe", document.id)
            return []
        from app.workers.tasks import send_notification

        send_notification.apply_async(args=[document.id, run.id, kinds], queue="notifications")
        return kinds
    except Exception:  # noqa: BLE001 -- notifications are best-effort
        log.exception("Could not enqueue notification for document %s", document.id)
        return []


# --------------------------------------------------------------------------- message


def build_message(document: Document, run: ValidationRun, flags: list[Flag], kinds: list[str], settings: Settings | None = None) -> Message:
    s = settings or get_settings()
    open_flags = sorted([f for f in flags if f.status == FlagStatus.open], key=lambda f: (-f.severity.rank, f.confidence))
    counts: dict[str, int] = {}
    for f in open_flags:
        counts[f.severity.value] = counts.get(f.severity.value, 0) + 1
    summary = ", ".join(f"{counts[k]} {k}" for k in ("critical", "error", "warning", "info") if counts.get(k)) or "no open flags"
    link = f"{s.frontend_base_url.rstrip('/')}/review/{document.id}"
    reason = ", ".join({"needs_review": "routed to the review queue", "high_severity": "high-severity flags"}[k] for k in kinds)
    top = open_flags[:3]
    decision = run.routing_decision.value.replace("_", " ") if run.routing_decision else "pending"

    subject = f"[Validito] {document.original_filename}: {reason} ({summary})"
    lines = [
        f"Document: {document.original_filename} (#{document.id})",
        f"Decision: {decision} — {run.routing_reason or ''}".rstrip(" —"),
        f"Open flags: {summary}",
        "",
        "Top flags:",
        *[f"  - [{f.severity.value.upper()}] {f.title} (confidence {f.confidence:.0%}) — {f.explanation}" for f in top],
        "",
        f"Review: {link}",
    ]
    text = "\n".join(lines)
    html = (
        f"<p><strong>{_e(document.original_filename)}</strong> (#{document.id}) — {_e(reason)}</p>"
        f"<p>Decision: <strong>{_e(decision)}</strong><br/>{_e(run.routing_reason or '')}</p>"
        f"<p>Open flags: {_e(summary)}</p><ul>"
        + "".join(f"<li><strong>{_e(f.severity.value.upper())}</strong> {_e(f.title)} ({f.confidence:.0%})<br/><small>{_e(f.explanation)}</small></li>" for f in top)
        + f'</ul><p><a href="{_e(link)}">Open the review screen</a></p>'
    )
    blocks: list[dict[str, Any]] = [
        {"type": "header", "text": {"type": "plain_text", "text": f"Validito: {document.original_filename}"[:150]}},
        {"type": "section", "text": {"type": "mrkdwn", "text": f"*{decision}* — {reason}\nOpen flags: {summary}"}},
    ]
    if top:
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": "\n".join(f"• *{f.severity.value.upper()}* {f.title} ({f.confidence:.0%})" for f in top)}})
    blocks.append({"type": "actions", "elements": [{"type": "button", "text": {"type": "plain_text", "text": "Review document"}, "url": link}]})
    return Message(subject=subject, text=text, html=html, slack_blocks=blocks, fallback=subject)


def _e(v: Any) -> str:
    return str(v).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
