from fastapi import APIRouter, Query
from sqlalchemy.orm import Session

from app.api.deps import DB, CurrentUser
from app.models import User
from app.schemas.metrics import MetricsSummary
from app.services import metrics_service

router = APIRouter(prefix="/metrics", tags=["metrics"])


@router.get("/summary", response_model=MetricsSummary, summary="Dashboard stats: auto-approval rate, manual review reduction, flag mix")
def summary(days: int = Query(14, ge=1, le=90), user: User = CurrentUser, db: Session = DB):
    return metrics_service.summary(db, user, days=days)
