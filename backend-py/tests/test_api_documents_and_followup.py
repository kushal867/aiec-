import io

from reportlab.pdfgen import canvas

from app.db import create_user, upsert_student
from app.services.auth import hash_password


def _make_ielts_pdf() -> bytes:
    buf = io.BytesIO()
    c = canvas.Canvas(buf)
    c.drawString(100, 750, "IELTS Test Report Form")
    c.drawString(100, 730, "Candidate Name: Jane Doe")
    c.drawString(100, 710, "Test Date: 12/05/2025")
    c.drawString(100, 690, "Overall Band Score: 7.0")
    c.save()
    return buf.getvalue()


def test_document_upload_end_to_end(client, seeded_courses):
    # Matches the real UI flow (CounsellorPanel.tsx gates DocumentUpload
    # behind `analyzed`) — a student row must exist before a document upload
    # actually persists. See test_document_upload_without_profile_is_silently_dropped
    # below for what happens when that order is violated.
    analyze = client.post(
        "/api/profile/analyze",
        json={
            "fullName": "Jane Doe", "gpa": 3.7, "ielts": 6.5, "budget": 20000, "gap": 1,
            "academicBackground": "bachelors", "migrationIntent": "undecided", "sessionId": "sess-upload",
        },
    )
    assert analyze.status_code == 200

    files = {"file": ("ielts.pdf", _make_ielts_pdf(), "application/pdf")}
    data = {"documentType": "ielts_certificate", "sessionId": "sess-upload"}
    r = client.post("/api/documents/upload", files=files, data=data)
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "valid"
    assert body["checklist"]["missing"] == ["citizenship", "marksheet"]


def test_document_upload_without_a_profile_yet_still_persists(client):
    """Regression: uploading before a profile exists used to be verified,
    told "valid", and then silently discarded — no student row existed to
    attach it to. ensure_student_stub() now guarantees a row exists first,
    so the upload actually persists regardless of call order, and a later
    real profile submission for the same session safely upgrades the stub
    without losing the uploaded document (see the next test)."""
    files = {"file": ("ielts.pdf", _make_ielts_pdf(), "application/pdf")}
    data = {"documentType": "ielts_certificate", "sessionId": "sess-no-profile"}
    r = client.post("/api/documents/upload", files=files, data=data)
    assert r.status_code == 200
    assert r.json()["status"] == "valid"

    checklist = client.get("/api/documents/checklist/sess-no-profile")
    assert "ielts_certificate" not in checklist.json()["checklist"]["missing"]


def test_stub_gets_upgraded_by_a_later_profile_submission_without_losing_documents(client, seeded_courses):
    files = {"file": ("ielts.pdf", _make_ielts_pdf(), "application/pdf")}
    data = {"documentType": "ielts_certificate", "sessionId": "sess-upgrade"}
    upload = client.post("/api/documents/upload", files=files, data=data)
    assert upload.status_code == 200

    analyze = client.post(
        "/api/profile/analyze",
        json={
            "fullName": "Real Name", "gpa": 3.7, "ielts": 6.5, "budget": 20000, "gap": 1,
            "academicBackground": "bachelors", "migrationIntent": "undecided", "sessionId": "sess-upgrade",
        },
    )
    assert analyze.status_code == 200

    checklist = client.get("/api/documents/checklist/sess-upgrade")
    assert "ielts_certificate" not in checklist.json()["checklist"]["missing"]


def test_document_upload_rejects_bad_document_type(client):
    files = {"file": ("x.pdf", _make_ielts_pdf(), "application/pdf")}
    data = {"documentType": "not_a_real_type", "sessionId": "sess-upload-2"}
    r = client.post("/api/documents/upload", files=files, data=data)
    assert r.status_code == 400
    assert "error" in r.json()


def test_document_upload_rejects_disallowed_mime_type(client):
    files = {"file": ("x.txt", b"hello", "text/plain")}
    data = {"documentType": "ielts_certificate", "sessionId": "sess-upload-3"}
    r = client.post("/api/documents/upload", files=files, data=data)
    assert r.status_code == 400


def test_admin_followup_generates_and_persists_suggestion(client, test_db):
    create_user(test_db, "Admin", "admin@test.com", hash_password("secret123"), "admin")
    login = client.post("/api/auth/login", json={"email": "admin@test.com", "password": "secret123"})
    headers = {"Authorization": f"Bearer {login.json()['token']}"}

    student = upsert_student(
        test_db,
        {
            "sessionId": "sess-followup", "name": "Jane Doe", "email": None, "phone": None,
            "gpa": 3.0, "ielts": 6.0, "budget": 10000, "gap": 0, "academicBackground": "bachelors",
            "careerGoals": "", "migrationIntent": "undecided", "preferredCountry": "ANY",
            "score": 5.0, "status": "Warm", "countries": "", "aiResponse": "", "nextSteps": "[]",
            "suggestedCounsellorId": None,
        },
    )

    r = client.post(f"/api/admin/leads/{student['id']}/followup", headers=headers)
    assert r.status_code == 200
    lead = r.json()["lead"]
    assert lead["followupSuggestion"]
    assert lead["followupAction"]


def test_status_export_pdf_and_docx(client, test_db):
    student = upsert_student(
        test_db,
        {
            "sessionId": "sess-status-export", "name": "Jane Doe", "email": None, "phone": None,
            "gpa": 3.0, "ielts": 6.0, "budget": 10000, "gap": 0, "academicBackground": "bachelors",
            "careerGoals": "", "migrationIntent": "undecided", "preferredCountry": "ANY",
            "score": 5.0, "status": "Warm", "countries": "", "aiResponse": "", "nextSteps": "[]",
            "suggestedCounsellorId": None,
        },
    )
    pdf = client.get(f"/api/status/{student['reference_code']}/export?format=pdf")
    assert pdf.status_code == 200 and pdf.headers["content-type"] == "application/pdf"

    docx = client.get(f"/api/status/{student['reference_code']}/export?format=docx")
    assert docx.status_code == 200

    bad_format = client.get(f"/api/status/{student['reference_code']}/export?format=exe")
    assert bad_format.status_code == 400
