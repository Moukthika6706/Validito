from sqlalchemy import select

from app.audit import record, verify_chain
from app.models import AuditLog


def test_chain_links_and_verifies(db):
    a = record(db, event_type="t.one", target_type="x", target_id=1, payload={"k": 1})
    b = record(db, event_type="t.two", target_type="x", target_id=2, payload={"k": 2})
    db.commit()

    assert a.prev_hash is None
    assert b.prev_hash == a.hash
    assert verify_chain(db) == (True, None)


def test_tampering_is_detected(db):
    record(db, event_type="t.one", target_type="x", target_id=1, payload={"amount": 100})
    record(db, event_type="t.two", target_type="x", target_id=2, payload={"amount": 200})
    db.commit()

    # Simulate a direct DB edit bypassing the logger.
    row = db.execute(select(AuditLog).where(AuditLog.target_id == 1)).scalar_one()
    row.payload = {"amount": 999}
    db.commit()

    ok, bad_id = verify_chain(db)
    assert not ok
    assert bad_id == row.id


def test_payload_key_order_does_not_matter(db):
    a = record(db, event_type="t", target_type="x", payload={"b": 1, "a": 2})
    db.commit()
    db.expire_all()
    assert verify_chain(db) == (True, None)
    assert a.hash == db.get(AuditLog, a.id).hash
