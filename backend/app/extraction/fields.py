"""Field specifications: which entity types we extract, the labels that introduce them in a
term sheet, and how to normalize their values. Adding a new field is one entry here."""

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from app.extraction import normalizers as n

Normalizer = Callable[[str], dict[str, Any] | None]


@dataclass(frozen=True)
class FieldSpec:
    entity_type: str
    labels: tuple[str, ...]  # regex fragments, matched case-insensitively at line start
    normalizer: Normalizer
    multi: bool = False  # keep every match (e.g. all counterparties) instead of the best
    spacy_labels: frozenset[str] = frozenset()  # NER labels used as a fallback
    context_keywords: tuple[str, ...] = ()  # words near a NER hit that support the fallback
    role_from_label: bool = False  # record which label matched (party_a / borrower / ...)
    description: str = ""


FIELD_SPECS: tuple[FieldSpec, ...] = (
    FieldSpec(
        "notional_amount",
        (
            r"notional(?:\s+amount)?", r"facility\s+amount", r"principal(?:\s+amount)?",
            r"aggregate\s+principal(?:\s+amount)?", r"total\s+commitments?", r"commitment(?:\s+amount)?",
            r"loan\s+amount", r"amount", r"tranche\s+[a-z0-9]+\s+amount",
        ),
        n.parse_amount,
        spacy_labels=frozenset({"MONEY"}),
        context_keywords=("notional", "facility", "principal", "commitment", "amount"),
        description="Notional / facility / principal amount",
    ),
    FieldSpec(
        "currency",
        (r"currency", r"settlement\s+currency", r"facility\s+currency", r"denomination"),
        n.parse_currency,
        description="Contract currency",
    ),
    FieldSpec(
        "trade_date",
        (r"trade\s+date", r"pricing\s+date", r"date\s+of\s+(?:this\s+)?(?:term\s+sheet|agreement)"),
        n.parse_date,
        description="Trade / pricing date",
    ),
    FieldSpec(
        "effective_date",
        (r"effective\s+date", r"start\s+date", r"commencement\s+date", r"utilisation\s+date", r"drawdown\s+date", r"closing\s+date", r"signing\s+date"),
        n.parse_date,
        description="Effective / start date",
    ),
    FieldSpec(
        "maturity_date",
        (
            r"maturity(?:\s+date)?", r"final\s+maturity(?:\s+date)?", r"termination\s+date",
            r"scheduled\s+termination\s+date", r"expiry(?:\s+date)?", r"expiration\s+date",
            r"tenor", r"term(?:\s+of\s+(?:the\s+)?(?:facility|loan|transaction))?",
        ),
        n.parse_date,
        spacy_labels=frozenset({"DATE"}),
        context_keywords=("matur", "terminat", "expir", "tenor"),
        description="Maturity / termination date or tenor",
    ),
    FieldSpec(
        "counterparty",
        (
            r"party\s+a", r"party\s+b", r"counterparty", r"borrower", r"lender", r"lenders",
            r"arranger", r"mandated\s+lead\s+arranger", r"agent", r"facility\s+agent", r"buyer", r"seller",
            r"fixed\s+(?:rate\s+)?payer", r"floating\s+(?:rate\s+)?payer", r"issuer", r"guarantor",
            r"obligor", r"dealer", r"client",
        ),
        n.normalize_party,
        multi=True,
        spacy_labels=frozenset({"ORG"}),
        context_keywords=("party", "borrower", "lender", "counterparty", "bank"),
        role_from_label=True,
        description="Contracting parties",
    ),
    FieldSpec(
        "interest_rate",
        (
            r"interest\s+rate", r"fixed\s+rate", r"floating\s+rate", r"floating\s+rate\s+option",
            r"coupon", r"rate\s+of\s+interest", r"all-?in\s+rate", r"reference\s+rate", r"benchmark",
        ),
        n.parse_rate,
        description="Interest rate / coupon",
    ),
    FieldSpec(
        "margin",
        (r"margin", r"spread", r"applicable\s+margin"),
        n.parse_rate,
        description="Margin / spread over benchmark",
    ),
    FieldSpec(
        "governing_law",
        (r"governing\s+law", r"applicable\s+law", r"law", r"jurisdiction"),
        n.normalize_governing_law,
        spacy_labels=frozenset({"GPE", "LAW"}),
        context_keywords=("law", "govern", "jurisdiction"),
        description="Governing law",
    ),
    FieldSpec(
        "settlement_terms",
        (r"settlement(?:\s+(?:terms|method|type))?", r"settlement\s+basis"),
        n.normalize_settlement,
        description="Settlement terms",
    ),
    FieldSpec(
        "payment_frequency",
        (r"payment\s+frequency", r"payment\s+dates?", r"interest\s+period", r"interest\s+payment\s+dates?", r"frequency", r"interest\s+periods?"),
        n.normalize_frequency,
        description="Payment frequency",
    ),
    FieldSpec(
        "day_count",
        (r"day\s+count(?:\s+(?:fraction|convention|basis))?", r"fixed\s+rate\s+day\s+count\s+fraction", r"floating\s+rate\s+day\s+count\s+fraction"),
        n.normalize_day_count,
        description="Day count convention",
    ),
    FieldSpec(
        "business_day_convention",
        (r"business\s+day\s+convention", r"business\s+days?"),
        n.normalize_text,
        description="Business day convention",
    ),
    FieldSpec(
        "calculation_agent",
        (r"calculation\s+agent",),
        n.normalize_party,
        description="Calculation agent",
    ),
    FieldSpec(
        "credit_support",
        (r"credit\s+support(?:\s+annex)?", r"collateral", r"security", r"csa", r"guarantee"),
        n.normalize_text,
        description="Credit support / collateral / security",
    ),
    FieldSpec(
        "product_type",
        (r"product(?:\s+type)?", r"transaction\s+type", r"instrument", r"facility\s+type", r"type\s+of\s+facility", r"facility", r"trade\s+type"),
        n.normalize_text,
        description="Product / facility type",
    ),
    FieldSpec(
        "purpose",
        (r"purpose", r"use\s+of\s+proceeds"),
        n.normalize_text,
        description="Purpose / use of proceeds",
    ),
    FieldSpec(
        "repayment_terms",
        (r"repayment(?:\s+terms)?", r"amorti[sz]ation", r"repayment\s+schedule", r"prepayment"),
        n.normalize_text,
        description="Repayment / amortisation",
    ),
    FieldSpec(
        "fees",
        (r"(?:upfront|arrangement|commitment|agency|participation|underwriting)\s+fee", r"fees?"),
        n.parse_rate,
        multi=True,
        description="Fees",
    ),
    FieldSpec(
        "documentation",
        (r"documentation", r"master\s+agreement", r"agreement\s+form", r"form\s+of\s+agreement"),
        n.normalize_text,
        description="Governing documentation (e.g. ISDA Master, LMA facility agreement)",
    ),
)

FIELD_SPECS_BY_TYPE: dict[str, FieldSpec] = {s.entity_type: s for s in FIELD_SPECS}
ENTITY_TYPES: tuple[str, ...] = tuple(s.entity_type for s in FIELD_SPECS)
