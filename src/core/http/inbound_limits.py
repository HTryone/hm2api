"""Bound inbound body size and concurrent inference requests before work is scheduled."""
from __future__ import annotations

import asyncio
import json

_INFERENCE_PATHS = {"/v1/chat/completions"}


def _error(status, message, code):
    return {"error": {"message": message, "type": "invalid_request_error", "code": code}}


class InboundBodyLimitMiddleware:
    """Reject an oversized declared body before the application buffers it."""

    def __init__(self, app, config):
        self.app = app
        self.config = config

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http" or scope.get("path") not in _INFERENCE_PATHS:
            return await self.app(scope, receive, send)
        maximum = int(self.config.get("max_inbound_bytes") or 0)
        if maximum <= 0:
            return await self.app(scope, receive, send)
        declared = 0
        for name, value in scope.get("headers", ()):
            if name == b"content-length":
                try:
                    declared = int(value)
                except ValueError:
                    declared = 0
        if declared > maximum:
            body = json.dumps(_error(413, "请求体超过大小上限", "request_too_large")).encode("utf-8")
            await send({"type": "http.response.start", "status": 413, "headers": [
                (b"content-type", b"application/json; charset=utf-8"),
                (b"content-length", str(len(body)).encode()),
                (b"cache-control", b"no-store")]})
            await send({"type": "http.response.body", "body": body})
            return
        await self.app(scope, receive, send)


class ConcurrencyLimitMiddleware:
    """Cap in-flight inference requests; excess callers are rejected immediately."""

    def __init__(self, app, config):
        self.app = app
        self.config = config
        self._semaphore = None
        self._limit = None

    def _acquire_semaphore(self):
        limit = int(self.config.get("max_concurrent") or 0)
        if limit <= 0:
            return None
        if self._semaphore is None or self._limit != limit:
            self._semaphore = asyncio.Semaphore(limit)
            self._limit = limit
        return self._semaphore

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http" or scope.get("path") not in _INFERENCE_PATHS:
            return await self.app(scope, receive, send)
        semaphore = self._acquire_semaphore()
        if semaphore is None:
            return await self.app(scope, receive, send)
        if semaphore.locked():
            body = json.dumps(_error(503, "网关并发已满，请稍后重试", "server_busy")).encode("utf-8")
            await send({"type": "http.response.start", "status": 503, "headers": [
                (b"content-type", b"application/json; charset=utf-8"),
                (b"content-length", str(len(body)).encode()),
                (b"retry-after", b"2"),
                (b"cache-control", b"no-store")]})
            await send({"type": "http.response.body", "body": body})
            return
        async with semaphore:
            await self.app(scope, receive, send)
