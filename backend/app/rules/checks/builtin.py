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
    a = ctx.document.first_with(f, rule.params.get("path"))
    b = ctx.document.first_with(rule.params["other_field"], rule.params.get("other_path"))
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
    path = rule.params.get("path")
    return ctx.document.first_with(_field(rule), path), ctx.related.first_with(_field(rule), path)


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


# ----------------------------------------------------------------------------- Feature 5 checks


def _scalar_key(e):
    """Comparable summary of an entity's normalised value (None when unparsed)."""
    nv = e.normalized_value or {}
    if not nv:
        return None
    if "amount" in nv:
        return ("amount", round(float(nv["amount"]), 2), nv.get("currency"))
    if "date" in nv:
        return ("date", nv["date"])
    if "tenor" in nv:
        return ("tenor", nv["tenor"].get("value"), nv["tenor"].get("unit"))
    if nv.get("type") in ("fixed", "floating", "spread"):
        return ("rate", nv.get("type"), nv.get("rate_pct"), nv.get("benchmark"), nv.get("spread_bps"))
    if "jurisdiction" in nv:
        return ("law", nv["jurisdiction"])
    if "key" in nv:
        return ("party", nv["key"])
    if "pair" in nv and "rate" not in nv:
        return ("pair", nv["pair"])
    if "rate" in nv:
        return ("fx", round(float(nv["rate"]), 6))
    if "convention" in nv:
        return ("dc", nv["convention"])
    if "frequency" in nv:
        return ("freq", nv.get("per_year"))
    if "currency" in nv and len(nv) == 1:
        return ("ccy", nv["currency"])
    if "type" in nv:
        return ("type", nv["type"])
    if "text" in nv:
        return ("text", re.sub(r"\s+", " ", str(nv["text"])).strip().lower())
    return ("raw", str(sorted(nv.items())))


def _field_key(doc, entity_type):
    """Set of scalar keys for a field (multi-valued fields like counterparty compare as sets)."""
    keys = {_scalar_key(e) for e in doc.of_type(entity_type)}
    keys.discard(None)
    return frozenset(keys)


def _display(doc, entity_type) -> str:
    items = doc.of_type(entity_type)
    return "; ".join(sorted(e.raw_text for e in items)) if items else "—"


@check("amendment_changes")
def amendment_changes(rule: Rule, ctx: RuleContext) -> list[Finding]:
    """Compare fields with the document this one amends.

    params.mode = 'undeclared' (default): flag fields whose value changed but were not listed
    in the amendment's declared `amended_fields`; 'declared_unchanged': flag declared fields
    that did not actually change. params.fields limits the comparison (default: every field
    present in both documents); params.exclude_fields removes some.
    """
    base = ctx.amendment_of
    if base is None:
        return []
    mode = rule.params.get("mode", "undeclared")
    declared = set(ctx.declared_amendments or [])
    fields = rule.params.get("fields")
    if not fields:
        fields = sorted({e.entity_type for e in ctx.document.entities} & {e.entity_type for e in base.entities})
    fields = [f for f in fields if f not in set(rule.params.get("exclude_fields", []))]
    out = []
    for f_ in fields:
        new_key, old_key = _field_key(ctx.document, f_), _field_key(base, f_)
        if not new_key or not old_key:
            continue  # cannot compare unparsed / absent values
        changed = new_key != old_key
        if mode == "undeclared" and changed and f_ not in declared:
            entity = ctx.document.first(f_)
            fd = finding(
                rule, ctx, entity=entity,
                evidence={"field": f_, "value": _display(ctx.document, f_), "related_value": _display(base, f_),
                          "related_document_id": base.id, "declared_amendments": sorted(declared), "declared": False},
                field_label=f_.replace("_", " "), value=_display(ctx.document, f_), related_value=_display(base, f_),
            )
            fd.source = "cross_doc"
            out.append(fd)
        elif mode == "declared_unchanged" and not changed and f_ in declared:
            entity = ctx.document.first(f_)
            fd = finding(
                rule, ctx, entity=entity,
                evidence={"field": f_, "value": _display(ctx.document, f_), "related_value": _display(base, f_),
                          "related_document_id": base.id, "declared": True},
                field_label=f_.replace("_", " "), value=_display(ctx.document, f_),
            )
            fd.source = "cross_doc"
            out.append(fd)
    return out


@check("relative_difference")
def relative_difference(rule: Rule, ctx: RuleContext) -> list[Finding]:
    """|a - b| / |b| must not exceed params.max_pct (a = field/path, b = other_field/other_path)."""
    f_ = _field(rule)
    a = ctx.document.first_with(f_, rule.params.get("path"))
    b = ctx.document.first_with(rule.params["other_field"], rule.params.get("other_path"))
    if not a or not b:
        return []
    va, vb = a.get(rule.params.get("path")), b.get(rule.params.get("other_path"))
    if not isinstance(va, (int, float)) or not isinstance(vb, (int, float)) or vb == 0:
        return []
    pct = abs(va - vb) / abs(vb) * 100
    limit = float(rule.params.get("max_pct", 10))
    if pct <= limit:
        return []
    return [finding(rule, ctx, entity=a, evidence={"value": va, "other_value": vb, "difference_pct": round(pct, 3), "max_pct": limit},
                    value=va, other_value=vb, pct=round(pct, 2), max=limit, other_field=rule.params["other_field"].replace("_", " "))]


@check("conditional_presence")
def conditional_presence(rule: Rule, ctx: RuleContext) -> list[Finding]:
    """When params.when_field/when_path equals params.equals, params.require_field must be present."""
    trigger = ctx.document.first_with(rule.params["when_field"], rule.params.get("when_path"))
    if trigger is None or trigger.get(rule.params.get("when_path")) != rule.params.get("equals"):
        return []
    required = rule.params["require_field"]
    if ctx.document.of_type(required):
        return []
    return [finding(rule, ctx, entity=trigger, evidence={"condition": {"field": rule.params["when_field"], "equals": rule.params.get("equals")}, "missing": required},
                    field_label=required.replace("_", " "), condition_value=trigger.raw_text)]


@check("value_in_other")
def value_in_other(rule: Rule, ctx: RuleContext) -> list[Finding]:
    """Value at field/path must equal one of the values at other_field/other_paths."""
    f_ = _field(rule)
    a = ctx.document.first_with(f_, rule.params.get("path"))
    b = ctx.document.first(rule.params["other_field"])
    if not a or not b:
        return []
    va = a.get(rule.params.get("path"))
    allowed = [b.get(p) for p in rule.params.get("other_paths", [])]
    allowed = [x for x in allowed if x is not None]
    if va is None or not allowed or va in allowed:
        return []
    return [finding(rule, ctx, entity=a, evidence={"value": va, "allowed": allowed, "other_field": rule.params["other_field"]},
                    value=va, allowed=", ".join(map(str, allowed)), other_field=rule.params["other_field"].replace("_", " "))]
