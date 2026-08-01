from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, EmailStr

from app.limiter import limiter
from app.db import get_db, get_user_by_email
from app.services.auth import sign_token, verify_password

router = APIRouter()
# Login attempts are a brute-force target — keep this tight regardless of the
# general admin traffic pattern.


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = ""


@router.post("/auth/login")
@limiter.limit("10/minute")
def login(request: Request, body: LoginRequest):
    if not body.password:
        raise HTTPException(status_code=400, detail="Invalid request body")

    user = get_user_by_email(get_db(), body.email)
    if not user or not verify_password(body.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid email or password")

    token = sign_token({"userId": user["id"], "role": user["role"], "name": user["name"]})
    return {"token": token, "user": {"id": user["id"], "name": user["name"], "email": user["email"], "role": user["role"]}}
