"""Celery application. Each pipeline stage is its own task and its own queue so worker pools
can be scaled independently (e.g. `celery -A app.workers.celery_app worker -Q extraction`)."""

from celery import Celery

from app.core.config import get_settings
from app.core.logging import configure_logging

settings = get_settings()
configure_logging()

celery_app = Celery(
    "validito",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=["app.workers.tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,  # OCR tasks are long; don't hoard them
    task_always_eager=settings.celery_task_always_eager,
    task_eager_propagates=True,
    task_routes={
        "app.workers.tasks.extract_document": {"queue": "extraction"},
        "app.workers.tasks.validate_document": {"queue": "validation"},
    },
    task_default_queue="default",
)
