"""Pipeline tasks. `process_document` chains the stages; each stage can also be re-run alone."""

import logging

from celery import chain

from app.core.db import session_scope
from app.extraction.pipeline import run_extraction
from app.models import Document
from app.workers.celery_app import celery_app

log = logging.getLogger(__name__)


@celery_app.task(name="app.workers.tasks.extract_document", bind=True, max_retries=2, default_retry_delay=30)
def extract_document(self, document_id: int) -> int:
    with session_scope() as db:
        document = db.get(Document, document_id)
        if document is None:
            log.warning("extract_document: document %s not found", document_id)
            return document_id
        try:
            run_extraction(db, document)
        except Exception as exc:  # noqa: BLE001
            # Transient failures (OCR model download, DB hiccup) get retried; the document
            # is already marked failed with the error, so a retry simply resets it.
            raise self.retry(exc=exc)
    return document_id


@celery_app.task(name="app.workers.tasks.validate_document", bind=True, max_retries=2, default_retry_delay=15)
def validate_document(self, document_id: int) -> int:
    # Implemented by the validation stage; imported lazily to keep the task registry
    # importable while that module is still being built.
    from app.validation.pipeline import run_validation

    with session_scope() as db:
        document = db.get(Document, document_id)
        if document is None:
            log.warning("validate_document: document %s not found", document_id)
            return document_id
        try:
            run_validation(db, document)
        except Exception as exc:  # noqa: BLE001
            raise self.retry(exc=exc)
    return document_id


def enqueue_processing(document_id: int):
    """Extraction then validation. Returns the AsyncResult of the chain."""
    return chain(extract_document.s(document_id), validate_document.s()).apply_async()


def enqueue_validation(document_id: int):
    """Re-run rules/ML/routing on already-extracted entities (e.g. after a rule pack edit)."""
    return validate_document.apply_async(args=(document_id,))
