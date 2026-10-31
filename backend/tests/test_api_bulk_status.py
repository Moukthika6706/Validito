"""Feature 1: bulk upload, poll-friendly status endpoint, lifecycle transitions, failure path."""

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models import Document, DocumentStatus
from app.workers.tasks import extract_document, validate_document
from tests.test_api_documents import PDF_SHEET_LINES, pdf_bytes, register_and_login

CLEAN = [
    "Trade Date: 15 March 2026", "Effective Date: 17 March 2026", "Termination Date: 17 March 2031",
    "Notional Amount: USD 50,000,000", "Party A: Barclays Bank PLC", "Party B: Northwind Industries Ltd",
    "Fixed Rate: 3.75% per annum", "Floating Rate Option: 3-month SOFR plus 45 bps", "Payment Frequency: Quarterly",
    "Settlement: Cash settlement", "Governing Law: English law", "Documentation: ISDA 2002 Master Agreement",
]
# Passes MIME sniffing (%PDF header) but PyMuPDF cannot open it -> extraction raises.
CORRUPT_PDF = b"%PDF-1.4\n" + b"\x00garbage" * 50


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def run_chain(doc_id):
    extract_document.apply(args=(doc_id,))
    validate_document.apply(args=(doc_id,))


def test_bulk_upload_mixed_files(client):
    headers = register_and_login(client, "bulk@example.com")
    files = [
        ("files", ("clean.pdf", pdf_bytes(CLEAN), "application/pdf")),
        ("files", ("payload.exe", b"MZ\x90\x00" * 20, "application/octet-stream")),
        ("files", ("fake.pdf", b"not a pdf", "application/pdf")),
        ("files", ("second.pdf", pdf_bytes(CLEAN[:6]), "application/pdf")),
    ]
    with patch("app.workers.tasks.enqueue_processing") as enq:
        r = client.post("/api/v1/documents/bulk", headers=headers, files=files, data={"rule_pack_key": "isda"})
    assert r.status_code == 202, r.text
    body = r.json()
    assert body["accepted"] == 2 and body["rejected"] == 2
    by_name = {x["filename"]: x for x in body["results"]}
    assert by_name["clean.pdf"]["accepted"] and by_name["clean.pdf"]["document_id"] and by_name["clean.pdf"]["status"] == "queued"
    assert not by_name["payload.exe"]["accepted"] and "Unsupported" in by_name["payload.exe"]["reason"]
    assert not by_name["fake.pdf"]["accepted"] and "does not match" in by_name["fake.pdf"]["reason"]
    assert enq.call_count == 2  # only accepted files are queued

    # The batch is audited as one event plus one per accepted file.
    trail = client.get("/api/v1/audit", headers=headers, params={"event_type": "document.bulk_uploaded"}).json()
    assert trail["total"] == 1 and trail["items"][0]["payload"]["rejected"] == 2


def test_status_endpoint_is_scoped_and_lightweight(client):
    h1 = register_and_login(client, "one@example.com")
    h2 = register_and_login(client, "two@example.com")
    with patch("app.workers.tasks.enqueue_processing"):
        d1 = client.post("/api/v1/documents", headers=h1, files={"file": ("a.pdf", pdf_bytes(CLEAN), "application/pdf")}).json()["id"]
        d2 = client.post("/api/v1/documents", headers=h2, files={"file": ("b.pdf", pdf_bytes(CLEAN), "application/pdf")}).json()["id"]

    mine = client.get("/api/v1/documents/status", headers=h1, params={"ids": f"{d1},{d2},999"}).json()
    assert [x["id"] for x in mine] == [d1]  # other user's doc and unknown id are omitted
    assert mine[0]["status"] == "queued" and mine[0]["terminal"] is False and mine[0]["attempts"] == 0

    assert client.get("/api/v1/documents/status", headers=h1, params={"ids": "abc"}).json() == []
    assert client.get("/api/v1/documents/status", params={"ids": "1"}).status_code == 401


def test_lifecycle_transitions_are_audited(client, db):
    headers = register_and_login(client, "life@example.com")
    with patch("app.workers.tasks.enqueue_processing", side_effect=run_chain):
        doc_id = client.post("/api/v1/documents", headers=headers, files={"file": ("a.pdf", pdf_bytes(CLEAN), "application/pdf")}, data={"rule_pack_key": "isda"}).json()["id"]

    snap = client.get("/api/v1/documents/status", headers=headers, params={"ids": str(doc_id)}).json()[0]
    assert snap["status"] == "auto_approved" and snap["terminal"] is True and snap["routing_decision"] == "auto_approved"
    assert snap["attempts"] == 2  # one extraction attempt + one validation attempt

    trail = client.get(f"/api/v1/audit/documents/{doc_id}", headers=headers, params={"limit": 500}).json()["items"]
    transitions = [(e["payload"]["from"], e["payload"]["to"]) for e in reversed(trail) if e["event_type"] == "document.status_changed"]
    assert transitions == [("queued", "extracting"), ("extracting", "extracted"), ("extracted", "validating"), ("validating", "auto_approved")]


def test_failure_path_marks_stage_and_retry_recovers(client, db):
    headers = register_and_login(client, "fail@example.com")
    with patch("app.workers.tasks.enqueue_processing", side_effect=lambda i: extract_document.apply(args=(i,))):
        r = client.post("/api/v1/documents", headers=headers, files={"file": ("broken.pdf", CORRUPT_PDF, "application/pdf")})
    assert r.status_code == 202
    doc_id = r.json()["id"]

    snap = client.get("/api/v1/documents/status", headers=headers, params={"ids": str(doc_id)}).json()[0]
    assert snap["status"] == "failed" and snap["terminal"] is True
    assert snap["failed_stage"] == "extracting"
    assert snap["error_message"] and snap["attempts"] >= 1

    retries = client.get(f"/api/v1/audit/documents/{doc_id}", headers=headers, params={"limit": 500}).json()["items"]
    assert any(e["event_type"] == "document.retry_scheduled" for e in retries) or snap["attempts"] == 1

    # Retry: reprocess resets the counters and queues it again.
    with patch("app.workers.tasks.enqueue_processing"):
        r = client.post(f"/api/v1/documents/{doc_id}/reprocess", headers=headers)
    assert r.status_code == 202
    assert r.json()["status"] == "queued" and r.json()["failed_stage"] is None and r.json()["attempts"] == 0 and r.json()["error_message"] is None


def test_direct_runner_still_marks_failed(db):
    """Scripts / tests that call run_extraction directly keep the terminal transition."""
    from app.core.security import hash_password
    from app.extraction.pipeline import run_extraction
    from app.ingestion.storage import store_upload
    from app.models import User

    u = User(email="d@example.com", password_hash=hash_password("password123"), full_name="D")
    db.add(u)
    db.flush()
    rel, digest = store_upload(u.id, "pdf", CORRUPT_PDF)
    doc = Document(owner_id=u.id, original_filename="x.pdf", storage_path=rel, mime_type="application/pdf", size_bytes=len(CORRUPT_PDF), sha256=digest)
    db.add(doc)
    db.commit()
    with pytest.raises(Exception):
        run_extraction(db, doc)
    db.refresh(doc)
    assert doc.status == DocumentStatus.failed and doc.failed_stage == "extracting"
