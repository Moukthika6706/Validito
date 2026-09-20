from fastapi import APIRouter, Query
from sqlalchemy.orm import Session

from app.api.deps import DB, ReviewerOrAdmin
from app.models import User
from app.schemas.common import Page
from app.schemas.document import DocumentOut
from app.schemas.validation import FlagDetail, ReviewActionIn, ReviewCompleteIn, ReviewQueueItem
from app.services import document_service, review_service

router = APIRouter(prefix="/review", tags=["review"])


@router.get("/queue", response_model=Page[ReviewQueueItem], summary="Documents awaiting human review, oldest first")
def queue(limit: int = Query(25, ge=1, le=200), offset: int = Query(0, ge=0), user: User = ReviewerOrAdmin, db: Session = DB):
    items, total = review_service.review_queue(db, limit=limit, offset=offset)
    return Page(items=items, total=total, limit=limit, offset=offset)


@router.post("/flags/{flag_id}/actions", response_model=FlagDetail, summary="Accept, reject or override a flag")
def act(flag_id: int, data: ReviewActionIn, user: User = ReviewerOrAdmin, db: Session = DB):
    flag = review_service.get_flag_or_404(db, flag_id)
    flag = review_service.act_on_flag(db, flag, user, data)
    return review_service.flag_to_detail(review_service.get_flag_or_404(db, flag.id))


@router.post("/documents/{document_id}/complete", response_model=DocumentOut, summary="Record the final human verdict on a document")
def complete(document_id: int, data: ReviewCompleteIn, user: User = ReviewerOrAdmin, db: Session = DB):
    document = document_service.get_document_or_404(db, document_id, user)
    return review_service.complete_review(db, document, user, data)
