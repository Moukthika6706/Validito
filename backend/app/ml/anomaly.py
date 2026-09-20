"""Isolation-forest anomaly detector with per-feature explanations.

The model itself is a standard scikit-learn IsolationForest. What makes it non-black-box is
the wrapper: alongside the forest we store the training distribution of every feature, so a
hit is explained as "which values sit furthest from what this rule pack normally sees",
with z-scores the reviewer can sanity-check.
"""

import logging
import math
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import joblib
import numpy as np
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import StandardScaler

from app.core.config import get_settings
from app.ml.features import FEATURE_NAMES, FEATURES_BY_NAME, featurize, to_vector
from app.rules.context import DocumentView

log = logging.getLogger(__name__)

MODEL_VERSION = "if-1.0"
Z_EXPLAIN_THRESHOLD = 1.5
Z_SCORE_FLOOR = 2.0  # deviations below this contribute nothing to the score
Z_SCORE_CEIL = 6.0  # deviations at/above this saturate the score
MAX_CONTRIBUTIONS = 4


@dataclass
class Contribution:
    feature: str
    label: str
    value: float
    value_text: str
    typical: float
    typical_text: str
    z: float

    @property
    def direction(self) -> str:
        return "above" if self.z > 0 else "below"


@dataclass
class AnomalyResult:
    score: float  # 0 = typical, 1 = extreme (max of forest_score and deviation_score)
    raw_decision: float
    forest_score: float = 0.0  # isolation-forest isolation depth, normalised against training
    deviation_score: float = 0.0  # largest single-feature z-score, normalised (2σ -> 0, 6σ -> 1)
    contributions: list[Contribution] = field(default_factory=list)
    model_version: str = MODEL_VERSION
    pack_key: str = ""

    def to_evidence(self) -> dict[str, Any]:
        return {
            "model": "IsolationForest",
            "model_version": self.model_version,
            "pack_key": self.pack_key,
            "anomaly_score": round(self.score, 4),
            "forest_score": round(self.forest_score, 4),
            "deviation_score": round(self.deviation_score, 4),
            "raw_decision": round(self.raw_decision, 4),
            "contributions": [
                {
                    "feature": c.feature, "label": c.label, "value": c.value, "value_text": c.value_text,
                    "typical": c.typical, "typical_text": c.typical_text, "z_score": round(c.z, 2),
                }
                for c in self.contributions
            ],
        }

    def explanation(self) -> str:
        head = (
            f"The extracted values are unusual for this rule pack (anomaly score {self.score:.2f}: "
            f"isolation forest {self.forest_score:.2f}, largest single deviation {self.deviation_score:.2f})."
        )
        if not self.contributions:
            return head + " No single field stands out; the pattern across fields is atypical."
        parts = [
            f"{c.label} is {c.value_text} vs typical {c.typical_text} ({abs(c.z):.1f}σ {c.direction})"
            for c in self.contributions
        ]
        return head + " Largest deviations: " + "; ".join(parts) + "."


class AnomalyModel:
    def __init__(self, pack_key: str) -> None:
        self.pack_key = pack_key
        self.scaler = StandardScaler()
        self.forest = IsolationForest(n_estimators=200, contamination=0.03, random_state=42)
        self.means: np.ndarray | None = None
        self.stds: np.ndarray | None = None
        self.q_median = 0.0
        self.q_low = -0.1
        self.trained_on = 0

    # ---------------------------------------------------------------- training

    def fit(self, X: np.ndarray) -> "AnomalyModel":
        X = np.asarray(X, dtype=float)
        self.means = X.mean(axis=0)
        self.stds = X.std(axis=0) + 1e-9
        Xs = self.scaler.fit_transform(X)
        self.forest.fit(Xs)
        d = self.forest.decision_function(Xs)
        # Map decision values onto 0..1: median training doc -> 0, 1st percentile -> 1.
        self.q_median = float(np.median(d))
        self.q_low = float(np.percentile(d, 1))
        self.trained_on = int(X.shape[0])
        return self

    # ---------------------------------------------------------------- scoring

    def score_document(self, doc: DocumentView) -> AnomalyResult:
        feats = featurize(doc)
        x = np.asarray([to_vector(feats)], dtype=float)
        d = float(self.forest.decision_function(self.scaler.transform(x))[0])
        span = max(self.q_median - self.q_low, 1e-6)
        forest_score = float(min(1.0, max(0.0, (self.q_median - d) / span)))
        contributions = self._contributions(x[0])
        # The forest captures unusual *combinations*; a single wildly off value can still be
        # diluted across 20+ features, so the largest per-feature deviation is blended in.
        max_z = max((abs(c.z) for c in contributions), default=0.0)
        deviation_score = float(min(1.0, max(0.0, (max_z - Z_SCORE_FLOOR) / (Z_SCORE_CEIL - Z_SCORE_FLOOR))))
        return AnomalyResult(
            score=round(max(forest_score, deviation_score), 4), raw_decision=d,
            forest_score=round(forest_score, 4), deviation_score=round(deviation_score, 4),
            contributions=contributions, pack_key=self.pack_key,
        )

    def _contributions(self, x: np.ndarray) -> list[Contribution]:
        assert self.means is not None and self.stds is not None
        out = []
        for i, name in enumerate(FEATURE_NAMES):
            spec = FEATURES_BY_NAME[name]
            if not spec.explainable:
                continue
            z = float((x[i] - self.means[i]) / self.stds[i])
            if abs(z) < Z_EXPLAIN_THRESHOLD or self.stds[i] < 1e-6:
                continue
            out.append(Contribution(
                feature=name, label=spec.label, value=float(x[i]), value_text=spec.describe(float(x[i])),
                typical=float(self.means[i]), typical_text=spec.describe(float(self.means[i])), z=z,
            ))
        out.sort(key=lambda c: abs(c.z), reverse=True)
        return out[:MAX_CONTRIBUTIONS]

    # ---------------------------------------------------------------- persistence

    @staticmethod
    def path_for(pack_key: str) -> Path:
        return get_settings().ml_model_dir / f"anomaly_{pack_key}.joblib"

    def save(self) -> Path:
        path = self.path_for(self.pack_key)
        path.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(self, path)
        return path

    @classmethod
    def load(cls, pack_key: str) -> "AnomalyModel | None":
        path = cls.path_for(pack_key)
        if not path.exists():
            return None
        model = joblib.load(path)
        return model if isinstance(model, cls) else None


# -------------------------------------------------------------------- synthetic training data


def synthetic_training_set(pack_key: str, n: int = 3000, seed: int = 7) -> np.ndarray:
    """Plausible 'normal' feature vectors for a market, used to bootstrap the model before
    real reviewed documents exist. Distributions follow common vanilla-deal ranges."""
    rng = np.random.default_rng(seed)
    rows = []
    loan = pack_key == "lma"
    for _ in range(n):
        f = {name: 0.0 for name in FEATURE_NAMES}
        f["has_notional"] = 1.0
        f["log10_notional"] = rng.normal(7.4 if loan else 7.6, 0.55)  # ~25m / ~40m median
        f["has_tenor"] = 1.0
        f["tenor_years"] = float(np.clip(rng.normal(5 if loan else 6, 2.2), 0.25, 30))
        floating = rng.random() < (0.9 if loan else 0.5)
        f["is_floating"] = 1.0 if floating else 0.0
        f["rate_pct"] = float(np.clip(rng.normal(2.4, 0.9), 0.2, 8)) if loan else (0.0 if floating else float(np.clip(rng.normal(3.6, 1.2), 0.1, 9)))
        f["spread_bps"] = float(np.clip(rng.normal(60, 40), 0, 300)) if floating and not loan else 0.0
        f["payments_per_year"] = float(rng.choice([1, 2, 4, 12], p=[0.1, 0.3, 0.5, 0.1]))
        f["n_parties"] = float(rng.choice([2, 3, 4], p=[0.6, 0.3, 0.1]))
        f["fields_present_ratio"] = float(np.clip(rng.normal(0.9, 0.08), 0.5, 1))
        f["n_entities"] = float(np.clip(rng.normal(15, 3), 6, 25))
        f["mean_confidence"] = float(np.clip(rng.normal(0.9, 0.04), 0.6, 0.99))
        f["min_confidence"] = float(np.clip(f["mean_confidence"] - abs(rng.normal(0.15, 0.1)), 0.3, 0.99))
        f["unparsed_ratio"] = float(np.clip(rng.normal(0.03, 0.04), 0, 0.3))
        f["ocr_used"] = 1.0 if rng.random() < 0.2 else 0.0
        ccy = rng.choice(["USD", "GBP", "EUR", "other"], p=[0.25, 0.5, 0.2, 0.05] if loan else [0.5, 0.25, 0.2, 0.05])
        f["ccy_other" if ccy == "other" else f"ccy_{ccy}"] = 1.0
        law = rng.choice([0, 1, 2], p=[0.85, 0.1, 0.05] if loan else [0.55, 0.4, 0.05])
        f["law_other" if law == 2 else f"law_{law}"] = 1.0
        rows.append(to_vector(f))
    return np.asarray(rows, dtype=float)


def train_model(pack_key: str, extra_vectors: np.ndarray | None = None) -> AnomalyModel:
    X = synthetic_training_set(pack_key)
    if extra_vectors is not None and len(extra_vectors):
        X = np.vstack([X, np.asarray(extra_vectors, dtype=float)])
    model = AnomalyModel(pack_key).fit(X)
    model.save()
    log.info("Trained anomaly model for %s on %s rows -> %s", pack_key, model.trained_on, model.path_for(pack_key))
    return model


# -------------------------------------------------------------------- cache

_models: dict[str, AnomalyModel] = {}
_lock = threading.Lock()


def get_model(pack_key: str) -> AnomalyModel:
    if pack_key in _models:
        return _models[pack_key]
    with _lock:
        if pack_key not in _models:
            model = AnomalyModel.load(pack_key)
            if model is None:
                model = train_model(pack_key)
            _models[pack_key] = model
    return _models[pack_key]


def reset_cache() -> None:
    _models.clear()


def sigmoid(x: float) -> float:
    return 1 / (1 + math.exp(-x))
