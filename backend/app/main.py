import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

import app.models  # noqa: F401  -- register ORM models
from app.api.v1.router import api_router
from app.core.config import get_settings
from app.core.db import engine
from app.core.logging import configure_logging

DESCRIPTION = """
Validito validates ISDA / LMA-style term sheets: it extracts key clauses (OCR + NER),
checks them against pluggable regulatory rule packs and an ML anomaly layer, explains every
flag it raises, and routes only ambiguous cases to human review — with an immutable audit trail.
"""


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    settings = get_settings()
    settings.storage_dir.mkdir(parents=True, exist_ok=True)
    _seed_rule_packs()
    yield


def _seed_rule_packs() -> None:
    """Make the bundled ISDA / LMA packs available on first boot (idempotent)."""
    from app.core.db import session_scope
    from app.rules import seed_rule_packs

    try:
        with session_scope() as db:
            seed_rule_packs(db)
    except Exception:  # noqa: BLE001 -- e.g. migrations not applied yet; /health will say so
        logging.getLogger(__name__).exception("Could not seed rule packs at startup")


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="Validito API",
        version="1.0.0",
        description=DESCRIPTION,
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(api_router)

    @app.get("/health", tags=["ops"], summary="Liveness / readiness")
    def health():
        try:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            db_ok = True
        except Exception:  # noqa: BLE001
            db_ok = False
        return {"status": "ok" if db_ok else "degraded", "database": db_ok, "env": settings.app_env}

    return app


app = create_app()
