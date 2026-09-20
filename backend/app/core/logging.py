import logging
import sys


def configure_logging(level: int = logging.INFO) -> None:
    logging.basicConfig(
        level=level,
        stream=sys.stdout,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )
    # Quieten noisy third-party loggers.
    for name in ("uvicorn.access", "celery.utils.functional", "PIL"):
        logging.getLogger(name).setLevel(logging.WARNING)
