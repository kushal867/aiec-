import logging
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app.limiter import limiter
from app.config import config
from app.db import get_db, get_student_by_session_id
from app.services.chat_answer import NO_INFO_REPLY, generate_answer
from app.services.lead_scoring import student_row_to_profile
from app.services.retrieval import retrieve_relevant_chunks

router = APIRouter()
logger = logging.getLogger("aiec.chat")


class ChatMessageIn(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=4000)


class ChatRequest(BaseModel):
    messages: list[ChatMessageIn] = Field(min_length=1, max_length=50)
    sessionId: str | None = Field(default=None, max_length=200)


@router.post("/chat")
@limiter.limit(f"{config.rate_limit_max}/minute")
def chat(request: Request, body: ChatRequest):
    messages = body.messages

    # No LLM call anymore, so there's no first-message-role API constraint to
    # satisfy — but the widget still seeds a leading assistant greeting, so
    # this trimming stays to find the latest actual user message.
    first_user_idx = next((i for i, m in enumerate(messages) if m.role == "user"), -1)
    trimmed_messages = messages[first_user_idx:] if first_user_idx != -1 else []

    latest_user_message = next((m for m in reversed(trimmed_messages) if m.role == "user"), None)
    if not latest_user_message:
        raise HTTPException(status_code=400, detail="No user message found in request")

    conn = get_db()
    student = get_student_by_session_id(conn, body.sessionId) if body.sessionId else None
    profile = student_row_to_profile(student) if student else None

    try:
        retrieved_chunks = retrieve_relevant_chunks(latest_user_message.content)
        result = generate_answer(latest_user_message.content, retrieved_chunks, profile)
    except Exception:
        logger.exception("[chat] request failed")
        raise HTTPException(status_code=500, detail="Failed to generate a response. Please try again.")

    logger.info("[chat] session=%s student_found=%s", body.sessionId or "-", bool(student))
    if result.reply == NO_INFO_REPLY:
        # The single most useful signal for improving chat_answer.py's
        # coverage going forward: what real students actually typed that we
        # had nothing for, instead of guessing likely phrasings ourselves.
        # Session id, not any name/PII, and only logged for the genuine
        # "found nothing at all" case, not every message.
        logger.warning("[chat] no-info fallback session=%s message=%r", body.sessionId or "-", latest_user_message.content)

    return {
        "reply": result.reply,
        "sources": result.sources,
        "coursesReferenced": result.coursesReferenced,
        "sessionId": body.sessionId,
    }
