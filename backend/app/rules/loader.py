"""Load rule packs from YAML files (bundled defaults) or the database (admin-editable)."""

from pathlib import Path

import yaml
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import RulePack
from app.rules.schema import RulePackConfig

PACKS_DIR = Path(__file__).resolve().parent / "packs"


def load_yaml_pack(path: Path) -> RulePackConfig:
    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    return RulePackConfig.model_validate(data)


def bundled_packs() -> dict[str, RulePackConfig]:
    packs = {}
    for path in sorted(PACKS_DIR.glob("*.yaml")):
        cfg = load_yaml_pack(path)
        packs[cfg.key] = cfg
    return packs


def seed_rule_packs(db: Session, *, created_by: int | None = None) -> list[RulePack]:
    """Insert bundled packs that are not yet in the DB (keyed by key+version). Idempotent."""
    created = []
    for cfg in bundled_packs().values():
        exists = db.execute(
            select(RulePack).where(RulePack.key == cfg.key, RulePack.version == cfg.version)
        ).scalar_one_or_none()
        if exists:
            continue
        # Deactivate older versions of the same key so the newest bundled one wins.
        for old in db.execute(select(RulePack).where(RulePack.key == cfg.key)).scalars():
            old.is_active = False
        row = RulePack(
            key=cfg.key, name=cfg.name, version=cfg.version, description=cfg.description,
            config=cfg.model_dump(mode="json"), is_active=True, created_by=created_by,
        )
        db.add(row)
        created.append(row)
    db.flush()
    return created


def active_pack(db: Session, key: str) -> tuple[RulePackConfig, RulePack | None]:
    """DB-active pack for `key`, falling back to the bundled YAML if the table is empty."""
    row = db.execute(
        select(RulePack).where(RulePack.key == key, RulePack.is_active.is_(True)).order_by(RulePack.id.desc()).limit(1)
    ).scalar_one_or_none()
    if row is not None:
        return RulePackConfig.model_validate(row.config), row
    bundled = bundled_packs()
    if key in bundled:
        return bundled[key], None
    raise KeyError(f"No rule pack with key '{key}'")


def available_keys(db: Session) -> list[str]:
    keys = {r for r in db.execute(select(RulePack.key).where(RulePack.is_active.is_(True))).scalars()}
    keys |= set(bundled_packs())
    return sorted(keys)


def detect_pack_key(db: Session, text: str, entity_texts: list[str]) -> str:
    """Pick a pack from document content when the uploader didn't specify one."""
    haystack = " ".join([text[:20000], *entity_texts]).lower()
    best_key, best_score = None, 0
    for key in available_keys(db):
        cfg, _ = active_pack(db, key)
        score = sum(haystack.count(kw.lower()) for kw in cfg.applies_to)
        if score > best_score:
            best_key, best_score = key, score
    return best_key or "isda"
