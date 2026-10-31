"""Locate extracted values on their source page.

Boxes are stored as fractions of the page size so the UI can overlay them on a render at any
DPI. Text PDFs use PyMuPDF's search (the n-th occurrence on the page, matched to the char
offset the extractor recorded); OCR pages use the EasyOCR line that contains the value.
DOCX has no page geometry, so those entities keep `bbox=None` and the UI falls back to text.
"""

import logging
from pathlib import Path
from typing import Any

from app.extraction.ner import EntityCandidate
from app.extraction.text import ExtractedText, PageText

log = logging.getLogger(__name__)


def _norm(box: tuple[float, float, float, float], width: float, height: float, page: int) -> dict[str, Any]:
    x0, y0, x1, y1 = box
    return {
        "page": page,
        "x0": round(max(0.0, x0 / width), 5),
        "y0": round(max(0.0, y0 / height), 5),
        "x1": round(min(1.0, x1 / width), 5),
        "y1": round(min(1.0, y1 / height), 5),
    }


def _occurrence_index(page_text: str, value: str, local_offset: int | None) -> int:
    """Which occurrence of `value` on the page the extractor pointed at (0-based)."""
    if local_offset is None or local_offset <= 0:
        return 0
    return page_text[:local_offset].count(value)


def _boxes_from_ocr(page: PageText, value: str) -> list[tuple[float, float, float, float]]:
    needle = value.strip().lower()
    hits = [box for text, box in page.ocr_lines if needle and needle in text.lower()]
    return hits[:1]


def locate_boxes(path: Path, mime_type: str, extracted: ExtractedText, candidates: list[EntityCandidate]) -> None:
    """Fill `candidate.bbox` in place. Never raises: provenance is best-effort."""
    pages = {p.number: p for p in extracted.pages}
    spans = {num: (start, end) for num, start, end in extracted.page_offsets()}
    is_pdf = mime_type == "application/pdf"
    doc = None
    try:
        if is_pdf:
            import pymupdf as fitz

            doc = fitz.open(path)
        for cand in candidates:
            page = pages.get(cand.page) if cand.page else None
            if page is None or not page.width or not page.height or not cand.raw_text.strip():
                continue
            local = cand.char_start - spans[page.number][0] if cand.char_start is not None else None
            try:
                if page.ocr:
                    raw = _boxes_from_ocr(page, cand.raw_text)
                elif doc is not None:
                    rects = doc[page.number - 1].search_for(cand.raw_text)
                    if not rects:
                        continue
                    idx = min(_occurrence_index(page.text, cand.raw_text, local), len(rects) - 1)
                    raw = [tuple(rects[idx])]
                else:
                    continue
            except Exception:  # noqa: BLE001
                log.debug("provenance lookup failed for %s", cand.entity_type, exc_info=True)
                continue
            if raw:
                cand.bbox = [_norm(b, page.width, page.height, page.number) for b in raw]
    finally:
        if doc is not None:
            doc.close()
