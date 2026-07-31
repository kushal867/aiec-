# AIEC Global — AI Counsellor Chatbot + CRM

A RAG-grounded chat assistant for the "Chat to Counsellor" section of the AIEC Global website, a student profile → course-matching → recommendation flow backed by a real database of 406 courses across 16 countries, document upload + Claude vision verification, a student-facing application status portal, and an internal, role-gated CRM dashboard for lead qualification, counsellor assignment, and AI-assisted follow-ups. All course/fee/university facts come from the real course database or ingested PDFs — never invented.

## Structure

- `backend/` — Express + TypeScript API service:
  - RAG over ingested PDFs (visa rules, fees, institutional policy) for general policy Q&A
  - A real, structured course database (406 courses, 16 countries) for course/fee/university matching — see `backend/data/seed_courses.sql`
  - Rule-based Hot/Warm/Cold lead scoring, application-status explanations, and inactivity detection (cheap, instant, auditable — no LLM call)
  - Claude Sonnet 5 for chat (with a `search_courses` tool), structured profile reports, document vision verification, and follow-up message suggestions
  - JWT-based auth (bcrypt password hashes) with two roles: `admin` (sees/manages every lead) and `counsellor` (sees only their assigned + suggested leads)
- `widget/` — Embeddable React components for the client's existing Next.js/React site: `ChatWidget` (chat only), `CounsellorPanel` (profile form + chat + document upload, feeds the CRM — **the single consolidated interface**, not separate widgets stacked on a page), and `StatusChecker` (standalone application-status lookup by reference code, usable from any device).
- `crm-dashboard/` — **Internal** Next.js app (not part of the client's public site), gated by login. Leads table with Hot/Warm/Cold + application status, counsellor assignment/claiming, document checklist, inactivity flagging, and on-demand AI follow-up suggestions.
- `test-site/` — throwaway local harness for previewing the widget; not shipped anywhere.

## Backend setup

```bash
cd backend
npm install
cp .env.example .env
```

Edit `.env` and fill in:

- `ANTHROPIC_API_KEY` — your Claude API key
- `ALLOWED_ORIGIN` — the client's production domain (e.g. `https://aiecglobal.com`)
- `ADMIN_ALLOWED_ORIGIN` — the CRM dashboard's origin (separate from the public site)

Embeddings run entirely locally via `@huggingface/transformers` (no API key, no cost, no rate limits) — the model weights (~130MB) download once from the Hugging Face Hub on first run and are cached locally after that.

### 1. Seed the course database (required)

```bash
npm run seed-courses
```

Loads the real 406-course dataset (`backend/data/seed_courses.sql`) into the local database. This is the source of truth for all course/fee/university recommendations and the `search_courses` chat tool. Re-run this whenever the course catalog changes — it's a full rebuild and never touches captured student leads.

**Currently local (SQLite), designed to migrate to Supabase.** This project was built against a Supabase schema (`students`/`courses` tables with RLS) supplied for the real deployment. Since the Supabase project URL/service-role key weren't available while building, everything runs against an equivalent local SQLite schema instead — same column names/types, same behavior. Swapping in the real Supabase project later is a contained change (one new data-access implementation file + env vars), not a rewrite, once those credentials are available.

### 2. Add source PDFs (for general policy Q&A)

Drop the client's visa-rule / institutional-policy PDFs into `backend/data/pdfs/`, then:

```bash
npm run ingest
```

Re-run any time the PDFs change — full rebuild of the PDF knowledge base only. Never touches courses or leads (separate tables).

### 3. Seed initial admin/counsellor accounts (required for the CRM)

```bash
npm run seed-users
```

Creates `admin@aiecglobal.com` (role `admin`) and `counsellor@aiecglobal.com` (role `counsellor`) with randomly-generated passwords, printed **once** at creation time — save them (or set `ADMIN_PASSWORD`/`COUNSELLOR_PASSWORD` env vars beforehand to choose your own). Safe to re-run — skips any email that already exists.

### 4. Run the server

```bash
npm run dev     # local development, auto-reload
npm run build && npm start   # production
```

The API listens on `PORT` (default 3001):

```
POST /api/chat
{ "messages": [{ "role": "user", "content": "..." }], "sessionId": "optional" }
→ { "reply": "...", "sources": [...], "coursesReferenced": [...], "sessionId": "..." }
```
Grounded in both the ingested PDFs (policy questions) and the real course database via a `search_courses` tool Claude calls on demand (course/fee/university questions) — never answers these from general knowledge.

```
POST /api/profile/analyze
{ "fullName", "email", "phone", "gpa", "ielts", "budget", "gap",
  "academicBackground": "high_school"|"bachelors"|"masters"|"phd",
  "careerGoals": "optional free text",
  "migrationIntent": "study_only"|"study_then_work"|"migrate_permanently"|"undecided",
  "preferredCountry", "sessionId" }
→ { "reply": "...", "status": "Hot"|"Warm"|"Cold", "score": 0-10, "recommendedCountries": [...], "nextSteps": [...],
    "suggestedCounsellor": { "id", "name" } | null, "referenceCode": "AIEC-XXXXXXXX", "sessionId": "..." }
```
Matches the student against the real course database (Australia/Canada/USA prioritized by default; a single specified country is respected and alternatives aren't suggested unless that country has no viable matches; course *level* — Undergraduate/Postgraduate/Diploma/etc. — is soft-filtered by academic background, falling back to unfiltered results if too few remain), then Claude writes a structured report — fee margins, matching courses/universities, eligibility, career-goal/migration-intent framing where the data supports it, and a step-by-step action plan — grounded only in the actual matched courses. Also assigns a stable, student-shareable `referenceCode` (generated once, kept across profile edits) and a suggested (not auto-assigned) counsellor, picked as whoever currently has the fewest assigned students.

`sessionId` links a profile to later `/api/chat` turns — once a student analyzes their profile, follow-up chat questions (e.g. "what visa fee applies to me") automatically use their stated country/budget as context.

```
POST /api/documents/upload   (multipart/form-data)
  file: <image or PDF, max 10MB>
  documentType: "citizenship" | "marksheet" | "ielts_certificate"
  sessionId: "..."
→ { "documentType", "status": "valid"|"issues_found"|"unclear", "issues": [...], "extractedSummary", "message", "sessionId", "checklist": {...} }

GET /api/documents/checklist/:sessionId
→ { "sessionId", "checklist": { "items": [...], "missing": [...], "needsAttention": [...], "complete": bool } }
```
Claude vision checks the uploaded document before a counsellor ever sees it — legibility, whether it's actually the right document type, and (for marksheets/IELTS certificates) whether the GPA/IELTS score on the document matches what the student self-reported in their profile, flagging mismatches or expired IELTS results (>2 years old). Files are stored under `backend/data/uploads/{sessionId}/` (gitignored — real student documents, never commit these). Every response includes a **document-completeness checklist** across all 3 required types (not just the one just uploaded) — the "identify missing documents" requirement — computed from the most recent upload of each type, so a re-upload after a rejected scan supersedes the old result.

```
GET /api/status/:referenceCode
→ { "referenceCode", "name", "applicationStatus": { "status", "label", "description", "whatHappensNext", "isTerminal" },
    "documentChecklist": {...}, "updatedAt" }
```
Public, gated only by knowing the reference code (like a parcel tracker) — deliberately returns a minimal, student-safe projection and never the internal Hot/Warm/Cold score, counsellor notes, or contact info. Application-status explanations are rule-based (9 fixed statuses — a template lookup, not a Claude call), matching the cost/auditability reasoning already used for lead scoring.

```
POST /api/auth/login
{ "email", "password" } → { "token", "user": { "id", "name", "email", "role" } }
```
JWT auth (bcrypt-hashed passwords). Bootstrap accounts via `npm run seed-users` (see setup above). Tokens are sent as `Authorization: Bearer <token>` on every `/api/admin/*` request below.

```
GET  /api/admin/leads?status=Hot|Warm|Cold&sort=asc|desc&inactiveOnly=true
GET  /api/admin/counsellors
PATCH /api/admin/leads/:id/notes     { "notes": "..." }
PATCH /api/admin/leads/:id/status    { "applicationStatus": "not_started"|"documents_pending"|"submitted"|"under_review"|"offer_received"|"visa_processing"|"enrolled"|"rejected"|"deferred" }
POST  /api/admin/leads/:id/assign    { "counsellorId": number }
POST  /api/admin/leads/:id/contacted
POST  /api/admin/leads/:id/followup
```
Role-gated: **admins** see and can assign every lead to any counsellor; **counsellors** only see leads already assigned to them plus unassigned leads the suggestion engine pointed at them, and may only claim a lead for themselves (not reassign to a colleague or take one already owned by someone else). `inactiveOnly=true` filters to leads overdue for contact — thresholds are rule-based per Hot/Warm/Cold tier (2/5/14 days since last contact), never the terminal "enrolled" status. `POST .../followup` is the on-demand AI CRM assistant: Claude drafts a suggested action + a personalized message template (timing itself stays rule-based); never auto-generated in bulk, to keep cost predictable.

## Integrating into the client's site

The widget has no dependencies beyond `react`/`react-dom`. Copy `widget/src/` into the client's Next.js `components/` folder (e.g. `components/ChatWidget/`). **Add `"use client"` as the first line** of `ChatWidget.tsx`, `CounsellorPanel.tsx`, and `StatusChecker.tsx` — the client's Next.js App Router needs this since all three use React state/hooks and are typically imported directly from a Server Component page.

**Use `CounsellorPanel`** (profile form + chat + document upload, one consolidated interface — this is what drives the CRM and matches the reference design):
```tsx
import { CounsellorPanel } from "@/components/ChatWidget/CounsellorPanel";

<CounsellorPanel apiUrl={process.env.NEXT_PUBLIC_CHAT_API_URL!} />
```

**Use `StatusChecker`** (standalone — a student enters their reference code to check status from any device, no chat session required; suitable for a dedicated "Track My Application" page):
```tsx
import { StatusChecker } from "@/components/ChatWidget/StatusChecker";

<StatusChecker apiUrl={process.env.NEXT_PUBLIC_CHAT_API_URL!} />
```

`ChatWidget` (chat only, no profile form) is still exported separately for a floating site-wide chat bubble elsewhere on the client's site — just don't render both on the same page/section, which is redundant.

`CounsellorPanel`'s `countries` prop defaults to the 16 countries actually in the course database — edit it if the catalog changes.

## CRM dashboard

```bash
cd crm-dashboard
npm install
cp .env.local.example .env.local
npm run dev   # http://localhost:3002
```

Gated by login (`POST /api/auth/login`) — sign in with an account from `npm run seed-users`. Shows every lead captured via "Analyse My Profile": Hot/Warm/Cold + score, application status (editable dropdown), counsellor assignment (admin: reassign via dropdown; counsellor: claim button, scoped to their own + suggested leads), document checklist, inactivity flag, and on-demand "Generate suggestion" for the AI follow-up assistant, alongside each row's full AI report, recommended countries, next steps, and an editable counsellor-notes field.

## Lead scoring, application status, and inactivity — all rule-based

Deliberately not an LLM call (cheap, instant, auditable, zero hallucination risk on business-critical classification) — same reasoning applied consistently across three places:
- `backend/src/services/leadScoring.ts` — 10-point rubric across GPA, IELTS, budget, study gap, and country specificity, bucketed into Hot (≥7.0) / Warm (4.0–6.9) / Cold (<4.0), with a budget-viability override that caps a lead at "Warm" if the stated budget is unrealistically low regardless of academics.
- `backend/src/services/applicationStatus.ts` — plain-language label/description/next-step copy for each of the 9 fixed application statuses.
- `backend/src/services/crmAssistant.ts` — inactivity thresholds (days since last contact before a Hot/Warm/Cold lead is "overdue"). Only the AI follow-up **message** itself (`POST /api/admin/leads/:id/followup`) calls Claude, on demand, since personalized phrasing is where an LLM actually adds value over a template.

All thresholds/copy are named constants in those files — edit them directly to retune.

## Verifying it works

1. Run `npm run seed-courses` and `npm run ingest`; confirm both logged non-zero counts.
2. Submit a profile with `preferredCountry: "ANY"` — confirm the report prioritizes Australia/Canada/USA, states real fee margins, and includes other countries as alternatives.
3. Submit a profile with a specific country (e.g. Germany) — confirm the report focuses only on that country and does not suggest alternatives.
4. Ask the chat "what CS courses are available in Canada" — confirm it calls `search_courses` and returns real matching rows (check `coursesReferenced` in the response).
5. Ask a policy question genuinely covered by the ingested PDFs — confirm it cites a source.
6. Ask a chat follow-up after submitting a profile (e.g. "what visa fee applies to me") — confirm it uses your stated country without repeating it.
7. Check the CRM dashboard shows the lead with correct score/status, and that adding counsellor notes saves.
8. Re-run `npm run seed-courses` / `npm run ingest` — confirm leads and course counts are unaffected by each other's rebuild.
9. After analyzing a profile, upload a document in the "Document Check" section — try one that matches the student's stated GPA/IELTS (expect `valid`) and one that doesn't (expect `issues_found` with the mismatch named explicitly). Confirm the document checklist updates and both appear in the CRM dashboard's expanded lead row.
10. Log into the CRM as the seeded counsellor — confirm you only see leads assigned or suggested to you, and "Claim" works but assigning to a different counsellor is rejected (403).
11. Log in as admin — confirm you see every lead, can reassign via the dropdown, and can change application status; confirm the status change is reflected via `GET /api/status/:referenceCode` using the reference code returned from profile analysis.
12. Toggle "Inactive only" in the CRM — confirm it matches leads whose `last_contacted_at` exceeds their Hot/Warm/Cold threshold, and clears after "Mark contacted".
13. Click "Generate suggestion" on a lead — confirm a personalized suggested action + message draft appear, grounded in that student's actual status/documents/notes.

## Scope

Covers the AI counsellor chat (grounded in real course data + PDFs), student profile → course matching → recommendation (including academic background, career goals, and migration intent), document upload + Claude vision verification with a missing-documents checklist, a student-facing application status portal, and a role-gated CRM covering lead qualification, counsellor assignment, and AI-assisted follow-ups — client brief Sections 2.1–2.5, 2.7, and 4.3–4.4. Real Supabase wiring is pending project credentials (currently running on an equivalent local SQLite schema with identical column names/types).
