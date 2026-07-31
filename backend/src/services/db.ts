import Database from "better-sqlite3";
import * as sqliteVec from "sqlite-vec";
import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import { config } from "../config";

// Must match the output dimension of config.embeddingModel (bge-small-en-v1.5 = 384).
// If you change EMBEDDING_MODEL, verify the dimension via a test embed call
// and update this constant before re-running ingestion.
export const EMBEDDING_DIMENSION = 384;

let db: Database.Database | null = null;

/**
 * `CREATE TABLE IF NOT EXISTS` is a no-op against a table that already
 * exists — it does NOT retroactively add new columns to a table created by
 * an older version of this schema. Every column added to an existing table
 * after its first release must be backfilled here, or `getDb()` silently
 * keeps serving the old shape and every query referencing the new column
 * fails at runtime instead of at startup.
 */
function ensureColumn(database: Database.Database, table: string, column: string, definition: string): void {
  const existing = database.prepare(`PRAGMA table_info(${table})`).all() as { name: string }[];
  if (existing.some((c) => c.name === column)) return;
  database.exec(`ALTER TABLE ${table} ADD COLUMN ${column} ${definition}`);
}

export function getDb(): Database.Database {
  if (db) return db;

  fs.mkdirSync(path.dirname(config.databasePath), { recursive: true });
  db = new Database(config.databasePath);
  sqliteVec.load(db);

  db.exec(`
    CREATE TABLE IF NOT EXISTS chunks (
      id INTEGER PRIMARY KEY,
      text TEXT NOT NULL,
      document TEXT NOT NULL,
      page INTEGER NOT NULL,
      chunk_index INTEGER NOT NULL
    );
  `);
  db.exec(`
    CREATE VIRTUAL TABLE IF NOT EXISTS vec_chunks USING vec0(
      embedding float[${EMBEDDING_DIMENSION}] distance_metric=cosine
    );
  `);

  // Internal-only — not part of the Supabase target schema (that schema had
  // no auth), added to support role-based behavior (Admin vs Counsellor).
  db.exec(`
    CREATE TABLE IF NOT EXISTS users (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      name TEXT NOT NULL,
      email TEXT NOT NULL UNIQUE,
      password_hash TEXT NOT NULL,
      role TEXT NOT NULL CHECK (role IN ('admin','counsellor')),
      created_at TEXT NOT NULL
    );
  `);

  // Mirrors the target Supabase `students` schema, extended with:
  // academic_background/career_goals/migration_intent (2.3 recommendation
  // inputs), application_status (2.5 status explainer), assigned/suggested
  // counsellor + last_contacted_at + followup_* (2.2 assignment, 2.7 CRM
  // assistant). `session_id` is an internal addition needed to link a chat
  // session back to its profile.
  db.exec(`
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
    );
  `);

  // Migration step for any `students` table created before these columns
  // existed — see ensureColumn() doc comment above.
  ensureColumn(db, "students", "reference_code", "TEXT");
  ensureColumn(db, "students", "academic_background", "TEXT");
  ensureColumn(db, "students", "career_goals", "TEXT");
  ensureColumn(db, "students", "migration_intent", "TEXT");
  ensureColumn(db, "students", "application_status", "TEXT NOT NULL DEFAULT 'not_started'");
  ensureColumn(db, "students", "application_status_updated_at", "TEXT");
  ensureColumn(db, "students", "assigned_counsellor_id", "INTEGER REFERENCES users(id)");
  ensureColumn(db, "students", "suggested_counsellor_id", "INTEGER REFERENCES users(id)");
  ensureColumn(db, "students", "last_contacted_at", "TEXT");
  ensureColumn(db, "students", "followup_suggestion", "TEXT");
  ensureColumn(db, "students", "followup_action", "TEXT");
  ensureColumn(db, "students", "followup_timing", "TEXT");
  ensureColumn(db, "students", "followup_generated_at", "TEXT");
  ensureColumn(db, "students", "study_path", "TEXT");
  ensureColumn(db, "students", "study_path_generated_at", "TEXT");

  db.exec(`CREATE INDEX IF NOT EXISTS idx_students_status ON students(status);`);
  db.exec(`CREATE INDEX IF NOT EXISTS idx_students_score ON students(score DESC);`);
  db.exec(`CREATE INDEX IF NOT EXISTS idx_students_created_at ON students(created_at);`);
  db.exec(`CREATE INDEX IF NOT EXISTS idx_students_assigned ON students(assigned_counsellor_id);`);
  // UNIQUE enforced via index rather than an inline column constraint — ALTER
  // TABLE ADD COLUMN (used by ensureColumn() above for pre-existing DBs)
  // can't add UNIQUE inline, so both the fresh-create and migration paths
  // go through this same index to stay consistent.
  db.exec(`CREATE UNIQUE INDEX IF NOT EXISTS idx_students_reference_code ON students(reference_code);`);

  // Mirrors the target Supabase `courses` schema. Seeded separately via
  // `npm run seed-courses` (backend/data/seed_courses.sql) — not created empty
  // and left that way, since course matching depends on this being populated.
  db.exec(`
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
    );
  `);
  db.exec(`CREATE INDEX IF NOT EXISTS idx_courses_ielts ON courses(ielts_required);`);
  db.exec(`CREATE INDEX IF NOT EXISTS idx_courses_fee ON courses(fee_per_year);`);
  db.exec(`CREATE INDEX IF NOT EXISTS idx_courses_country ON courses(country);`);

  return db;
}

// NOTE: intentionally does NOT touch `students`, `courses`, or `users` —
// ingestion is a PDF-knowledge-base rebuild only. Do not add DROP/CREATE for
// those tables here; that would delete captured leads / the course catalog /
// user accounts every time `npm run ingest` runs.
export function resetSchema(): void {
  const database = getDb();
  database.exec(`DROP TABLE IF EXISTS chunks;`);
  database.exec(`DROP TABLE IF EXISTS vec_chunks;`);
  database.exec(`
    CREATE TABLE chunks (
      id INTEGER PRIMARY KEY,
      text TEXT NOT NULL,
      document TEXT NOT NULL,
      page INTEGER NOT NULL,
      chunk_index INTEGER NOT NULL
    );
  `);
  database.exec(`
    CREATE VIRTUAL TABLE vec_chunks USING vec0(
      embedding float[${EMBEDDING_DIMENSION}] distance_metric=cosine
    );
  `);
}

// ---------------------------------------------------------------------------
// Users / auth
// ---------------------------------------------------------------------------

export type UserRole = "admin" | "counsellor";

export interface UserRow {
  id: number;
  name: string;
  email: string;
  password_hash: string;
  role: UserRole;
  created_at: string;
}

export function createUser(
  database: Database.Database,
  input: { name: string; email: string; passwordHash: string; role: UserRole },
): UserRow {
  return database
    .prepare(
      `INSERT INTO users (name, email, password_hash, role, created_at) VALUES (?, ?, ?, ?, ?) RETURNING *`,
    )
    .get(input.name, input.email, input.passwordHash, input.role, new Date().toISOString()) as UserRow;
}

export function getUserByEmail(database: Database.Database, email: string): UserRow | undefined {
  return database.prepare(`SELECT * FROM users WHERE email = ?`).get(email) as UserRow | undefined;
}

export function getUserById(database: Database.Database, id: number): UserRow | undefined {
  return database.prepare(`SELECT * FROM users WHERE id = ?`).get(id) as UserRow | undefined;
}

export function listCounsellors(database: Database.Database): UserRow[] {
  return database.prepare(`SELECT * FROM users WHERE role = 'counsellor' ORDER BY name`).all() as UserRow[];
}

/** Least-loaded counsellor by count of currently-assigned students — a suggestion, not an auto-assignment. */
export function suggestCounsellor(database: Database.Database): UserRow | undefined {
  return database
    .prepare(
      `SELECT u.* FROM users u
       LEFT JOIN students s ON s.assigned_counsellor_id = u.id
       WHERE u.role = 'counsellor'
       GROUP BY u.id
       ORDER BY COUNT(s.id) ASC, u.id ASC
       LIMIT 1`,
    )
    .get() as UserRow | undefined;
}

// ---------------------------------------------------------------------------
// Students
// ---------------------------------------------------------------------------

export type LeadStatus = "Hot" | "Warm" | "Cold";
export type ApplicationStatus =
  | "not_started"
  | "documents_pending"
  | "submitted"
  | "under_review"
  | "offer_received"
  | "visa_processing"
  | "enrolled"
  | "rejected"
  | "deferred";

export const APPLICATION_STATUSES: ApplicationStatus[] = [
  "not_started",
  "documents_pending",
  "submitted",
  "under_review",
  "offer_received",
  "visa_processing",
  "enrolled",
  "rejected",
  "deferred",
];

// 24 letters + 8 digits, excluding visually-ambiguous O/0/I/1 — a code a
// student can read off an email/SMS and retype without transcription errors.
const REFERENCE_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789";

// 256 % 32 === 0, so byte-to-symbol mapping below is uniform (no modulo bias).
function generateReferenceCode(): string {
  const bytes = crypto.randomBytes(8);
  let code = "";
  for (let i = 0; i < bytes.length; i++) {
    code += REFERENCE_CODE_ALPHABET[bytes[i] % REFERENCE_CODE_ALPHABET.length];
  }
  return `AIEC-${code}`;
}

export interface StudentRow {
  id: number;
  session_id: string;
  reference_code: string | null;
  name: string;
  email: string | null;
  phone: string | null;
  gpa: number;
  ielts: number;
  budget: number;
  gap: number;
  academic_background: string | null;
  career_goals: string | null;
  migration_intent: string | null;
  preferred_country: string | null;
  score: number;
  status: LeadStatus;
  countries: string | null;
  ai_response: string | null;
  next_steps: string | null;
  counsellor_notes: string | null;
  documents: string | null;
  application_status: ApplicationStatus;
  application_status_updated_at: string | null;
  assigned_counsellor_id: number | null;
  suggested_counsellor_id: number | null;
  last_contacted_at: string | null;
  followup_suggestion: string | null;
  followup_action: string | null;
  followup_timing: string | null;
  followup_generated_at: string | null;
  study_path: string | null;
  study_path_generated_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface UpsertStudentInput {
  sessionId: string;
  name: string;
  email?: string | null;
  phone?: string | null;
  gpa: number;
  ielts: number;
  budget: number;
  gap: number;
  academicBackground?: string | null;
  careerGoals?: string | null;
  migrationIntent?: string | null;
  preferredCountry?: string | null;
  score: number;
  status: LeadStatus;
  countries?: string | null;
  aiResponse?: string | null;
  nextSteps?: string | null;
  suggestedCounsellorId?: number | null;
}

export function upsertStudent(database: Database.Database, input: UpsertStudentInput): StudentRow {
  const now = new Date().toISOString();
  // Assigned once at first insert, then preserved across edits — looked up
  // explicitly (rather than generated fresh every call) so we never depend
  // on ON CONFLICT's specific-column semantics to protect an *unrelated*
  // UNIQUE constraint (reference_code) from a spurious collision error.
  const existing = database
    .prepare(`SELECT reference_code FROM students WHERE session_id = ?`)
    .get(input.sessionId) as { reference_code: string | null } | undefined;
  const referenceCode = existing?.reference_code ?? generateReferenceCode();

  return database
    .prepare(
      `INSERT INTO students (session_id, reference_code, name, email, phone, gpa, ielts, budget, gap,
                             academic_background, career_goals, migration_intent,
                             preferred_country, score, status, countries, ai_response, next_steps,
                             suggested_counsellor_id, created_at, updated_at)
       VALUES (@sessionId, @referenceCode, @name, @email, @phone, @gpa, @ielts, @budget, @gap,
               @academicBackground, @careerGoals, @migrationIntent,
               @preferredCountry, @score, @status, @countries, @aiResponse, @nextSteps,
               @suggestedCounsellorId, @now, @now)
       ON CONFLICT(session_id) DO UPDATE SET
         name = excluded.name, email = excluded.email, phone = excluded.phone,
         gpa = excluded.gpa, ielts = excluded.ielts, budget = excluded.budget, gap = excluded.gap,
         academic_background = excluded.academic_background, career_goals = excluded.career_goals,
         migration_intent = excluded.migration_intent,
         preferred_country = excluded.preferred_country, score = excluded.score, status = excluded.status,
         countries = excluded.countries, ai_response = excluded.ai_response, next_steps = excluded.next_steps,
         suggested_counsellor_id = excluded.suggested_counsellor_id, updated_at = excluded.updated_at
       RETURNING *;`,
    )
    .get({
      ...input,
      referenceCode,
      email: input.email ?? null,
      phone: input.phone ?? null,
      academicBackground: input.academicBackground ?? null,
      careerGoals: input.careerGoals ?? null,
      migrationIntent: input.migrationIntent ?? null,
      preferredCountry: input.preferredCountry ?? null,
      countries: input.countries ?? null,
      aiResponse: input.aiResponse ?? null,
      nextSteps: input.nextSteps ?? null,
      suggestedCounsellorId: input.suggestedCounsellorId ?? null,
      now,
    }) as StudentRow;
}

export function getStudentByReferenceCode(database: Database.Database, referenceCode: string): StudentRow | undefined {
  return database.prepare(`SELECT * FROM students WHERE reference_code = ?`).get(referenceCode) as
    | StudentRow
    | undefined;
}

export function getStudentBySessionId(database: Database.Database, sessionId: string): StudentRow | undefined {
  return database.prepare(`SELECT * FROM students WHERE session_id = ?`).get(sessionId) as StudentRow | undefined;
}

export function getStudentById(database: Database.Database, id: number): StudentRow | undefined {
  return database.prepare(`SELECT * FROM students WHERE id = ?`).get(id) as StudentRow | undefined;
}

export function listStudents(
  database: Database.Database,
  opts: { status?: string; sort?: "asc" | "desc"; counsellorId?: number },
): StudentRow[] {
  const order = opts.sort === "asc" ? "ASC" : "DESC";
  const clauses: string[] = [];
  const params: Record<string, unknown> = {};
  if (opts.status) {
    clauses.push("status = @status");
    params.status = opts.status;
  }
  if (typeof opts.counsellorId === "number") {
    // A counsellor's view = leads already assigned to them, PLUS unassigned
    // leads the suggestion engine pointed at them (so they have something to
    // claim) — not a plain equality filter, or newly-submitted leads would
    // never be visible to the counsellor suggestCounsellor() picked.
    clauses.push(
      `(assigned_counsellor_id = @counsellorId OR (assigned_counsellor_id IS NULL AND suggested_counsellor_id = @counsellorId))`,
    );
    params.counsellorId = opts.counsellorId;
  }
  const where = clauses.length > 0 ? `WHERE ${clauses.join(" AND ")}` : "";
  return database.prepare(`SELECT * FROM students ${where} ORDER BY created_at ${order}`).all(params) as StudentRow[];
}

export function updateCounsellorNotes(database: Database.Database, id: number, notes: string): StudentRow | undefined {
  return database
    .prepare(`UPDATE students SET counsellor_notes = ?, updated_at = ? WHERE id = ? RETURNING *`)
    .get(notes, new Date().toISOString(), id) as StudentRow | undefined;
}

export function assignCounsellor(database: Database.Database, id: number, counsellorId: number): StudentRow | undefined {
  const now = new Date().toISOString();
  return database
    .prepare(`UPDATE students SET assigned_counsellor_id = ?, updated_at = ? WHERE id = ? RETURNING *`)
    .get(counsellorId, now, id) as StudentRow | undefined;
}

export function markContacted(database: Database.Database, id: number): StudentRow | undefined {
  const now = new Date().toISOString();
  return database
    .prepare(`UPDATE students SET last_contacted_at = ?, updated_at = ? WHERE id = ? RETURNING *`)
    .get(now, now, id) as StudentRow | undefined;
}

export function updateApplicationStatus(
  database: Database.Database,
  id: number,
  applicationStatus: ApplicationStatus,
): StudentRow | undefined {
  const now = new Date().toISOString();
  return database
    .prepare(
      `UPDATE students SET application_status = ?, application_status_updated_at = ?, updated_at = ? WHERE id = ? RETURNING *`,
    )
    .get(applicationStatus, now, now, id) as StudentRow | undefined;
}

export function saveFollowupSuggestion(
  database: Database.Database,
  id: number,
  input: { suggestion: string; action: string; timing: string },
): StudentRow | undefined {
  const now = new Date().toISOString();
  return database
    .prepare(
      `UPDATE students SET followup_suggestion = ?, followup_action = ?, followup_timing = ?, followup_generated_at = ?, updated_at = ? WHERE id = ? RETURNING *`,
    )
    .get(input.suggestion, input.action, input.timing, now, now, id) as StudentRow | undefined;
}

/** Cached like followup_suggestion — generated on-demand, not automatically, to keep Claude spend predictable. */
export function saveStudyPath(database: Database.Database, id: number, stagesJson: string): StudentRow | undefined {
  const now = new Date().toISOString();
  return database
    .prepare(`UPDATE students SET study_path = ?, study_path_generated_at = ?, updated_at = ? WHERE id = ? RETURNING *`)
    .get(stagesJson, now, now, id) as StudentRow | undefined;
}

/**
 * Appends a document-verification record to a student's `documents` JSON
 * array (stored as TEXT — SQLite has no native JSONB). No-op (returns
 * undefined) if the sessionId has no matching student yet — the caller still
 * returns the verification result to the uploader either way.
 */
export function appendDocumentRecord(
  database: Database.Database,
  sessionId: string,
  record: Record<string, unknown>,
): StudentRow | undefined {
  const student = getStudentBySessionId(database, sessionId);
  if (!student) return undefined;

  const existing: Record<string, unknown>[] = student.documents ? JSON.parse(student.documents) : [];
  existing.push(record);

  return database
    .prepare(`UPDATE students SET documents = ?, updated_at = ? WHERE session_id = ? RETURNING *`)
    .get(JSON.stringify(existing), new Date().toISOString(), sessionId) as StudentRow | undefined;
}

// ---------------------------------------------------------------------------
// Courses
// ---------------------------------------------------------------------------

export interface CourseRow {
  id: number;
  course_name: string;
  course_level: string;
  university: string | null;
  country: string;
  duration_years: number | null;
  ielts_required: number | null;
  fee_per_year: number | null;
  total_fee: number | null;
  fee_range: string | null;
  intake: string | null;
}

export interface CourseQueryFilters {
  countries?: string[];
  maxIelts?: number; // student's IELTS — matches courses requiring <= this
  maxFeePerYear?: number; // student's budget — matches courses costing <= this
  courseLevel?: string;
  courseLevels?: string[]; // used for soft academic-background eligibility filtering
  keyword?: string;
  limit?: number;
}

export function queryCourses(database: Database.Database, filters: CourseQueryFilters): CourseRow[] {
  const clauses: string[] = [];
  const params: Record<string, unknown> = {};

  if (filters.countries && filters.countries.length > 0) {
    const placeholders = filters.countries.map((_, i) => `@country${i}`).join(", ");
    clauses.push(`country IN (${placeholders})`);
    filters.countries.forEach((c, i) => {
      params[`country${i}`] = c;
    });
  }
  if (typeof filters.maxIelts === "number") {
    clauses.push(`(ielts_required IS NULL OR ielts_required <= @maxIelts)`);
    params.maxIelts = filters.maxIelts;
  }
  if (typeof filters.maxFeePerYear === "number") {
    clauses.push(`(fee_per_year IS NULL OR fee_per_year <= @maxFeePerYear)`);
    params.maxFeePerYear = filters.maxFeePerYear;
  }
  if (filters.courseLevel) {
    clauses.push(`course_level = @courseLevel`);
    params.courseLevel = filters.courseLevel;
  }
  if (filters.courseLevels && filters.courseLevels.length > 0) {
    const placeholders = filters.courseLevels.map((_, i) => `@level${i}`).join(", ");
    clauses.push(`course_level IN (${placeholders})`);
    filters.courseLevels.forEach((lvl, i) => {
      params[`level${i}`] = lvl;
    });
  }
  if (filters.keyword) {
    clauses.push(`course_name LIKE @keyword`);
    params.keyword = `%${filters.keyword}%`;
  }

  const where = clauses.length > 0 ? `WHERE ${clauses.join(" AND ")}` : "";
  const limit = Math.min(filters.limit ?? 20, 50);

  return database
    .prepare(
      `SELECT id, course_name, course_level, university, country, duration_years,
              ielts_required, fee_per_year, total_fee, fee_range, intake
       FROM courses ${where}
       ORDER BY fee_per_year ASC
       LIMIT ${limit}`,
    )
    .all(params) as CourseRow[];
}

export function getCourseCountsByCountry(database: Database.Database): { country: string; count: number }[] {
  return database
    .prepare(`SELECT country, COUNT(*) as count FROM courses GROUP BY country ORDER BY country`)
    .all() as { country: string; count: number }[];
}
