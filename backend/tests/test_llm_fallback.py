"""Feature 6: LLM-assisted extraction fallback. The Anthropic client is mocked; no network."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.extraction.llm_fallback import LLMField, LLMProposal, missing_required_fields, propose_missing_fields
from app.extraction.text import ExtractedText, PageText
from app.main import app
from app.workers.tasks import extract_document, validate_document
from tests.test_api_documents import pdf_bytes, register_and_login

# No "Settlement:" label and no "Governing Law:" label, so both are missing after label/NER.
UNLABELLED = [
    "Trade Date: 15 March 2026",
    "Effective Date: 17 March 2026",
    "Termination Date: 17 March 2031",
    "Notional Amount: USD 50,000,000",
    "Party A: Barclays Bank PLC",
    "Party B: Northwind Industries Ltd",
    "Fixed Rate: 3.75% per annum",
    "Floating Rate Option: 3-month SOFR plus 45 bps",
    "Payment Frequency: Quarterly",
    "Documentation: ISDA 2002 Master Agreement",
    "Each payment shall be settled in cash on the relevant payment date.",
]


def _response(fields, stop_reason="end_turn"):
    return SimpleNamespace(parsed_output=LLMProposal(fields=[LLMField(**f) for f in fields]), stop_reason=stop_reason)


@pytest.fixture
def llm_on(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "llm_fallback_enabled", True)
    monkeypatch.setattr(s, "anthropic_api_key", "sk-ant-test")
    return s


@pytest.fixture
def anthropic_mock(monkeypatch):
    """Patch anthropic.Anthropic so .messages.parse returns what the test sets."""
    import anthropic

    client = MagicMock()
    monkeypatch.setattr(anthropic, "Anthropic", MagicMock(return_value=client))
    return client


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def _upload(client, headers, lines):
    def run(doc_id):
        extract_document.apply(args=(doc_id,))
        validate_document.apply(args=(doc_id,))

    with patch("app.workers.tasks.enqueue_processing", side_effect=run):
        r = client.post("/api/v1/documents", headers=headers, files={"file": ("s.pdf", pdf_bytes(lines), "application/pdf")}, data={"rule_pack_key": "isda"})
    assert r.status_code == 202, r.text
    return r.json()["id"]


def test_disabled_by_default_makes_no_call(anthropic_mock):
    s = get_settings()
    assert s.llm_fallback_enabled is False
    extracted = ExtractedText(pages=[PageText(number=1, text="\n".join(UNLABELLED))])
    result = propose_missing_fields(extracted, ["settlement_terms"])
    assert result.attempted is False and result.candidates == []
    anthropic_mock.messages.parse.assert_not_called()


def test_missing_required_fields_only_lists_known_gaps():
    assert missing_required_fields({"notional_amount", "maturity_date"}) == ["effective_date", "counterparty", "interest_rate", "governing_law", "settlement_terms"]
    assert missing_required_fields(set(), ["settlement_terms", "not_a_field"]) == ["settlement_terms"]


def test_proposals_are_verified_normalised_and_low_confidence(llm_on, anthropic_mock):
    anthropic_mock.messages.parse.return_value = _response([
        {"field": "settlement_terms", "value": "settled in cash", "quote": "Each payment shall be settled in cash on the relevant payment date."},
        {"field": "governing_law", "value": "English law", "quote": None},  # NOT in the text -> discarded
        {"field": "notional_amount", "value": "USD 50,000,000", "quote": None},  # not requested -> discarded
    ])
    extracted = ExtractedText(pages=[PageText(number=1, text="\n".join(UNLABELLED))])
    result = propose_missing_fields(extracted, ["settlement_terms", "governing_law"])

    assert result.attempted and result.model == llm_on.llm_model
    assert result.accepted == ["settlement_terms"]
    assert result.discarded == {"governing_law": "value not present verbatim in document text", "notional_amount": "not a requested field"}
    cand = result.candidates[0]
    assert cand.extractor.value == "llm" and cand.confidence == llm_on.llm_confidence == 0.45
    assert cand.normalized_value == {"type": "cash", "raw": "settled in cash"}
    assert extracted.text[cand.char_start:cand.char_end] == "settled in cash" and cand.page == 1
    # Only the minimal text goes out, with a strict schema, on the configured model.
    kwargs = anthropic_mock.messages.parse.call_args.kwargs
    assert kwargs["model"] == llm_on.llm_model and kwargs["output_format"] is LLMProposal
    assert "settlement_terms" in kwargs["messages"][0]["content"] and "notional_amount: " not in kwargs["messages"][0]["content"]
    # Audit payload never carries text or secrets.
    payload = result.audit_payload()
    assert payload["accepted_fields"] == ["settlement_terms"] and "settled in cash" not in str(payload) and "sk-ant" not in str(payload)


def test_api_errors_and_refusals_fail_gracefully(llm_on, anthropic_mock):
    import anthropic

    extracted = ExtractedText(pages=[PageText(number=1, text="\n".join(UNLABELLED))])
    anthropic_mock.messages.parse.side_effect = anthropic.APIConnectionError(request=MagicMock())
    r = propose_missing_fields(extracted, ["settlement_terms"])
    assert r.attempted and r.candidates == [] and r.error == "APIConnectionError"

    anthropic_mock.messages.parse.side_effect = None
    anthropic_mock.messages.parse.return_value = _response([], stop_reason="refusal")
    r = propose_missing_fields(extracted, ["settlement_terms"])
    assert r.candidates == [] and r.error == "refusal"


def test_end_to_end_marks_entity_and_routes_to_review(client, llm_on, anthropic_mock):
    anthropic_mock.messages.parse.return_value = _response([
        {"field": "settlement_terms", "value": "settled in cash", "quote": None},
        {"field": "governing_law", "value": "laws of Narnia", "quote": None},
    ])
    headers = register_and_login(client, "llm@example.com")
    doc_id = _upload(client, headers, UNLABELLED)

    detail = client.get(f"/api/v1/documents/{doc_id}", headers=headers).json()
    settlement = next(e for e in detail["entities"] if e["entity_type"] == "settlement_terms")
    assert settlement["extractor"] == "llm" and settlement["confidence"] == 0.45
    assert settlement["bbox"] and settlement["bbox"][0]["page"] == 1  # provenance still located on the page
    assert not any(e["entity_type"] == "governing_law" and e["extractor"] == "llm" for e in detail["entities"])

    # The AI-proposed field produces an explicit, explainable warning that routes to review.
    assert detail["status"] == "needs_review"
    flags = client.get(f"/api/v1/documents/{doc_id}/flags", headers=headers).json()
    llm_flag = next(f for f in flags if f["rule_id"] == "extraction.llm_proposed")
    assert llm_flag["source"] == "ml" and llm_flag["confidence"] == 0.45 and llm_flag["confidence_band"] == "low"
    assert llm_flag["entity"]["id"] == settlement["id"] and "settled in cash" in llm_flag["explanation"]
    assert "isda.settlement.present" not in {f["rule_id"] for f in flags}  # the presence rule is satisfied by the proposal

    # Audit: model + field names, no text.
    trail = client.get("/api/v1/audit", headers=headers, params={"document_id": doc_id, "event_type": "extraction.llm_fallback"}).json()
    assert trail["total"] == 1
    p = trail["items"][0]["payload"]
    assert p["model"] == llm_on.llm_model and p["accepted_fields"] == ["settlement_terms"] and "governing_law" in p["discarded"]
    assert "settled in cash" not in str(p)


def test_without_fallback_same_document_is_missing_settlement(client, anthropic_mock):
    headers = register_and_login(client, "nollm@example.com")
    doc_id = _upload(client, headers, UNLABELLED)
    flags = client.get(f"/api/v1/documents/{doc_id}/flags", headers=headers).json()
    assert "isda.settlement.present" in {f["rule_id"] for f in flags}
    anthropic_mock.messages.parse.assert_not_called()
