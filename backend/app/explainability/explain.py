"""Human-facing explanation helpers.

The rule engine and ML layer already produce explanation text and evidence per finding;
this module adds the document-level narrative and the vocabulary (confidence bands, source
descriptions) shared by the API and the UI so every surface tells the same story.
"""

from collections import Counter
from typing import Any

from app.models.enums import Severity


def confidence_band(confidence: float, ambiguous_below: float = 0.85) -> str:
    if confidence >= ambiguous_below:
        return "high"
    if confidence >= 0.6:
        return "medium"
    return "low"


def describe_source(source: str) -> str:
    return {
        "rule": "Deterministic rule from the applied rule pack",
        "ml": "Statistical anomaly detector (Isolation Forest) with per-feature deviations",
        "cross_doc": "Comparison against the linked related document",
    }.get(source, source)


def summarize_flags(findings: list[dict[str, Any]], *, decision: str, reason: str) -> str:
    """One paragraph a reviewer can read before opening any flag."""
    if not findings:
        return "No issues were detected. " + reason
    by_sev = Counter(f["severity"] for f in findings)
    order = [s.value for s in sorted(Severity, key=lambda s: -s.rank)]
    counts = ", ".join(f"{by_sev[s]} {s}" for s in order if by_sev.get(s))
    sources = Counter(f.get("source", "rule") for f in findings)
    src = ", ".join(f"{n} from {describe_source(s).split(' (')[0].lower()}" for s, n in sources.items())
    top = sorted(findings, key=lambda f: (-Severity(f["severity"]).rank, -f["confidence"]))[:3]
    headline = "; ".join(f"{f['title']} ({f['severity']}, confidence {f['confidence']:.2f})" for f in top)
    return f"{len(findings)} flag(s): {counts} ({src}). Most significant: {headline}. Decision: {decision.replace('_', ' ')} — {reason}"
