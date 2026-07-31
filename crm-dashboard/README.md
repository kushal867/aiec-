# AIEC Global — CRM Leads Dashboard (internal tool)

Shows every lead captured via the "Analyse My Profile" flow — Hot/Warm/Cold classification, application status, document checklist, counsellor assignment, and AI follow-up suggestions — sourced from the backend's `/api/admin/*` endpoints.

Gated by real login (JWT, `POST /api/auth/login` on the backend). Admins see and manage every lead; counsellors only see leads assigned to them plus unassigned leads the system suggested for them to claim.

This is an **internal AIEC staff tool**, not part of the client's public website — deploy it separately (e.g. a different subdomain or path on the same VPS).

## Setup

```bash
npm install
cp .env.local.example .env.local   # point NEXT_PUBLIC_ADMIN_API_URL at the backend
npm run dev     # http://localhost:3002
```

Before first login, bootstrap accounts on the backend:

```bash
cd ../backend
npm run seed-users   # prints the admin/counsellor passwords once — save them
```
