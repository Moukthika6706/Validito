"""Feature 2: entity provenance (page + normalised bbox) and page rendering endpoints."""

from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.extraction import extract_entities, extract_text
from app.extraction.provenance import locate_boxes
from app.ingestion.validators import DOCX_MIME
from app.main import app
from app.workers.tasks import extract_document, validate_document
from tests.test_api_documents import register_and_login

SAMPLES = Path(__file__).resolve().parents[2] / "samples"


def _locate(name, mime):
    path = SAMPLES / name
    extracted = extract_text(path, mime)
    cands = extract_entities(extracted, use_ner=False)
    locate_boxes(path, mime, extracted, cands)
    return {c.entity_type: c for c in cands}


def test_text_pdf_entities_have_boxes_on_their_page():
    by_type = _locate("isda_irs_clean.pdf", "application/pdf")
    notional = by_type["notional_amount"]
    assert notional.page == 1 and notional.bbox and len(notional.bbox) == 1
    box = notional.bbox[0]
    assert box["page"] == 1
    assert 0 <= box["x0"] < box["x1"] <= 1 and 0 <= box["y0"] < box["y1"] <= 1
    # Value sits to the right of the label column in the generated sample.
    assert box["x0"] > 0.3
    # Boxes are per-entity: the maturity date is lower on the page than the trade date.
    assert by_type["maturity_date"].bbox[0]["y0"] > by_type["trade_date"].bbox[0]["y0"]
    located = sum(1 for c in by_type.values() if c.bbox)
    assert located >= len(by_type) - 2  # the derived currency entity shares the notional's text


def test_docx_entities_have_no_boxes_but_still_extract():
    by_type = _locate("lma_term_loan_clean.docx", DOCX_MIME)
    assert by_type["notional_amount"].normalized_value["amount"] == 25_000_000
    assert all(c.bbox is None for c in by_type.values())


def test_scanned_image_entities_have_boxes():
    pytest.importorskip("easyocr")
    by_type = _locate("isda_irs_scanned.png", "image/png")
    notional = by_type["notional_amount"]
    assert notional.bbox and notional.bbox[0]["page"] == 1
    assert 0 <= notional.bbox[0]["x0"] < notional.bbox[0]["x1"] <= 1


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def _upload(client, headers, name, mime):
    def run(doc_id):
        extract_document.apply(args=(doc_id,))
        validate_document.apply(args=(doc_id,))

    with patch("app.workers.tasks.enqueue_processing", side_effect=run):
        r = client.post("/api/v1/documents", headers=headers, files={"file": (name, (SAMPLES / name).read_bytes(), mime)}, data={"rule_pack_key": "isda"})
    assert r.status_code == 202, r.text
    return r.json()["id"]


def test_pages_and_png_endpoints_respect_role_guards(client):
    owner = register_and_login(client, "owner@example.com")
    other = register_and_login(client, "other@example.com")
    doc_id = _upload(client, owner, "isda_irs_faulty.pdf", "application/pdf")

    info = client.get(f"/api/v1/documents/{doc_id}/pages", headers=owner).json()
    assert info["renderable"] is True and info["render_source"] == "pdf" and info["page_count"] == 1
    assert info["pages"][0]["width"] > 0

    r = client.get(f"/api/v1/documents/{doc_id}/pages/1.png", headers=owner, params={"dpi": 72})
    assert r.status_code == 200 and r.headers["content-type"] == "image/png" and r.content[:8] == b"\x89PNG\r\n\x1a\n"
    assert client.get(f"/api/v1/documents/{doc_id}/pages/2.png", headers=owner).status_code == 404

    # Another analyst cannot see pages (404, not 403, to avoid id enumeration) and anon gets 401.
    assert client.get(f"/api/v1/documents/{doc_id}/pages", headers=other).status_code == 404
    assert client.get(f"/api/v1/documents/{doc_id}/pages/1.png", headers=other).status_code == 404
    assert client.get(f"/api/v1/documents/{doc_id}/pages/1.png").status_code == 401

    # Provenance is exposed on entities and inside flag evidence.
    entities = client.get(f"/api/v1/documents/{doc_id}/entities", headers=owner).json()
    notional = next(e for e in entities if e["entity_type"] == "notional_amount")
    assert notional["bbox"][0]["page"] == 1
    flags = client.get(f"/api/v1/documents/{doc_id}/flags", headers=owner).json()
    libor = next(f for f in flags if f["rule_id"] == "isda.benchmark.discontinued")
    assert libor["evidence"]["entity"]["bbox"][0]["x1"] <= 1

    # Rendering is audited once per document view.
    trail = client.get("/api/v1/audit", headers=owner, params={"event_type": "document.rendered", "document_id": doc_id}).json()
    assert trail["total"] == 1


def test_docx_reports_not_renderable_with_a_reason(client):
    owner = register_and_login(client, "docx@example.com")
    doc_id = _upload(client, owner, "lma_term_loan_clean.docx", DOCX_MIME)
    with patch("app.services.render_service.shutil.which", return_value=None):
        info = client.get(f"/api/v1/documents/{doc_id}/pages", headers=owner).json()
        assert info["renderable"] is False and info["render_source"] is None and "LibreOffice" in info["note"]
        assert client.get(f"/api/v1/documents/{doc_id}/pages/1.png", headers=owner).status_code == 404
