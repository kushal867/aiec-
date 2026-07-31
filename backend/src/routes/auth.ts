import { Router } from "express";
import cors from "cors";
import rateLimit from "express-rate-limit";
import { z } from "zod";
import { getDb, getUserByEmail } from "../services/db";
import { verifyPassword, signToken } from "../services/auth";
import { config } from "../config";

export const authRouter = Router();

const authCors = cors({ origin: config.adminAllowedOrigin });

// Login attempts are a brute-force target — keep this tight regardless of
// the general admin traffic pattern.
const loginLimiter = rateLimit({
  windowMs: 60 * 1000,
  max: 10,
  standardHeaders: true,
  legacyHeaders: false,
});

const loginSchema = z.object({
  email: z.string().email(),
  password: z.string().min(1),
});

// The browser preflights POST /auth/login with an OPTIONS request (JSON
// body => not a "simple" request). `.post(path, authCors, ...)` only ever
// matches the POST method, so without this the preflight hits no route,
// gets no CORS headers, and the browser fails the real request client-side
// with an opaque "Failed to fetch" — never even visible on the server.
authRouter.options("/auth/login", authCors);

authRouter.post("/auth/login", authCors, loginLimiter, async (req, res) => {
  const parsed = loginSchema.safeParse(req.body);
  if (!parsed.success) {
    res.status(400).json({ error: "Invalid request body" });
    return;
  }
  const { email, password } = parsed.data;

  const user = getUserByEmail(getDb(), email);
  if (!user) {
    res.status(401).json({ error: "Invalid email or password" });
    return;
  }
  const valid = await verifyPassword(password, user.password_hash);
  if (!valid) {
    res.status(401).json({ error: "Invalid email or password" });
    return;
  }

  const token = signToken({ userId: user.id, role: user.role, name: user.name });
  res.json({ token, user: { id: user.id, name: user.name, email: user.email, role: user.role } });
});
