"""Feature 5: LSTA + FX-forward packs, new fields, amendment links and the new check types."""

from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.extraction import normalizers as n
from app.main import app
from app.rules import DocumentView, EntityView, RuleContext, RulePackConfig, bundled_packs, evaluate
from app.rules.schema import Rule
from app.workers.tasks import extract_document, validate_document
from tests.test_api_documents import register_and_login
from tests.test_rule_engine import clean_isda_doc, ev

SAMPLES = Path(__file__).resolve().parents[2] / "samples"


# ---------------------------------------------------------------- normalisers / fields


@pytest.mark.parametrize("text, base, quote", [("EUR/USD", "EUR", "USD"), ("GBP-USD", "GBP", "USD"), ("USDJPY", "USD", "JPY"), ("Currency pair: usd / inr", "USD", "INR")])
def test_parse_currency_pair(text, base, quote):
    assert n.parse_currency_pair(text) == {"base": base, "quote": quote, "pair": f"{base}/{quote}"}


def test_parse_currency_pair_rejects_noise():
    assert n.parse_currency_pair("USD/USD") is None and n.parse_currency_pair("ABC/XYZ") is None and n.parse_currency_pair("EUR") is None


def test_parse_fx_rate_and_ndf_settlement():
    assert n.parse_fx_rate("1.0850")["rate"] == 1.085
    assert n.parse_fx_rate("EUR/USD 1.08500") == {"rate": 1.085, "raw": "EUR/USD 1.08500", "pair": "EUR/USD"}
    assert n.parse_fx_rate("148.25 JPY per USD")["rate"] == 148.25
    assert n.parse_fx_rate("to be fixed") is None
    assert n.normalize_settlement("Non-deliverable (NDF)")["type"] == "non_deliverable"
    assert n.normalize_settlement("Deliverable")["type"] == "deliverable"


# ---------------------------------------------------------------- pack loading + detection


def test_new_packs_load_with_known_checks_and_amendment_rules():
    from app.rules.checks import registered_checks

    known = set(registered_checks())
    packs = bundled_packs()
    assert {"isda", "lma", "lsta", "fx_forward"} <= set(packs)
    for key in ("lsta", "fx_forward"):
        p = packs[key]
        assert p.rules and p.cross_document_rules and p.amendment_rules and p.applies_to
        assert all(r.check in known for r in [*p.rules, *p.cross_document_rules, *p.amendment_rules])
    assert all(packs[k].amendment_rules for k in ("isda", "lma"))


def test_detection_prefers_explicit_standard(db):
    from app.rules import detect_pack_key, seed_rule_packs

    seed_rule_packs(db)
    db.commit()
    lsta_text = "Borrower: X Inc.\nAdministrative Agent: Y\nFacility: Term Loan B\nDocumentation: LSTA standard credit agreement\nLender commitments"
    lma_text = "Borrower: X Ltd\nLender: Y plc\nFacility Agent: Y plc\nUtilisation Date: 1 April 2026\nDocumentation: LMA standard facility agreement"
    fx_text = "FX Forward\nCurrency Pair: EUR/USD\nForward Rate: 1.0850\nValue Date: 15 September 2026\nSpot Rate: 1.0790\nSettlement: Deliverable\nDocumentation: ISDA 2002 Master Agreement"
    assert detect_pack_key(db, lsta_text, []) == "lsta"
    assert detect_pack_key(db, lma_text, []) == "lma"
    assert detect_pack_key(db, fx_text, []) == "fx_forward"


# ---------------------------------------------------------------- new check types (unit)


def _pack(*rules):
    return RulePackConfig(key="t", name="t", version="1", rules=list(rules))


def test_relative_difference_check():
    rule = Rule(id="t.fwd", check="relative_difference", field="forward_rate", params={"path": "rate", "other_field": "spot_rate", "other_path": "rate", "max_pct": 10},
                title="far", explanation="{value} vs {other_value} {pct}%")
    doc = DocumentView(id=1, doc_type="term_sheet", entities=[ev("forward_rate", {"rate": 93.8}, "93.80"), ev("spot_rate", {"rate": 83.2}, "83.20")])
    [f] = evaluate(_pack(rule), RuleContext(document=doc)).findings
    assert f.evidence["difference_pct"] == pytest.approx(12.74, abs=0.01) and "12.74%" in f.explanation
    doc.entities[0] = ev("forward_rate", {"rate": 84.0}, "84.00")
    assert evaluate(_pack(rule), RuleContext(document=doc)).findings == []


def test_conditional_presence_check():
    rule = Rule(id="t.ndf", check="conditional_presence", params={"when_field": "settlement_terms", "when_path": "type", "equals": "non_deliverable", "require_field": "fixing_date"},
                title="ndf", explanation="{field_label} missing for {condition_value}")
    ndf = DocumentView(id=1, doc_type="term_sheet", entities=[ev("settlement_terms", {"type": "non_deliverable"}, "NDF")])
    [f] = evaluate(_pack(rule), RuleContext(document=ndf)).findings
    assert f.evidence["missing"] == "fixing_date" and "fixing date" in f.explanation
    ndf.entities.append(ev("fixing_date", {"date": "2026-09-13"}, "13 September 2026"))
    assert evaluate(_pack(rule), RuleContext(document=ndf)).findings == []
    deliverable = DocumentView(id=1, doc_type="term_sheet", entities=[ev("settlement_terms", {"type": "deliverable"}, "Deliverable")])
    assert evaluate(_pack(rule), RuleContext(document=deliverable)).findings == []


def test_value_in_other_check():
    rule = Rule(id="t.ccy", check="value_in_other", field="notional_amount", params={"path": "currency", "other_field": "currency_pair", "other_paths": ["base", "quote"]},
                title="ccy", explanation="{value} not in {allowed}")
    doc = DocumentView(id=1, doc_type="term_sheet", entities=[ev("notional_amount", {"amount": 1e7, "currency": "GBP"}, "GBP 10m"), ev("currency_pair", {"base": "USD", "quote": "INR", "pair": "USD/INR"}, "USD/INR")])
    [f] = evaluate(_pack(rule), RuleContext(document=doc)).findings
    assert f.evidence["allowed"] == ["USD", "INR"]
    doc.entities[0] = ev("notional_amount", {"amount": 1e7, "currency": "INR"}, "INR 10m")
    assert evaluate(_pack(rule), RuleContext(document=doc)).findings == []


def test_amendment_changes_check_modes():
    base = clean_isda_doc()
    base.id = 1
    amended = clean_isda_doc(
        interest_rate=ev("interest_rate", {"type": "fixed", "rate_pct": 3.9}, "3.90% per annum", id=8),
        governing_law=ev("governing_law", {"jurisdiction": "New York", "raw": "New York law"}, "New York law", id=9),
    )
    amended.id = 2
    core = Rule(id="t.core", check="amendment_changes", params={"mode": "undeclared", "fields": ["governing_law", "notional_amount"]}, severity="critical", title="core", explanation="{field_label}: {related_value} -> {value}")
    other = Rule(id="t.other", check="amendment_changes", params={"mode": "undeclared", "exclude_fields": ["governing_law", "notional_amount"]}, severity="warning", title="other", explanation="{field_label}")
    unchanged = Rule(id="t.same", check="amendment_changes", params={"mode": "declared_unchanged"}, severity="info", title="same", explanation="{field_label}")
    pack = RulePackConfig(key="t", name="t", version="1", amendment_rules=[core, other, unchanged])

    # Not an amendment: rules are skipped, nothing fires.
    res = evaluate(pack, RuleContext(document=amended))
    assert res.findings == [] and set(res.rules_skipped) == {"t.core", "t.other", "t.same"}

    # Declared: interest_rate (changed) and notional_amount (not actually changed).
    res = evaluate(pack, RuleContext(document=amended, amendment_of=base, declared_amendments=["interest_rate", "notional_amount"]))
    by_id = {}
    for f in res.findings:
        by_id.setdefault(f.rule_id, []).append(f)
    assert [f.evidence["field"] for f in by_id["t.core"]] == ["governing_law"]
    assert by_id["t.core"][0].source == "cross_doc" and by_id["t.core"][0].evidence["related_document_id"] == 1
    assert "England and Wales" in by_id["t.core"][0].evidence["related_value"] or "English law" in by_id["t.core"][0].explanation
    assert "t.other" not in by_id  # the rate change was declared
    assert [f.evidence["field"] for f in by_id["t.same"]] == ["notional_amount"]

    # Undeclared rate change surfaces through the broad rule as a warning.
    res = evaluate(pack, RuleContext(document=amended, amendment_of=base, declared_amendments=[]))
    assert {f.rule_id: f.evidence["field"] for f in res.findings if f.rule_id == "t.other"} == {"t.other": "interest_rate"}


# ---------------------------------------------------------------- integration on the samples


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def _upload(client, headers, name, pack=None, **extra):
    def run(doc_id):
        extract_document.apply(args=(doc_id,))
        validate_document.apply(args=(doc_id,))

    data = {k: v for k, v in {"rule_pack_key": pack, **extra}.items() if v is not None}
    with patch("app.workers.tasks.enqueue_processing", side_effect=run):
        r = client.post("/api/v1/documents", headers=headers, files={"file": (name, (SAMPLES / name).read_bytes(), "application/pdf")}, data=data)
    assert r.status_code == 202, r.text
    return r.json()


def _ids(client, headers, doc_id):
    return {f["rule_id"] for f in client.get(f"/api/v1/documents/{doc_id}/flags", headers=headers).json() if f["severity"] != "info"}


def test_lsta_samples(client):
    h = register_and_login(client, "lsta@example.com")
    clean = _upload(client, h, "lsta_term_loan_b_clean.pdf")  # auto-detected
    detail = client.get(f"/api/v1/documents/{clean['id']}", headers=h).json()
    assert detail["rule_pack_key"] == "lsta" and detail["status"] == "auto_approved"
    types = {e["entity_type"]: e for e in detail["entities"]}
    assert types["commitment_fee"]["normalized_value"]["spread_bps"] == 50
    assert types["margin"]["normalized_value"]["rate_pct"] == 3.5
    assert types["governing_law"]["normalized_value"]["jurisdiction"] == "New York"
    roles = {e["normalized_value"]["role"] for e in detail["entities"] if e["entity_type"] == "counterparty"}
    assert {"borrower", "administrative_agent", "lead_arranger"} <= roles

    faulty = _upload(client, h, "lsta_term_loan_b_faulty.pdf", "lsta")
    assert client.get(f"/api/v1/documents/{faulty['id']}", headers=h).json()["status"] == "needs_review"
    assert {
        "lsta.governing_law.present", "lsta.dates.closing_before_maturity", "lsta.benchmark.discontinued",
        "lsta.margin.range", "lsta.currency.usd", "lsta.commitment_fee.present", "lsta.purpose.present", "lsta.security.present",
    } <= _ids(client, h, faulty["id"])


def test_fx_forward_samples(client):
    h = register_and_login(client, "fx@example.com")
    clean = _upload(client, h, "fx_forward_clean.pdf")
    detail = client.get(f"/api/v1/documents/{clean['id']}", headers=h).json()
    assert detail["rule_pack_key"] == "fx_forward" and detail["status"] == "auto_approved"
    types = {e["entity_type"]: e for e in detail["entities"]}
    assert types["currency_pair"]["normalized_value"]["pair"] == "EUR/USD"
    assert types["forward_rate"]["normalized_value"]["rate"] == 1.085 and types["spot_rate"]["normalized_value"]["rate"] == 1.079
    assert types["value_date"]["normalized_value"]["date"] == "2026-09-15"
    assert types["settlement_terms"]["normalized_value"]["type"] == "deliverable"

    faulty = _upload(client, h, "fx_forward_faulty.pdf", "fx_forward")
    assert client.get(f"/api/v1/documents/{faulty['id']}", headers=h).json()["status"] == "needs_review"
    ids = _ids(client, h, faulty["id"])
    assert {"fx.governing_law.present", "fx.dates.trade_before_value", "fx.notional.currency_in_pair", "fx.forward_vs_spot", "fx.ndf.fixing_date_required"} <= ids
    fx = next(f for f in client.get(f"/api/v1/documents/{faulty['id']}/flags", headers=h).json() if f["rule_id"] == "fx.forward_vs_spot")
    assert fx["evidence"]["difference_pct"] > 10 and "93.8" in fx["explanation"]


def test_amendment_pair_flags_undeclared_change_only(client):
    h = register_and_login(client, "amend@example.com")
    base = _upload(client, h, "isda_irs_clean.pdf", "isda")
    amend = _upload(client, h, "isda_irs_amendment.pdf", "isda", amendment_of_id=base["id"], amended_fields="interest_rate,bogus_field")
    assert amend["amendment_of_id"] == base["id"] and amend["amended_fields"] == ["interest_rate"]  # unknown names dropped

    detail = client.get(f"/api/v1/documents/{amend['id']}", headers=h).json()
    assert detail["status"] == "needs_review"
    flags = client.get(f"/api/v1/documents/{amend['id']}/flags", headers=h).json()
    by_rule = {}
    for f in flags:
        by_rule.setdefault(f["rule_id"], []).append(f)
    [law] = by_rule["isda.amend.core_term_changed"]
    assert law["severity"] == "critical" and law["source"] == "cross_doc"
    assert law["evidence"]["field"] == "governing_law" and law["evidence"]["related_document_id"] == base["id"]
    assert "English law" in law["explanation"] and "New York law" in law["explanation"]
    assert "isda.amend.undeclared_change" not in by_rule  # the declared fixed-rate change is accepted
    assert "isda.amend.declared_unchanged" not in by_rule  # ... and it really changed

    # Re-link via the API declaring governing law too -> re-validate -> no amendment flags remain.
    r = client.put(f"/api/v1/documents/{amend['id']}/amendment", headers=h, json={"amendment_of_id": base["id"], "amended_fields": ["interest_rate", "governing_law"]})
    assert r.status_code == 200 and r.json()["amended_fields"] == ["governing_law", "interest_rate"]
    with patch("app.workers.tasks.enqueue_validation", side_effect=lambda i: validate_document.apply(args=(i,))):
        assert client.post(f"/api/v1/documents/{amend['id']}/validate", headers=h).status_code == 202
    assert not any(f["rule_id"].startswith("isda.amend") and f["status"] == "open" for f in client.get(f"/api/v1/documents/{amend['id']}/flags", headers=h).json())
    assert client.get(f"/api/v1/documents/{amend['id']}", headers=h).json()["status"] == "auto_approved"

    # Linking is audited and cannot point at itself or another user's document.
    assert client.put(f"/api/v1/documents/{amend['id']}/amendment", headers=h, json={"amendment_of_id": amend["id"], "amended_fields": []}).status_code == 422
    other = register_and_login(client, "stranger@example.com")
    assert client.put(f"/api/v1/documents/{amend['id']}/amendment", headers=other, json={"amendment_of_id": base["id"], "amended_fields": []}).status_code == 404
    trail = client.get("/api/v1/audit", headers=h, params={"document_id": amend["id"], "event_type": "document.linked"}).json()
    assert trail["total"] >= 1 and trail["items"][0]["payload"]["kind"] == "amendment"
