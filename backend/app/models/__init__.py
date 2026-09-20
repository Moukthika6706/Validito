"""ORM models. Import this package to register every table on `Base.metadata`."""

from app.models.audit import AuditLog
from app.models.document import Document
from app.models.entity import ExtractedEntity
from app.models.enums import (
    DocumentStatus,
    DocumentType,
    Extractor,
    FlagSource,
    FlagStatus,
    ReviewAction,
    RoutingDecision,
    RunStatus,
    Severity,
    UserRole,
)
from app.models.rule_pack import RulePack
from app.models.user import User
from app.models.validation import Flag, ReviewActionRecord, ValidationRun

__all__ = [
    "AuditLog",
    "Document",
    "DocumentStatus",
    "DocumentType",
    "ExtractedEntity",
    "Extractor",
    "Flag",
    "FlagSource",
    "FlagStatus",
    "ReviewAction",
    "ReviewActionRecord",
    "RoutingDecision",
    "RulePack",
    "RunStatus",
    "Severity",
    "User",
    "UserRole",
    "ValidationRun",
]
