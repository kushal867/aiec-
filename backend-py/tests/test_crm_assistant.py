from datetime import datetime, timedelta, timezone

from app.db import upsert_student
from app.services.crm_assistant import check_inactivity, generate_followup_suggestion


def _student(test_db, **overrides):
    base = {
        "sessionId": "sess-crm", "name": "Jane Doe", "email": None, "phone": None,
        "gpa": 3.0, "ielts": 6.0, "budget": 10000, "gap": 0, "academicBackground": "bachelors",
        "careerGoals": "", "migrationIntent": "undecided", "preferredCountry": "ANY",
        "score": 5.0, "status": "Hot", "countries": "", "aiResponse": "", "nextSteps": "[]",
        "suggestedCounsellorId": None,
    }
    base.update(overrides)
    return upsert_student(test_db, base)


def test_enrolled_student_never_flagged_inactive(test_db):
    student = _student(test_db, status="Hot")
    test_db.execute(
        "UPDATE students SET application_status='enrolled', last_contacted_at=NULL WHERE id=?", (student["id"],)
    )
    test_db.commit()
    student = test_db.execute("SELECT * FROM students WHERE id=?", (student["id"],)).fetchone()
    result = check_inactivity(student)
    assert result.isInactive is False


def test_hot_lead_flagged_inactive_after_threshold(test_db):
    student = _student(test_db, status="Hot")
    stale = (datetime.now(timezone.utc) - timedelta(days=5)).isoformat()
    test_db.execute("UPDATE students SET last_contacted_at=? WHERE id=?", (stale, student["id"]))
    test_db.commit()
    student = test_db.execute("SELECT * FROM students WHERE id=?", (student["id"],)).fetchone()
    result = check_inactivity(student)
    assert result.isInactive is True  # Hot threshold is 2 days


def test_followup_suggestion_mentions_missing_documents_by_name(test_db):
    student = _student(test_db, status="Hot")
    student = test_db.execute("SELECT * FROM students WHERE id=?", (student["id"],)).fetchone()
    inactivity = check_inactivity(student)

    suggestion = generate_followup_suggestion(student, inactivity)
    assert "citizenship" in suggestion.suggestedAction.lower() or "marksheet" in suggestion.suggestedAction.lower()
    assert student["name"] in suggestion.messageTemplate


def test_followup_suggestion_no_urgent_action_when_on_track_and_complete(test_db):
    import json

    student = _student(test_db, status="Cold")
    test_db.execute(
        "UPDATE students SET last_contacted_at=?, documents=? WHERE id=?",
        (
            datetime.now(timezone.utc).isoformat(),
            json.dumps(
                [
                    {"documentType": t, "filename": "x", "status": "valid", "issues": [], "extractedSummary": "", "uploadedAt": "2025-01-01"}
                    for t in ("citizenship", "marksheet", "ielts_certificate")
                ]
            ),
            student["id"],
        ),
    )
    test_db.commit()
    student = test_db.execute("SELECT * FROM students WHERE id=?", (student["id"],)).fetchone()
    inactivity = check_inactivity(student)
    assert inactivity.isInactive is False

    suggestion = generate_followup_suggestion(student, inactivity)
    assert "no urgent action" in suggestion.suggestedAction.lower()


# --- regression: the message shown to counsellors AND the message template
# actually sent to students used raw internal keys ("citizenship, marksheet,
# ielts_certificate") instead of human labels, and "upload it" (singular)
# even when listing 3 missing documents ---
def test_followup_uses_human_labels_not_raw_keys(test_db):
    student = _student(test_db, status="Hot")
    student = test_db.execute("SELECT * FROM students WHERE id=?", (student["id"],)).fetchone()
    inactivity = check_inactivity(student)
    suggestion = generate_followup_suggestion(student, inactivity)

    for raw_key in ("ielts_certificate",):
        assert raw_key not in suggestion.suggestedAction
        assert raw_key not in suggestion.messageTemplate
    assert "IELTS certificate" in suggestion.suggestedAction
    assert "upload them" in suggestion.messageTemplate  # not "upload it" for 3 missing docs
