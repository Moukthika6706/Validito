import io
import zipfile

import pytest

from app.ingestion.validators import UploadValidationError, sanitize_filename, validate_upload

PDF_BYTES = b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\ntrailer\n<< /Root 1 0 R >>\n%%EOF\n"
PNG_BYTES = bytes.fromhex("89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489")


def _docx_bytes() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("[Content_Types].xml", "<Types/>")
        zf.writestr("word/document.xml", "<w:document/>")
    return buf.getvalue()


def test_accepts_pdf():
    info = validate_upload("sheet.pdf", PDF_BYTES, max_bytes=1_000_000)
    assert info.extension == "pdf"
    assert info.mime_type == "application/pdf"


def test_accepts_png():
    info = validate_upload("scan.PNG", PNG_BYTES, max_bytes=1_000_000)
    assert info.extension == "png"


def test_accepts_docx():
    info = validate_upload("sheet.docx", _docx_bytes(), max_bytes=1_000_000)
    assert info.mime_type.endswith("wordprocessingml.document")


def test_rejects_extension_mismatch():
    with pytest.raises(UploadValidationError, match="does not match"):
        validate_upload("sheet.pdf", PNG_BYTES, max_bytes=1_000_000)


def test_rejects_disallowed_extension():
    with pytest.raises(UploadValidationError, match="Unsupported"):
        validate_upload("payload.exe", b"MZ\x90\x00" * 10, max_bytes=1_000_000)


def test_rejects_oversize_and_empty():
    with pytest.raises(UploadValidationError, match="limit"):
        validate_upload("sheet.pdf", PDF_BYTES, max_bytes=10)
    with pytest.raises(UploadValidationError, match="empty"):
        validate_upload("sheet.pdf", b"", max_bytes=10)


def test_zip_that_is_not_docx_is_rejected():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("hello.txt", "hi")
    with pytest.raises(UploadValidationError):
        validate_upload("sheet.docx", buf.getvalue(), max_bytes=1_000_000)


def test_sanitize_filename_strips_paths():
    assert sanitize_filename("../../etc/passwd") == "passwd"
    assert sanitize_filename("C:\\Users\\x\\term sheet (v2).pdf") == "term sheet (v2).pdf"
    assert sanitize_filename(".hidden") == "upload.hidden"
