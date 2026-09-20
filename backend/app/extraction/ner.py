"""Entity extraction: label-driven regex extraction (primary) plus a rule-augmented spaCy
NER fallback for fields the label pass missed.

Term sheets are overwhelmingly "Label: Value" documents, so the label pass is both the most
precise and the most explainable source; spaCy adds recall on free-text sheets and OCR output
where the label punctuation may be lost.
"""

import logging
import re
import threading
from dataclasses import dataclass, field
from typing import Any

from app.core.config import get_settings
from app.extraction.fields import FIELD_SPECS, FieldSpec
from app.extraction.normalizers import BENCHMARKS, ISO_CURRENCIES
from app.extraction.text import ExtractedText
from app.models.enums import Extractor

log = logging.getLogger(__name__)

LABEL_BASE_CONFIDENCE = 0.92
NER_BASE_CONFIDENCE = 0.55
NORMALIZED_BONUS = 0.03
UNNORMALIZED_PENALTY = 0.25
CONTEXT_BONUS = 0.10
CONTEXT_WINDOW = 80


@dataclass
class EntityCandidate:
    entity_type: str
    raw_text: str
    normalized_value: dict[str, Any] | None
    confidence: float
    extractor: Extractor
    page: int | None = None
    char_start: int | None = None
    char_end: int | None = None
    meta: dict[str, Any] = field(default_factory=dict)


# ----------------------------------------------------------------------------- label pass

_SEP = r"\s*[:\-–—=]\s*|\t+|\s{2,}"


def _label_regex(spec: FieldSpec) -> re.Pattern[str]:
    labels = "|".join(f"(?:{lbl})" for lbl in spec.labels)
    # ^ Label [(...)] [:|-|tab|2+spaces] Value
    return re.compile(
        rf"^\s*(?:\d+[.)]\s*)?(?P<label>{labels})(?:\s*\([^)]*\))?(?:{_SEP})(?P<value>.+?)\s*$",
        re.IGNORECASE,
    )


def _label_only_regex(spec: FieldSpec) -> re.Pattern[str]:
    labels = "|".join(f"(?:{lbl})" for lbl in spec.labels)
    return re.compile(rf"^\s*(?:\d+[.)]\s*)?(?P<label>{labels})(?:\s*\([^)]*\))?\s*:?\s*$", re.IGNORECASE)


_LABEL_RES = [(spec, _label_regex(spec), _label_only_regex(spec)) for spec in FIELD_SPECS]


def _page_for_offset(offset: int, spans: list[tuple[int, int, int]]) -> int | None:
    for number, start, end in spans:
        if start <= offset <= end:
            return number
    return None


def _ocr_scale(page: int | None, extracted: ExtractedText) -> float:
    if page is None:
        return 1.0
    p = next((x for x in extracted.pages if x.number == page), None)
    if p is None or not p.ocr or p.ocr_confidence is None:
        return 1.0
    return 0.7 + 0.3 * p.ocr_confidence


def extract_by_labels(extracted: ExtractedText) -> list[EntityCandidate]:
    text = extracted.text
    spans = extracted.page_offsets()
    lines = text.split("\n")
    offsets: list[int] = []
    pos = 0
    for line in lines:
        offsets.append(pos)
        pos += len(line) + 1

    found: list[EntityCandidate] = []
    for i, line in enumerate(lines):
        if not line.strip():
            continue
        for spec, rx, rx_label_only in _LABEL_RES:
            m = rx.match(line)
            value: str | None = None
            label: str | None = None
            value_offset = offsets[i]
            if m:
                label, value = m.group("label"), m.group("value")
                value_offset = offsets[i] + m.start("value")
            else:
                m2 = rx_label_only.match(line)
                if m2:
                    # Value sits on the next non-empty line (common in table extractions).
                    for j in range(i + 1, min(i + 3, len(lines))):
                        if lines[j].strip():
                            label, value = m2.group("label"), lines[j].strip()
                            value_offset = offsets[j] + (len(lines[j]) - len(lines[j].lstrip()))
                            break
            if not value:
                continue
            value = value.strip().strip("\"'")
            if len(value) < 1 or len(value) > 400:
                continue
            page = _page_for_offset(value_offset, spans)
            normalized = _safe_normalize(spec, value)
            confidence = LABEL_BASE_CONFIDENCE + (NORMALIZED_BONUS if normalized else -UNNORMALIZED_PENALTY)
            confidence *= _ocr_scale(page, extracted)
            meta = {"label": label.strip()} if label else {}
            if spec.role_from_label and label:
                meta["role"] = re.sub(r"\s+", "_", label.strip().lower())
                if normalized is not None:
                    normalized = {**normalized, "role": meta["role"]}
            found.append(
                EntityCandidate(
                    entity_type=spec.entity_type,
                    raw_text=value,
                    normalized_value=normalized,
                    confidence=round(min(confidence, 0.99), 4),
                    extractor=Extractor.regex,
                    page=page,
                    char_start=value_offset,
                    char_end=value_offset + len(value),
                    meta=meta,
                )
            )
            break  # one field per line
    return found


def _safe_normalize(spec: FieldSpec, value: str) -> dict[str, Any] | None:
    try:
        return spec.normalizer(value)
    except Exception:  # noqa: BLE001 -- a normalizer bug must never kill extraction
        log.exception("Normalizer for %s failed on %r", spec.entity_type, value)
        return None


# ----------------------------------------------------------------------------- spaCy pass

_nlp = None
_nlp_lock = threading.Lock()


def get_nlp():
    """Load the spaCy pipeline once, augmented with an EntityRuler for finance terms."""
    global _nlp
    if _nlp is not None:
        return _nlp
    with _nlp_lock:
        if _nlp is not None:
            return _nlp
        import spacy

        model = get_settings().spacy_model
        try:
            nlp = spacy.load(model, disable=["lemmatizer"])
        except OSError:
            log.warning("spaCy model %s not found; falling back to blank 'en' (NER disabled)", model)
            nlp = spacy.blank("en")
        ruler = nlp.add_pipe("entity_ruler", before="ner" if "ner" in nlp.pipe_names else None, config={"overwrite_ents": False})
        patterns = [{"label": "BENCHMARK", "pattern": [{"LOWER": b.lower()}]} for b in BENCHMARKS]
        patterns += [{"label": "CURRENCY", "pattern": [{"TEXT": c}]} for c in sorted(ISO_CURRENCIES)]
        patterns += [
            {"label": "LAW", "pattern": [{"LOWER": "english"}, {"LOWER": "law"}]},
            {"label": "LAW", "pattern": [{"LOWER": "new"}, {"LOWER": "york"}, {"LOWER": "law"}]},
            {"label": "LAW", "pattern": [{"LOWER": "laws"}, {"LOWER": "of"}, {"IS_TITLE": True, "OP": "+"}]},
            {"label": "DOC_STANDARD", "pattern": [{"LOWER": "isda"}, {"LOWER": "master"}, {"LOWER": "agreement"}]},
            {"label": "DOC_STANDARD", "pattern": [{"LOWER": "lma"}, {"IS_ALPHA": True, "OP": "*"}, {"LOWER": {"IN": ["agreement", "documentation", "standard"]}}]},
        ]
        ruler.add_patterns(patterns)
        _nlp = nlp
        return _nlp


def extract_by_ner(extracted: ExtractedText, already_found: set[str]) -> list[EntityCandidate]:
    """Fallback NER for specs that declare spaCy labels and were not found by the label pass."""
    specs = [s for s in FIELD_SPECS if s.spacy_labels and s.entity_type not in already_found]
    if not specs:
        return []
    text = extracted.text
    if not text.strip():
        return []
    nlp = get_nlp()
    doc = nlp(text[:200_000])  # guard against pathological inputs
    spans = extracted.page_offsets()
    low = text.lower()
    out: list[EntityCandidate] = []
    for spec in specs:
        best: list[EntityCandidate] = []
        for ent in doc.ents:
            if ent.label_ not in spec.spacy_labels:
                continue
            window = low[max(0, ent.start_char - CONTEXT_WINDOW): ent.end_char + CONTEXT_WINDOW]
            has_context = any(k in window for k in spec.context_keywords)
            normalized = _safe_normalize(spec, ent.text)
            if normalized is None and spec.normalizer is not None:
                continue  # NER fallback only keeps values we can actually interpret
            page = _page_for_offset(ent.start_char, spans)
            confidence = NER_BASE_CONFIDENCE + (CONTEXT_BONUS if has_context else 0) + NORMALIZED_BONUS
            confidence *= _ocr_scale(page, extracted)
            best.append(
                EntityCandidate(
                    entity_type=spec.entity_type,
                    raw_text=ent.text,
                    normalized_value=normalized,
                    confidence=round(confidence, 4),
                    extractor=Extractor.spacy_ner,
                    page=page,
                    char_start=ent.start_char,
                    char_end=ent.end_char,
                    meta={"ner_label": ent.label_, "context_match": has_context},
                )
            )
        if not best:
            continue
        best.sort(key=lambda c: c.confidence, reverse=True)
        out.extend(_dedupe(best)[:2] if spec.multi else best[:1])
    return out


def _dedupe(cands: list[EntityCandidate]) -> list[EntityCandidate]:
    seen: set[str] = set()
    out = []
    for c in cands:
        nv = c.normalized_value or {}
        # Same party in two roles (e.g. Lender and Facility Agent) is two distinct facts.
        key = f"{nv.get('key') or c.raw_text.lower()}|{nv.get('role') or c.meta.get('role') or ''}"
        if key in seen:
            continue
        seen.add(key)
        out.append(c)
    return out


# ----------------------------------------------------------------------------- combined

def extract_entities(extracted: ExtractedText, *, use_ner: bool = True) -> list[EntityCandidate]:
    candidates = extract_by_labels(extracted)

    # Keep every match for multi-valued fields; otherwise the highest-confidence one.
    by_type: dict[str, list[EntityCandidate]] = {}
    for c in candidates:
        by_type.setdefault(c.entity_type, []).append(c)
    selected: list[EntityCandidate] = []
    for entity_type, cands in by_type.items():
        spec = next(s for s in FIELD_SPECS if s.entity_type == entity_type)
        cands.sort(key=lambda c: c.confidence, reverse=True)
        selected.extend(_dedupe(cands) if spec.multi else cands[:1])

    # Derive currency from the notional if the sheet has no explicit currency line.
    found_types = {c.entity_type for c in selected}
    if "currency" not in found_types:
        notional = next((c for c in selected if c.entity_type == "notional_amount"), None)
        if notional and (notional.normalized_value or {}).get("currency"):
            selected.append(
                EntityCandidate(
                    entity_type="currency",
                    raw_text=notional.raw_text,
                    normalized_value={"currency": notional.normalized_value["currency"]},
                    confidence=round(notional.confidence * 0.95, 4),
                    extractor=notional.extractor,
                    page=notional.page,
                    char_start=notional.char_start,
                    char_end=notional.char_end,
                    meta={"derived_from": "notional_amount"},
                )
            )
            found_types.add("currency")

    if use_ner:
        selected.extend(extract_by_ner(extracted, found_types))
    return selected
