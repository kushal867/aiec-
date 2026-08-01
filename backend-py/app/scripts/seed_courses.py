from pathlib import Path

from app.db import get_course_counts_by_country, get_db

_SEED_FILE = Path(__file__).resolve().parent.parent.parent / "data" / "seed_courses.sql"


def main() -> None:
    conn = get_db()

    existing = conn.execute("SELECT COUNT(*) as c FROM courses").fetchone()["c"]
    if existing > 0:
        print(f"courses table already has {existing} rows — clearing before reseeding.")
        conn.execute("DELETE FROM courses")

    sql = _SEED_FILE.read_text()
    conn.executescript(sql)
    conn.commit()

    total = conn.execute("SELECT COUNT(*) as c FROM courses").fetchone()["c"]
    print(f"Seeded {total} courses.")

    print("By country:")
    for row in get_course_counts_by_country(conn):
        print(f"  {row['country']}: {row['count']}")


if __name__ == "__main__":
    main()
