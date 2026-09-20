"""Validation stage orchestrator (rules + ML + cross-document -> flags -> routing).

Placeholder until the rule engine lands; keeps the Celery chain importable.
"""

from sqlalchemy.orm import Session

from app.models import Document


def run_validation(db: Session, document: Document) -> None:  # pragma: no cover - replaced next milestone
    raise NotImplementedError("Validation stage is implemented in the rule-engine milestone.")
