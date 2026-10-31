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


LSTA_CLEAN = [
    ("SENIOR SECURED TERM LOAN B - SUMMARY OF TERMS (LSTA)", None),
    ("Borrower", "Contoso US Holdings Inc."),
    ("Administrative Agent", "Barclays Bank PLC"),
    ("Lead Arranger", "Barclays Bank PLC"),
    ("Facility Type", "Term Loan B"),
    ("Facility Amount", "USD 350,000,000"),
    ("Purpose", "Acquisition financing and general corporate purposes"),
    ("Closing Date", "1 May 2026"),
    ("Maturity Date", "1 May 2033"),
    ("Interest Rate", "Term SOFR plus Applicable Margin"),
    ("Margin", "3.50% per annum"),
    ("Commitment Fee", "50 bps"),
    ("Interest Period", "3 months"),
    ("Repayment", "1.00% per annum amortization, balance at maturity"),
    ("Security", "First-priority lien on substantially all assets"),
    ("Governing Law", "New York"),
    ("Documentation", "LSTA standard credit agreement"),
]

LSTA_FAULTY = [
    ("SENIOR SECURED TERM LOAN B - SUMMARY OF TERMS (LSTA)", None),
    ("Borrower", "Contoso US Holdings Inc."),
    ("Administrative Agent", "Barclays Bank PLC"),
    ("Facility Type", "Term Loan B"),
    ("Facility Amount", "EUR 350,000,000"),       # non-USD under US conventions
    ("Closing Date", "1 May 2026"),
    ("Maturity Date", "1 May 2025"),              # before closing
    ("Interest Rate", "3-month LIBOR plus Applicable Margin"),  # discontinued benchmark
    ("Margin", "15.00% per annum"),               # off-market
    ("Repayment", "Bullet at maturity"),
    ("Documentation", "LSTA standard credit agreement"),
    # governing law, commitment fee, purpose, security deliberately missing
]

FX_FORWARD_CLEAN = [
    ("FX FORWARD - TERM SHEET", None),
    ("Transaction Type", "FX Forward (outright forward)"),
    ("Trade Date", "15 March 2026"),
    ("Party A", "Barclays Bank PLC"),
    ("Party B", "Northwind Industries Ltd"),
    ("Currency Pair", "EUR/USD"),
    ("Notional Amount", "EUR 10,000,000"),
    ("Spot Rate", "1.0790"),
    ("Forward Rate", "1.0850"),
    ("Value Date", "15 September 2026"),
    ("Settlement", "Deliverable"),
    ("Governing Law", "English law"),
    ("Documentation", "ISDA 2002 Master Agreement and 1998 FX Definitions"),
]

FX_FORWARD_FAULTY = [
    ("FX FORWARD - TERM SHEET", None),
    ("Transaction Type", "FX Forward (non-deliverable)"),
    ("Trade Date", "15 March 2026"),
    ("Party A", "Barclays Bank PLC"),
    ("Party B", "Northwind Industries Ltd"),
    ("Currency Pair", "USD/INR"),
    ("Notional Amount", "GBP 10,000,000"),        # currency not in the pair
    ("Spot Rate", "83.20"),
    ("Forward Rate", "93.80"),                    # >10% from spot
    ("Value Date", "15 March 2026"),              # not after trade date
    ("Settlement", "Non-deliverable (NDF)"),      # ... but no fixing date
    # governing law deliberately missing
]

# Amendment of ISDA_CLEAN: the fixed rate change is declared; the governing law change is not.
ISDA_AMENDMENT = [
    ("AMENDMENT TO INTEREST RATE SWAP TERM SHEET", None),
    ("Trade Date", "15 March 2026"),
    ("Effective Date", "17 March 2026"),
    ("Termination Date", "17 March 2031"),
    ("Notional Amount", "USD 50,000,000"),
    ("Party A", "Barclays Bank PLC"),
    ("Party B", "Northwind Industries Ltd"),
    ("Fixed Rate Payer", "Party B"),
    ("Fixed Rate", "3.90% per annum"),
    ("Floating Rate Option", "3-month SOFR plus 45 bps"),
    ("Payment Frequency", "Quarterly"),
    ("Fixed Rate Day Count Fraction", "30/360"),
    ("Business Day Convention", "Modified Following"),
    ("Calculation Agent", "Barclays Bank PLC"),
    ("Settlement", "Cash settlement"),
    ("Credit Support", "ISDA Credit Support Annex (2016 VM)"),
    ("Governing Law", "New York law"),
    ("Documentation", "ISDA 2002 Master Agreement"),
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
    write_pdf(LSTA_CLEAN, SAMPLES / "lsta_term_loan_b_clean.pdf")
    write_pdf(LSTA_FAULTY, SAMPLES / "lsta_term_loan_b_faulty.pdf")
    write_pdf(FX_FORWARD_CLEAN, SAMPLES / "fx_forward_clean.pdf")
    write_pdf(FX_FORWARD_FAULTY, SAMPLES / "fx_forward_faulty.pdf")
    write_pdf(ISDA_AMENDMENT, SAMPLES / "isda_irs_amendment.pdf")
    print(f"Wrote samples to {SAMPLES}")


if __name__ == "__main__":
    sys.exit(main())
