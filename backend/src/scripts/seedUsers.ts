import crypto from "node:crypto";
import { getDb, createUser, getUserByEmail } from "../services/db";
import { hashPassword } from "../services/auth";

function randomPassword(): string {
  return crypto.randomBytes(9).toString("base64url");
}

async function ensureUser(name: string, email: string, role: "admin" | "counsellor", envPasswordVar: string) {
  const db = getDb();
  const existing = getUserByEmail(db, email);
  if (existing) {
    console.log(`${role} already exists: ${email} (skipped)`);
    return;
  }
  const password = process.env[envPasswordVar] || randomPassword();
  const passwordHash = await hashPassword(password);
  createUser(db, { name, email, passwordHash, role });
  console.log(`Created ${role}: ${email} / ${password}  (save this — it will not be shown again)`);
}

async function main() {
  await ensureUser("Admin", process.env.ADMIN_EMAIL || "admin@aiecglobal.com", "admin", "ADMIN_PASSWORD");
  await ensureUser(
    "Counsellor",
    process.env.COUNSELLOR_EMAIL || "counsellor@aiecglobal.com",
    "counsellor",
    "COUNSELLOR_PASSWORD",
  );
}

main().catch((err) => {
  console.error("Seeding users failed:", err);
  process.exit(1);
});
