import os
import secrets

from app.db import create_user, get_db, get_user_by_email
from app.services.auth import hash_password


def _random_password() -> str:
    return secrets.token_urlsafe(9)


def _ensure_user(name: str, email: str, role: str, env_password_var: str) -> None:
    conn = get_db()
    existing = get_user_by_email(conn, email)
    if existing:
        print(f"{role} already exists: {email} (skipped)")
        return
    password = os.environ.get(env_password_var) or _random_password()
    password_hash = hash_password(password)
    create_user(conn, name, email, password_hash, role)
    print(f"Created {role}: {email} / {password}  (save this — it will not be shown again)")


def main() -> None:
    _ensure_user("Admin", os.environ.get("ADMIN_EMAIL") or "admin@aiecglobal.com", "admin", "ADMIN_PASSWORD")
    _ensure_user(
        "Counsellor",
        os.environ.get("COUNSELLOR_EMAIL") or "counsellor@aiecglobal.com",
        "counsellor",
        "COUNSELLOR_PASSWORD",
    )


if __name__ == "__main__":
    main()
