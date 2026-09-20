"""Inputs to the rule engine, decoupled from the ORM so the engine is unit-testable."""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class EntityView:
    id: int | None
    entity_type: str
    raw_text: str
    normalized_value: dict[str, Any] | None
    confidence: float
    page: int | None = None

    def get(self, path: str | None) -> Any:
        """Dotted-path lookup into the normalized value; None if unset."""
        if not path:
            return self.normalized_value
        node: Any = self.normalized_value
        for part in path.split("."):
            if not isinstance(node, dict):
                return None
            node = node.get(part)
        return node


@dataclass
class DocumentView:
    id: int | None
    doc_type: str
    ocr_used: bool = False
    page_count: int | None = None
    raw_text: str = ""
    entities: list[EntityView] = field(default_factory=list)

    def of_type(self, entity_type: str) -> list[EntityView]:
        return [e for e in self.entities if e.entity_type == entity_type]

    def first(self, entity_type: str) -> EntityView | None:
        items = self.of_type(entity_type)
        return max(items, key=lambda e: e.confidence) if items else None

    def first_with(self, entity_type: str, path: str | None) -> EntityView | None:
        """Highest-confidence entity of the type that has a value at `path` (a swap's
        floating leg has no rate_pct, its fixed leg has no benchmark)."""
        items = [e for e in self.of_type(entity_type) if e.get(path) is not None]
        return max(items, key=lambda e: e.confidence) if items else None

    @property
    def quality(self) -> float:
        """Extraction quality factor used to temper flag confidence: OCR'd documents are
        more likely to produce spurious flags caused by recognition errors."""
        return 0.8 if self.ocr_used else 1.0


@dataclass
class RuleContext:
    document: DocumentView
    related: DocumentView | None = None


@dataclass
class Finding:
    rule_id: str
    check: str
    severity: str
    confidence: float
    title: str
    explanation: str
    evidence: dict[str, Any] = field(default_factory=dict)
    entity_id: int | None = None
    source: str = "rule"
