"""Generate demo term sheets into ../samples: a clean ISDA PDF, a clean LMA DOCX, a
deliberately faulty ISDA PDF (missing governing law, inconsistent dates), a matching
confirmation for cross-document checks, and a scanned-style PNG for the OCR path.

Run:  python scripts/make_samples.py
"""

import sys
from pathlib import Path

import pymupdf as fitz
import docx

ROOT = Path(__file__).resolve().parents[2]
SAMPLES = ROOT / "samples"

ISDA_CLEAN = [
    ("INTEREST RATE SWAP - INDICATIVE TERM SHEET", None),
    ("Trade Date", "15 March 2026"),
    ("Effective Date", "17 March 2026"),
    ("Termination Date", "17 March 2031"),
    ("Notional Amount", "USD 50,000,000"),
    ("Party A", "Barclays Bank PLC"),
    ("Party B", "Northwind Industries Ltd"),
    ("Fixed Rate Payer", "Party B"),
    ("Fixed Rate", "3.75% per annum"),
    ("Floating Rate Option", "3-month SOFR plus 45 bps"),
    ("Payment Frequency", "Quarterly"),
    ("Fixed Rate Day Count Fraction", "30/360"),
    ("Business Day Convention", "Modified Following"),
    ("Calculation Agent", "Barclays Bank PLC"),
    ("Settlement", "Cash settlement"),
    ("Credit Support", "ISDA Credit Support Annex (2016 VM)"),
    ("Governing Law", "English law"),
    ("Documentation", "ISDA 2002 Master Agreement"),
]

ISDA_FAULTY = [
    ("INTEREST RATE SWAP - INDICATIVE TERM SHEET", None),
    ("Trade Date", "15 March 2026"),
    ("Effective Date", "17 March 2026"),
    ("Termination Date", "17 March 2025"),  # before effective date
    ("Notional Amount", "USD 5,000,000,000"),  # implausibly large for the counterparty
    ("Party A", "Barclays Bank PLC"),
    ("Party B", "Northwind Industries Ltd"),
    ("Fixed Rate", "18.5% per annum"),  # off-market
    ("Floating Rate Option", "3-month LIBOR plus 45 bps"),  # discontinued benchmark
    ("Payment Frequency", "Quarterly"),
    ("Settlement", "To be agreed"),
    ("Documentation", "ISDA 2002 Master Agreement"),
    # governing law deliberately missing
]

ISDA_CONFIRMATION = [
    ("SWAP CONFIRMATION", None),
    ("Trade Date", "15 March 2026"),
    ("Effective Date", "17 March 2026"),
    ("Termination Date", "17 March 2031"),
    ("Notional Amount", "USD 55,000,000"),  # mismatch vs term sheet
    ("Party A", "Barclays Bank PLC"),
    ("Party B", "Northwind Industries Ltd"),
    ("Fixed Rate", "3.75% per annum"),
    ("Floating Rate Option", "3-month SOFR plus 45 bps"),
    ("Governing Law", "English law"),
]

LMA_CLEAN = [
    ("SENIOR TERM LOAN FACILITY - SUMMARY OF TERMS", None),
    ("Borrower", "Contoso Holdings Limited"),
    ("Lender", "Barclays Bank PLC"),
    ("Facility Agent", "Barclays Bank PLC"),
    ("Facility Type", "Senior secured term loan"),
    ("Facility Amount", "GBP 25,000,000"),
    ("Purpose", "Refinancing of existing indebtedness"),
    ("Utilisation Date", "1 April 2026"),
    ("Final Maturity Date", "1 April 2031"),
    ("Interest Rate", "SONIA plus Margin"),
    ("Margin", "2.25% per annum"),
    ("Interest Period", "3 months"),
    ("Repayment", "Bullet at Final Maturity Date"),
    ("Arrangement Fee", "75 bps"),
    ("Security", "Fixed and floating charge over all assets"),
    ("Governing Law", "England and Wales"),
    ("Documentation", "LMA standard facility agreement"),
]


def write_pdf(rows, path: Path) -> None:
    doc = fitz.open()
    page = doc.new_page()
    y = 72
    for label, value in rows:
        if value is None:
            page.insert_text((72, y), label, fontsize=14, fontname="helv")
            y += 30
            continue
        page.insert_text((72, y), f"{label}:", fontsize=10, fontname="helv")
        page.insert_text((260, y), value, fontsize=10, fontname="helv")
        y += 18
    doc.save(path)
    doc.close()


def write_docx(rows, path: Path) -> None:
    d = docx.Document()
    title, *fields = rows
    d.add_heading(title[0], level=1)
    table = d.add_table(rows=0, cols=2)
    table.style = "Table Grid"
    for label, value in fields:
        cells = table.add_row().cells
        cells[0].text = label
        cells[1].text = value
    d.save(path)


def write_scanned_png(rows, path: Path) -> None:
    """Render the PDF to a bitmap so the file has no text layer (forces OCR)."""
    tmp = path.with_suffix(".tmp.pdf")
    write_pdf(rows, tmp)
    with fitz.open(tmp) as doc:
        pix = doc[0].get_pixmap(dpi=150)
        pix.save(path)
    tmp.unlink()


def main() -> None:
    SAMPLES.mkdir(exist_ok=True)
    write_pdf(ISDA_CLEAN, SAMPLES / "isda_irs_clean.pdf")
    write_pdf(ISDA_FAULTY, SAMPLES / "isda_irs_faulty.pdf")
    write_pdf(ISDA_CONFIRMATION, SAMPLES / "isda_irs_confirmation.pdf")
    write_docx(LMA_CLEAN, SAMPLES / "lma_term_loan_clean.docx")
    write_scanned_png(ISDA_CLEAN, SAMPLES / "isda_irs_scanned.png")
    print(f"Wrote samples to {SAMPLES}")


if __name__ == "__main__":
    sys.exit(main())
