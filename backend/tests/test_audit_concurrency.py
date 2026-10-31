"""Concurrent writers must not fork the hash chain.

Uses a file-backed SQLite database with one connection per thread (the in-memory test DB
shares a single connection, which would hide the race).
"""

import threading
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401
from app.audit import record, verify_chain
from app.core.db import Base
from app.models import AuditLog

THREADS = 8
PER_THREAD = 25


@pytest.fixture
def file_db(tmp_path: Path):
    engine = create_engine(f"sqlite:///{tmp_path / 'concurrency.db'}", connect_args={"check_same_thread": False, "timeout": 30})
    Base.metadata.create_all(bind=engine)
    yield sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    engine.dispose()


def test_parallel_recorders_keep_a_single_chain(file_db):
    errors: list[Exception] = []
    start = threading.Barrier(THREADS)

    def worker(n: int):
        start.wait()
        for i in range(PER_THREAD):
            db = file_db()
            try:
                record(db, event_type="t.parallel", target_type="x", target_id=n * 1000 + i, payload={"thread": n, "i": i})
                db.commit()
            except Exception as exc:  # noqa: BLE001
                db.rollback()
                errors.append(exc)
            finally:
                db.close()

    threads = [threading.Thread(target=worker, args=(n,)) for n in range(THREADS)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, errors[:3]
    db = file_db()
    try:
        rows = db.execute(select(AuditLog).order_by(AuditLog.id)).scalars().all()
        assert len(rows) == THREADS * PER_THREAD
        prev_hashes = [r.prev_hash for r in rows]
        # Every entry has a distinct predecessor -> no two entries chained onto the same row.
        assert len(set(prev_hashes)) == len(prev_hashes)
        assert verify_chain(db) == (True, None)
    finally:
        db.close()
