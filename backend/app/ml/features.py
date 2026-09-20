"""Feature engineering for the anomaly detector.

Every feature has a human-readable `describe` so the ML layer can explain *which* values
looked unusual in the same language the rule engine uses. Features are computed from the
same `DocumentView` the rule engine consumes, so both layers see identical inputs.
"""

import math
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date

from app.rules.context import DocumentView

EXPECTED_FIELDS = (
    "notional_amount", "currency", "effective_date", "maturity_date", "counterparty",
    "interest_rate", "governing_law", "settlement_terms", "payment_frequency", "documentation",
)
CURRENCIES = ("USD", "GBP", "EUR")
JURISDICTIONS = ("England and Wales", "New York")


@dataclass(frozen=True)
class FeatureSpec:
    name: str
    label: str
    describe: Callable[[float], str]  # value -> human string
    explainable: bool = True  # include in "largest deviations" narrative


def _money(v: float) -> str:
    amt = 10 ** v if v > 0 else 0
    if amt >= 1e9:
        return f"{amt / 1e9:.1f}bn"
    if amt >= 1e6:
        return f"{amt / 1e6:.1f}m"
    return f"{amt:,.0f}"


FEATURES: tuple[FeatureSpec, ...] = (
    FeatureSpec("log10_notional", "notional amount", _money),
    FeatureSpec("has_notional", "notional present", lambda v: "yes" if v else "no", explainable=False),
    FeatureSpec("tenor_years", "tenor", lambda v: f"{v:.1f} years"),
    FeatureSpec("has_tenor", "tenor present", lambda v: "yes" if v else "no", explainable=False),
    FeatureSpec("rate_pct", "fixed rate / margin", lambda v: f"{v:.2f}%"),
    FeatureSpec("spread_bps", "spread", lambda v: f"{v:.0f} bps"),
    FeatureSpec("is_floating", "floating rate", lambda v: "yes" if v else "no"),
    FeatureSpec("payments_per_year", "payments per year", lambda v: f"{v:.0f}"),
    FeatureSpec("n_parties", "number of parties", lambda v: f"{v:.0f}"),
    FeatureSpec("n_entities", "fields extracted", lambda v: f"{v:.0f}"),
    FeatureSpec("fields_present_ratio", "expected fields present", lambda v: f"{v:.0%}"),
    FeatureSpec("mean_confidence", "mean extraction confidence", lambda v: f"{v:.2f}"),
    FeatureSpec("min_confidence", "lowest extraction confidence", lambda v: f"{v:.2f}"),
    FeatureSpec("unparsed_ratio", "unreadable values", lambda v: f"{v:.0%}"),
    FeatureSpec("ocr_used", "scanned document", lambda v: "yes" if v else "no"),
    *[FeatureSpec(f"ccy_{c}", f"currency is {c}", lambda v: "yes" if v else "no") for c in CURRENCIES],
    FeatureSpec("ccy_other", "currency is other", lambda v: "yes" if v else "no"),
    *[FeatureSpec(f"law_{i}", f"governing law is {j}", lambda v: "yes" if v else "no") for i, j in enumerate(JURISDICTIONS)],
    FeatureSpec("law_other", "governing law is other", lambda v: "yes" if v else "no"),
)
FEATURE_NAMES: tuple[str, ...] = tuple(f.name for f in FEATURES)
FEATURES_BY_NAME: dict[str, FeatureSpec] = {f.name: f for f in FEATURES}


def featurize(doc: DocumentView) -> dict[str, float]:
    f: dict[str, float] = {name: 0.0 for name in FEATURE_NAMES}

    notional = doc.first("notional_amount")
    amount = (notional.get("amount") if notional else None) or 0
    f["has_notional"] = 1.0 if amount > 0 else 0.0
    f["log10_notional"] = math.log10(amount) if amount > 0 else 0.0

    tenor = _tenor_years(doc)
    f["has_tenor"] = 1.0 if tenor is not None else 0.0
    f["tenor_years"] = tenor or 0.0

    fixed = doc.first_with("interest_rate", "rate_pct") or doc.first_with("margin", "rate_pct")
    floating = doc.first_with("interest_rate", "benchmark")
    spread_src = doc.first_with("interest_rate", "spread_bps") or doc.first_with("margin", "spread_bps")
    f["rate_pct"] = float(fixed.get("rate_pct")) if fixed else 0.0
    f["spread_bps"] = float(spread_src.get("spread_bps")) if spread_src else 0.0
    f["is_floating"] = 1.0 if floating else 0.0

    freq = doc.first("payment_frequency")
    f["payments_per_year"] = float((freq.get("per_year") if freq else None) or 0)

    f["n_parties"] = float(len(doc.of_type("counterparty")))
    f["n_entities"] = float(len(doc.entities))
    present = {e.entity_type for e in doc.entities}
    f["fields_present_ratio"] = sum(1 for x in EXPECTED_FIELDS if x in present) / len(EXPECTED_FIELDS)
    confs = [e.confidence for e in doc.entities]
    f["mean_confidence"] = sum(confs) / len(confs) if confs else 0.0
    f["min_confidence"] = min(confs) if confs else 0.0
    f["unparsed_ratio"] = (sum(1 for e in doc.entities if e.normalized_value is None) / len(doc.entities)) if doc.entities else 0.0
    f["ocr_used"] = 1.0 if doc.ocr_used else 0.0

    ccy_ent = doc.first("currency")
    ccy = (ccy_ent.get("currency") if ccy_ent else None) or (notional.get("currency") if notional else None)
    if ccy in CURRENCIES:
        f[f"ccy_{ccy}"] = 1.0
    elif ccy:
        f["ccy_other"] = 1.0

    law = doc.first("governing_law")
    jur = law.get("jurisdiction") if law else None
    if jur in JURISDICTIONS:
        f[f"law_{JURISDICTIONS.index(jur)}"] = 1.0
    elif jur:
        f["law_other"] = 1.0
    return f


def _tenor_years(doc: DocumentView) -> float | None:
    start, end = doc.first("effective_date") or doc.first("trade_date"), doc.first("maturity_date")
    if end is None:
        return None
    tenor = end.get("tenor")
    if tenor:
        unit, value = tenor.get("unit"), float(tenor.get("value", 0))
        return value * {"year": 1, "month": 1 / 12, "week": 1 / 52, "day": 1 / 365}.get(unit, 0)
    if start and start.get("date") and end.get("date"):
        try:
            return (date.fromisoformat(end.get("date")) - date.fromisoformat(start.get("date"))).days / 365.25
        except ValueError:
            return None
    return None


def to_vector(features: dict[str, float]) -> list[float]:
    return [float(features.get(name, 0.0)) for name in FEATURE_NAMES]
