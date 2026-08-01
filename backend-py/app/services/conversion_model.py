import json
import sqlite3
from typing import Any

import joblib
from sklearn.linear_model import LogisticRegression

from app.config import config
from app.services.conversion_prediction import (
    ConversionPrediction,
    STATUS_STAGE_MULTIPLIER,
    likelihood_band,
    predict_conversion as predict_conversion_rule_based,
)
from app.services.crm_assistant import check_inactivity
from app.services.document_checklist import build_document_checklist
from app.services.lead_scoring import ACADEMIC_BACKGROUNDS, PRIORITY_COUNTRIES

# The self-learning piece: predicts conversion probability from the same
# feature set the rule-based version in conversion_prediction.py already
# uses, but trained on real outcomes (students whose application_status
# reached enrolled/rejected) instead of hand-picked weights. Below
# CONVERSION_MODEL_MIN_TRAINING_ROWS real terminal outcomes, there isn't
# enough signal to trust a trained model, so predict_conversion() here falls
# back to the rule-based version verbatim — no code change needed as real
# data accumulates, it switches over on its own.

_ACADEMIC_BACKGROUND_ORDER = {b: i for i, b in enumerate(ACADEMIC_BACKGROUNDS)}
_LEAD_STATUS_ORDER = {"Cold": 0, "Warm": 1, "Hot": 2}
_TERMINAL_LABELS = {"enrolled": 1, "rejected": 0}

_model_cache: LogisticRegression | None = None
_model_cache_loaded = False


def _feature_vector(student: Any) -> list[float]:
    documents = json.loads(student["documents"]) if student["documents"] else []
    checklist = build_document_checklist(documents)
    inactivity = check_inactivity(student)
    return [
        student["gpa"],
        student["ielts"],
        student["budget"],
        student["gap"],
        _ACADEMIC_BACKGROUND_ORDER.get(student["academic_background"], 1),
        1.0 if student["preferred_country"] in PRIORITY_COUNTRIES else 0.0,
        float(_LEAD_STATUS_ORDER.get(student["status"], 0)),
        STATUS_STAGE_MULTIPLIER.get(student["application_status"], 1.0),
        float(inactivity.daysSinceContact or 0),
        1.0 if checklist.complete else 0.0,
    ]


def extract_training_data(conn: sqlite3.Connection) -> tuple[list[list[float]], list[int]]:
    rows = conn.execute("SELECT * FROM students WHERE application_status IN ('enrolled', 'rejected')").fetchall()
    features = [_feature_vector(r) for r in rows]
    labels = [_TERMINAL_LABELS[r["application_status"]] for r in rows]
    return features, labels


def train_and_save(conn: sqlite3.Connection) -> int:
    """Returns the number of training rows found. Only actually trains (and
    only overwrites the persisted model) once both the row-count threshold is
    met and both outcome classes are present — LogisticRegression can't fit
    meaningfully on a single class."""
    features, labels = extract_training_data(conn)
    if len(features) < config.conversion_model_min_training_rows or len(set(labels)) < 2:
        return len(features)

    model = LogisticRegression(max_iter=1000)
    model.fit(features, labels)

    config.conversion_model_path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, config.conversion_model_path)

    global _model_cache, _model_cache_loaded
    _model_cache = model
    _model_cache_loaded = True
    return len(features)


def _load_model() -> LogisticRegression | None:
    global _model_cache, _model_cache_loaded
    if _model_cache_loaded:
        return _model_cache
    _model_cache_loaded = True
    if config.conversion_model_path.exists():
        _model_cache = joblib.load(config.conversion_model_path)
    return _model_cache


def predict_conversion(student: Any) -> ConversionPrediction:
    # Terminal states short-circuit identically in the rule-based version —
    # reuse it rather than duplicating that logic.
    if student["application_status"] in ("enrolled", "rejected"):
        return predict_conversion_rule_based(student)

    model = _load_model()
    if model is None:
        return predict_conversion_rule_based(student)

    proba_enrolled = model.predict_proba([_feature_vector(student)])[0][1]
    probability = round(min(99, max(1, proba_enrolled * 100)))
    return ConversionPrediction(
        probability=probability,
        likelihood=likelihood_band(probability),
        factors=["Predicted by a model trained on this organization's past lead outcomes"],
    )
