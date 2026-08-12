/** Generates a random session identifier.
 *
 * crypto.randomUUID() is undefined in non-secure contexts (plain HTTP —
 * realistic for a widget embedded on a client site that hasn't set up HTTPS
 * everywhere) and on older browsers. Calling it unguarded throws during
 * render, and since this runs at hook-init time with no ErrorBoundary above
 * it in a host page's tree, that crash used to be able to take down the
 * entire host page, not just this widget. */
export function generateSessionId(): string {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  // Fallback UUIDv4-shaped id. Not cryptographically strong, but a session
  // id only needs to be hard to guess, not withstand a targeted attack.
  return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0;
    const v = c === "x" ? r : (r & 0x3) | 0x8;
    return v.toString(16);
  });
}
