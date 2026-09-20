import secrets
import sqlite3
import string
import struct
import threading
from datetime import datetime, timezone
from typing import Any, Iterable

import sqlite_vec

from app.config import config

# Must match the output dimension of config.embedding_model (bge-small-en-v1.5 = 384).
EMBEDDING_DIMENSION = 384

_local = threading.local()


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    """CREATE TABLE IF NOT EXISTS is a no-op against a table that already exists —
    it does NOT retroactively add new columns. Every column added after first
    release must be backfilled here."""
    existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    if column in existing:
        return
    conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def _init_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS chunks (
          id INTEGER PRIMARY KEY,
          text TEXT NOT NULL,
          document TEXT NOT NULL,
          page INTEGER NOT NULL,
          chunk_index INTEGER NOT NULL
        )
        """
    )
    conn.execute(
        f"""
        CREATE VIRTUAL TABLE IF NOT EXISTS vec_chunks USING vec0(
          embedding float[{EMBEDDING_DIMENSION}] distance_metric=cosine
        )
        """
    )

    # Internal-only — supports role-based behavior (Admin vs Counsellor).
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          name TEXT NOT NULL,
          email TEXT NOT NULL UNIQUE,
          password_hash TEXT NOT NULL,
          role TEXT NOT NULL CHECK (role IN ('admin','counsellor')),
          created_at TEXT NOT NULL
        )
        """
    )

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS students (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          session_id TEXT NOT NULL UNIQUE,
          reference_code TEXT,
          name TEXT NOT NULL,
          email TEXT,
          phone TEXT,
          gpa REAL NOT NULL CHECK (gpa >= 0 AND gpa <= 4.0),
          ielts REAL NOT NULL CHECK (ielts >= 0 AND ielts <= 9.0),
          budget INTEGER NOT NULL CHECK (budget > 0),
          gap INTEGER NOT NULL DEFAULT 0 CHECK (gap >= 0),
          academic_background TEXT,
          career_goals TEXT,
          migration_intent TEXT,
          preferred_country TEXT,
          score REAL NOT NULL CHECK (score >= 0 AND score <= 10),
          status TEXT NOT NULL CHECK (status IN ('Hot', 'Warm', 'Cold')),
          countries TEXT,
          ai_response TEXT,
          next_steps TEXT,
          counsellor_notes TEXT,
          documents TEXT,
          application_status TEXT NOT NULL DEFAULT 'not_started',
          application_status_updated_at TEXT,
          assigned_counsellor_id INTEGER REFERENCES users(id),
          suggested_counsellor_id INTEGER REFERENCES users(id),
          last_contacted_at TEXT,
          followup_suggestion TEXT,
          followup_action TEXT,
          followup_timing TEXT,
          followup_generated_at TEXT,
          study_path TEXT,
          study_path_generated_at TEXT,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        )
        """
    )

    for column, definition in [
        ("reference_code", "TEXT"),
        ("academic_background", "TEXT"),
        ("career_goals", "TEXT"),
        ("migration_intent", "TEXT"),
        ("application_status", "TEXT NOT NULL DEFAULT 'not_started'"),
        ("application_status_updated_at", "TEXT"),
        ("assigned_counsellor_id", "INTEGER REFERENCES users(id)"),
        ("suggested_counsellor_id", "INTEGER REFERENCES users(id)"),
        ("last_contacted_at", "TEXT"),
        ("followup_suggestion", "TEXT"),
        ("followup_action", "TEXT"),
        ("followup_timing", "TEXT"),
        ("followup_generated_at", "TEXT"),
        ("study_path", "TEXT"),
        ("study_path_generated_at", "TEXT"),
    ]:
        _ensure_column(conn, "students", column, definition)

    conn.execute("CREATE INDEX IF NOT EXISTS idx_students_status ON students(status)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_students_score ON students(score DESC)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_students_created_at ON students(created_at)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_students_assigned ON students(assigned_counsellor_id)")
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_students_reference_code ON students(reference_code)"
    )

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS courses (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          course_name TEXT NOT NULL,
          course_level TEXT NOT NULL,
          university TEXT,
          country TEXT NOT NULL,
          duration_years REAL,
          ielts_required REAL,
          fee_per_year REAL,
          total_fee REAL,
          fee_range TEXT,
          intake TEXT,
          created_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
        """
    )
    # Real partner institutions (from AIEC Global's live site sitemap/universities
    # page), kept as a separate table from `courses` rather than filling in
    # courses.university — we know these universities are real AIEC partners in a
    # given country, but not which specific course/fee row above corresponds to
    # which one, and guessing that pairing would be fabricating a fact this system
    # otherwise goes out of its way never to invent (see chat_answer.py, claude.ts).
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS universities (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          name TEXT NOT NULL,
          country TEXT NOT NULL,
          city TEXT,
          qs_rank INTEGER,
          tuition_range TEXT,
          has_scholarship INTEGER NOT NULL DEFAULT 0,
          created_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_universities_country ON universities(country)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_universities_qs_rank ON universities(qs_rank)")

    conn.execute("CREATE INDEX IF NOT EXISTS idx_courses_ielts ON courses(ielts_required)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_courses_fee ON courses(fee_per_year)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_courses_country ON courses(country)")

    conn.commit()


def get_db() -> sqlite3.Connection:
    """One connection per thread (FastAPI/uvicorn workers each need their own —
    sqlite3 connections aren't safe to share across threads)."""
    conn = getattr(_local, "conn", None)
    if conn is not None:
        return conn

    config.database_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(config.database_path), timeout=30)
    conn.row_factory = sqlite3.Row
    # WAL lets readers (e.g. GET /admin/leads) proceed concurrently with a
    # writer instead of blocking on the single rollback-journal lock — without
    # this, concurrent staff + student traffic intermittently fails with
    # "database is locked" once there's more than trivial concurrent load.
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)

    _init_schema(conn)
    _local.conn = conn
    return conn


def reset_schema() -> None:
    """Ingestion-only rebuild (PDF knowledge base) — intentionally does NOT touch
    students/courses/users. Do not add DROP/CREATE for those tables here."""
    conn = get_db()
    conn.execute("DROP TABLE IF EXISTS chunks")
    conn.execute("DROP TABLE IF EXISTS vec_chunks")
    conn.execute(
        """
        CREATE TABLE chunks (
          id INTEGER PRIMARY KEY,
          text TEXT NOT NULL,
          document TEXT NOT NULL,
          page INTEGER NOT NULL,
          chunk_index INTEGER NOT NULL
        )
        """
    )
    conn.execute(
        f"""
        CREATE VIRTUAL TABLE vec_chunks USING vec0(
          embedding float[{EMBEDDING_DIMENSION}] distance_metric=cosine
        )
        """
    )
    conn.commit()


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def serialize_embedding(vector: Iterable[float]) -> bytes:
    values = list(vector)
    return struct.pack(f"{len(values)}f", *values)


# ---------------------------------------------------------------------------
# Users / auth
# ---------------------------------------------------------------------------


def create_user(conn: sqlite3.Connection, name: str, email: str, password_hash: str, role: str) -> sqlite3.Row:
    cur = conn.execute(
        "INSERT INTO users (name, email, password_hash, role, created_at) VALUES (?, ?, ?, ?, ?)",
        (name, email, password_hash, role, now_iso()),
    )
    conn.commit()
    return get_user_by_id(conn, cur.lastrowid)


def get_user_by_email(conn: sqlite3.Connection, email: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()


def get_user_by_id(conn: sqlite3.Connection, user_id: int) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()


def list_counsellors(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM users WHERE role = 'counsellor' ORDER BY name").fetchall()


def suggest_counsellor(conn: sqlite3.Connection) -> sqlite3.Row | None:
    """Least-loaded counsellor by count of currently-assigned students — a
    suggestion, not an auto-assignment."""
    return conn.execute(
        """
        SELECT u.* FROM users u
        LEFT JOIN students s ON s.assigned_counsellor_id = u.id
        WHERE u.role = 'counsellor'
        GROUP BY u.id
        ORDER BY COUNT(s.id) ASC, u.id ASC
        LIMIT 1
        """
    ).fetchone()


# ---------------------------------------------------------------------------
# Students
# ---------------------------------------------------------------------------

APPLICATION_STATUSES = [
    "not_started",
    "documents_pending",
    "submitted",
    "under_review",
    "offer_received",
    "visa_processing",
    "enrolled",
    "rejected",
    "deferred",
]

# 24 letters + 8 digits, excluding visually-ambiguous O/0/I/1.
_REFERENCE_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def _generate_reference_code() -> str:
    # 256 % 32 == 0, so byte-to-symbol mapping is uniform (no modulo bias).
    return "AIEC-" + "".join(secrets.choice(_REFERENCE_CODE_ALPHABET) for _ in range(8))


def upsert_student(conn: sqlite3.Connection, input: dict[str, Any]) -> sqlite3.Row:
    now = now_iso()
    existing = conn.execute(
        "SELECT reference_code FROM students WHERE session_id = ?", (input["sessionId"],)
    ).fetchone()
    reference_code = existing["reference_code"] if existing else _generate_reference_code()

    conn.execute(
        """
        INSERT INTO students (session_id, reference_code, name, email, phone, gpa, ielts, budget, gap,
                               academic_background, career_goals, migration_intent,
                               preferred_country, score, status, countries, ai_response, next_steps,
                               suggested_counsellor_id, created_at, updated_at)
        VALUES (:sessionId, :referenceCode, :name, :email, :phone, :gpa, :ielts, :budget, :gap,
                :academicBackground, :careerGoals, :migrationIntent,
                :preferredCountry, :score, :status, :countries, :aiResponse, :nextSteps,
                :suggestedCounsellorId, :now, :now)
        ON CONFLICT(session_id) DO UPDATE SET
          name = excluded.name, email = excluded.email, phone = excluded.phone,
          gpa = excluded.gpa, ielts = excluded.ielts, budget = excluded.budget, gap = excluded.gap,
          academic_background = excluded.academic_background, career_goals = excluded.career_goals,
          migration_intent = excluded.migration_intent,
          preferred_country = excluded.preferred_country, score = excluded.score, status = excluded.status,
          countries = excluded.countries, ai_response = excluded.ai_response, next_steps = excluded.next_steps,
          suggested_counsellor_id = excluded.suggested_counsellor_id, updated_at = excluded.updated_at
        """,
        {
            **input,
            "referenceCode": reference_code,
            "email": input.get("email"),
            "phone": input.get("phone"),
            "academicBackground": input.get("academicBackground"),
            "careerGoals": input.get("careerGoals"),
            "migrationIntent": input.get("migrationIntent"),
            "preferredCountry": input.get("preferredCountry"),
            "countries": input.get("countries"),
            "aiResponse": input.get("aiResponse"),
            "nextSteps": input.get("nextSteps"),
            "suggestedCounsellorId": input.get("suggestedCounsellorId"),
            "now": now,
        },
    )
    conn.commit()
    return get_student_by_session_id(conn, input["sessionId"])


def get_student_by_reference_code(conn: sqlite3.Connection, reference_code: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM students WHERE reference_code = ?", (reference_code,)).fetchone()


def get_student_by_session_id(conn: sqlite3.Connection, session_id: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM students WHERE session_id = ?", (session_id,)).fetchone()


def get_student_by_id(conn: sqlite3.Connection, student_id: int) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM students WHERE id = ?", (student_id,)).fetchone()


def list_students(
    conn: sqlite3.Connection,
    status: str | None = None,
    sort: str = "desc",
    counsellor_id: int | None = None,
) -> list[sqlite3.Row]:
    order = "ASC" if sort == "asc" else "DESC"
    clauses = []
    params: dict[str, Any] = {}
    if status:
        clauses.append("status = :status")
        params["status"] = status
    if counsellor_id is not None:
        # A counsellor's view = leads already assigned to them, PLUS unassigned
        # leads the suggestion engine pointed at them.
        clauses.append(
            "(assigned_counsellor_id = :counsellorId OR "
            "(assigned_counsellor_id IS NULL AND suggested_counsellor_id = :counsellorId))"
        )
        params["counsellorId"] = counsellor_id
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    return conn.execute(f"SELECT * FROM students {where} ORDER BY created_at {order}", params).fetchall()


def update_counsellor_notes(conn: sqlite3.Connection, student_id: int, notes: str) -> sqlite3.Row | None:
    conn.execute(
        "UPDATE students SET counsellor_notes = ?, updated_at = ? WHERE id = ?",
        (notes, now_iso(), student_id),
    )
    conn.commit()
    return get_student_by_id(conn, student_id)


def assign_counsellor(conn: sqlite3.Connection, student_id: int, counsellor_id: int) -> sqlite3.Row | None:
    conn.execute(
        "UPDATE students SET assigned_counsellor_id = ?, updated_at = ? WHERE id = ?",
        (counsellor_id, now_iso(), student_id),
    )
    conn.commit()
    return get_student_by_id(conn, student_id)


def mark_contacted(conn: sqlite3.Connection, student_id: int) -> sqlite3.Row | None:
    now = now_iso()
    conn.execute(
        "UPDATE students SET last_contacted_at = ?, updated_at = ? WHERE id = ?",
        (now, now, student_id),
    )
    conn.commit()
    return get_student_by_id(conn, student_id)


def update_application_status(conn: sqlite3.Connection, student_id: int, status: str) -> sqlite3.Row | None:
    now = now_iso()
    conn.execute(
        "UPDATE students SET application_status = ?, application_status_updated_at = ?, updated_at = ? WHERE id = ?",
        (status, now, now, student_id),
    )
    conn.commit()
    return get_student_by_id(conn, student_id)


def save_followup_suggestion(
    conn: sqlite3.Connection, student_id: int, suggestion: str, action: str, timing: str
) -> sqlite3.Row | None:
    now = now_iso()
    conn.execute(
        """UPDATE students SET followup_suggestion = ?, followup_action = ?, followup_timing = ?,
           followup_generated_at = ?, updated_at = ? WHERE id = ?""",
        (suggestion, action, timing, now, now, student_id),
    )
    conn.commit()
    return get_student_by_id(conn, student_id)


def save_study_path(conn: sqlite3.Connection, student_id: int, stages_json: str) -> sqlite3.Row | None:
    """Cached like followup_suggestion — generated on-demand, not automatically,
    to keep Claude spend predictable."""
    now = now_iso()
    conn.execute(
        "UPDATE students SET study_path = ?, study_path_generated_at = ?, updated_at = ? WHERE id = ?",
        (stages_json, now, now, student_id),
    )
    conn.commit()
    return get_student_by_id(conn, student_id)


def ensure_student_stub(conn: sqlite3.Connection, session_id: str) -> sqlite3.Row:
    """Guarantees a student row exists for this session before a document
    upload is attached to it. The real UI (CounsellorPanel.tsx) gates
    document upload behind profile completion, so this shouldn't be reached
    in normal use — but without it, a document uploaded before that (any
    direct API call, or a future frontend change) would be verified, told
    "valid" to the caller, and then silently discarded with no row to attach
    it to. A later real profile submission for the same session_id safely
    overwrites this placeholder via upsert_student()'s ON CONFLICT — that
    statement never touches the documents column, so nothing uploaded here
    is ever lost.
    """
    existing = get_student_by_session_id(conn, session_id)
    if existing:
        return existing
    return upsert_student(
        conn,
        {
            "sessionId": session_id,
            "name": "(profile not yet submitted)",
            "email": None,
            "phone": None,
            "gpa": 0,
            "ielts": 0,
            "budget": 1,
            "gap": 0,
            "academicBackground": None,
            "careerGoals": None,
            "migrationIntent": None,
            "preferredCountry": None,
            "score": 0,
            "status": "Cold",
            "countries": None,
            "aiResponse": None,
            "nextSteps": None,
            "suggestedCounsellorId": None,
        },
    )


def append_document_record(conn: sqlite3.Connection, session_id: str, record: dict[str, Any]) -> sqlite3.Row | None:
    import json

    student = get_student_by_session_id(conn, session_id)
    if not student:
        return None

    existing = json.loads(student["documents"]) if student["documents"] else []
    existing.append(record)

    conn.execute(
        "UPDATE students SET documents = ?, updated_at = ? WHERE session_id = ?",
        (json.dumps(existing), now_iso(), session_id),
    )
    conn.commit()
    return get_student_by_session_id(conn, session_id)


# ---------------------------------------------------------------------------
# Courses
# ---------------------------------------------------------------------------


def query_courses(
    conn: sqlite3.Connection,
    countries: list[str] | None = None,
    max_ielts: float | None = None,
    max_fee_per_year: float | None = None,
    course_level: str | None = None,
    course_levels: list[str] | None = None,
    keyword: str | None = None,
    limit: int = 20,
) -> list[sqlite3.Row]:
    clauses = []
    params: dict[str, Any] = {}

    if countries:
        placeholders = ", ".join(f":country{i}" for i in range(len(countries)))
        clauses.append(f"country IN ({placeholders})")
        for i, c in enumerate(countries):
            params[f"country{i}"] = c
    if max_ielts is not None:
        clauses.append("(ielts_required IS NULL OR ielts_required <= :maxIelts)")
        params["maxIelts"] = max_ielts
    if max_fee_per_year is not None:
        clauses.append("(fee_per_year IS NULL OR fee_per_year <= :maxFeePerYear)")
        params["maxFeePerYear"] = max_fee_per_year
    if course_level:
        clauses.append("course_level = :courseLevel")
        params["courseLevel"] = course_level
    if course_levels:
        placeholders = ", ".join(f":level{i}" for i in range(len(course_levels)))
        clauses.append(f"course_level IN ({placeholders})")
        for i, lvl in enumerate(course_levels):
            params[f"level{i}"] = lvl
    if keyword:
        clauses.append("course_name LIKE :keyword")
        params["keyword"] = f"%{keyword}%"

    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    safe_limit = min(limit or 20, 50)

    return conn.execute(
        f"""SELECT id, course_name, course_level, university, country, duration_years,
                   ielts_required, fee_per_year, total_fee, fee_range, intake
            FROM courses {where}
            ORDER BY fee_per_year ASC
            LIMIT {safe_limit}""",
        params,
    ).fetchall()


def get_course_counts_by_country(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT country, COUNT(*) as count FROM courses GROUP BY country ORDER BY country"
    ).fetchall()


# ---------------------------------------------------------------------------
# Universities (real partner institutions — see schema comment in _init_schema)
# ---------------------------------------------------------------------------


def query_universities(
    conn: sqlite3.Connection,
    country: str | None = None,
    limit: int = 10,
) -> list[sqlite3.Row]:
    """Ranked-first (QS rank, when known) then alphabetical — mirrors how the
    live site's "Top Recommended Universities" surfaces ranked institutions
    ahead of unranked partner listings."""
    clauses = []
    params: dict[str, Any] = {}
    if country:
        clauses.append("country = :country")
        params["country"] = country
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    safe_limit = min(limit or 10, 30)
    return conn.execute(
        f"""SELECT id, name, country, city, qs_rank, tuition_range, has_scholarship
            FROM universities {where}
            ORDER BY CASE WHEN qs_rank IS NULL THEN 1 ELSE 0 END, qs_rank ASC, name ASC
            LIMIT {safe_limit}""",
        params,
    ).fetchall()


def get_university_counts_by_country(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT country, COUNT(*) as count FROM universities GROUP BY country ORDER BY country"
    ).fetchall()


def get_country_stats(conn: sqlite3.Connection, countries: list[str]) -> list[sqlite3.Row]:
    """Aggregate fee/IELTS stats per country, computed straight from the real
    course table — used for chat's "compare X vs Y" replies so the numbers
    are always real catalog data, never a guess."""
    placeholders = ", ".join(f":country{i}" for i in range(len(countries)))
    params = {f"country{i}": c for i, c in enumerate(countries)}
    return conn.execute(
        f"""SELECT country,
                   COUNT(*) as course_count,
                   MIN(fee_per_year) as min_fee,
                   MAX(fee_per_year) as max_fee,
                   AVG(fee_per_year) as avg_fee,
                   MIN(ielts_required) as min_ielts,
                   MAX(ielts_required) as max_ielts
            FROM courses
            WHERE country IN ({placeholders})
            GROUP BY country""",
        params,
    ).fetchall()
