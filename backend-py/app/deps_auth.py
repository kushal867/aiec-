from fastapi import Header, HTTPException

from app.services.auth import AuthTokenPayload, verify_token


def require_auth(authorization: str | None = Header(default=None)) -> AuthTokenPayload:
    """Requires a valid Bearer token (any role — admin or counsellor)."""
    token = authorization[len("Bearer ") :] if authorization and authorization.startswith("Bearer ") else None
    if not token:
        raise HTTPException(status_code=401, detail="Missing Authorization header")
    payload = verify_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    return payload


def require_admin_role(user: AuthTokenPayload) -> None:
    """Requires a valid token AND the 'admin' role. Call after require_auth."""
    if user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Admin role required")
