import json

from app.db import create_user, upsert_student
from app.services.auth import hash_password


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


# --- error shape: FastAPI's default {"detail": ...} would silently break
# every frontend error handler, which reads body.error (see AuthContext.tsx,
# LeadsTable.tsx, DocumentUpload.tsx, CounsellorPanel.tsx) ---
def test_404_uses_error_key_not_detail(client):
    r = client.get("/api/status/NOPE12345")
    assert r.status_code == 404
    assert "error" in r.json()
    assert "detail" not in r.json()


def test_401_uses_error_key(client):
    r = client.get("/api/admin/leads")
    assert r.status_code == 401
    assert r.json()["error"] == "Missing Authorization header"


def test_validation_failure_returns_400_with_error_key_not_422(client):
    r = client.post("/api/chat", json={"messages": [{"role": "system", "content": "hi"}]})
    assert r.status_code == 400
    assert "error" in r.json()


# --- CORS: public routes and admin routes must get different allowed
# origins — a single global policy would either leak the admin origin onto
# public routes or block the CRM dashboard entirely ---
def test_cors_differs_between_public_and_admin_routes(client):
    public = client.get("/api/health")
    admin = client.get("/api/admin/counsellors")  # 401, but CORS header still set
    assert public.headers["access-control-allow-origin"] != admin.headers["access-control-allow-origin"]


def test_login_success_and_failure(client, test_db):
    create_user(test_db, "Admin", "admin@test.com", hash_password("secret123"), "admin")

    ok = client.post("/api/auth/login", json={"email": "admin@test.com", "password": "secret123"})
    assert ok.status_code == 200
    assert "token" in ok.json()

    bad = client.post("/api/auth/login", json={"email": "admin@test.com", "password": "wrong"})
    assert bad.status_code == 401
    assert bad.json()["error"] == "Invalid email or password"


def test_login_rate_limited_after_10_attempts(client, test_db):
    codes = [
        client.post("/api/auth/login", json={"email": "nope@test.com", "password": "x"}).status_code
        for _ in range(12)
    ]
    assert codes.count(401) == 10
    assert codes.count(429) == 2


def _login(client, test_db, role="admin"):
    create_user(test_db, role.title(), f"{role}@test.com", hash_password("secret123"), role)
    r = client.post("/api/auth/login", json={"email": f"{role}@test.com", "password": "secret123"})
    return {"Authorization": f"Bearer {r.json()['token']}"}


def test_admin_leads_full_crud_flow(client, test_db):
    headers = _login(client, test_db, "admin")
    student = upsert_student(
        test_db,
        {
            "sessionId": "sess-1", "name": "Jane Doe", "email": "jane@test.com", "phone": None,
            "gpa": 3.7, "ielts": 6.5, "budget": 20000, "gap": 1, "academicBackground": "bachelors",
            "careerGoals": "", "migrationIntent": "study_then_work", "preferredCountry": "Australia",
            "score": 9.0, "status": "Hot", "countries": "Australia", "aiResponse": "Great fit",
            "nextSteps": json.dumps(["Step 1"]), "suggestedCounsellorId": None,
        },
    )

    leads = client.get("/api/admin/leads", headers=headers)
    assert leads.status_code == 200 and len(leads.json()["leads"]) == 1

    notes = client.patch(f"/api/admin/leads/{student['id']}/notes", json={"notes": "Called"}, headers=headers)
    assert notes.status_code == 200 and notes.json()["lead"]["counsellorNotes"] == "Called"

    status = client.patch(
        f"/api/admin/leads/{student['id']}/status", json={"applicationStatus": "documents_pending"}, headers=headers
    )
    assert status.status_code == 200
    assert status.json()["lead"]["applicationStatus"]["status"] == "documents_pending"

    contacted = client.post(f"/api/admin/leads/{student['id']}/contacted", headers=headers)
    assert contacted.status_code == 200 and contacted.json()["lead"]["lastContactedAt"] is not None


def test_counsellor_can_only_self_assign(client, test_db):
    counsellor_headers = _login(client, test_db, "counsellor")
    admin_headers = _login(client, test_db, "admin")
    # need the counsellor's own id for the self-assign check
    counsellor_id = test_db.execute("SELECT id FROM users WHERE role='counsellor'").fetchone()["id"]
    other_counsellor_id = create_user(
        test_db, "Other", "other@test.com", hash_password("x"), "counsellor"
    )["id"]

    student = upsert_student(
        test_db,
        {
            "sessionId": "sess-2", "name": "Test", "email": None, "phone": None,
            "gpa": 3.0, "ielts": 6.0, "budget": 10000, "gap": 0, "academicBackground": "bachelors",
            "careerGoals": "", "migrationIntent": "undecided", "preferredCountry": "ANY",
            "score": 5.0, "status": "Warm", "countries": "", "aiResponse": "",
            "nextSteps": "[]", "suggestedCounsellorId": None,
        },
    )

    denied = client.post(
        f"/api/admin/leads/{student['id']}/assign",
        json={"counsellorId": other_counsellor_id},
        headers=counsellor_headers,
    )
    assert denied.status_code == 403

    allowed = client.post(
        f"/api/admin/leads/{student['id']}/assign", json={"counsellorId": counsellor_id}, headers=counsellor_headers
    )
    assert allowed.status_code == 200

    # Admins, unlike counsellors, may reassign a lead regardless of current
    # assignment — only counsellors are restricted to claiming unassigned
    # leads for themselves.
    admin_reassign = client.post(
        f"/api/admin/leads/{student['id']}/assign",
        json={"counsellorId": other_counsellor_id},
        headers=admin_headers,
    )
    assert admin_reassign.status_code == 200
    assert admin_reassign.json()["lead"]["assignedCounsellorId"] == other_counsellor_id


def test_public_status_lookup_never_exposes_internal_fields(client, test_db):
    student = upsert_student(
        test_db,
        {
            "sessionId": "sess-3", "name": "Public Test", "email": "x@test.com", "phone": None,
            "gpa": 3.0, "ielts": 6.0, "budget": 10000, "gap": 0, "academicBackground": "bachelors",
            "careerGoals": "", "migrationIntent": "undecided", "preferredCountry": "ANY",
            "score": 5.0, "status": "Warm", "countries": "", "aiResponse": "",
            "nextSteps": "[]", "suggestedCounsellorId": None,
        },
    )
    r = client.get(f"/api/status/{student['reference_code']}")
    assert r.status_code == 200
    body = r.json()
    assert "score" not in body
    assert "status" not in body  # Hot/Warm/Cold is internal-only
    assert "counsellorNotes" not in body


def test_documents_checklist_for_unknown_session_is_all_missing_not_an_error(client):
    r = client.get("/api/documents/checklist/never-existed")
    assert r.status_code == 200
    assert r.json()["checklist"]["missing"] == ["citizenship", "marksheet", "ielts_certificate"]


def test_chat_returns_real_courses_for_a_known_query(client, seeded_courses):
    r = client.post("/api/chat", json={"messages": [{"role": "user", "content": "for the health"}]})
    assert r.status_code == 200
    assert len(r.json()["coursesReferenced"]) > 0


def test_profile_analyze_and_pdf_export_roundtrip(client, seeded_courses):
    analyze = client.post(
        "/api/profile/analyze",
        json={
            "fullName": "Export Test", "gpa": 3.7, "ielts": 6.5, "budget": 20000, "gap": 1,
            "academicBackground": "bachelors", "migrationIntent": "undecided",
            "preferredCountry": "Australia", "sessionId": "sess-export",
        },
    )
    assert analyze.status_code == 200

    export = client.get("/api/profile/sess-export/export?format=pdf")
    assert export.status_code == 200
    assert export.headers["content-type"] == "application/pdf"
