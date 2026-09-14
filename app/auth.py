"""Simple API token auth for single-user DropScore."""

import os
from fastapi import Request, HTTPException, status
from starlette.middleware.base import BaseHTTPMiddleware

API_TOKEN = os.getenv("API_TOKEN", "")


class TokenAuthMiddleware(BaseHTTPMiddleware):
    """Check API token in X-API-Key header (web UI passes it via query param or cookie)."""

    async def dispatch(self, request: Request, call_next):
        # Allow docs and openapi without token
        if request.url.path in ("/docs", "/openapi.json", "/redoc"):
            return await call_next(request)

        # Token via header
        token = request.headers.get("X-API-Key", "")
        if not token:
            token = request.query_params.get("token", "")

        if API_TOKEN and token != API_TOKEN:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or missing API token",
            )

        return await call_next(request)