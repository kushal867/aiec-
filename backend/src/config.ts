import "dotenv/config";
import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";

function requireEnv(name: string): string {
  const value = process.env[name];
  if (!value) {
    throw new Error(`Missing required environment variable: ${name}`);
  }
  return value;
}

/**
 * A JWT secret must never be hardcoded in source. If JWT_SECRET isn't set,
 * generate a random one and persist it locally so tokens survive restarts
 * (but not commits — data/ is gitignored). Set JWT_SECRET explicitly for any
 * real deployment (so restarts on a redeploy don't invalidate every session).
 */
function resolveJwtSecret(): string {
  if (process.env.JWT_SECRET) return process.env.JWT_SECRET;

  const secretPath = path.resolve(process.cwd(), process.env.DATABASE_PATH || "./data/knowledge.db", "..", ".jwt-secret");
  if (fs.existsSync(secretPath)) {
    return fs.readFileSync(secretPath, "utf8").trim();
  }
  const generated = crypto.randomBytes(48).toString("hex");
  fs.mkdirSync(path.dirname(secretPath), { recursive: true });
  fs.writeFileSync(secretPath, generated, { mode: 0o600 });
  return generated;
}

export const config = {
  anthropicApiKey: requireEnv("ANTHROPIC_API_KEY"),
  claudeModel: process.env.CLAUDE_MODEL || "claude-sonnet-5",
  // Runs locally via @huggingface/transformers (ONNX/CPU) — no API key, no cost.
  embeddingModel: process.env.EMBEDDING_MODEL || "Xenova/bge-small-en-v1.5",
  databasePath: path.resolve(process.cwd(), process.env.DATABASE_PATH || "./data/knowledge.db"),
  port: Number(process.env.PORT || 3001),
  allowedOrigin: process.env.ALLOWED_ORIGIN || "*",
  // Separate from allowedOrigin: the CRM dashboard is a different internal
  // app on its own origin (not the client's public site), so it needs its
  // own CORS allowance rather than sharing the public widget's origin.
  adminAllowedOrigin: process.env.ADMIN_ALLOWED_ORIGIN || "http://localhost:3002",
  topK: Number(process.env.TOP_K || 5),
  similarityThreshold: Number(process.env.SIMILARITY_THRESHOLD || 0.5),
  rateLimitMax: Number(process.env.RATE_LIMIT_MAX || 20),
  profileRateLimitMax: Number(process.env.PROFILE_RATE_LIMIT_MAX || 5),
  documentRateLimitMax: Number(process.env.DOCUMENT_RATE_LIMIT_MAX || 8),
  uploadsDir: path.resolve(process.cwd(), process.env.UPLOADS_DIR || "./data/uploads"),
  jwtSecret: resolveJwtSecret(),
  jwtExpiresIn: process.env.JWT_EXPIRES_IN || "12h",
};
