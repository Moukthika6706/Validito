import pytest

from app.extraction import normalizers as n


@pytest.mark.parametrize(
    "text, amount, currency",
    [
        ("USD 10,000,000", 10_000_000, "USD"),
        ("$10,000,000.00", 10_000_000, "USD"),
        ("EUR 5 million", 5_000_000, "EUR"),
        ("GBP 25m", 25_000_000, "GBP"),
        ("£12.5bn", 12_500_000_000, "GBP"),
        ("25,000,000 GBP", 25_000_000, "GBP"),
        ("10,000,000 (USD)", 10_000_000, "USD"),
        ("JPY 1,500,000,000", 1_500_000_000, "JPY"),
    ],
)
def test_parse_amount(text, amount, currency):
    out = n.parse_amount(text)
    assert out == {"amount": pytest.approx(amount), "currency": currency}


def test_parse_amount_rejects_noise():
    assert n.parse_amount("see schedule") is None
    assert n.parse_amount("2026") is None


@pytest.mark.parametrize(
    "text, iso",
    [
        ("15 March 2026", "2026-03-15"),
        ("March 15, 2026", "2026-03-15"),
        ("15/03/2026", "2026-03-15"),
        ("2026-03-15", "2026-03-15"),
        ("17th March 2031", "2031-03-17"),
        ("1 April 2026 (or the next Business Day)", "2026-04-01"),
    ],
)
def test_parse_date(text, iso):
    assert n.parse_date(text)["date"] == iso


def test_parse_date_tenor():
    out = n.parse_date("5 years from the Effective Date")
    assert out["tenor"] == {"value": 5.0, "unit": "year"}


def test_parse_date_garbage():
    assert n.parse_date("to be agreed") is None


def test_parse_rate_fixed():
    assert n.parse_rate("3.75% per annum") == {"type": "fixed", "rate_pct": 3.75}


@pytest.mark.parametrize(
    "text, bench, bps",
    [
        ("3-month SOFR plus 45 bps", "SOFR", 45),
        ("SONIA + 1.25%", "SONIA", 125),
        ("6M EURIBOR plus 0.75 per cent", "EURIBOR", 75),
        ("SONIA plus Margin", "SONIA", None),
    ],
)
def test_parse_rate_floating(text, bench, bps):
    out = n.parse_rate(text)
    assert out["type"] == "floating"
    assert out["benchmark"] == bench
    assert out["spread_bps"] == bps


def test_governing_law():
    assert n.normalize_governing_law("English law")["jurisdiction"] == "England and Wales"
    assert n.normalize_governing_law("Laws of the State of New York")["jurisdiction"] == "New York"
    assert n.normalize_governing_law("TBD") is None


def test_party_key_ignores_legal_form_and_case():
    a = n.normalize_party("Barclays Bank PLC")
    b = n.normalize_party("BARCLAYS BANK plc (the \"Lender\")")
    assert a["key"] == b["key"] == "barclays"
    assert a["legal_form"] == "plc"


def test_frequency_and_day_count():
    assert n.normalize_frequency("Quarterly")["per_year"] == 4
    assert n.normalize_frequency("every 6 months")["per_year"] == 2
    assert n.normalize_day_count("Actual/365 (Fixed)")["convention"] == "ACT/365F"
    assert n.normalize_day_count("30/360")["convention"] == "30/360"
