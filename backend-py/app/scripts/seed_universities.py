"""
Seeds the `universities` table from data/partner_universities.json — real
partner institution names, cities, QS ranks, and tuition ranges scraped from
AIEC Global's own live site (asian.edu.np/universities), not fabricated.

Only Canada, Australia, and USA are populated (that's what the live site
actually has); Japan, South Korea, and UK have no real university data yet
and are deliberately left out rather than guessed.
"""

import json
from pathlib import Path

from app.db import get_db, get_university_counts_by_country

_DATA_FILE = Path(__file__).resolve().parent.parent.parent / "data" / "partner_universities.json"


def main() -> None:
    conn = get_db()

    existing = conn.execute("SELECT COUNT(*) as c FROM universities").fetchone()["c"]
    if existing > 0:
        print(f"universities table already has {existing} rows — clearing before reseeding.")
        conn.execute("DELETE FROM universities")

    records = json.loads(_DATA_FILE.read_text(encoding="utf-8"))
    for r in records:
        conn.execute(
            """INSERT INTO universities (name, country, city, qs_rank, tuition_range, has_scholarship)
               VALUES (:name, :country, :city, :qs_rank, :tuition, :has_scholarship)""",
            {
                "name": r["name"],
                "country": r["country"],
                "city": r["city"],
                "qs_rank": r["qs_rank"],
                "tuition": r["tuition"],
                "has_scholarship": 1 if r["has_scholarship"] else 0,
            },
        )
    conn.commit()

    total = conn.execute("SELECT COUNT(*) as c FROM universities").fetchone()["c"]
    print(f"Seeded {total} universities.")
    print("By country:")
    for row in get_university_counts_by_country(conn):
        print(f"  {row['country']}: {row['count']}")


if __name__ == "__main__":
    main()
