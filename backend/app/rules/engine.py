"""Rule engine: runs every enabled rule of a pack against a RuleContext.

The engine knows nothing about ISDA or LMA; all domain knowledge lives in the YAML packs and
the small check functions in `checks/`.
"""

import logging
from dataclasses import dataclass, field

from app.rules.checks import get_check
from app.rules.context import Finding, RuleContext
from app.rules.schema import Rule, RulePackConfig

log = logging.getLogger(__name__)


@dataclass
class EngineResult:
    findings: list[Finding] = field(default_factory=list)
    rules_evaluated: int = 0
    rules_skipped: list[str] = field(default_factory=list)
    errors: dict[str, str] = field(default_factory=dict)  # rule_id -> error message


def evaluate(pack: RulePackConfig, ctx: RuleContext, *, include_cross_document: bool = True) -> EngineResult:
    result = EngineResult()
    rules: list[Rule] = list(pack.rules)
    if include_cross_document and ctx.related is not None:
        rules += pack.cross_document_rules
    elif pack.cross_document_rules:
        result.rules_skipped += [r.id for r in pack.cross_document_rules]

    for rule in rules:
        if not rule.enabled:
            result.rules_skipped.append(rule.id)
            continue
        try:
            fn = get_check(rule.check)
            hits = fn(rule, ctx)
        except Exception as exc:  # noqa: BLE001 -- one bad rule must not abort validation
            log.exception("Rule %s failed", rule.id)
            result.errors[rule.id] = f"{type(exc).__name__}: {exc}"
            continue
        result.rules_evaluated += 1
        result.findings.extend(hits)
    return result


def rule_snapshot(rule: Rule, pack: RulePackConfig) -> dict:
    """What gets frozen onto a flag so the audit trail is self-describing."""
    return {"pack": pack.key, "pack_version": pack.version, **rule.model_dump(mode="json")}
