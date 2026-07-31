import express from "express";
import cors from "cors";
import { config } from "./config";
import { chatRouter } from "./routes/chat";
import { healthRouter } from "./routes/health";
import { profileRouter } from "./routes/profile";
import { documentsRouter } from "./routes/documents";
import { adminLeadsRouter } from "./routes/adminLeads";
import { authRouter } from "./routes/auth";
import { statusRouter } from "./routes/status";

const app = express();

app.use(express.json({ limit: "1mb" }));

// Default CORS for the public routes (chat widget / counsellor panel on the
// client's site) only. Path-scoped rather than blanket `app.use(cors(...))`
// — an unscoped instance matches every method including OPTIONS on every
// path, so it would intercept and answer /api/admin/* and /api/auth/*
// preflight requests too (with the WRONG origin allowlist), before those
// routers' own CORS middleware ever got a chance to run. The admin/auth
// routers own their own, different-origin CORS attached directly to their
// routes (see adminLeads.ts / auth.ts) — this must never shadow that.
app.use(["/api/chat", "/api/profile", "/api/documents", "/api/status"], cors({ origin: config.allowedOrigin }));

app.use("/api", healthRouter);
app.use("/api", chatRouter); // rate limit scoped to its own route in chat.ts
app.use("/api", profileRouter); // rate limit scoped to its own route in profile.ts
app.use("/api", documentsRouter); // rate limit scoped to its own route in documents.ts
app.use("/api", statusRouter); // rate limit scoped to its own route in status.ts
app.use("/api", authRouter); // CORS + rate limit scoped to its own route in auth.ts
app.use("/api", adminLeadsRouter); // CORS + auth scoped to its own route in adminLeads.ts

app.listen(config.port, () => {
  console.log(`AIEC chat backend listening on port ${config.port}`);
});
