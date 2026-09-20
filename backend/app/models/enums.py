"""Enumerations shared by ORM models and API schemas."""

import enum


class UserRole(str, enum.Enum):
    analyst = "analyst"
    reviewer = "reviewer"
    admin = "admin"


class DocumentType(str, enum.Enum):
    term_sheet = "term_sheet"
    confirmation = "confirmation"
    other = "other"


class DocumentStatus(str, enum.Enum):
    uploaded = "uploaded"
    processing = "processing"
    extracted = "extracted"
    validated = "validated"
    auto_approved = "auto_approved"
    needs_review = "needs_review"
    reviewed = "reviewed"
    failed = "failed"


class Extractor(str, enum.Enum):
    spacy_ner = "spacy_ner"
    entity_ruler = "entity_ruler"
    regex = "regex"


class RunStatus(str, enum.Enum):
    running = "running"
    completed = "completed"
    failed = "failed"


class RoutingDecision(str, enum.Enum):
    auto_approved = "auto_approved"
    needs_review = "needs_review"


class FlagSource(str, enum.Enum):
    rule = "rule"
    ml = "ml"
    cross_doc = "cross_doc"


class Severity(str, enum.Enum):
    info = "info"
    warning = "warning"
    error = "error"
    critical = "critical"

    @property
    def rank(self) -> int:
        return _SEVERITY_RANK[self]


_SEVERITY_RANK = {
    Severity.info: 0,
    Severity.warning: 1,
    Severity.error: 2,
    Severity.critical: 3,
}


class FlagStatus(str, enum.Enum):
    open = "open"
    accepted = "accepted"
    rejected = "rejected"
    overridden = "overridden"


class ReviewAction(str, enum.Enum):
    accept = "accept"
    reject = "reject"
    override = "override"
