from fastapi import HTTPException, status
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit import events, record
from app.models import RulePack, User
from app.rules import RulePackConfig, bundled_packs
from app.rules.checks import registered_checks
from app.rules.checks.registry import _REGISTRY
from app.schemas.rule_pack import RuleUpdate


def _with_counts(row: RulePack) -> dict:
    cfg = row.config or {}
    return {
        **{c: getattr(row, c) for c in RulePack.__table__.columns.keys()},
        "rule_count": len(cfg.get("rules", [])),
        "cross_document_rule_count": len(cfg.get("cross_document_rules", [])),
    }


def list_packs(db: Session, *, include_inactive: bool = False) -> list[dict]:
    q = select(RulePack).order_by(RulePack.key, RulePack.id.desc())
    if not include_inactive:
        q = q.where(RulePack.is_active.is_(True))
    return [_with_counts(r) for r in db.execute(q).scalars()]


def get_active_or_404(db: Session, key: str) -> RulePack:
    row = db.execute(select(RulePack).where(RulePack.key == key, RulePack.is_active.is_(True)).order_by(RulePack.id.desc()).limit(1)).scalar_one_or_none()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"No active rule pack '{key}'.")
    return row


def get_or_404(db: Session, pack_id: int) -> RulePack:
    row = db.get(RulePack, pack_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Rule pack not found.")
    return row


def create_version(db: Session, cfg: RulePackConfig, actor: User, *, activate: bool = True, reason: str = "created") -> RulePack:
    exists = db.execute(select(RulePack).where(RulePack.key == cfg.key, RulePack.version == cfg.version)).scalar_one_or_none()
    if exists:
        raise HTTPException(status.HTTP_409_CONFLICT, f"Rule pack {cfg.key} version {cfg.version} already exists.")
    if activate:
        for old in db.execute(select(RulePack).where(RulePack.key == cfg.key, RulePack.is_active.is_(True))).scalars():
            old.is_active = False
    row = RulePack(key=cfg.key, name=cfg.name, version=cfg.version, description=cfg.description,
                   config=cfg.model_dump(mode="json"), is_active=activate, created_by=actor.id)
    db.add(row)
    db.flush()
    record(db, event_type=events.RULE_PACK_CREATED, target_type="rule_pack", target_id=row.id, actor_id=actor.id,
           payload={"key": cfg.key, "version": cfg.version, "reason": reason, "rule_count": len(cfg.rules), "active": activate})
    db.commit()
    return row


def _bump_patch(version: str) -> str:
    parts = version.split(".")
    try:
        parts[-1] = str(int(parts[-1]) + 1)
    except ValueError:
        parts.append("1")
    return ".".join(parts)


def update_rule(db: Session, key: str, rule_id: str, patch: RuleUpdate, actor: User) -> RulePack:
    """Edit one rule by cutting a new patch version of the pack (old version stays for audit)."""
    current = get_active_or_404(db, key)
    cfg = RulePackConfig.model_validate(current.config)
    target = cfg.rule_by_id(rule_id)
    if target is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Rule '{rule_id}' not in pack '{key}'.")
    changes = patch.model_dump(exclude_none=True)
    if not changes:
        raise HTTPException(422, "No changes supplied.")
    before = target.model_dump(mode="json")
    updated = target.model_copy(update=changes)
    cfg.rules = [updated if r.id == rule_id else r for r in cfg.rules]
    cfg.cross_document_rules = [updated if r.id == rule_id else r for r in cfg.cross_document_rules]
    cfg.version = _bump_patch(cfg.version)
    try:
        cfg = RulePackConfig.model_validate(cfg.model_dump(mode="json"))
    except ValidationError as exc:
        raise HTTPException(422, str(exc))
    row = create_version(db, cfg, actor, activate=True, reason=f"rule {rule_id} updated")
    record(db, event_type=events.RULE_PACK_UPDATED, target_type="rule_pack", target_id=row.id, actor_id=actor.id,
           payload={"key": key, "rule_id": rule_id, "from_version": current.version, "to_version": cfg.version, "before": before, "after": updated.model_dump(mode="json")})
    db.commit()
    return row


def activate_version(db: Session, pack_id: int, actor: User) -> RulePack:
    row = get_or_404(db, pack_id)
    for other in db.execute(select(RulePack).where(RulePack.key == row.key)).scalars():
        other.is_active = other.id == row.id
    record(db, event_type=events.RULE_PACK_UPDATED, target_type="rule_pack", target_id=row.id, actor_id=actor.id,
           payload={"key": row.key, "activated_version": row.version})
    db.commit()
    return row


def check_types() -> list[dict]:
    return [{"name": name, "description": (_REGISTRY[name].__doc__ or "").strip()} for name in registered_checks()]


def bundled_summaries() -> list[dict]:
    return [{"key": c.key, "name": c.name, "version": c.version, "description": c.description} for c in bundled_packs().values()]
