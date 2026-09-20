from app.extraction.ner import extract_by_labels, extract_entities
from app.extraction.text import ExtractedText, PageText
from app.models.enums import Extractor
from tests.conftest import ISDA_SAMPLE_TEXT, LMA_SAMPLE_TEXT


def _doc(text: str, ocr: bool = False, ocr_conf: float | None = None) -> ExtractedText:
    return ExtractedText(pages=[PageText(number=1, text=text, ocr=ocr, ocr_confidence=ocr_conf)])


def _by_type(cands):
    out = {}
    for c in cands:
        out.setdefault(c.entity_type, []).append(c)
    return out


def test_isda_label_extraction():
    found = _by_type(extract_entities(_doc(ISDA_SAMPLE_TEXT), use_ner=False))

    assert found["notional_amount"][0].normalized_value == {"amount": 50_000_000.0, "currency": "USD"}
    assert found["currency"][0].normalized_value == {"currency": "USD"}
    assert found["trade_date"][0].normalized_value["date"] == "2026-03-15"
    assert found["effective_date"][0].normalized_value["date"] == "2026-03-17"
    assert found["maturity_date"][0].normalized_value["date"] == "2031-03-17"
    assert found["governing_law"][0].normalized_value["jurisdiction"] == "England and Wales"
    assert found["settlement_terms"][0].normalized_value["type"] == "cash"
    assert found["payment_frequency"][0].normalized_value["per_year"] == 4
    assert found["day_count"][0].normalized_value["convention"] == "30/360"
    assert found["interest_rate"][0].normalized_value == {"type": "fixed", "rate_pct": 3.75}

    parties = {c.normalized_value["role"]: c.normalized_value["name"] for c in found["counterparty"]}
    assert parties["party_a"] == "Barclays Bank PLC"
    assert parties["party_b"] == "Northwind Industries Ltd"

    assert all(c.extractor == Extractor.regex for cs in found.values() for c in cs)
    assert all(c.confidence >= 0.9 for c in found["notional_amount"])


def test_lma_label_extraction():
    found = _by_type(extract_entities(_doc(LMA_SAMPLE_TEXT), use_ner=False))
    assert found["notional_amount"][0].normalized_value == {"amount": 25_000_000.0, "currency": "GBP"}
    assert found["margin"][0].normalized_value == {"type": "fixed", "rate_pct": 2.25}
    assert found["interest_rate"][0].normalized_value["benchmark"] == "SONIA"
    assert found["maturity_date"][0].normalized_value["date"] == "2031-04-01"
    roles = {c.normalized_value["role"] for c in found["counterparty"]}
    assert {"borrower", "lender", "facility_agent"} <= roles


def test_value_on_next_line_is_picked_up():
    text = "Notional Amount\nEUR 7,500,000\nGoverning Law:\nNew York"
    found = _by_type(extract_by_labels(_doc(text)))
    assert found["notional_amount"][0].normalized_value["amount"] == 7_500_000
    assert found["governing_law"][0].normalized_value["jurisdiction"] == "New York"


def test_unparseable_value_is_kept_with_lower_confidence():
    found = _by_type(extract_by_labels(_doc("Notional Amount: to be agreed")))
    cand = found["notional_amount"][0]
    assert cand.normalized_value is None
    assert cand.raw_text == "to be agreed"
    assert cand.confidence < 0.75


def test_ocr_pages_scale_confidence_down():
    clean = extract_by_labels(_doc("Notional Amount: USD 1,000,000"))[0]
    ocr = extract_by_labels(_doc("Notional Amount: USD 1,000,000", ocr=True, ocr_conf=0.5))[0]
    assert ocr.confidence < clean.confidence


def test_char_offsets_point_at_value():
    text = "Trade Date: 15 March 2026"
    cand = extract_by_labels(_doc(text))[0]
    assert text[cand.char_start:cand.char_end] == "15 March 2026"
