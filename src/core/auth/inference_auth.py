"""Require a configured key on every inference route, before any body is consumed."""
from __future__ import annotations

import hmac
import json


def _unauthorized(message):
    return {"error": {"message": message, "type": "invalid_request_error", "code": "invalid_api_key"}}


class InferenceAuthMiddleware:
    """Authenticate ``Authorization: Bearer`` / ``X-Api-Key`` on the inference paths only."""

    PATHS = {"/v1/chat/completions", "/v1/models"}

    def __init__(self, app, config):
        self.app = app
        self.config = config

    def _key(self):
        key = self.config.get("api_key") or ""
        return key if isinstance(key, str) else ""

    def _authorized(self, scope):
        key = self._key()
        if not key:
            return False
        supplied = []
        for name, value in scope.get("headers", ()):
            if name == b"authorization":
                text = value.decode("latin-1")
                if text[:7].lower() == "bearer ":
                    supplied.append(text[7:].strip())
            elif name == b"x-api-key":
                supplied.append(value.decode("latin-1").strip())
        return any(hmac.compare_digest(candidate.encode(), key.encode()) for candidate in supplied if candidate)

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http" or scope.get("path") not in self.PATHS:
            return await self.app(scope, receive, send)
        if self._authorized(scope):
            return await self.app(scope, receive, send)
        body = json.dumps(_unauthorized("缺少或无效的 API key")).encode("utf-8")
        await send({"type": "http.response.start", "status": 401, "headers": [
            (b"content-type", b"application/json; charset=utf-8"),
            (b"content-length", str(len(body)).encode()),
            (b"www-authenticate", b"Bearer"),
            (b"cache-control", b"no-store")]})
        await send({"type": "http.response.body", "body": body})
