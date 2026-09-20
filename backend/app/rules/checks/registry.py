"""Check registry: a check is a function `(rule, ctx) -> list[Finding]`. New check types are
added with `@check("name")` and become available to every rule pack immediately."""

from collections.abc import Callable
from typing import Any

from app.rules.context import EntityView, Finding, RuleContext
from app.rules.schema import Rule

CheckFn = Callable[[Rule, RuleContext], list[Finding]]

_REGISTRY: dict[str, CheckFn] = {}


def check(name: str) -> Callable[[CheckFn], CheckFn]:
    def deco(fn: CheckFn) -> CheckFn:
        if name in _REGISTRY:
            raise RuntimeError(f"Check '{name}' already registered")
        _REGISTRY[name] = fn
        fn.check_name = name  # type: ignore[attr-defined]
        return fn

    return deco


def get_check(name: str) -> CheckFn:
    try:
        return _REGISTRY[name]
    except KeyError:
        raise KeyError(f"Unknown check type '{name}'. Registered: {sorted(_REGISTRY)}")


def registered_checks() -> list[str]:
    return sorted(_REGISTRY)


# ----------------------------------------------------------------------------- helpers


def render(template: str, **kwargs: Any) -> str:
    """Format a rule's explanation template, tolerating missing keys."""

    class _Safe(dict):
        def __missing__(self, key):
            return "{" + key + "}"

    try:
        return template.format_map(_Safe(**{k: _fmt(v) for k, v in kwargs.items()}))
    except (ValueError, IndexError):
        return template


def _fmt(v: Any) -> Any:
    if isinstance(v, float):
        return f"{v:,.2f}".rstrip("0").rstrip(".") if abs(v) >= 1000 else round(v, 4)
    return v


def finding(rule: Rule, ctx: RuleContext, *, entity: EntityView | None = None, evidence: dict[str, Any] | None = None, **fmt: Any) -> Finding:
    """Build a Finding whose confidence is the rule's base confidence tempered by extraction
    quality: an issue on a low-confidence entity may be an extraction error, so it should read
    as ambiguous and go to a human."""
    entity_factor = (0.5 + 0.5 * entity.confidence) if entity is not None else 1.0
    confidence = round(min(1.0, rule.confidence * entity_factor * ctx.document.quality), 4)
    ev: dict[str, Any] = {
        "check": rule.check,
        "field": rule.field,
        "params": rule.params,
        "extraction_quality": ctx.document.quality,
    }
    if entity is not None:
        ev["entity"] = {
            "id": entity.id, "type": entity.entity_type, "raw_text": entity.raw_text,
            "normalized_value": entity.normalized_value, "confidence": entity.confidence, "page": entity.page,
        }
    ev.update(evidence or {})
    return Finding(
        rule_id=rule.id,
        check=rule.check,
        severity=rule.severity.value,
        confidence=confidence,
        title=rule.title,
        explanation=render(rule.explanation, field=rule.field, **fmt),
        evidence=ev,
        entity_id=entity.id if entity else None,
    )
