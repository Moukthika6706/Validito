"""API flow: analyst uploads a faulty sheet -> pipeline runs inline -> reviewer works the
queue -> audit trail and metrics reflect every step."""

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.core.security import hash_password
from app.main import app
from app.models import User, UserRole
from tests.test_api_documents import pdf_bytes, register_and_login

FAULTY = [
    "Trade Date: 15 March 2026",
    "Effective Date: 17 March 2026",
    "Termination Date: 17 March 2025",
    "Notional Amount: USD 5,000,000,000",
    "Party A: Barclays Bank PLC",
    "Party B: Northwind Industries Ltd",
    "Fixed Rate: 18.5% per annum",
    "Floating Rate Option: 3-month LIBOR plus 45 bps",
    "Settlement: To be agreed",
    "Documentation: ISDA 2002 Master Agreement",
]
CLEAN = [
    "Trade Date: 15 March 2026", "Effective Date: 17 March 2026", "Termination Date: 17 March 2031",
    "Notional Amount: USD 50,000,000", "Party A: Barclays Bank PLC", "Party B: Northwind Industries Ltd",
    "Fixed Rate: 3.75% per annum", "Floating Rate Option: 3-month SOFR plus 45 bps", "Payment Frequency: Quarterly",
    "Settlement: Cash settlement", "Governing Law: English law", "Documentation: ISDA 2002 Master Agreement",
]


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def make_role_user(db, email, role):
    u = User(email=email, password_hash=hash_password("password123"), full_name=role.value.title(), role=role)
    db.add(u)
    db.commit()


def login(client, email):
    r = client.post("/api/v1/auth/login", data={"username": email, "password": "password123"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def upload_inline(client, headers, lines, pack="isda"):
    """Upload and run extraction + validation synchronously (Celery eager chain)."""
    from app.workers.tasks import extract_document, validate_document

    def run(doc_id):
        extract_document.apply(args=(doc_id,))
        validate_document.apply(args=(doc_id,))

    with patch("app.workers.tasks.enqueue_processing", side_effect=run):
        r = client.post("/api/v1/documents", headers=headers, files={"file": ("s.pdf", pdf_bytes(lines), "application/pdf")}, data={"rule_pack_key": pack})
    assert r.status_code == 202, r.text
    return r.json()["id"]


def test_full_review_flow(client, db):
    make_role_user(db, "rev@example.com", UserRole.reviewer)
    make_role_user(db, "adm@example.com", UserRole.admin)
    analyst = register_and_login(client, "ana@example.com")
    reviewer = login(client, "rev@example.com")
    admin = login(client, "adm@example.com")

    faulty_id = upload_inline(client, analyst, FAULTY)
    clean_id = upload_inline(client, analyst, CLEAN)

    # --- routing outcome visible to the analyst
    d = client.get(f"/api/v1/documents/{faulty_id}", headers=analyst).json()
    assert d["status"] == "needs_review" and d["routing_decision"] == "needs_review" and d["open_flag_count"] > 0
    assert client.get(f"/api/v1/documents/{clean_id}", headers=analyst).json()["status"] == "auto_approved"

    # --- flags are fully explained
    flags = client.get(f"/api/v1/documents/{faulty_id}/flags", headers=analyst).json()
    assert flags[0]["severity"] == "critical"  # sorted most severe first
    for f in flags:
        assert f["rule_id"] and f["explanation"] and f["rule_snapshot"] and f["evidence"] and f["confidence_band"] in ("high", "medium", "low")
    libor = next(f for f in flags if f["rule_id"] == "isda.benchmark.discontinued")
    assert libor["entity"]["raw_text"] == "3-month LIBOR plus 45 bps"
    run = client.get(f"/api/v1/validation/runs/{flags[0]['validation_run_id']}", headers=analyst).json()
    assert run["routing_decision"] == "needs_review" and "Decision" in run["summary"]

    # --- analysts cannot review; reviewers can
    assert client.get("/api/v1/review/queue", headers=analyst).status_code == 403
    queue = client.get("/api/v1/review/queue", headers=reviewer).json()
    assert queue["total"] == 1 and queue["items"][0]["document_id"] == faulty_id
    assert queue["items"][0]["max_severity"] == "critical"

    r = client.post(f"/api/v1/review/flags/{libor['id']}/actions", headers=reviewer, json={"action": "accept", "comment": "Confirmed legacy LIBOR reference"})
    assert r.status_code == 200 and r.json()["status"] == "accepted"
    assert r.json()["review_actions"][0]["reviewer"]["email"] == "rev@example.com"

    notional = next(f for f in flags if f["rule_id"] == "isda.notional.range")
    r = client.post(f"/api/v1/review/flags/{notional['id']}/actions", headers=reviewer, json={"action": "override", "override_value": {"amount": 50_000_000, "currency": "USD"}, "comment": "OCR added zeros"})
    assert r.status_code == 200 and r.json()["status"] == "overridden"
    r = client.post(f"/api/v1/review/flags/{notional['id']}/actions", headers=reviewer, json={"action": "override"})
    assert r.status_code == 422

    # completing with open flags requires an explicit resolution
    r = client.post(f"/api/v1/review/documents/{faulty_id}/complete", headers=reviewer, json={"outcome": "rejected"})
    assert r.status_code == 409
    r = client.post(f"/api/v1/review/documents/{faulty_id}/complete", headers=reviewer, json={"outcome": "rejected", "resolve_remaining": "accept", "comment": "Send back to desk"})
    assert r.status_code == 200 and r.json()["status"] == "reviewed" and r.json()["review_outcome"] == "rejected"
    assert client.get("/api/v1/review/queue", headers=reviewer).json()["total"] == 0

    # --- audit trail: every step, scoped, verifiable
    trail = client.get(f"/api/v1/audit/documents/{faulty_id}", headers=analyst).json()
    types = {e["event_type"] for e in trail["items"]}
    assert {"document.uploaded", "extraction.completed", "entity.extracted", "validation.completed", "flag.raised", "routing.decided", "review.action", "document.status_changed"} <= types
    review_events = client.get("/api/v1/audit", headers=reviewer, params={"event_type": "review.*", "document_id": faulty_id}).json()
    assert review_events["total"] >= 3
    assert all(e["actor_name"] == "Reviewer" for e in review_events["items"])
    assert client.get("/api/v1/audit/verify", headers=reviewer).status_code == 403
    assert client.get("/api/v1/audit/verify", headers=admin).json()["ok"] is True
    # an analyst can't read another user's document trail
    other = register_and_login(client, "other@example.com")
    assert client.get(f"/api/v1/audit/documents/{faulty_id}", headers=other).status_code == 404

    # --- metrics
    m = client.get("/api/v1/metrics/summary", headers=admin).json()
    assert m["documents_total"] == 2 and m["decided_total"] == 2
    assert m["auto_approved_total"] == 1 and m["auto_approved_pct"] == 50.0
    assert m["manual_review_reduction_pct"] == 50.0
    assert m["review_actions"]["accept"] >= 1 and m["review_actions"]["override"] == 1
    assert any(r["rule_id"] == "isda.benchmark.discontinued" and r["accepted"] == 1 for r in m["top_rules"])
    assert m["flags_by_source"].get("rule", 0) > 0


def test_rule_pack_admin_flow(client, db):
    make_role_user(db, "adm@example.com", UserRole.admin)
    admin = login(client, "adm@example.com")
    analyst = register_and_login(client, "ana@example.com")

    packs = client.get("/api/v1/rule-packs", headers=analyst).json()
    assert {p["key"] for p in packs} == {"isda", "lma"}  # seeded at startup
    isda = client.get("/api/v1/rule-packs/isda", headers=analyst).json()
    assert isda["rule_count"] > 20 and isda["config"]["routing"]["auto_approve_confidence"] == 0.85
    checks = client.get("/api/v1/rule-packs/checks", headers=analyst).json()
    assert any(c["name"] == "date_order" for c in checks)

    # analysts cannot edit
    r = client.patch("/api/v1/rule-packs/isda/rules/isda.notional.range", headers=analyst, json={"severity": "error"})
    assert r.status_code == 403

    # admin edit cuts a new version and it becomes active
    r = client.patch("/api/v1/rule-packs/isda/rules/isda.notional.range", headers=admin, json={"severity": "error", "params": {"path": "amount", "min": 100000, "max": 1000000000}})
    assert r.status_code == 200, r.text
    assert r.json()["version"] == "1.0.1" and r.json()["is_active"]
    rule = next(x for x in r.json()["config"]["rules"] if x["id"] == "isda.notional.range")
    assert rule["severity"] == "error" and rule["params"]["max"] == 1000000000

    versions = client.get("/api/v1/rule-packs", headers=admin, params={"include_inactive": True}).json()
    isda_versions = [p for p in versions if p["key"] == "isda"]
    assert {p["version"] for p in isda_versions} == {"1.0.0", "1.0.1"}
    old = next(p for p in isda_versions if p["version"] == "1.0.0")
    r = client.post(f"/api/v1/rule-packs/versions/{old['id']}/activate", headers=admin)
    assert r.json()["version"] == "1.0.0" and r.json()["is_active"]

    # invalid config rejected
    r = client.post("/api/v1/rule-packs", headers=admin, json={"config": {"key": "x", "name": "x", "version": "1", "rules": [{"id": "bad id", "check": "presence", "title": "t", "explanation": "e"}]}})
    assert r.status_code == 422

    audit = client.get("/api/v1/audit", headers=admin, params={"event_type": "rule_pack.*"}).json()
    assert audit["total"] >= 3


def test_user_admin(client, db):
    make_role_user(db, "adm@example.com", UserRole.admin)
    admin = login(client, "adm@example.com")
    register_and_login(client, "ana@example.com")
    users = client.get("/api/v1/users", headers=admin).json()
    ana = next(u for u in users if u["email"] == "ana@example.com")
    r = client.patch(f"/api/v1/users/{ana['id']}", headers=admin, json={"role": "reviewer"})
    assert r.json()["role"] == "reviewer"
    me = next(u for u in users if u["email"] == "adm@example.com")
    assert client.patch(f"/api/v1/users/{me['id']}", headers=admin, json={"role": "analyst"}).status_code == 409
