"""Pipeline tasks. `enqueue_processing` chains the stages; each stage can also be re-run alone.

Status ownership: a task moves the document into its stage (`extracting` / `validating`),
retries transient failures with exponential backoff, and only marks the document `failed`
(with `failed_stage` and `error_message`) once retries are exhausted. Both stages are
idempotent: extraction replaces prior entities and validation supersedes prior flags, so a
duplicate delivery or a manual re-run is safe.
"""

import logging

from celery import chain
from celery.exceptions import MaxRetriesExceededError

from app.audit import events, record
from app.core.db import session_scope
from app.extraction.pipeline import run_extraction, set_status
from app.models import Document, DocumentStatus
from app.workers.celery_app import celery_app

log = logging.getLogger(__name__)

MAX_RETRIES = 3
BACKOFF_BASE_SECONDS = 30
BACKOFF_MAX_SECONDS = 600


def _backoff(retries: int) -> int:
    return min(BACKOFF_BASE_SECONDS * (2 ** retries), BACKOFF_MAX_SECONDS)


def _run_stage(task, document_id: int, stage: DocumentStatus, runner) -> int:
    """Shared retry / failure bookkeeping for both pipeline stages."""
    with session_scope() as db:
        document = db.get(Document, document_id)
        if document is None:
            log.warning("%s: document %s not found", task.name, document_id)
            return document_id
        document.attempts = (document.attempts or 0) + 1
        db.commit()
        try:
            runner(db, document, mark_failed=False)
            return document_id
        except Exception as exc:  # noqa: BLE001
            db.rollback()
            document = db.get(Document, document_id)
            retries = task.request.retries
            # In eager mode (tests, CELERY_TASK_ALWAYS_EAGER dev loop) retry() cannot
            # re-schedule, so the first failure is final.
            if retries < MAX_RETRIES and not task.request.is_eager:
                delay = _backoff(retries)
                document.error_message = f"{type(exc).__name__}: {exc}"[:2000]
                record(
                    db, event_type=events.DOCUMENT_RETRY_SCHEDULED, target_type="document", target_id=document.id, document_id=document.id,
                    payload={"stage": stage.value, "attempt": document.attempts, "retry_in_seconds": delay, "error": document.error_message},
                )
                db.commit()
                try:
                    raise task.retry(exc=exc, countdown=delay)
                except MaxRetriesExceededError:
                    pass  # fall through to terminal failure
            document.failed_stage = stage.value
            document.error_message = f"{type(exc).__name__}: {exc}"[:2000]
            set_status(db, document, DocumentStatus.failed, stage=stage.value, attempts=document.attempts, final=True)
            db.commit()
            raise


@celery_app.task(name="app.workers.tasks.extract_document", bind=True, max_retries=MAX_RETRIES, acks_late=True)
def extract_document(self, document_id: int) -> int:
    return _run_stage(self, document_id, DocumentStatus.extracting, run_extraction)


@celery_app.task(name="app.workers.tasks.validate_document", bind=True, max_retries=MAX_RETRIES, acks_late=True)
def validate_document(self, document_id: int) -> int:
    # Imported lazily so the task registry imports without the ML stack being loaded.
    from app.validation.pipeline import run_validation

    with session_scope() as db:
        document = db.get(Document, document_id)
        if document is not None and document.status == DocumentStatus.validating and self.request.retries == 0:
            # Another worker is already validating this document (duplicate delivery).
            log.info("validate_document: %s already validating, skipping duplicate", document_id)
            return document_id
    return _run_stage(self, document_id, DocumentStatus.validating, run_validation)


@celery_app.task(name="app.workers.tasks.send_notification", bind=True, max_retries=MAX_RETRIES, acks_late=True)
def send_notification(self, document_id: int, run_id: int, kinds: list[str]) -> dict:
    """Deliver one notification through every enabled channel. Retries with backoff on
    channel errors; channels already recorded as sent for this run are not re-sent. Never
    raises except to retry, so a dead SMTP server can never fail a document."""
    from sqlalchemy import select

    from app.core.config import get_settings
    from app.models import Flag, FlagStatus, ValidationRun
    from app.notifications.channels import ChannelError, enabled_channels
    from app.notifications.service import already_notified, build_message

    settings = get_settings()
    outcome: dict = {"sent": [], "failed": [], "skipped": []}
    with session_scope() as db:
        document = db.get(Document, document_id)
        run = db.get(ValidationRun, run_id)
        if document is None or run is None:
            return outcome
        flags = db.execute(select(Flag).where(Flag.validation_run_id == run_id, Flag.status != FlagStatus.superseded)).scalars().all()
        message = build_message(document, run, flags, kinds, settings)
        for channel in enabled_channels(settings):
            if already_notified(db, document_id, channel=channel.name, run_id=run_id):
                outcome["skipped"].append(channel.name)
                continue
            try:
                detail = channel.send(message)
            except ChannelError as exc:
                outcome["failed"].append(channel.name)
                record(db, event_type=events.NOTIFICATION_FAILED, target_type="document", target_id=document_id, document_id=document_id,
                       payload={"channel": channel.name, "kinds": kinds, "run_id": run_id, "attempt": self.request.retries + 1, "error": str(exc)[:500]})
                log.warning("notification via %s failed for document %s: %s", channel.name, document_id, exc)
                continue
            outcome["sent"].append(channel.name)
            record(db, event_type=events.NOTIFICATION_SENT, target_type="document", target_id=document_id, document_id=document_id,
                   payload={"channel": channel.name, "kinds": kinds, "run_id": run_id, "subject": message.subject[:200], **detail})
        db.commit()
    if outcome["failed"] and self.request.retries < MAX_RETRIES and not self.request.is_eager:
        raise self.retry(countdown=_backoff(self.request.retries))
    return outcome


def enqueue_processing(document_id: int):
    """Extraction then validation. Returns the AsyncResult of the chain."""
    return chain(extract_document.s(document_id), validate_document.s()).apply_async()


def enqueue_validation(document_id: int):
    """Re-run rules/ML/routing on already-extracted entities (e.g. after a rule pack edit)."""
    return validate_document.apply_async(args=(document_id,))
