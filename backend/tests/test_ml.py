import numpy as np
import pytest

from app.ml.anomaly import AnomalyModel, synthetic_training_set
from app.ml.features import FEATURE_NAMES, featurize
from tests.test_rule_engine import clean_isda_doc, ev


@pytest.fixture(scope="module")
def model() -> AnomalyModel:
    return AnomalyModel("isda").fit(synthetic_training_set("isda", n=1500))


def test_featurize_covers_every_feature():
    feats = featurize(clean_isda_doc())
    assert set(feats) == set(FEATURE_NAMES)
    assert feats["log10_notional"] == pytest.approx(np.log10(50_000_000))
    assert feats["tenor_years"] == pytest.approx(5.0, abs=0.01)
    assert feats["rate_pct"] == 3.75
    assert feats["n_parties"] == 2
    assert feats["ccy_USD"] == 1.0 and feats["law_0"] == 1.0


def test_typical_document_scores_low(model):
    result = model.score_document(clean_isda_doc())
    assert result.score < 0.6


def test_anomalous_document_scores_high_with_explanations(model):
    doc = clean_isda_doc(
        notional_amount=ev("notional_amount", {"amount": 5e9, "currency": "USD"}, "USD 5,000,000,000", id=1),
        interest_rate=ev("interest_rate", {"type": "fixed", "rate_pct": 18.5}, "18.5% per annum", id=8),
        maturity_date=ev("maturity_date", {"date": "2071-03-17"}, "17 March 2071", id=5),
    )
    result = model.score_document(doc)
    assert result.score > 0.6
    labels = [c.label for c in result.contributions]
    assert "fixed rate / margin" in labels
    assert any(l in labels for l in ("notional amount", "tenor"))
    text = result.explanation()
    assert "18.50%" in text and "σ" in text
    ev_ = result.to_evidence()
    assert ev_["model"] == "IsolationForest"
    assert all({"feature", "z_score", "value_text", "typical_text"} <= set(c) for c in ev_["contributions"])


def test_model_round_trips_through_disk(model, tmp_path, monkeypatch):
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "ml_model_dir", tmp_path)
    model.save()
    loaded = AnomalyModel.load("isda")
    assert loaded is not None
    assert loaded.score_document(clean_isda_doc()).score == pytest.approx(model.score_document(clean_isda_doc()).score)
