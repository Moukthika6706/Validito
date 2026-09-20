import pytest

from app.rules import DocumentView, EntityView, RuleContext, RulePackConfig, bundled_packs, evaluate
from app.rules.checks import registered_checks
from app.rules.checks.registry import check
from app.rules.schema import Rule


def ev(entity_type, normalized, raw="x", confidence=0.95, id=None):
    return EntityView(id=id, entity_type=entity_type, raw_text=raw, normalized_value=normalized, confidence=confidence)


def clean_isda_doc(**overrides) -> DocumentView:
    entities = {
        "notional_amount": ev("notional_amount", {"amount": 50_000_000.0, "currency": "USD"}, "USD 50,000,000", id=1),
        "currency": ev("currency", {"currency": "USD"}, "USD", id=2),
        "trade_date": ev("trade_date", {"date": "2026-03-15"}, "15 March 2026", id=3),
        "effective_date": ev("effective_date", {"date": "2026-03-17"}, "17 March 2026", id=4),
        "maturity_date": ev("maturity_date", {"date": "2031-03-17"}, "17 March 2031", id=5),
        "party_a": ev("counterparty", {"name": "Barclays Bank PLC", "key": "barclays", "role": "party_a"}, "Barclays Bank PLC", id=6),
        "party_b": ev("counterparty", {"name": "Northwind Industries Ltd", "key": "northwind industries", "role": "party_b"}, "Northwind Industries Ltd", id=7),
        "interest_rate": ev("interest_rate", {"type": "fixed", "rate_pct": 3.75}, "3.75% per annum", id=8),
        "governing_law": ev("governing_law", {"jurisdiction": "England and Wales", "raw": "English law"}, "English law", id=9),
        "settlement_terms": ev("settlement_terms", {"type": "cash", "raw": "Cash settlement"}, "Cash settlement", id=10),
        "documentation": ev("documentation", {"text": "ISDA 2002 Master Agreement"}, "ISDA 2002 Master Agreement", id=11),
    }
    for k, v in overrides.items():
        if v is None:
            entities.pop(k, None)
        else:
            entities[k] = v
    return DocumentView(id=1, doc_type="term_sheet", entities=list(entities.values()))


@pytest.fixture(scope="module")
def isda() -> RulePackConfig:
    return bundled_packs()["isda"]


@pytest.fixture(scope="module")
def lma() -> RulePackConfig:
    return bundled_packs()["lma"]


def test_bundled_packs_load_and_reference_known_checks(isda, lma):
    known = set(registered_checks())
    for pack in (isda, lma):
        for rule in [*pack.rules, *pack.cross_document_rules]:
            assert rule.check in known, f"{rule.id} uses unknown check {rule.check}"


def test_clean_document_has_no_findings(isda):
    result = evaluate(isda, RuleContext(document=clean_isda_doc()))
    assert result.errors == {}
    assert result.findings == []
    assert result.rules_evaluated > 20


def test_missing_governing_law_is_critical(isda):
    result = evaluate(isda, RuleContext(document=clean_isda_doc(governing_law=None)))
    ids = {f.rule_id for f in result.findings}
    assert ids == {"isda.governing_law.present"}
    f = result.findings[0]
    assert f.severity == "critical"
    assert f.confidence == pytest.approx(0.95)
    assert "governing law" in f.explanation.lower()
    assert f.evidence["check"] == "presence"


def test_date_order_and_explanation_rendering(isda):
    doc = clean_isda_doc(maturity_date=ev("maturity_date", {"date": "2025-03-17"}, "17 March 2025", id=5))
    result = evaluate(isda, RuleContext(document=doc))
    by_id = {f.rule_id: f for f in result.findings}
    f = by_id["isda.dates.effective_before_maturity"]
    assert "2025-03-17" in f.explanation and "2026-03-17" in f.explanation
    assert f.entity_id == 5
    assert f.evidence["earlier"]["date"] == "2026-03-17"


def test_range_check_carries_evidence_and_tempers_confidence(isda):
    big = ev("notional_amount", {"amount": 5e9, "currency": "USD"}, "USD 5,000,000,000", confidence=0.6, id=1)
    result = evaluate(isda, RuleContext(document=clean_isda_doc(notional_amount=big)))
    f = next(x for x in result.findings if x.rule_id == "isda.notional.range")
    assert f.evidence["value"] == 5e9
    assert f.evidence["max"] == 2e9
    # base 0.75 * (0.5 + 0.5*0.6) = 0.6
    assert f.confidence == pytest.approx(0.6)


def test_forbidden_benchmark_and_when_clause(isda):
    libor = ev("interest_rate", {"type": "floating", "benchmark": "LIBOR", "spread_bps": 45}, "3M LIBOR + 45bps", id=8)
    result = evaluate(isda, RuleContext(document=clean_isda_doc(interest_rate=libor)))
    ids = {f.rule_id for f in result.findings}
    assert "isda.benchmark.discontinued" in ids
    assert "isda.fixed_rate.range" not in ids  # `when: type == fixed` excludes floating


def test_unnormalized_value_flags_format_rule(isda):
    bad = ev("settlement_terms", None, "To be agreed", confidence=0.67, id=10)
    result = evaluate(isda, RuleContext(document=clean_isda_doc(settlement_terms=bad)))
    ids = {f.rule_id for f in result.findings}
    assert {"isda.settlement.format", "isda.extraction.low_confidence"} <= ids


def test_ocr_document_lowers_confidence(isda):
    doc = clean_isda_doc(governing_law=None)
    doc.ocr_used = True
    f = evaluate(isda, RuleContext(document=doc)).findings[0]
    assert f.confidence == pytest.approx(0.95 * 0.8)


def test_cross_document_rules_only_run_with_related(isda):
    doc = clean_isda_doc()
    related = clean_isda_doc(notional_amount=ev("notional_amount", {"amount": 55_000_000.0, "currency": "USD"}, "USD 55,000,000", id=101))
    related.id = 2

    alone = evaluate(isda, RuleContext(document=doc))
    assert all(r.startswith("isda.xdoc") for r in alone.rules_skipped)

    paired = evaluate(isda, RuleContext(document=doc, related=related))
    f = next(x for x in paired.findings if x.rule_id == "isda.xdoc.notional")
    assert f.source == "cross_doc"
    assert f.evidence["related_value"] == 55_000_000.0
    assert "USD 55,000,000" in f.explanation


def test_lma_pack_on_clean_loan(lma):
    doc = DocumentView(id=1, doc_type="term_sheet", entities=[
        ev("notional_amount", {"amount": 25e6, "currency": "GBP"}, "GBP 25,000,000"),
        ev("currency", {"currency": "GBP"}),
        ev("counterparty", {"name": "Contoso Holdings Limited", "key": "contoso holdings", "role": "borrower"}),
        ev("counterparty", {"name": "Barclays Bank PLC", "key": "barclays", "role": "lender"}),
        ev("effective_date", {"date": "2026-04-01"}),
        ev("maturity_date", {"date": "2031-04-01"}),
        ev("interest_rate", {"type": "floating", "benchmark": "SONIA", "spread_bps": None}),
        ev("margin", {"type": "fixed", "rate_pct": 2.25}),
        ev("governing_law", {"jurisdiction": "England and Wales"}),
        ev("purpose", {"text": "Refinancing"}),
        ev("repayment_terms", {"text": "Bullet"}),
        ev("credit_support", {"text": "Fixed and floating charge"}),
        ev("payment_frequency", {"frequency": "quarterly", "per_year": 4}),
        ev("documentation", {"text": "LMA standard facility agreement"}),
    ])
    result = evaluate(lma, RuleContext(document=doc))
    assert result.errors == {}
    assert result.findings == []


def test_disabled_rule_is_skipped(lma):
    result = evaluate(lma, RuleContext(document=DocumentView(id=1, doc_type="term_sheet")))
    assert "lma.borrower.present" in result.rules_skipped


def test_bad_rule_does_not_abort_run():
    pack = RulePackConfig(key="t", name="t", version="1", rules=[
        Rule(id="t.broken", check="range", field=None, title="x", explanation="x"),  # range requires field
        Rule(id="t.ok", check="presence", field="notional_amount", title="missing", explanation="missing"),
    ])
    result = evaluate(pack, RuleContext(document=DocumentView(id=1, doc_type="term_sheet")))
    assert "t.broken" in result.errors
    assert [f.rule_id for f in result.findings] == ["t.ok"]


def test_custom_check_is_pluggable():
    @check("always_fires_test")
    def always(rule, ctx):
        from app.rules.checks.registry import finding
        return [finding(rule, ctx, evidence={"hello": "world"})]

    pack = RulePackConfig(key="t", name="t", version="1", rules=[
        Rule(id="t.custom", check="always_fires_test", title="custom", explanation="fires {field}")
    ])
    result = evaluate(pack, RuleContext(document=DocumentView(id=1, doc_type="term_sheet")))
    assert result.findings[0].evidence["hello"] == "world"


def test_duplicate_rule_ids_rejected():
    with pytest.raises(ValueError, match="Duplicate"):
        RulePackConfig(key="t", name="t", version="1", rules=[
            Rule(id="t.a", check="presence", field="x", title="a", explanation="a"),
            Rule(id="t.a", check="presence", field="y", title="b", explanation="b"),
        ])
