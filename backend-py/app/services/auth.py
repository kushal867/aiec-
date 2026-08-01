from datetime import datetime, timedelta, timezone
from typing import TypedDict

import bcrypt
import jwt

from app.config import config


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=10)).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))


class AuthTokenPayload(TypedDict):
    userId: int
    role: str
    name: str


def sign_token(payload: AuthTokenPayload) -> str:
    exp = datetime.now(timezone.utc) + timedelta(hours=config.jwt_expires_in_hours)
    return jwt.encode({**payload, "exp": exp}, config.jwt_secret, algorithm="HS256")


def verify_token(token: str) -> AuthTokenPayload | None:
    try:
        decoded = jwt.decode(token, config.jwt_secret, algorithms=["HS256"])
    except jwt.PyJWTError:
        return None
    return {"userId": decoded["userId"], "role": decoded["role"], "name": decoded["name"]}
