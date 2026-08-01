import random

import pytest

from app import db as db_module
from app.config import config
from app.services import conversion_model as conversion_model_module
from app.services.conversion_model import predict_conversion, train_and_save
from app.services.conversion_prediction import predict_conversion as predict_conversion_rule_based


@pytest.fixture()
def isolated_model(tmp_path, monkeypatch):
    """Points the model at a scratch file and resets its in-memory cache —
    without this, model state would leak between tests."""
    monkeypatch.setattr(config, "conversion_model_path", tmp_path / "model.joblib")
    monkeypatch.setattr(config, "conversion_model_min_training_rows", 20)
    conversion_model_module._model_cache = None
    conversion_model_module._model_cache_loaded = False
    yield
    conversion_model_module._model_cache = None
    conversion_model_module._model_cache_loaded = False


def _make_student(conn, session_id, *, strong: bool, status: str):
    gpa = round(random.uniform(3.3, 4.0), 2) if strong else round(random.uniform(2.0, 2.8), 2)
    ielts = round(random.uniform(7.0, 9.0), 1) if strong else round(random.uniform(5.0, 6.0), 1)
    budget = random.randint(20000, 30000) if strong else random.randint(8000, 12000)
    student = db_module.upsert_student(
        conn,
        {
            "sessionId": session_id, "name": session_id, "email": None, "phone": None,
            "gpa": gpa, "ielts": ielts, "budget": budget, "gap": random.randint(0, 3),
            "academicBackground": "bachelors", "careerGoals": "", "migrationIntent": "study_only",
            "preferredCountry": "Australia", "score": 5.0, "status": "Hot" if strong else "Cold",
            "countries": "Australia", "aiResponse": "", "nextSteps": "[]", "suggestedCounsellorId": None,
        },
    )
    db_module.update_application_status(conn, student["id"], status)
    return db_module.get_student_by_id(conn, student["id"])


def test_terminal_states_bypass_the_model_entirely(test_db, isolated_model):
    enrolled = _make_student(test_db, "s-enrolled", strong=True, status="enrolled")
    rejected = _make_student(test_db, "s-rejected", strong=False, status="rejected")
    assert predict_conversion(enrolled).probability == 100
    assert predict_conversion(rejected).probability == 0


def test_below_training_threshold_falls_back_to_rule_based(test_db, isolated_model):
    random.seed(1)
    for i in range(10):  # below the 20-row threshold set in the fixture
        _make_student(test_db, f"s-{i}", strong=(i % 2 == 0), status="enrolled" if i % 2 == 0 else "rejected")

    row_count = train_and_save(test_db)
    assert row_count == 10

    candidate = _make_student(test_db, "s-candidate", strong=True, status="under_review")
    assert predict_conversion(candidate) == predict_conversion_rule_based(candidate)


def test_above_threshold_trains_and_learns_the_real_pattern(test_db, isolated_model):
    random.seed(2)
    for i in range(24):  # above the 20-row threshold
        strong = i % 2 == 0
        _make_student(test_db, f"s-{i}", strong=strong, status="enrolled" if strong else "rejected")

    row_count = train_and_save(test_db)
    assert row_count == 24

    strong_candidate = _make_student(test_db, "s-strong", strong=True, status="under_review")
    weak_candidate = _make_student(test_db, "s-weak", strong=False, status="under_review")

    strong_prediction = predict_conversion(strong_candidate)
    weak_prediction = predict_conversion(weak_candidate)

    assert "trained on" in strong_prediction.factors[0].lower()
    assert strong_prediction.probability > weak_prediction.probability
