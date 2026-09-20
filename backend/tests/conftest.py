"""Test configuration. Environment is pinned *before* any app import so the engine is built
against an in-memory SQLite database and Celery runs tasks inline."""

import os
import tempfile

os.environ["DATABASE_URL"] = "sqlite:///:memory:"
os.environ["CELERY_TASK_ALWAYS_EAGER"] = "true"
os.environ["STORAGE_DIR"] = tempfile.mkdtemp(prefix="validito-test-")
os.environ["SECRET_KEY"] = "test-secret-key-that-is-at-least-32-bytes-long"

import pytest  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

import app.models  # noqa: E402, F401
from app.core.db import Base, SessionLocal, engine  # noqa: E402


@pytest.fixture(autouse=True)
def _fresh_schema():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def db() -> Session:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


ISDA_SAMPLE_TEXT = """
INTEREST RATE SWAP - INDICATIVE TERM SHEET

Trade Date: 15 March 2026
Effective Date: 17 March 2026
Termination Date: 17 March 2031
Notional Amount: USD 50,000,000
Party A: Barclays Bank PLC
Party B: Northwind Industries Ltd
Fixed Rate Payer: Party B
Fixed Rate: 3.75% per annum
Floating Rate Option: 3-month SOFR plus 45 bps
Payment Frequency: Quarterly
Fixed Rate Day Count Fraction: 30/360
Business Day Convention: Modified Following
Calculation Agent: Barclays Bank PLC
Settlement: Cash settlement
Credit Support: ISDA Credit Support Annex (2016 VM)
Governing Law: English law
Documentation: ISDA 2002 Master Agreement
"""

LMA_SAMPLE_TEXT = """
SENIOR TERM LOAN FACILITY - SUMMARY OF TERMS

Borrower: Contoso Holdings Limited
Lender: Barclays Bank PLC
Facility Agent: Barclays Bank PLC
Facility Type: Senior secured term loan
Facility Amount: GBP 25,000,000
Purpose: Refinancing of existing indebtedness
Utilisation Date: 1 April 2026
Final Maturity Date: 1 April 2031
Interest Rate: SONIA plus Margin
Margin: 2.25% per annum
Interest Period: 3 months
Repayment: Bullet at Final Maturity Date
Arrangement Fee: 75 bps
Security: Fixed and floating charge over all assets
Governing Law: England and Wales
Documentation: LMA standard facility agreement
"""
