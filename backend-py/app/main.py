from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.config import config
from app.cors import PathScopedCORSMiddleware
from app.limiter import limiter
from app.routers import admin_leads, auth, chat, documents, health, profile, status


@asynccontextmanager
async def _lifespan(app: FastAPI):
    print(f"AIEC chat backend listening on port {config.port}")
    yield


app = FastAPI(title="AIEC chat backend", lifespan=_lifespan)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


# The original Node/Express API always returns errors as {"error": "..."}
# (occasionally with a "details" field for validation failures) — every
# frontend (widget, CRM dashboard) reads `body.error` directly on a failed
# fetch, with a generic fallback message if it's missing. FastAPI's default
# HTTPException/validation-error bodies use {"detail": ...} instead, which
# would silently degrade every error message in the UI to a generic fallback
# without ever raising an exception, so it wouldn't be caught by testing —
# these two handlers restore the original {"error": ...} shape.
@app.exception_handler(HTTPException)
async def _http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content={"error": exc.detail}, headers=exc.headers)


def _humanize_validation_errors(errors: list[dict]) -> str:
    """Pydantic's raw error list is only surfaced via the "details" field,
    which no frontend actually reads (see _http_exception_handler's
    docstring) — every validation failure showed the same unhelpful flat
    "Invalid request body" regardless of which field or why. Building a
    specific summary into "error" itself makes it actionable without
    needing every frontend call site to be changed."""
    parts = []
    for err in errors:
        # loc is like ("body", "budget") — "body" itself isn't meaningful to
        # someone filling out a form, only the field name(s) after it are.
        field = ".".join(str(p) for p in err["loc"][1:]) or "request"
        parts.append(f"{field}: {err['msg']}")
    return "; ".join(parts) or "Invalid request body"


@app.exception_handler(RequestValidationError)
async def _validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    errors = jsonable_encoder(exc.errors())
    return JSONResponse(status_code=400, content={"error": _humanize_validation_errors(errors), "details": errors})


app.add_middleware(PathScopedCORSMiddleware)

app.include_router(health.router, prefix="/api")
app.include_router(chat.router, prefix="/api")
app.include_router(profile.router, prefix="/api")
app.include_router(documents.router, prefix="/api")
app.include_router(status.router, prefix="/api")
app.include_router(auth.router, prefix="/api")
app.include_router(admin_leads.router, prefix="/api")
