import fs from "node:fs";
import path from "node:path";
import { getDb, getCourseCountsByCountry } from "../services/db";

const SEED_FILE = path.resolve(__dirname, "../../data/seed_courses.sql");

function main() {
  const db = getDb();

  const existing = db.prepare(`SELECT COUNT(*) as c FROM courses`).get() as { c: number };
  if (existing.c > 0) {
    console.log(`courses table already has ${existing.c} rows — clearing before reseeding.`);
    db.exec(`DELETE FROM courses;`);
  }

  const sql = fs.readFileSync(SEED_FILE, "utf8");
  db.exec(sql);

  const total = (db.prepare(`SELECT COUNT(*) as c FROM courses`).get() as { c: number }).c;
  console.log(`Seeded ${total} courses.`);

  console.log("By country:");
  for (const row of getCourseCountsByCountry(db)) {
    console.log(`  ${row.country}: ${row.count}`);
  }
}

main();
