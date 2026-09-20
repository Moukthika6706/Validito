from fastapi import APIRouter, Query
from sqlalchemy.orm import Session

from app.api.deps import DB, AdminOnly, CurrentUser
from app.models import User
from app.schemas.rule_pack import CheckTypeOut, RulePackCreate, RulePackOut, RulePackSummary, RuleUpdate
from app.services import rule_pack_service as svc

router = APIRouter(prefix="/rule-packs", tags=["rule packs"])


@router.get("", response_model=list[RulePackSummary], summary="Rule packs (active versions by default)")
def list_packs(include_inactive: bool = Query(False), user: User = CurrentUser, db: Session = DB):
    return svc.list_packs(db, include_inactive=include_inactive and user.role.value == "admin")


@router.get("/checks", response_model=list[CheckTypeOut], summary="Check types a rule may use")
def checks(user: User = CurrentUser):
    return svc.check_types()


@router.get("/{key}", response_model=RulePackOut, summary="Active version of a pack with its full rule config")
def get_pack(key: str, user: User = CurrentUser, db: Session = DB):
    return svc._with_counts(svc.get_active_or_404(db, key))


@router.get("/versions/{pack_id}", response_model=RulePackOut)
def get_version(pack_id: int, user: User = AdminOnly, db: Session = DB):
    return svc._with_counts(svc.get_or_404(db, pack_id))


@router.post("", response_model=RulePackOut, status_code=201, summary="Create a new pack version from a full config (admin)")
def create(data: RulePackCreate, activate: bool = Query(True), user: User = AdminOnly, db: Session = DB):
    return svc._with_counts(svc.create_version(db, data.config, user, activate=activate))


@router.patch("/{key}/rules/{rule_id}", response_model=RulePackOut, summary="Edit one rule; cuts a new patch version (admin)")
def patch_rule(key: str, rule_id: str, data: RuleUpdate, user: User = AdminOnly, db: Session = DB):
    return svc._with_counts(svc.update_rule(db, key, rule_id, data, user))


@router.post("/versions/{pack_id}/activate", response_model=RulePackOut, summary="Make a stored version the active one (admin)")
def activate(pack_id: int, user: User = AdminOnly, db: Session = DB):
    return svc._with_counts(svc.activate_version(db, pack_id, user))
