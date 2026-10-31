"""EasyOCR wrapper. The reader is created lazily because loading the model is slow and
pulls in torch; text-based PDFs and DOCX files never need it."""

import logging
import threading
from dataclasses import dataclass, field

from app.core.config import get_settings

log = logging.getLogger(__name__)


class OCRUnavailableError(RuntimeError):
    pass


@dataclass
class OCRLine:
    text: str
    bbox: tuple[float, float, float, float]  # x0, y0, x1, y1 in image pixels


@dataclass
class OCRResult:
    text: str
    confidence: float  # mean per-line confidence, 0..1
    line_count: int
    lines: list[OCRLine] = field(default_factory=list)


class OCREngine:
    def __init__(self) -> None:
        self._reader = None
        self._lock = threading.Lock()

    def _get_reader(self):
        if self._reader is None:
            with self._lock:
                if self._reader is None:
                    try:
                        import easyocr  # noqa: WPS433 -- intentionally lazy
                    except ImportError as exc:  # pragma: no cover
                        raise OCRUnavailableError(
                            "easyocr is not installed; scanned documents cannot be processed."
                        ) from exc
                    settings = get_settings()
                    langs = [x.strip() for x in settings.ocr_languages.split(",") if x.strip()]
                    log.info("Loading EasyOCR reader (languages=%s, gpu=%s)", langs, settings.ocr_use_gpu)
                    self._reader = easyocr.Reader(langs, gpu=settings.ocr_use_gpu, verbose=False)
        return self._reader

    def read(self, image_bytes: bytes) -> OCRResult:
        reader = self._get_reader()
        # readtext returns [(bbox, text, confidence), ...] in reading order.
        results = reader.readtext(image_bytes, detail=1, paragraph=False)
        grouped = _group_into_lines(results)
        lines = [g[0] for g in grouped]
        text = "\n".join(lines)
        confs = [float(r[2]) for r in results] or [0.0]
        return OCRResult(
            text=text, confidence=sum(confs) / len(confs), line_count=len(lines),
            lines=[OCRLine(text=t, bbox=b) for t, b in grouped],
        )


def _group_into_lines(results, y_tolerance: float = 12.0) -> list[tuple[str, tuple[float, float, float, float]]]:
    """Merge boxes that share a baseline into a single line, left-to-right, returning
    (line_text, union_bbox). Keeping 'Label: Value' pairs on one line is what the field
    extractor relies on; the union box is the provenance for anything found on that line."""
    items = []
    for bbox, text, _conf in results:
        ys = [p[1] for p in bbox]
        xs = [p[0] for p in bbox]
        items.append(((min(ys) + max(ys)) / 2, min(xs), text, (min(xs), min(ys), max(xs), max(ys))))
    items.sort(key=lambda t: (t[0], t[1]))

    lines: list[list[tuple[float, str, tuple]]] = []
    current_y: float | None = None
    for y, x, text, box in items:
        if current_y is None or abs(y - current_y) > y_tolerance:
            lines.append([])
            current_y = y
        lines[-1].append((x, text, box))
    out = []
    for line in lines:
        line.sort(key=lambda t: t[0])
        boxes = [b for _, _, b in line]
        union = (min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes))
        out.append((" ".join(t for _, t, _ in line), union))
    return out


_engine: OCREngine | None = None


def get_ocr_engine() -> OCREngine:
    global _engine
    if _engine is None:
        _engine = OCREngine()
    return _engine
