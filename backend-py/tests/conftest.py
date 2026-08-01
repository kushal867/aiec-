import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from app import db as db_module
from app.config import config


@pytest.fixture()
def test_db(tmp_path, monkeypatch):
    """Isolated, freshly-schema'd SQLite DB per test — never touches the real
    knowledge.db. Reaches into db.py's thread-local connection cache and
    config's singleton path so every module that calls get_db() picks up the
    same fresh, empty database for the duration of the test. Also isolates
    uploads_dir — without this, document-upload tests write real files into
    the real data/uploads/ directory."""
    db_path = tmp_path / "test_knowledge.db"
    monkeypatch.setattr(config, "database_path", db_path)
    monkeypatch.setattr(config, "uploads_dir", tmp_path / "uploads")

    if hasattr(db_module._local, "conn"):
        db_module._local.conn.close()
        del db_module._local.conn

    conn = db_module.get_db()
    yield conn

    conn.close()
    if hasattr(db_module._local, "conn"):
        del db_module._local.conn


@pytest.fixture()
def seeded_courses(test_db):
    """A small, representative slice of the real catalog — enough to exercise
    matching/filtering logic without loading all 406 real rows."""
    rows = [
        ("Bachelor in Information Technology", "Undergraduate", "USA", 4.0, 6.0, 20000, "20K-45K", "Fall, Spring"),
        ("Bachelor in Nursing", "Undergraduate", "Australia", 3.0, 7.0, 25000, "25K-45K", "T1, T2"),
        ("Certificate in Healthcare Assistant", "Certificate", "Ireland", 1.0, 5.5, 4000, "4000-8000", "Jan, Sep"),
        ("Diploma in Hospitality", "Diploma", "Australia", 1.0, 5.5, 15000, "15K-28K", "T1, T2, T3"),
        ("Bachelor in Fashion Design", "Undergraduate", "Japan", 4.0, 5.5, 7000, "7000-13000", "Apr"),
        ("Diploma in Automobile Engineering", "Diploma", "Japan", 2.0, 5.5, 6000, "6000-10000", "Apr"),
        ("Master in Business Administration (MBA)", "Postgraduate", "UK", 1.0, 6.5, 18000, "18K-35K total", "Sep, Jan"),
        ("Bachelor of Nursing", "Undergraduate", "UK", 3.0, 6.5, 14000, "14K-24K", "Sep"),
        ("Foundation / Pathway Program", "Foundation", "Ireland", 1.0, 5.5, 8000, "8000-15000", "Jan, Sep"),
    ]
    test_db.executemany(
        "INSERT INTO courses (course_name, course_level, country, duration_years, ielts_required, "
        "fee_per_year, fee_range, intake) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        rows,
    )
    test_db.commit()
    return test_db


@pytest.fixture()
def client(test_db):
    """A TestClient wired to the same isolated per-test DB, with rate-limit
    state reset — without the reset, slowapi's in-memory counters persist
    across tests (TestClient requests all appear to come from the same fake
    IP) and later tests would start failing with spurious 429s."""
    from fastapi.testclient import TestClient

    from app.limiter import limiter
    from app.main import app

    limiter.reset()
    with TestClient(app) as c:
        yield c
    limiter.reset()
