from fastapi import APIRouter, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import DB, CurrentUser
from app.explainability import summarize_flags
from app.models import DocumentStatus, FlagStatus, User, ValidationRun
from app.schemas.document import DocumentOut
from app.schemas.validation import FlagDetail, FlagOut, ValidationRunDetail, ValidationRunOut
from app.services import document_service, review_service

router = APIRouter(tags=["validation"])


@router.post("/documents/{document_id}/validate", response_model=DocumentOut, status_code=202, summary="Re-run rules, ML and routing on the extracted entities")
def revalidate(document_id: int, user: User = CurrentUser, db: Session = DB):
    document = document_service.get_document_or_404(db, document_id, user)
    if document.status in (DocumentStatus.uploaded, DocumentStatus.processing):
        from fastapi import HTTPException
        raise HTTPException(409, "Document has not finished extraction yet.")
    from app.workers.tasks import enqueue_validation

    enqueue_validation(document.id)
    return document


@router.get("/documents/{document_id}/flags", response_model=list[FlagDetail], summary="Flags on a document, most severe / least confident first")
def document_flags(
    document_id: int,
    status: FlagStatus | None = None,
    run_id: int | None = None,
    user: User = CurrentUser,
    db: Session = DB,
):
    document_service.get_document_or_404(db, document_id, user)
    return [review_service.flag_to_detail(f) for f in review_service.list_flags(db, document_id, status_filter=status, run_id=run_id)]


@router.get("/documents/{document_id}/runs", response_model=list[ValidationRunOut])
def document_runs(document_id: int, user: User = CurrentUser, db: Session = DB):
    document_service.get_document_or_404(db, document_id, user)
    runs = db.execute(select(ValidationRun).where(ValidationRun.document_id == document_id).order_by(ValidationRun.id.desc())).scalars().all()
    return [_run_out(r) for r in runs]


@router.get("/validation/runs/{run_id}", response_model=ValidationRunDetail, summary="A validation run with all its flags and a narrative summary")
def run_detail(run_id: int, user: User = CurrentUser, db: Session = DB):
    run = db.get(ValidationRun, run_id)
    if run is None:
        from fastapi import HTTPException
        raise HTTPException(404, "Validation run not found.")
    document_service.get_document_or_404(db, run.document_id, user)
    flags = review_service.list_flags(db, run.document_id, run_id=run.id)
    summary = summarize_flags(
        [{"severity": f.severity.value, "confidence": f.confidence, "title": f.title, "source": f.source.value} for f in flags],
        decision=run.routing_decision.value if run.routing_decision else "pending",
        reason=run.routing_reason or "",
    )
    return {**_run_out(run), "flags": [review_service.flag_to_detail(f) for f in flags], "summary": summary}


@router.get("/flags/{flag_id}", response_model=FlagDetail, summary="Full explainability record for one flag")
def flag_detail(flag_id: int, user: User = CurrentUser, db: Session = DB):
    flag = review_service.get_flag_or_404(db, flag_id)
    document_service.get_document_or_404(db, flag.document_id, user)
    return review_service.flag_to_detail(flag)


def _run_out(run: ValidationRun) -> dict:
    return {**{c: getattr(run, c) for c in ValidationRun.__table__.columns.keys()}, "rule_pack_key": run.rule_pack.key if run.rule_pack else None}
