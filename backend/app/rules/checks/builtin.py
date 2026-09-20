"""Built-in check types. Each is small and single-purpose so a rule pack author can compose
them in YAML without touching Python."""

import re
from datetime import date

from app.rules.checks.registry import check, finding
from app.rules.context import Finding, RuleContext
from app.rules.schema import Rule


def _field(rule: Rule) -> str:
    if not rule.field:
        raise ValueError(f"Rule {rule.id} ({rule.check}) requires 'field'")
    return rule.field


@check("presence")
def presence(rule: Rule, ctx: RuleContext) -> list[Finding]:
    """Field must have at least one extracted value."""
    f = _field(rule)
    if ctx.document.of_type(f):
        return []
    return [finding(rule, ctx, evidence={"found": False}, field_label=f.replace("_", " "))]


@check("normalized")
def normalized(rule: Rule, ctx: RuleContext) -> list[Finding]:
    """Field was found but could not be parsed into a structured value."""
    f = _field(rule)
    out = []
    for e in ctx.document.of_type(f):
        if e.normalized_value is None:
            out.append(finding(rule, ctx, entity=e, raw=e.raw_text))
    return out


@check("range")
def range_check(rule: Rule, ctx: RuleContext) -> list[Finding]:
    """Numeric value at `params.path` must be within [min, max]. Optional `params.when`
    ({path, equals}) restricts the rule to matching entities (e.g. only fixed rates)."""
    f = _field(rule)
    path = rule.params.get("path")
    lo, hi = rule.params.get("min"), rule.params.get("max")
    when = rule.params.get("when")
    out = []
    for e in ctx.document.of_type(f):
        if when and e.get(when.get("path")) != when.get("equals"):
            continue
        value = e.get(path)
        if not isinstance(value, (int, float)):
            continue
        if (lo is not None and value < lo) or (hi is not None and value > hi):
            out.append(finding(
                rule, ctx, entity=e,
                evidence={"value": value, "min": lo, "max": hi},
                value=value, min=lo, max=hi, currency=e.get("currency") or "", raw=e.raw_text,
            ))
    return out


@check("allowed_values")
def allowed_values(rule: Rule, ctx: RuleContext) -> list[Finding]:
    f = _field(rule)
    path = rule.params.get("path")
    allowed = rule.params.get("values", [])
    out = []
    for e in ctx.document.of_type(f):
        value = e.get(path)
        if value is None or value in allowed:
            continue
        out.append(finding(rule, ctx, entity=e, evidence={"value": value, "allowed": allowed}, value=value, allowed=", ".join(map(str, allowed)), raw=e.raw_text))
    return out


@check("forbidden_values")
def forbidden_values(rule: Rule, ctx: RuleContext) -> list[Finding]:
    f = _field(rule)
    path = rule.params.get("path")
    forbidden = rule.params.get("values", [])
    out = []
    for e in ctx.document.of_type(f):
        value = e.get(path)
        if value is None or value not in forbidden:
            continue
        out.append(finding(rule, ctx, entity=e, evidence={"value": value, "forbidden": forbidden}, value=value, raw=e.raw_text))
    return out


@check("regex")
def regex(rule: Rule, ctx: RuleContext) -> list[Finding]:
    """Raw text (or `params.path`) must match `params.pattern` (or must not, if negate)."""
    f = _field(rule)
    pattern = re.compile(rule.params["pattern"], re.IGNORECASE)
    negate = bool(rule.params.get("negate", False))
    path = rule.params.get("path")
    out = []
    for e in ctx.document.of_type(f):
        text = e.get(path) if path else e.raw_text
        if not isinstance(text, str):
            continue
        matched = bool(pattern.search(text))
        if matched == negate:
            out.append(finding(rule, ctx, entity=e, evidence={"pattern": pattern.pattern, "matched": matched}, raw=e.raw_text))
    return out


@check("date_order")
def date_order(rule: Rule, ctx: RuleContext) -> list[Finding]:
    """`params.earlier` date must precede `params.later` (equal allowed with allow_equal)."""
    a, b = ctx.document.first(rule.params["earlier"]), ctx.document.first(rule.params["later"])
    if not a or not b:
        return []
    da, db_ = a.get("date"), b.get("date")
    if not da or not db_:
        return []
    d1, d2 = date.fromisoformat(da), date.fromisoformat(db_)
    allow_equal = rule.params.get("allow_equal", False)
    if d1 < d2 or (allow_equal and d1 == d2):
        return []
    return [finding(
        rule, ctx, entity=b,
        evidence={"earlier": {"field": a.entity_type, "date": da}, "later": {"field": b.entity_type, "date": db_}},
        earlier=da, later=db_, earlier_field=a.entity_type.replace("_", " "), later_field=b.entity_type.replace("_", " "),
    )]


@check("tenor_range")
def tenor_range(rule: Rule, ctx: RuleContext) -> list[Finding]:
    """Years between `params.start` and `params.end` must be within [min_years, max_years]."""
    a, b = ctx.document.first(rule.params["start"]), ctx.document.first(rule.params["end"])
    if not a or not b or not a.get("date") or not b.get("date"):
        return []
    years = (date.fromisoformat(b.get("date")) - date.fromisoformat(a.get("date"))).days / 365.25
    lo, hi = rule.params.get("min_years"), rule.params.get("max_years")
    if (lo is not None and years < lo) or (hi is not None and years > hi):
        return [finding(rule, ctx, entity=b, evidence={"years": round(years, 2), "min_years": lo, "max_years": hi}, years=round(years, 1), min=lo, max=hi)]
    return []


@check("min_count")
def min_count(rule: Rule, ctx: RuleContext) -> list[Finding]:
    f = _field(rule)
    n = len(ctx.document.of_type(f))
    need = int(rule.params.get("min", 1))
    if n >= need:
        return []
    return [finding(rule, ctx, evidence={"count": n, "min": need}, count=n, min=need)]


@check("distinct_values")
def distinct_values(rule: Rule, ctx: RuleContext) -> list[Finding]:
    """All entities of the field must have distinct values at `params.path` (e.g. two
    different counterparties)."""
    f = _field(rule)
    path = rule.params.get("path")
    seen: dict = {}
    out = []
    for e in ctx.document.of_type(f):
        v = e.get(path)
        if v is None:
            continue
        if v in seen:
            out.append(finding(rule, ctx, entity=e, evidence={"value": v, "duplicate_of_entity": seen[v].id}, value=e.raw_text, other=seen[v].raw_text))
        else:
            seen[v] = e
    return out


@check("consistency")
def consistency(rule: Rule, ctx: RuleContext) -> list[Finding]:
    """Value at field/path must equal value at `params.other_field`/`params.other_path`."""
    f = _field(rule)
    a = ctx.document.first(f)
    b = ctx.document.first(rule.params["other_field"])
    if not a or not b:
        return []
    va, vb = a.get(rule.params.get("path")), b.get(rule.params.get("other_path"))
    if va is None or vb is None or va == vb:
        return []
    return [finding(rule, ctx, entity=a, evidence={"value": va, "other_field": b.entity_type, "other_value": vb}, value=va, other_value=vb, other_field=b.entity_type.replace("_", " "))]


@check("min_confidence")
def min_confidence(rule: Rule, ctx: RuleContext) -> list[Finding]:
    """Extraction confidence below `params.threshold` for the field (or every field when
    field is null) — a signal that the value should be eyeballed rather than trusted."""
    threshold = float(rule.params.get("threshold", 0.7))
    entities = ctx.document.of_type(rule.field) if rule.field else ctx.document.entities
    out = []
    for e in entities:
        if e.confidence < threshold:
            out.append(finding(rule, ctx, entity=e, evidence={"threshold": threshold}, field_label=e.entity_type.replace("_", " "), confidence=e.confidence, threshold=threshold, raw=e.raw_text))
    return out


@check("text_contains")
def text_contains(rule: Rule, ctx: RuleContext) -> list[Finding]:
    """Whole-document text must (or must not, with negate) contain `params.pattern`."""
    pattern = re.compile(rule.params["pattern"], re.IGNORECASE)
    negate = bool(rule.params.get("negate", False))
    matched = bool(pattern.search(ctx.document.raw_text or ""))
    if matched == negate:
        return [finding(rule, ctx, evidence={"pattern": pattern.pattern, "matched": matched})]
    return []


# ----------------------------------------------------------------------------- cross-document


def _cross_pair(rule: Rule, ctx: RuleContext):
    if ctx.related is None:
        return None, None
    return ctx.document.first(_field(rule)), ctx.related.first(_field(rule))


@check("cross_doc_equal")
def cross_doc_equal(rule: Rule, ctx: RuleContext) -> list[Finding]:
    """Value at path must match the related document's value (numeric tolerance optional)."""
    a, b = _cross_pair(rule, ctx)
    if a is None or b is None:
        return []
    path = rule.params.get("path")
    va, vb = a.get(path), b.get(path)
    if va is None or vb is None:
        return []
    tol = float(rule.params.get("tolerance", 0))
    if isinstance(va, (int, float)) and isinstance(vb, (int, float)):
        if abs(va - vb) <= tol * max(abs(va), abs(vb), 1):
            return []
    elif va == vb:
        return []
    f = finding(
        rule, ctx, entity=a,
        evidence={"value": va, "related_value": vb, "related_document_id": ctx.related.id, "related_entity_id": b.id, "tolerance": tol},
        value=va, related_value=vb, related_raw=b.raw_text, raw=a.raw_text,
    )
    f.source = "cross_doc"
    return [f]


@check("cross_doc_set_equal")
def cross_doc_set_equal(rule: Rule, ctx: RuleContext) -> list[Finding]:
    """Multi-valued field (e.g. counterparties) must contain the same set of values."""
    if ctx.related is None:
        return []
    f_ = _field(rule)
    path = rule.params.get("path")
    sa = {e.get(path) for e in ctx.document.of_type(f_)} - {None}
    sb = {e.get(path) for e in ctx.related.of_type(f_)} - {None}
    if not sa or not sb or sa == sb:
        return []
    f = finding(
        rule, ctx,
        evidence={"values": sorted(map(str, sa)), "related_values": sorted(map(str, sb)), "related_document_id": ctx.related.id},
        only_here=", ".join(sorted(map(str, sa - sb))) or "-", only_related=", ".join(sorted(map(str, sb - sa))) or "-",
    )
    f.source = "cross_doc"
    return [f]


@check("role_conflict")
def role_conflict(rule: Rule, ctx: RuleContext) -> list[Finding]:
    """An entity appearing in a `roles_a` role must not also appear in a `roles_b` role
    (borrower vs lender). Same entity in two compatible roles (lender + agent) is fine."""
    f_ = _field(rule)
    path, role_path = rule.params.get("path"), rule.params.get("role_path", "role")
    roles_a, roles_b = set(rule.params.get("roles_a", [])), set(rule.params.get("roles_b", []))
    group_a = [e for e in ctx.document.of_type(f_) if e.get(role_path) in roles_a and e.get(path) is not None]
    group_b = [e for e in ctx.document.of_type(f_) if e.get(role_path) in roles_b and e.get(path) is not None]
    out = []
    for a in group_a:
        for b in group_b:
            if a.get(path) == b.get(path):
                out.append(finding(
                    rule, ctx, entity=a,
                    evidence={"value": a.get(path), "role_a": a.get(role_path), "role_b": b.get(role_path), "other_entity_id": b.id},
                    value_a=a.raw_text, role_a=a.get(role_path), value_b=b.raw_text, role_b=b.get(role_path),
                ))
    return out
