from unittest.mock import patch

import pymupdf as fitz
import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def register_and_login(client: TestClient, email: str, password: str = "password123") -> dict:
    r = client.post("/api/v1/auth/register", json={"email": email, "password": password, "full_name": "Test User"})
    assert r.status_code == 201, r.text
    r = client.post("/api/v1/auth/login", data={"username": email, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def pdf_bytes(lines: list[str]) -> bytes:
    doc = fitz.open()
    page = doc.new_page()
    y = 72
    for line in lines:
        page.insert_text((72, y), line, fontsize=11)
        y += 16
    data = doc.tobytes()
    doc.close()
    return data


SHEET = [
    "Trade Date: 15 March 2026",
    "Termination Date: 17 March 2031",
    "Notional Amount: USD 50,000,000",
    "Party A: Barclays Bank PLC",
    "Party B: Northwind Industries Ltd",
    "Governing Law: English law",
]


def test_register_duplicate_email_conflicts(client):
    register_and_login(client, "a@example.com")
    r = client.post("/api/v1/auth/register", json={"email": "a@example.com", "password": "password123", "full_name": "X"})
    assert r.status_code == 409


def test_login_wrong_password(client):
    register_and_login(client, "b@example.com")
    r = client.post("/api/v1/auth/login", data={"username": "b@example.com", "password": "nope-nope"})
    assert r.status_code == 401


def test_protected_routes_require_token(client):
    assert client.get("/api/v1/documents").status_code == 401
    assert client.get("/api/v1/auth/me").status_code == 401


def test_upload_runs_extraction_and_lists_document(client):
    headers = register_and_login(client, "analyst@example.com")

    # Only run the extraction stage inline; validation lands in the next milestone.
    from app.workers.tasks import extract_document

    with patch("app.services.document_service.enqueue_processing", side_effect=lambda doc_id: extract_document.apply(args=(doc_id,)), create=True), \
         patch("app.workers.tasks.enqueue_processing", side_effect=lambda doc_id: extract_document.apply(args=(doc_id,))):
        r = client.post(
            "/api/v1/documents",
            headers=headers,
            files={"file": ("sheet.pdf", pdf_bytes(SHEET), "application/pdf")},
            data={"doc_type": "term_sheet", "rule_pack_key": "isda"},
        )
    assert r.status_code == 202, r.text
    doc = r.json()
    assert doc["original_filename"] == "sheet.pdf"
    assert doc["rule_pack_key"] == "isda"

    r = client.get(f"/api/v1/documents/{doc['id']}", headers=headers)
    assert r.status_code == 200
    detail = r.json()
    assert detail["status"] == "extracted"
    types = {e["entity_type"] for e in detail["entities"]}
    assert {"trade_date", "maturity_date", "notional_amount", "counterparty", "governing_law", "currency"} <= types
    notional = next(e for e in detail["entities"] if e["entity_type"] == "notional_amount")
    assert notional["normalized_value"] == {"amount": 50_000_000.0, "currency": "USD"}

    r = client.get("/api/v1/documents", headers=headers)
    assert r.json()["total"] == 1

    r = client.get(f"/api/v1/documents/{doc['id']}/text", headers=headers)
    assert "Notional Amount" in r.json()["raw_text"]


def test_upload_rejects_wrong_content(client):
    headers = register_and_login(client, "c@example.com")
    r = client.post(
        "/api/v1/documents",
        headers=headers,
        files={"file": ("sheet.pdf", b"not a pdf at all", "application/pdf")},
    )
    assert r.status_code == 422
    assert "does not match" in r.json()["detail"]


def test_analysts_cannot_see_each_others_documents(client):
    h1 = register_and_login(client, "one@example.com")
    h2 = register_and_login(client, "two@example.com")
    with patch("app.workers.tasks.enqueue_processing"):
        r = client.post("/api/v1/documents", headers=h1, files={"file": ("s.pdf", pdf_bytes(SHEET), "application/pdf")})
    doc_id = r.json()["id"]

    assert client.get(f"/api/v1/documents/{doc_id}", headers=h1).status_code == 200
    assert client.get(f"/api/v1/documents/{doc_id}", headers=h2).status_code == 404
    assert client.get("/api/v1/documents", headers=h2).json()["total"] == 0
