from app.db import upsert_student
from app.services.report_export import generate_report_docx, generate_report_pdf


def _student_row(test_db):
    upsert_student(
        test_db,
        {
            "sessionId": "sess-report", "name": "Jane Doe", "email": "jane@test.com", "phone": "+123456789",
            "gpa": 3.7, "ielts": 6.5, "budget": 20000, "gap": 1, "academicBackground": "bachelors",
            "careerGoals": "Software engineer", "migrationIntent": "study_then_work",
            "preferredCountry": "Australia", "score": 9.0, "status": "Hot", "countries": "Australia",
            "aiResponse": "Great fit for you.\nSecond paragraph.", "nextSteps": '["Submit documents", "Book IELTS"]',
            "suggestedCounsellorId": None,
        },
    )
    return test_db.execute("SELECT * FROM students WHERE session_id='sess-report'").fetchone()


def test_pdf_report_is_well_formed(test_db):
    row = _student_row(test_db)
    pdf_bytes = generate_report_pdf(row)
    assert pdf_bytes.startswith(b"%PDF")
    assert len(pdf_bytes) > 500


def test_docx_report_is_well_formed(test_db):
    row = _student_row(test_db)
    docx_bytes = generate_report_docx(row)
    assert docx_bytes.startswith(b"PK")  # docx is a zip archive
    assert len(docx_bytes) > 500


def test_report_never_includes_internal_crm_fields():
    """Regression guard: this document goes to the student directly — the
    Hot/Warm/Cold score and counsellor notes must never appear in it."""
    import inspect

    from app.services import report_export

    source = inspect.getsource(report_export._build_report_data)
    assert '"score"' not in source
    assert "counsellor_notes" not in source
