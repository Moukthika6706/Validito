"""Turn raw clause strings into structured values.

Every normalizer returns a dict (stored as `extracted_entities.normalized_value`) or None
when the text could not be interpreted. The raw text is always kept alongside, so a failed
normalization is itself evidence a rule can flag.
"""

import re
from datetime import datetime
from typing import Any

from dateutil import parser as dateparser

CURRENCY_SYMBOLS = {"$": "USD", "£": "GBP", "€": "EUR", "¥": "JPY", "₹": "INR", "₣": "CHF"}
ISO_CURRENCIES = {
    "USD", "GBP", "EUR", "JPY", "CHF", "AUD", "CAD", "NZD", "SEK", "NOK", "DKK", "HKD",
    "SGD", "CNY", "CNH", "INR", "ZAR", "BRL", "MXN", "KRW", "TRY", "PLN", "CZK", "HUF", "AED", "SAR",
}
MULTIPLIERS = {
    "k": 1e3, "thousand": 1e3,
    "m": 1e6, "mm": 1e6, "mn": 1e6, "mio": 1e6, "million": 1e6, "millions": 1e6,
    "bn": 1e9, "b": 1e9, "billion": 1e9, "billions": 1e9,
    "tn": 1e12, "trillion": 1e12,
}

_AMOUNT_RE = re.compile(
    r"""
    (?P<pre>[$£€¥₹]|[A-Z]{3})?\s*
    (?P<num>\d{1,3}(?:[,\s]\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)
    \s*(?P<mult>k|thousand|mm|mn|mio|m|million|millions|bn|b|billion|billions|tn|trillion)?\b
    \s*(?P<post>[$£€¥₹]|[A-Z]{3})?
    """,
    re.IGNORECASE | re.VERBOSE,
)


def parse_amount(text: str) -> dict[str, Any] | None:
    """'USD 10,000,000' / '$10m' / 'EUR 5 million' / '25,000,000 GBP' -> amount + currency."""
    if not text:
        return None
    for m in _AMOUNT_RE.finditer(text):
        num = m.group("num").replace(",", "").replace(" ", "")
        try:
            value = float(num)
        except ValueError:
            continue
        mult = (m.group("mult") or "").lower()
        if mult:
            value *= MULTIPLIERS[mult]
        currency = _currency_code(m.group("pre")) or _currency_code(m.group("post"))
        if currency is None:
            # Look for an ISO code anywhere else in the string (e.g. "10,000,000 (USD)").
            iso = re.search(r"\b(" + "|".join(ISO_CURRENCIES) + r")\b", text.upper())
            currency = iso.group(1) if iso else None
            if currency is None:
                sym = re.search(r"[$£€¥₹]", text)
                currency = CURRENCY_SYMBOLS.get(sym.group(0)) if sym else None
        # Without a currency marker or multiplier, only accept thousands-grouped numbers;
        # a bare "2026" is far more likely a year than an amount.
        grouped = "," in m.group("num") or " " in m.group("num").strip()
        if currency is None and not mult and not grouped:
            continue
        return {"amount": value, "currency": currency}
    return None


def _currency_code(token: str | None) -> str | None:
    if not token:
        return None
    if token in CURRENCY_SYMBOLS:
        return CURRENCY_SYMBOLS[token]
    up = token.upper()
    return up if up in ISO_CURRENCIES else None


def parse_currency(text: str) -> dict[str, Any] | None:
    iso = re.search(r"\b(" + "|".join(ISO_CURRENCIES) + r")\b", text.upper())
    if iso:
        return {"currency": iso.group(1)}
    sym = re.search(r"[$£€¥₹]", text)
    if sym:
        return {"currency": CURRENCY_SYMBOLS[sym.group(0)]}
    names = {"dollar": "USD", "sterling": "GBP", "pound": "GBP", "euro": "EUR", "yen": "JPY"}
    for name, code in names.items():
        if name in text.lower():
            return {"currency": code}
    return None


_TENOR_RE = re.compile(r"(?P<n>\d+(?:\.\d+)?)\s*(?P<unit>year|yr|month|mth|week|day)s?\b", re.IGNORECASE)
_DATE_CLEAN_RE = re.compile(r"\b(on|or|the|of|dated|as|at|being|falling)\b|\(.*?\)", re.IGNORECASE)


def parse_date(text: str, *, dayfirst: bool = True) -> dict[str, Any] | None:
    """Absolute dates -> ISO; tenors like '5 years' -> {'tenor': ..}. UK day-first default."""
    if not text:
        return None
    m = _TENOR_RE.search(text)
    if m and not re.search(r"\b(19|20)\d{2}\b", text):
        unit = m.group("unit").lower().rstrip("s")
        unit = {"yr": "year", "mth": "month"}.get(unit, unit)
        return {"tenor": {"value": float(m.group("n")), "unit": unit}, "raw": text.strip()}

    cleaned = _DATE_CLEAN_RE.sub(" ", text)
    cleaned = re.sub(r"(\d+)(st|nd|rd|th)\b", r"\1", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .,;")
    try:
        parsed = dateparser.parse(cleaned, dayfirst=dayfirst, fuzzy=True, default=_DEFAULT_DATE)
    except (ValueError, OverflowError, TypeError):
        return None
    # dateutil fills missing fields from `default`; a result on the sentinel day means the
    # string had no real day/month/year, so treat it as unparsed.
    if parsed is None or parsed.year < 1990 or parsed.year > 2100:
        return None
    if not re.search(r"\d", cleaned):
        return None
    return {"date": parsed.date().isoformat(), "raw": text.strip()}


_DEFAULT_DATE = datetime(1900, 1, 1)


BENCHMARKS = ["SOFR", "SONIA", "EURIBOR", "ESTR", "€STR", "TONA", "SARON", "LIBOR", "BBSW", "CORRA", "HIBOR"]
_BENCH_RE = re.compile(
    r"(?P<tenor>\d+\s*-?\s*(?:month|m|week|w|day|d)\s*)?(?P<bench>" + "|".join(map(re.escape, BENCHMARKS)) + r")",
    re.IGNORECASE,
)
_PCT_RE = re.compile(r"(?P<n>\d+(?:\.\d+)?)\s*(?:%|per\s*cent|percent|pct)", re.IGNORECASE)
_BPS_RE = re.compile(r"(?P<n>\d+(?:\.\d+)?)\s*(?:bps|bp|basis\s*points?)", re.IGNORECASE)


def parse_rate(text: str) -> dict[str, Any] | None:
    """'3.50% p.a.' -> fixed; 'SOFR + 125 bps' / '3-month EURIBOR plus 1.25%' -> floating."""
    if not text:
        return None
    bench = _BENCH_RE.search(text)
    bps = _BPS_RE.search(text)
    pct = _PCT_RE.search(text)
    if bench:
        spread_bps: float | None = None
        if bps:
            spread_bps = float(bps.group("n"))
        elif pct:
            spread_bps = round(float(pct.group("n")) * 100, 4)
        out: dict[str, Any] = {
            "type": "floating",
            "benchmark": bench.group("bench").upper().replace("€STR", "ESTR"),
            "spread_bps": spread_bps,
        }
        if bench.group("tenor"):
            out["benchmark_tenor"] = re.sub(r"\s+", "", bench.group("tenor")).upper()
        return out
    if pct:
        return {"type": "fixed", "rate_pct": float(pct.group("n"))}
    if bps:
        return {"type": "spread", "spread_bps": float(bps.group("n"))}
    return None


GOVERNING_LAW_ALIASES: dict[str, tuple[str, ...]] = {
    "England and Wales": ("england", "english", "wales", "united kingdom", "uk law", "laws of england"),
    "New York": ("new york", "ny law", "state of new york"),
    "Delaware": ("delaware",),
    "Scotland": ("scotland", "scots law", "scottish"),
    "Ireland": ("ireland", "irish"),
    "Germany": ("germany", "german"),
    "France": ("france", "french"),
    "Netherlands": ("netherlands", "dutch"),
    "Luxembourg": ("luxembourg",),
    "Switzerland": ("switzerland", "swiss"),
    "Singapore": ("singapore",),
    "Hong Kong": ("hong kong",),
    "Japan": ("japan", "japanese"),
    "Australia": ("australia", "new south wales", "victoria"),
    "Cayman Islands": ("cayman",),
    "India": ("india", "indian"),
}


def normalize_governing_law(text: str) -> dict[str, Any] | None:
    if not text:
        return None
    low = text.lower()
    for canonical, aliases in GOVERNING_LAW_ALIASES.items():
        if any(alias in low for alias in aliases):
            return {"jurisdiction": canonical, "raw": text.strip()}
    return None


LEGAL_FORMS = (
    "plc", "ltd", "limited", "llc", "inc", "inc.", "corp", "corporation", "n.a.", "na", "ag", "sa",
    "s.a.", "gmbh", "bv", "b.v.", "nv", "n.v.", "llp", "lp", "pte", "pty", "co", "company", "bank",
    "sarl", "s.à r.l.", "kk", "ab", "oyj", "asa", "spa", "s.p.a.",
)


def normalize_party(text: str) -> dict[str, Any] | None:
    if not text:
        return None
    name = re.sub(r"\s+", " ", text).strip(" .,;:-")
    name = re.sub(r"\((?:the\s+)?[\"']?[A-Za-z ]+[\"']?\)$", "", name).strip(" .,;:-")  # (the "Borrower")
    if not name:
        return None
    tokens = name.replace(",", " ").split()
    legal_form = next((t.lower().strip(".") for t in reversed(tokens) if t.lower() in LEGAL_FORMS), None)
    return {"name": name, "legal_form": legal_form, "key": _party_key(name)}


def _party_key(name: str) -> str:
    """Comparison key: lowercase, strip legal form + punctuation so 'ABC Bank plc' == 'ABC BANK PLC'."""
    words = [w for w in re.sub(r"[^a-z0-9 ]", " ", name.lower()).split() if w not in LEGAL_FORMS]
    return " ".join(words)


def normalize_settlement(text: str) -> dict[str, Any] | None:
    if not text:
        return None
    low = text.lower()
    if "physical" in low:
        return {"type": "physical", "raw": text.strip()}
    if "cash" in low:
        return {"type": "cash", "raw": text.strip()}
    if "net" in low:
        return {"type": "net", "raw": text.strip()}
    return None


FREQUENCIES = {
    "monthly": 12, "quarterly": 4, "semi-annual": 2, "semi annual": 2, "semiannual": 2,
    "half-yearly": 2, "half yearly": 2, "annual": 1, "annually": 1, "yearly": 1, "weekly": 52,
    "daily": 365, "at maturity": 0, "bullet": 0,
}


def normalize_frequency(text: str) -> dict[str, Any] | None:
    if not text:
        return None
    low = text.lower()
    for label, per_year in FREQUENCIES.items():
        if label in low:
            return {"frequency": label.replace(" ", "-"), "per_year": per_year, "raw": text.strip()}
    m = re.search(r"every\s+(\d+)\s*(month|week|year)s?", low)
    if m:
        n, unit = int(m.group(1)), m.group(2)
        per_year = {"month": 12, "week": 52, "year": 1}[unit] / n
        return {"frequency": f"every-{n}-{unit}s", "per_year": per_year, "raw": text.strip()}
    return None


DAY_COUNTS = {
    "ACT/360": ("act/360", "actual/360"),
    "ACT/365F": ("act/365f", "actual/365 (fixed)", "act/365 (fixed)", "actual/365 fixed", "act/365 fixed"),
    "ACT/365": ("act/365", "actual/365"),
    "ACT/ACT": ("act/act", "actual/actual"),
    "30/360": ("30/360", "30e/360", "bond basis"),
    "30E/360": ("30e/360", "eurobond"),
}


def normalize_day_count(text: str) -> dict[str, Any] | None:
    if not text:
        return None
    low = text.lower().replace(" ", "")
    for canonical, aliases in DAY_COUNTS.items():
        if any(alias.replace(" ", "") in low for alias in aliases):
            return {"convention": canonical, "raw": text.strip()}
    return None


def normalize_text(text: str) -> dict[str, Any] | None:
    cleaned = re.sub(r"\s+", " ", text or "").strip()
    return {"text": cleaned} if cleaned else None
