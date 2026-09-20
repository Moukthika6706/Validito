"""Seed demo users and bundled rule packs. Idempotent.

    python scripts/seed.py            # users + rule packs
    python scripts/seed.py --samples  # also upload + process the sample documents inline

Demo accounts (password for all: Validito123!):
    admin@validito.demo     admin
    reviewer@validito.demo  reviewer
    analyst@validito.demo   analyst
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select  # noqa: E402

import app.models  # noqa: E402, F401
from app.core.db import Base, engine, session_scope  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.models import DocumentType, User, UserRole  # noqa: E402
from app.rules import seed_rule_packs  # noqa: E402

DEMO_PASSWORD = "Validito123!"
DEMO_USERS = [
    ("admin@validito.demo", "Ada Admin", UserRole.admin),
    ("reviewer@validito.demo", "Rhea Reviewer", UserRole.reviewer),
    ("analyst@validito.demo", "Anil Analyst", UserRole.analyst),
]
SAMPLES = Path(__file__).resolve().parents[2] / "samples"


def seed_users(db) -> dict[str, User]:
    out = {}
    for email, name, role in DEMO_USERS:
        user = db.execute(select(User).where(User.email == email)).scalar_one_or_none()
        if user is None:
            user = User(email=email, full_name=name, role=role, password_hash=hash_password(DEMO_PASSWORD))
            db.add(user)
            print(f"  created {role.value:<8} {email}")
        out[role.value] = user
    db.flush()
    return out


def seed_samples(db, analyst: User) -> None:
    from app.services.document_service import create_document
    from app.extraction.pipeline import run_extraction
    from app.validation import run_validation
    from unittest.mock import patch

    # (file, type, pack, related-to). The confirmation is linked to the clean term sheet so
    # the cross-document notional mismatch (50m vs 55m) shows up on the confirmation.
    plan = [
        ("isda_irs_clean.pdf", DocumentType.term_sheet, "isda", None),
        ("isda_irs_confirmation.pdf", DocumentType.confirmation, "isda", "isda_irs_clean.pdf"),
        ("isda_irs_faulty.pdf", DocumentType.term_sheet, "isda", None),
        ("lma_term_loan_clean.docx", DocumentType.term_sheet, "lma", None),
    ]
    created = {}
    with patch("app.workers.tasks.enqueue_processing"):  # process inline below
        for name, doc_type, pack, related_name in plan:
            path = SAMPLES / name
            if not path.exists():
                print(f"  skipping {name} (run scripts/make_samples.py first)")
                continue
            related = created.get(related_name) if related_name else None
            doc = create_document(db, owner=analyst, filename=name, content=path.read_bytes(), doc_type=doc_type,
                                  rule_pack_key=pack, related_document_id=related.id if related else None)
            created[name] = doc
            run_extraction(db, doc)
            run_validation(db, doc)
            db.refresh(doc)
            print(f"  {name:<28} -> {doc.status.value}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--samples", action="store_true", help="upload and process the demo term sheets")
    parser.add_argument("--create-schema", action="store_true", help="create tables directly (dev only; prefer alembic upgrade head)")
    args = parser.parse_args()

    if args.create_schema:
        Base.metadata.create_all(bind=engine)
        print("schema created")

    with session_scope() as db:
        print("users:")
        users = seed_users(db)
        packs = seed_rule_packs(db, created_by=users["admin"].id)
        print(f"rule packs: {len(packs)} new version(s) seeded")
        if args.samples:
            print("samples:")
            seed_samples(db, users["analyst"])
    print("done")


if __name__ == "__main__":
    main()
