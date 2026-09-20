"""Upload validation: extension allowlist, MIME sniffing, size limits, filename hygiene."""

import io
import re
import zipfile
from dataclasses import dataclass

import filetype

# Extension -> MIME types we accept for it. The sniffed MIME must be in the list.
ALLOWED_TYPES: dict[str, tuple[str, ...]] = {
    "pdf": ("application/pdf",),
    "docx": (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/zip",  # DOCX is a zip; some sniffers stop there
    ),
    "png": ("image/png",),
    "jpg": ("image/jpeg",),
    "jpeg": ("image/jpeg",),
    "tif": ("image/tiff",),
    "tiff": ("image/tiff",),
}

DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
IMAGE_EXTENSIONS = {"png", "jpg", "jpeg", "tif", "tiff"}

_SAFE_FILENAME = re.compile(r"[^A-Za-z0-9._ \-()]")


class UploadValidationError(ValueError):
    pass


@dataclass(frozen=True)
class UploadInfo:
    filename: str
    extension: str
    mime_type: str
    size_bytes: int


def sanitize_filename(name: str) -> str:
    # Strip any path component a client may have sent, then any unsafe chars.
    name = name.replace("\\", "/").split("/")[-1].strip()
    name = _SAFE_FILENAME.sub("_", name)
    if not name or name.startswith("."):
        name = f"upload{name}"
    return name[:200]


def _is_docx(content: bytes) -> bool:
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as zf:
            return "word/document.xml" in zf.namelist()
    except zipfile.BadZipFile:
        return False


def validate_upload(filename: str, content: bytes, *, max_bytes: int) -> UploadInfo:
    if not content:
        raise UploadValidationError("Uploaded file is empty.")
    if len(content) > max_bytes:
        raise UploadValidationError(
            f"File exceeds the {max_bytes // (1024 * 1024)} MB upload limit."
        )

    safe_name = sanitize_filename(filename)
    ext = safe_name.rsplit(".", 1)[-1].lower() if "." in safe_name else ""
    if ext not in ALLOWED_TYPES:
        raise UploadValidationError(
            f"Unsupported file type '.{ext}'. Allowed: {', '.join(sorted(ALLOWED_TYPES))}."
        )

    kind = filetype.guess(content)
    sniffed = kind.mime if kind else None
    if sniffed is None or sniffed not in ALLOWED_TYPES[ext]:
        raise UploadValidationError(
            f"File content does not match its '.{ext}' extension (detected: {sniffed or 'unknown'})."
        )

    mime = sniffed
    if ext == "docx":
        if not _is_docx(content):
            raise UploadValidationError("File is not a valid DOCX document.")
        mime = DOCX_MIME

    return UploadInfo(filename=safe_name, extension=ext, mime_type=mime, size_bytes=len(content))
