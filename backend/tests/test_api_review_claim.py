"""Reviewer claims: only one reviewer works a document at a time; claims expire."""

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.main import app
from app.models import Document, UserRole
from app.models.base import utcnow
from tests.test_api_documents import register_and_login
from tests.test_api_review_audit import FAULTY, login, make_role_user, upload_inline


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture
def setup(client, db):
    make_role_user(db, "r1@example.com", UserRole.reviewer)
    make_role_user(db, "r2@example.com", UserRole.reviewer)
    make_role_user(db, "adm@example.com", UserRole.admin)
    analyst = register_and_login(client, "ana@example.com")
    doc_id = upload_inline(client, analyst, FAULTY)
    return {"r1": login(client, "r1@example.com"), "r2": login(client, "r2@example.com"), "admin": login(client, "adm@example.com"), "doc": doc_id}


def test_second_reviewer_gets_conflict_until_release(client, setup):
    doc, r1, r2 = setup["doc"], setup["r1"], setup["r2"]

    r = client.post(f"/api/v1/review/documents/{doc}/claim", headers=r1)
    assert r.status_code == 200
    assert r.json()["claimed_by_name"] == "Reviewer" and r.json()["claim_expires_at"]

    r = client.post(f"/api/v1/review/documents/{doc}/claim", headers=r2)
    assert r.status_code == 409
    assert r.json()["detail"]["claimed_by_id"] == client.get("/api/v1/auth/me", headers=r1).json()["id"]

    # Actions by the other reviewer are refused too.
    flag_id = client.get(f"/api/v1/documents/{doc}/flags", headers=r2).json()[0]["id"]
    r = client.post(f"/api/v1/review/flags/{flag_id}/actions", headers=r2, json={"action": "accept"})
    assert r.status_code == 409
    r = client.post(f"/api/v1/review/documents/{doc}/complete", headers=r2, json={"outcome": "approved", "resolve_remaining": "reject"})
    assert r.status_code == 409

    # Queue shows who holds it.
    item = client.get("/api/v1/review/queue", headers=r2).json()["items"][0]
    assert item["claimed_by_name"] == "Reviewer"

    # Holder refreshes freely, then releases; the other reviewer can now claim.
    assert client.post(f"/api/v1/review/documents/{doc}/claim", headers=r1).status_code == 200
    assert client.delete(f"/api/v1/review/documents/{doc}/claim", headers=r2).status_code == 409
    assert client.delete(f"/api/v1/review/documents/{doc}/claim", headers=r1).status_code == 200
    assert client.post(f"/api/v1/review/documents/{doc}/claim", headers=r2).status_code == 200


def test_actions_auto_claim_and_completion_releases(client, setup):
    doc, r1, r2 = setup["doc"], setup["r1"], setup["r2"]
    flag_id = client.get(f"/api/v1/documents/{doc}/flags", headers=r1).json()[0]["id"]
    r = client.post(f"/api/v1/review/flags/{flag_id}/actions", headers=r1, json={"action": "reject", "comment": "fp"})
    assert r.status_code == 200
    assert client.get(f"/api/v1/documents/{doc}", headers=r1).json()["claimed_by_name"] == "Reviewer"
    assert client.post(f"/api/v1/review/documents/{doc}/claim", headers=r2).status_code == 409

    r = client.post(f"/api/v1/review/documents/{doc}/complete", headers=r1, json={"outcome": "rejected", "resolve_remaining": "accept"})
    assert r.status_code == 200
    assert r.json()["status"] == "reviewed" and r.json()["claimed_by_id"] is None

    events = client.get("/api/v1/audit", headers=setup["admin"], params={"document_id": doc, "event_type": "review.*"}).json()
    types = [e["event_type"] for e in events["items"]]
    assert "review.claimed" in types and "review.released" in types


def test_expired_claim_can_be_taken_over(client, setup, db):
    doc, r1, r2 = setup["doc"], setup["r1"], setup["r2"]
    assert client.post(f"/api/v1/review/documents/{doc}/claim", headers=r1).status_code == 200
    assert client.post(f"/api/v1/review/documents/{doc}/claim", headers=r2).status_code == 409

    # Age the claim past the TTL.
    row = db.get(Document, doc)
    row.claimed_at = utcnow() - timedelta(minutes=get_settings().review_claim_ttl_minutes + 1)
    db.commit()

    r = client.post(f"/api/v1/review/documents/{doc}/claim", headers=r2)
    assert r.status_code == 200
    assert r.json()["claimed_by_name"] == "Reviewer"
    assert client.post(f"/api/v1/review/documents/{doc}/claim", headers=r1).status_code == 409


def test_admin_can_release_anyones_claim(client, setup):
    doc, r1, admin = setup["doc"], setup["r1"], setup["admin"]
    assert client.post(f"/api/v1/review/documents/{doc}/claim", headers=r1).status_code == 200
    assert client.delete(f"/api/v1/review/documents/{doc}/claim", headers=admin).status_code == 200
    assert client.get(f"/api/v1/documents/{doc}", headers=admin).json()["claimed_by_id"] is None
