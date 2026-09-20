"""Typed view of a rule pack. Packs are authored in YAML (see `packs/`) or stored as JSON in
the `rule_packs` table; both validate through `RulePackConfig`."""

from typing import Any

from pydantic import BaseModel, Field, field_validator

from app.models.enums import Severity


class Rule(BaseModel):
    id: str = Field(pattern=r"^[a-z0-9_]+(\.[a-z0-9_]+)+$", description="Dotted, pack-prefixed id e.g. isda.notional.present")
    check: str = Field(description="Registered check type (see rules/checks)")
    severity: Severity = Severity.warning
    confidence: float = Field(0.9, ge=0, le=1, description="How sure the rule is that a hit is a real issue")
    title: str
    explanation: str = Field(description="Template rendered with the check's evidence, e.g. 'Notional {value} outside range'")
    field: str | None = None
    params: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True
    tags: list[str] = Field(default_factory=list)

    model_config = {"extra": "forbid"}

    @field_validator("params", mode="before")
    @classmethod
    def _none_to_dict(cls, v):
        return v or {}


class RoutingPolicy(BaseModel):
    auto_approve_confidence: float = Field(0.85, ge=0, le=1, description="Flags below this are 'ambiguous' and force review")
    block_severities: list[Severity] = Field(default_factory=lambda: [Severity.error, Severity.critical])
    min_auto_approve_score: float = Field(0.7, ge=0, le=1)
    severity_weights: dict[Severity, float] = Field(
        default_factory=lambda: {Severity.info: 0.02, Severity.warning: 0.1, Severity.error: 0.3, Severity.critical: 0.5}
    )


class MLPolicy(BaseModel):
    enabled: bool = True
    severity: Severity = Severity.warning
    confidence_floor: float = 0.4
    anomaly_threshold: float = Field(0.6, description="Anomaly score (0..1) above which a flag is raised")


class RulePackConfig(BaseModel):
    key: str = Field(pattern=r"^[a-z0-9_\-]+$")
    name: str
    version: str
    description: str = ""
    applies_to: list[str] = Field(default_factory=list, description="Keywords that auto-select this pack")
    routing: RoutingPolicy = Field(default_factory=RoutingPolicy)
    ml: MLPolicy = Field(default_factory=MLPolicy)
    rules: list[Rule] = Field(default_factory=list)
    cross_document_rules: list[Rule] = Field(default_factory=list)

    model_config = {"extra": "forbid"}

    @field_validator("rules", "cross_document_rules")
    @classmethod
    def _unique_ids(cls, rules: list[Rule]) -> list[Rule]:
        seen: set[str] = set()
        for r in rules:
            if r.id in seen:
                raise ValueError(f"Duplicate rule id: {r.id}")
            seen.add(r.id)
        return rules

    def rule_by_id(self, rule_id: str) -> Rule | None:
        return next((r for r in [*self.rules, *self.cross_document_rules] if r.id == rule_id), None)
