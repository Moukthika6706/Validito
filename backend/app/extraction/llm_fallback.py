"""LLM-assisted extraction fallback (OFF by default).

When the label extractor and NER leave required fields empty, and `LLM_FALLBACK_ENABLED`
is true with an API key configured, Claude is asked to propose values for *only those
fields* from the minimal text needed. Every proposal is:

  * validated against a strict Pydantic schema (structured output),
  * verified to literally appear in the document text — otherwise discarded,
  * normalised with the same normaliser as a label hit,
  * stored with extractor="llm" and a deliberately low confidence so the routing policy
    sends anything that depends on it to a human.

Failures (timeouts, API errors, refusals, bad JSON) are logged and audited by the caller;
they never interrupt extraction.
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field

from pydantic import BaseModel, Field, ValidationError

from app.core.config import Settings, get_settings
from app.extraction.fields import FIELD_SPECS_BY_TYPE
from app.extraction.ner import EntityCandidate, _safe_normalize
from app.extraction.text import ExtractedText
from app.models.enums import Extractor

log = logging.getLogger(__name__)

# Fields worth asking about; anything else stays label/NER-only.
DEFAULT_REQUIRED_FIELDS = (
    "notional_amount", "effective_date", "maturity_date", "counterparty",
    "interest_rate", "governing_law", "settlement_terms",
)


class LLMField(BaseModel):
    field: str = Field(description="One of the requested field names, verbatim")
    value: str = Field(description="The value exactly as it appears in the document text")
    quote: str | None = Field(default=None, description="The sentence or line the value came from, copied verbatim")

    model_config = {"extra": "forbid"}


class LLMProposal(BaseModel):
    fields: list[LLMField] = Field(default_factory=list)

    model_config = {"extra": "forbid"}


@dataclass
class LLMFallbackResult:
    model: str | None = None
    requested: list[str] = field(default_factory=list)
    proposed: list[str] = field(default_factory=list)
    accepted: list[str] = field(default_factory=list)
    discarded: dict[str, str] = field(default_factory=dict)  # field -> reason
    candidates: list[EntityCandidate] = field(default_factory=list)
    error: str | None = None
    latency_ms: int | None = None
    input_chars: int = 0

    @property
    def attempted(self) -> bool:
        return self.model is not None

    def audit_payload(self) -> dict:
        """Safe to log: field names, counts and timings only — never document text or keys."""
        return {
            "model": self.model, "requested_fields": self.requested, "proposed_fields": self.proposed,
            "accepted_fields": self.accepted, "discarded": self.discarded, "error": self.error,
            "latency_ms": self.latency_ms, "input_chars": self.input_chars,
        }


def is_configured(settings: Settings | None = None) -> bool:
    s = settings or get_settings()
    return bool(s.llm_fallback_enabled and s.anthropic_api_key)


def missing_required_fields(found_types: set[str], required: tuple[str, ...] | list[str] = DEFAULT_REQUIRED_FIELDS) -> list[str]:
    return [f for f in required if f not in found_types and f in FIELD_SPECS_BY_TYPE]


def _prompt(text: str, fields: list[str]) -> str:
    descriptions = "\n".join(f"- {f}: {FIELD_SPECS_BY_TYPE[f].description}" for f in fields)
    return (
        "You are helping validate a financial term sheet. The automated extractor could not find "
        "the fields listed below. Read the document text and, for each field you can locate, return "
        "its value copied EXACTLY as written in the text (same characters, same casing), plus the "
        "line or sentence it came from. If a field is genuinely absent, omit it — never guess, "
        "infer, or reformat.\n\n"
        f"Fields to find:\n{descriptions}\n\n"
        f"Document text:\n<document>\n{text}\n</document>"
    )


def _normalise_ws(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip().lower()


def _locate(text: str, value: str) -> tuple[int, int] | None:
    """Find `value` in `text`, tolerant of whitespace differences. Returns (start, end)."""
    idx = text.find(value)
    if idx >= 0:
        return idx, idx + len(value)
    pattern = r"\s+".join(re.escape(tok) for tok in value.split())
    if not pattern:
        return None
    m = re.search(pattern, text, flags=re.IGNORECASE)
    return (m.start(), m.end()) if m else None


def propose_missing_fields(extracted: ExtractedText, missing: list[str], settings: Settings | None = None) -> LLMFallbackResult:
    s = settings or get_settings()
    result = LLMFallbackResult(requested=list(missing))
    if not missing or not is_configured(s):
        return result

    import anthropic  # imported lazily: optional dependency path

    text = extracted.text
    if len(text) > s.llm_max_input_chars:
        text = text[: s.llm_max_input_chars]
    result.input_chars = len(text)
    result.model = s.llm_model

    client = anthropic.Anthropic(api_key=s.anthropic_api_key, timeout=s.llm_timeout_seconds, max_retries=1)
    started = time.perf_counter()
    try:
        response = client.messages.parse(
            model=s.llm_model,
            max_tokens=2048,
            output_config={"effort": "low"},
            messages=[{"role": "user", "content": _prompt(text, missing)}],
            output_format=LLMProposal,
        )
    except anthropic.APIStatusError as exc:  # 4xx / 5xx incl. auth, rate limit, bad request
        result.error = f"{type(exc).__name__} ({exc.status_code})"
        log.warning("LLM fallback API error: %s", result.error)
        return result
    except anthropic.APIConnectionError as exc:  # timeouts and network failures
        result.error = f"{type(exc).__name__}"
        log.warning("LLM fallback connection error: %s", result.error)
        return result
    except ValidationError as exc:
        result.error = f"invalid structured output ({exc.error_count()} errors)"
        return result
    except Exception as exc:  # noqa: BLE001 -- the fallback must never break extraction
        result.error = f"{type(exc).__name__}"
        log.exception("LLM fallback failed unexpectedly")
        return result
    finally:
        result.latency_ms = int((time.perf_counter() - started) * 1000)

    if response.stop_reason == "refusal":
        result.error = "refusal"
        return result
    proposal = response.parsed_output
    if proposal is None:
        result.error = "no parsed output"
        return result

    spans = extracted.page_offsets()
    seen: set[str] = set()
    for item in proposal.fields:
        name = item.field.strip()
        result.proposed.append(name)
        if name not in missing or name in seen:
            result.discarded[name] = "not a requested field" if name not in missing else "duplicate"
            continue
        value = item.value.strip()
        if not value or len(value) > 300:
            result.discarded[name] = "empty or implausibly long value"
            continue
        loc = _locate(extracted.text, value)
        if loc is None:
            result.discarded[name] = "value not present verbatim in document text"
            continue
        spec = FIELD_SPECS_BY_TYPE[name]
        normalized = _safe_normalize(spec, value)
        start, end = loc
        page = next((n for n, a, b in spans if a <= start <= b), None)
        seen.add(name)
        result.accepted.append(name)
        result.candidates.append(
            EntityCandidate(
                entity_type=name,
                raw_text=extracted.text[start:end],
                normalized_value=normalized,
                confidence=s.llm_confidence,
                extractor=Extractor.llm,
                page=page,
                char_start=start,
                char_end=end,
                meta={"source": "llm", "model": s.llm_model, "quote": (item.quote or "")[:300], "verified_in_text": True},
            )
        )
    return result
