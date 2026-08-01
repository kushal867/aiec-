from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.config import config

# Mirrors server.ts's path-scoped CORS: the public routes (chat widget /
# status checker on the client's site) get `allowedOrigin`; admin/auth
# routes (the internal CRM dashboard, a different origin) get
# `adminAllowedOrigin`. A single global CORS policy would either leak the
# admin origin onto public routes or block the CRM dashboard — never use
# FastAPI's plain CORSMiddleware here.
_ADMIN_PREFIXES = ("/api/admin", "/api/auth")


def _origin_for_path(path: str) -> str:
    if path.startswith(_ADMIN_PREFIXES):
        return config.admin_allowed_origin
    return config.allowed_origin


class PathScopedCORSMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        origin = _origin_for_path(request.url.path)

        if request.method == "OPTIONS":
            response = Response(status_code=204)
        else:
            response = await call_next(request)

        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, PATCH, OPTIONS"
        response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
        response.headers["Vary"] = "Origin"
        return response
