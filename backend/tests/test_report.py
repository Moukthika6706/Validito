"""Feature 3: per-document PDF validation report."""

from pathlib import Path
from unittest.mock import patch

import pymupdf
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models import UserRole
from app.services.report_service import verify_document_chain
from app.workers.tasks import extract_document, validate_document
from tests.test_api_documents import register_and_login
from tests.test_api_review_audit import login, make_role_user

SAMPLES = Path(__file__).resolve().parents[2] / "samples"


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def _upload(client, headers, name):
    def run(doc_id):
        extract_document.apply(args=(doc_id,))
        validate_document.apply(args=(doc_id,))

    with patch("app.workers.tasks.enqueue_processing", side_effect=run):
        r = client.post("/api/v1/documents", headers=headers, files={"file": (name, (SAMPLES / name).read_bytes(), "application/pdf")}, data={"rule_pack_key": "isda"})
    assert r.status_code == 202, r.text
    return r.json()["id"]


def _pdf_text(content: bytes) -> str:
    assert content[:5] == b"%PDF-"
    with pymupdf.open(stream=content, filetype="pdf") as doc:
        return "\n".join(p.get_text() for p in doc), len(doc)


def test_report_for_clean_document(client):
    headers = register_and_login(client, "clean@example.com")
    doc_id = _upload(client, headers, "isda_irs_clean.pdf")
    r = client.get(f"/api/v1/documents/{doc_id}/report.pdf", headers=headers)
    assert r.status_code == 200 and r.headers["content-type"] == "application/pdf"
    assert r.headers["content-disposition"].startswith("attachment; filename=")
    assert len(r.content) > 5_000
    text, pages = _pdf_text(r.content)
    assert pages >= 2
    assert "VALIDATION REPORT" in text and "isda_irs_clean.pdf" in text
    assert "auto approved" in text.lower()
    assert "Notional amount" in text.replace("notional amount", "Notional amount") and "USD 50m" in text
    assert "No flags were raised" in text
    assert "Chain verification" in text and "INTACT" in text
    assert "document.uploaded" in text and "routing.decided" in text


def test_report_for_faulty_document_includes_flags_actions_and_hashes(client, db):
    make_role_user(db, "rev@example.com", UserRole.reviewer)
    analyst = register_and_login(client, "faulty@example.com")
    reviewer = login(client, "rev@example.com")
    doc_id = _upload(client, analyst, "isda_irs_faulty.pdf")
    flags = client.get(f"/api/v1/documents/{doc_id}/flags", headers=reviewer).json()
    libor = next(f for f in flags if f["rule_id"] == "isda.benchmark.discontinued")
    client.post(f"/api/v1/review/flags/{libor['id']}/actions", headers=reviewer, json={"action": "accept", "comment": "Legacy LIBOR wording confirmed"})

    r = client.get(f"/api/v1/documents/{doc_id}/report.pdf", headers=reviewer)
    assert r.status_code == 200
    text, _ = _pdf_text(r.content)
    assert "needs review" in text.lower()
    assert "CRITICAL" in text and "Governing law missing" in text
    assert "isda.benchmark.discontinued" in text and "LIBOR" in text
    assert "ISDA v1.0.0" in text  # rule snapshot version
    assert "Legacy LIBOR wording confirmed" in text and "Reviewer" in text  # reviewer action + name
    assert "Unusual combination of terms" in text and "σ" in text  # ML flag with deviations
    assert "review.action" in text and "review.claimed" in text
    assert "INTACT" in text

    # Generating a report is audited (actor = the reviewer).
    trail = client.get("/api/v1/audit", headers=reviewer, params={"event_type": "report.generated", "document_id": doc_id}).json()
    assert trail["total"] == 1 and trail["items"][0]["payload"]["bytes"] == len(r.content)


def test_report_access_control(client):
    owner = register_and_login(client, "owner@example.com")
    other = register_and_login(client, "other@example.com")
    doc_id = _upload(client, owner, "isda_irs_clean.pdf")
    assert client.get(f"/api/v1/documents/{doc_id}/report.pdf", headers=other).status_code == 404
    assert client.get(f"/api/v1/documents/{doc_id}/report.pdf").status_code == 401
    assert client.get("/api/v1/documents/9999/report.pdf", headers=owner).status_code == 404


def test_document_chain_slice_detects_tampering(client, db):
    from sqlalchemy import select
    from app.models import AuditLog

    headers = register_and_login(client, "chain@example.com")
    doc_id = _upload(client, headers, "isda_irs_clean.pdf")
    result = verify_document_chain(db, doc_id)
    assert result["ok"] and result["checked"] > 5

    row = db.execute(select(AuditLog).where(AuditLog.document_id == doc_id, AuditLog.event_type == "routing.decided")).scalar_one()
    row.payload = {**row.payload, "decision": "auto_approved_tampered"}
    db.commit()
    bad = verify_document_chain(db, doc_id)
    assert bad["ok"] is False and bad["first_bad_id"] == row.id
    text, _ = _pdf_text(client.get(f"/api/v1/documents/{doc_id}/report.pdf", headers=headers).content)
    assert "BROKEN" in text
