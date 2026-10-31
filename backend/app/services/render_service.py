"""Page rendering for the review screen: PDFs and images render directly with PyMuPDF;
DOCX is converted with LibreOffice when `soffice` is on PATH (optional), otherwise the
document is reported as non-renderable and the UI highlights within the extracted text."""

import logging
import shutil
import subprocess
from pathlib import Path

from fastapi import HTTPException

from app.core.config import get_settings
from app.ingestion.storage import absolute_path
from app.ingestion.validators import DOCX_MIME
from app.models import Document

log = logging.getLogger(__name__)

MAX_DPI = 200
DEFAULT_DPI = 110


def libreoffice_available() -> bool:
    return shutil.which("soffice") is not None or shutil.which("libreoffice") is not None


def _converted_pdf_path(document: Document) -> Path:
    return (get_settings().storage_dir / "rendered" / f"{document.id}.pdf").resolve()


def _docx_to_pdf(document: Document) -> Path | None:
    out = _converted_pdf_path(document)
    if out.exists():
        return out
    exe = shutil.which("soffice") or shutil.which("libreoffice")
    if not exe:
        return None
    out.parent.mkdir(parents=True, exist_ok=True)
    src = absolute_path(document.storage_path)
    try:
        subprocess.run(
            [exe, "--headless", "--convert-to", "pdf", "--outdir", str(out.parent), str(src)],
            check=True, timeout=120, capture_output=True,
        )
        produced = out.parent / (src.stem + ".pdf")
        if produced.exists():
            produced.replace(out)
            return out
    except (subprocess.SubprocessError, OSError):
        log.exception("LibreOffice conversion failed for document %s", document.id)
    return None


def render_source(document: Document) -> tuple[str | None, Path | None]:
    """(kind, path) where kind is pdf | image | libreoffice | None."""
    if document.mime_type == "application/pdf":
        return "pdf", absolute_path(document.storage_path)
    if document.mime_type.startswith("image/"):
        return "image", absolute_path(document.storage_path)
    if document.mime_type == DOCX_MIME:
        pdf = _docx_to_pdf(document)
        return ("libreoffice", pdf) if pdf else (None, None)
    return None, None


def pages_info(document: Document) -> dict:
    kind, path = render_source(document)
    if path is None:
        note = (
            "Word documents have no page geometry. Install LibreOffice in the API image "
            "(INSTALL_LIBREOFFICE=true) to render them; until then highlights are shown in the extracted text."
            if document.mime_type == DOCX_MIME else "This file type cannot be rendered."
        )
        return {"document_id": document.id, "renderable": False, "render_source": None, "page_count": document.page_count or 0, "pages": [], "note": note}
    import pymupdf as fitz

    with fitz.open(path) as doc:
        pages = [{"number": i + 1, "width": p.rect.width, "height": p.rect.height} for i, p in enumerate(doc)]
    return {"document_id": document.id, "renderable": True, "render_source": kind, "page_count": len(pages), "pages": pages, "note": None}


def render_page_png(document: Document, number: int, dpi: int) -> bytes:
    kind, path = render_source(document)
    if path is None:
        raise HTTPException(404, "This document has no renderable pages.")
    import pymupdf as fitz

    dpi = max(36, min(int(dpi), MAX_DPI))
    with fitz.open(path) as doc:
        if number < 1 or number > len(doc):
            raise HTTPException(404, f"Page {number} does not exist (document has {len(doc)}).")
        return doc[number - 1].get_pixmap(dpi=dpi).tobytes("png")
