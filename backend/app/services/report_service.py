"""Per-document PDF validation report (reportlab).

The report is a faithful export of what the review screen shows: metadata, extracted
fields, the routing decision, every flag with its explanation / evidence / rule snapshot /
confidence, reviewer actions, and the document's audit events with their hashes plus a
verification of that slice of the chain. Nothing is summarised away — a compliance reader
should be able to reconstruct the decision from the PDF alone.
"""

import io
from datetime import datetime, timezone
from typing import Any

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.audit.logger import compute_hash
from app.models import AuditLog, Document, Flag, FlagStatus, ReviewActionRecord, User, ValidationRun
from app.utils_format import fmt_normalized

SEVERITY_COLOR = {
    "critical": colors.HexColor("#7a1a12"),
    "error": colors.HexColor("#b3261e"),
    "warning": colors.HexColor("#b45f06"),
    "info": colors.HexColor("#2d4f8f"),
}
INK = colors.HexColor("#1c1917")
MUTED = colors.HexColor("#6b6762")
LINE = colors.HexColor("#e2ded8")
CREAM = colors.HexColor("#f5f4f2")


def _styles():
    base = getSampleStyleSheet()
    s = {
        "h1": ParagraphStyle("h1", parent=base["Title"], fontName="Helvetica-Bold", fontSize=20, leading=24, alignment=TA_LEFT, textColor=INK, spaceAfter=2),
        "h2": ParagraphStyle("h2", parent=base["Heading2"], fontName="Helvetica-Bold", fontSize=12.5, leading=16, textColor=INK, spaceBefore=12, spaceAfter=6),
        "h3": ParagraphStyle("h3", parent=base["Heading3"], fontName="Helvetica-Bold", fontSize=10.5, leading=13, textColor=INK, spaceBefore=6, spaceAfter=3),
        "body": ParagraphStyle("body", parent=base["BodyText"], fontName="Helvetica", fontSize=9, leading=12.5, textColor=INK),
        "small": ParagraphStyle("small", parent=base["BodyText"], fontName="Helvetica", fontSize=7.8, leading=10.5, textColor=MUTED),
        "mono": ParagraphStyle("mono", parent=base["BodyText"], fontName="Courier", fontSize=7.6, leading=10, textColor=INK),
        "cell": ParagraphStyle("cell", parent=base["BodyText"], fontName="Helvetica", fontSize=8.2, leading=11, textColor=INK),
        "cellmono": ParagraphStyle("cellmono", parent=base["BodyText"], fontName="Courier", fontSize=7.4, leading=9.5, textColor=INK),
    }
    return s


def _esc(v: Any) -> str:
    text = "" if v is None else str(v)
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _ts(dt: datetime | None) -> str:
    if dt is None:
        return "—"
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _table(rows, col_widths, header=True, zebra=True):
    t = Table(rows, colWidths=col_widths, repeatRows=1 if header else 0, hAlign="LEFT")
    style = [
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LINEBELOW", (0, 0), (-1, -1), 0.25, LINE),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]
    if header:
        style += [("BACKGROUND", (0, 0), (-1, 0), CREAM), ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"), ("TEXTCOLOR", (0, 0), (-1, 0), MUTED), ("FONTSIZE", (0, 0), (-1, 0), 7.5)]
    if zebra:
        for i in range(1 if header else 0, len(rows)):
            if i % 2 == 0:
                style.append(("BACKGROUND", (0, i), (-1, i), colors.HexColor("#fbfaf8")))
    t.setStyle(TableStyle(style))
    return t


# --------------------------------------------------------------------------- chain slice


def verify_document_chain(db: Session, document_id: int) -> dict[str, Any]:
    """Re-hash every audit row for this document and check each one links to the row before
    it in the global log. Returns {ok, checked, first_bad_id}."""
    rows = db.execute(select(AuditLog).where(AuditLog.document_id == document_id).order_by(AuditLog.id)).scalars().all()
    if not rows:
        return {"ok": True, "checked": 0, "first_bad_id": None}
    prev_ids = [r.id - 1 for r in rows if r.id > 1]
    prevs = {p.id: p.hash for p in db.execute(select(AuditLog).where(AuditLog.id.in_(prev_ids))).scalars()} if prev_ids else {}
    for r in rows:
        expected = compute_hash(
            prev_hash=r.prev_hash, event_type=r.event_type, target_type=r.target_type, target_id=r.target_id,
            actor_id=r.actor_id, document_id=r.document_id, payload=r.payload, created_at=r.created_at,
        )
        linked = r.id == 1 or prevs.get(r.id - 1) == r.prev_hash
        if r.hash != expected or not linked:
            return {"ok": False, "checked": len(rows), "first_bad_id": r.id}
    return {"ok": True, "checked": len(rows), "first_bad_id": None}


# --------------------------------------------------------------------------- report


def build_report(db: Session, document: Document, *, generated_by: User) -> bytes:
    s = _styles()
    db.refresh(document)
    run = db.execute(select(ValidationRun).where(ValidationRun.document_id == document.id).order_by(ValidationRun.id.desc()).limit(1)).scalar_one_or_none()
    flags = db.execute(
        select(Flag).where(Flag.document_id == document.id, Flag.status != FlagStatus.superseded)
        .options(selectinload(Flag.entity), selectinload(Flag.review_actions).selectinload(ReviewActionRecord.reviewer))
    ).scalars().all()
    flags.sort(key=lambda f: (-f.severity.rank, f.confidence, f.id))
    events = db.execute(select(AuditLog).where(AuditLog.document_id == document.id).order_by(AuditLog.id)).scalars().all()
    actor_ids = {e.actor_id for e in events if e.actor_id} | {a.reviewer_id for f in flags for a in f.review_actions}
    names = {u.id: u.full_name for u in db.execute(select(User).where(User.id.in_(actor_ids))).scalars()} if actor_ids else {}
    chain = verify_document_chain(db, document.id)

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4, leftMargin=16 * mm, rightMargin=16 * mm, topMargin=16 * mm, bottomMargin=16 * mm,
        title=f"Validito report — {document.original_filename}", author="Validito",
    )
    W = A4[0] - 32 * mm
    story: list = []

    # ---- header
    story.append(Paragraph("VALIDITO — VALIDATION REPORT", s["h1"]))
    story.append(Paragraph(f"{_esc(document.original_filename)} · generated {_ts(datetime.now(timezone.utc))} by {_esc(generated_by.full_name)} ({_esc(generated_by.email)})", s["small"]))
    story.append(Spacer(1, 6))

    # ---- metadata + decision
    decision = run.routing_decision.value if run and run.routing_decision else "pending"
    meta_rows = [
        ["Document id", str(document.id), "Status", document.status.value.replace("_", " ")],
        ["Type", document.doc_type.value.replace("_", " "), "Routing decision", decision.replace("_", " ")],
        ["Rule pack", f"{document.rule_pack_key or '—'}" + (f" (run #{run.id}, model {run.ml_model_version})" if run else ""), "Overall score", f"{run.overall_score:.2f}" if run and run.overall_score is not None else "—"],
        ["Uploaded", _ts(document.created_at), "Decided", _ts(run.completed_at) if run else "—"],
        ["Owner", names.get(document.owner_id) or f"user #{document.owner_id}", "Final verdict", document.review_outcome or "—"],
        ["SHA-256", document.sha256, "Pages / OCR", f"{document.page_count or '?'} / {'yes' if document.ocr_used else 'no'}"],
    ]
    meta_rows = [[Paragraph(_esc(c), s["cell"] if i % 2 else s["small"]) for i, c in enumerate(r)] for r in meta_rows]
    story.append(_table(meta_rows, [28 * mm, W / 2 - 28 * mm, 30 * mm, W / 2 - 30 * mm], header=False, zebra=False))
    if run and run.routing_reason:
        story.append(Spacer(1, 4))
        story.append(Paragraph(f"<b>Why:</b> {_esc(run.routing_reason)}", s["body"]))

    # ---- extracted fields
    story.append(Paragraph("Extracted fields", s["h2"]))
    ents = sorted(document.entities, key=lambda e: (e.entity_type, -e.confidence))
    if ents:
        rows = [["Field", "Extracted text", "Interpreted as", "Conf.", "Source", "Page"]]
        for e in ents:
            rows.append([
                Paragraph(_esc(e.entity_type.replace("_", " ")), s["cell"]), Paragraph(_esc(e.raw_text), s["cellmono"]),
                Paragraph(_esc(fmt_normalized(e.normalized_value) or "could not parse"), s["cell"]),
                Paragraph(f"{e.confidence:.0%}", s["cell"]), Paragraph(_esc(e.extractor.value), s["cell"]), Paragraph(str(e.page or "—"), s["cell"]),
            ])
        story.append(_table(rows, [30 * mm, 52 * mm, 50 * mm, 12 * mm, 20 * mm, 12 * mm]))
    else:
        story.append(Paragraph("No fields were extracted.", s["small"]))

    # ---- flags
    open_count = sum(1 for f in flags if f.status == FlagStatus.open)
    story.append(Paragraph(f"Flags ({len(flags)} total, {open_count} open)", s["h2"]))
    if not flags:
        story.append(Paragraph("No flags were raised: every rule check passed and the anomaly model found nothing unusual.", s["body"]))
    for f in flags:
        block = []
        sev_color = SEVERITY_COLOR.get(f.severity.value, INK).hexval()[2:] if hasattr(SEVERITY_COLOR.get(f.severity.value, INK), "hexval") else "1c1917"
        block.append(Paragraph(
            f'<font color="#{sev_color}"><b>{_esc(f.severity.value.upper())}</b></font> · {_esc(f.title)} '
            f'<font color="#6b6762">— {_esc(f.source.value)} · status: {_esc(f.status.value)}</font>', s["h3"]))
        block.append(Paragraph(_esc(f.explanation), s["body"]))
        snap = f.rule_snapshot or {}
        ev = f.evidence or {}
        details = [
            ["Rule", f"{f.rule_id} ({snap.get('check') or ev.get('check', '—')})"],
            ["Rule pack version", f"{str(snap.get('pack', '—')).upper()} v{snap.get('pack_version', '—')}"],
            ["Confidence", f"{f.confidence:.0%}" + (f" (calibrated ×{ev['calibration']['multiplier']} from {ev['calibration']['samples']} reviewer decisions)" if ev.get("calibration", {}).get("applied") else "")],
        ]
        if f.entity is not None:
            details.append(["Clause", f"{f.entity.entity_type.replace('_', ' ')}: {f.entity.raw_text}" + (f" (page {f.entity.page})" if f.entity.page else "")])
        evid = {k: v for k, v in ev.items() if k not in ("check", "field", "params", "extraction_quality", "entity", "calibration", "contributions", "model", "model_version", "pack_key")}
        if ev.get("contributions"):
            evid["deviations"] = "; ".join(f"{c['label']} {c['value_text']} vs typical {c['typical_text']} ({c['z_score']:+}σ)" for c in ev["contributions"])
        if evid:
            details.append(["Evidence", ", ".join(f"{k}={v}" for k, v in evid.items())])
        if snap.get("params"):
            details.append(["Rule params", str(snap["params"])])
        block.append(_table([[Paragraph(_esc(k), s["small"]), Paragraph(_esc(v), s["cell"])] for k, v in details], [32 * mm, W - 32 * mm], header=False, zebra=False))
        if f.review_actions:
            acts = [["When", "Reviewer", "Action", "Comment / override"]]
            for a in f.review_actions:
                acts.append([
                    Paragraph(_ts(a.created_at), s["cell"]), Paragraph(_esc(names.get(a.reviewer_id) or f"user #{a.reviewer_id}"), s["cell"]),
                    Paragraph(_esc(a.action.value), s["cell"]),
                    Paragraph(_esc((a.comment or "") + (f" → {a.override_value}" if a.override_value else "")), s["cell"]),
                ])
            block.append(Spacer(1, 2))
            block.append(_table(acts, [36 * mm, 34 * mm, 20 * mm, W - 90 * mm]))
        block.append(Spacer(1, 6))
        story.append(KeepTogether(block))

    # ---- audit trail
    story.append(PageBreak())
    story.append(Paragraph(f"Audit trail for document #{document.id} ({len(events)} events)", s["h2"]))
    verdict = ("INTACT — every event re-hashed correctly and links to its predecessor." if chain["ok"]
               else f"BROKEN at entry #{chain['first_bad_id']} — a row was altered or removed outside the logger.")
    story.append(Paragraph(f"<b>Chain verification ({chain['checked']} entries):</b> {verdict}", s["body"]))
    story.append(Spacer(1, 4))
    rows = [["#", "Timestamp", "Event", "Actor", "Detail", "Hash (prev → this)"]]
    for e in events:
        rows.append([
            Paragraph(str(e.id), s["cell"]), Paragraph(_ts(e.created_at), s["cell"]), Paragraph(_esc(e.event_type), s["cellmono"]),
            Paragraph(_esc(names.get(e.actor_id) or ("system" if e.actor_id is None else f"user #{e.actor_id}")), s["cell"]),
            Paragraph(_esc(_event_detail(e)), s["cell"]),
            Paragraph(f"{(e.prev_hash or 'genesis')[:12]}…<br/>{e.hash[:12]}…", s["cellmono"]),
        ])
    story.append(_table(rows, [9 * mm, 32 * mm, 34 * mm, 22 * mm, W - 125 * mm, 28 * mm]))
    story.append(Spacer(1, 6))
    story.append(Paragraph("Hashes are SHA-256 over (previous hash, event, target, actor, document, canonical payload, timestamp). "
                           "Full hashes are available from GET /api/v1/audit/documents/{id}; GET /api/v1/audit/verify re-checks the entire log.", s["small"]))

    def _footer(canvas, d):
        canvas.saveState()
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(MUTED)
        canvas.drawString(16 * mm, 10 * mm, f"Validito · {document.original_filename} · document #{document.id}")
        canvas.drawRightString(A4[0] - 16 * mm, 10 * mm, f"page {d.page}")
        canvas.restoreState()

    doc.build(story, onFirstPage=_footer, onLaterPages=_footer)
    return buf.getvalue()


def _event_detail(e: AuditLog) -> str:
    p = e.payload or {}
    t = e.event_type
    if t == "document.status_changed":
        return f"{p.get('from')} → {p.get('to')}" + (f" ({p.get('outcome')})" if p.get("outcome") else "") + (f" · {p.get('reason')}" if p.get("reason") else "")
    if t == "flag.raised":
        return f"{p.get('severity')} · {p.get('rule_id')} · {p.get('title')} · conf {p.get('confidence')}"
    if t == "routing.decided":
        return f"{p.get('decision')}: {p.get('reason')}"
    if t == "review.action":
        return f"{p.get('action')} on {p.get('rule_id')}" + (f" — “{p.get('comment')}”" if p.get("comment") else "")
    if t == "entity.extracted":
        return f"{p.get('entity_type')}: {p.get('raw_text')} (conf {p.get('confidence')})"
    if t == "extraction.completed":
        return f"{p.get('entity_count')} fields from {p.get('page_count')} page(s)" + (" via OCR" if p.get("ocr_used") else "")
    if t == "validation.completed":
        return f"{p.get('flag_count')} flag(s), score {p.get('score')}"
    if t == "validation.started":
        return f"{p.get('rule_pack')} v{p.get('rule_pack_version')}, model {p.get('ml_model_version')}"
    if t == "document.uploaded":
        return f"{p.get('filename')} ({p.get('mime_type')}, {p.get('size_bytes')} bytes)"
    if t.startswith("review.claimed"):
        return f"expires {p.get('expires_at')}"
    if t == "report.generated":
        return f"{p.get('bytes')} bytes"
    return ", ".join(f"{k}={v}" for k, v in list(p.items())[:4]) if p else ""
