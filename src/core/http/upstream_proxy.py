"""Translate local OpenAI-compatible calls to the Loomy upstream and stream the reply back.

The Loomy endpoint already speaks the OpenAI chat protocol, so this module is a
faithful pass-through with four responsibilities:

1. attach the desktop session as ``Authorization: Bearer`` plus the ``token`` header
   the official client sends (both are accepted upstream; the pair matches the client);
2. bound the request body and the retained output;
3. lift the upstream's ``usage.points_consumed`` into the ``credit`` metric the audit
   store understands, without inventing a value when the field is absent;
4. never buffer a stream when the caller asked for one.
"""
from __future__ import annotations

import json
import re
import time

import httpx
from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse

from core.auth.session_provider import SessionError
from core.audit.session_labels import label_request
from core.upstreams import PLATFORMS

# Headers the official Loomy client sends alongside the bearer token. Upstream accepts a
# bare Authorization header, but matching the client keeps behaviour identical.
CLIENT_HEADERS = {
    "Accept": "application/json",
    "Content-Type": "application/json",
    "User-Agent": "Loomy/0.9.38",
    "loomy-version": "0.9.38",
}
_FORWARD_REQUEST_HEADERS = ("accept", "content-type", "user-agent")
_HOP_BY_HOP = {"connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
               "te", "trailers", "transfer-encoding", "upgrade", "content-length", "host"}
_MODEL_ID = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}\Z")
_SSE_CHUNK = 64 * 1024


def session_headers(token: str) -> dict:
    return {**CLIENT_HEADERS, "Authorization": f"Bearer {token}", "token": token}


def upstream_url(config, path: str, platform: str = "loomy") -> str:
    spec = PLATFORMS.get(platform) or PLATFORMS["loomy"]
    base = str(config.get(spec["url_key"]) or "").rstrip("/")
    return f"{base}/{path.lstrip('/')}"


def _chat_url(config, session, spec, platform: str) -> str:
    """Chat endpoint for a platform: static base from settings, or the session's own base."""
    if spec.get("dynamic_base"):
        base = str(getattr(session, "base_url", "") or "").rstrip("/")
        if not base:
            raise HTTPException(status_code=503, detail={"error": {
                "message": f"{spec['label']} 上游地址尚未就绪", "type": "service_unavailable"}})
        return f"{base}/{spec['chat_path'].lstrip('/')}"
    return upstream_url(config, spec["chat_path"], platform=platform)


def check_model(config, model, known):
    """Reject a model the upstream catalogue does not declare, before spending a request."""
    if not isinstance(model, str) or not _MODEL_ID.match(model):
        raise HTTPException(status_code=400, detail={"error": {
            "message": "model 必须是有效的模型标识", "type": "invalid_request_error", "param": "model"}})
    if not config.get("model_guard", True) or known is None:
        return
    if model not in known:
        raise HTTPException(status_code=404, detail={"error": {
            "message": f"The model '{model}' is not supported by this gateway. See GET /v1/models.",
            "type": "invalid_request_error", "param": "model", "code": "model_not_found"}})


def credit_from_usage(payload):
    """Lift ``usage.points_consumed`` into ``usage.credit``; never invent a number."""
    if not isinstance(payload, dict):
        return payload
    usage = payload.get("usage")
    if isinstance(usage, dict) and "credit" not in usage and "points_consumed" in usage:
        value = usage.get("points_consumed")
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            usage["credit"] = value
    return payload


async def read_json_body(request: Request, maximum: int):
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > maximum:
            raise HTTPException(status_code=413, detail={"error": {
                "message": "请求体超过大小上限", "type": "invalid_request_error"}})
    if not body:
        raise HTTPException(status_code=400, detail={"error": {
            "message": "请求体不能为空", "type": "invalid_request_error"}})
    try:
        payload = json.loads(body)
    except (ValueError, UnicodeDecodeError, RecursionError):
        raise HTTPException(status_code=400, detail={"error": {
            "message": "请求体必须是有效 JSON", "type": "invalid_request_error"}}) from None
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail={"error": {
            "message": "请求体必须是 JSON 对象", "type": "invalid_request_error"}})
    return payload


def _forward_headers(request: Request, token: str, platform: str = "loomy") -> dict:
    headers = PLATFORMS.get(platform, PLATFORMS["loomy"])["headers_for"](token)
    for name in _FORWARD_REQUEST_HEADERS:
        value = request.headers.get(name)
        if value:
            headers[name] = value
    return headers


def _upstream_error(response: httpx.Response):
    """Map an upstream error to a local HTTPException preserving status and body."""
    try:
        detail = json.loads(response.content)
    except (ValueError, UnicodeDecodeError, RecursionError):
        detail = {"error": {"message": response.text[:500] or "上游返回了无法解析的错误",
                            "type": "upstream_error"}}
    if not isinstance(detail, dict):
        detail = {"error": {"message": str(detail)[:500], "type": "upstream_error"}}
    status = response.status_code if 400 <= response.status_code < 600 else 502
    return HTTPException(status_code=status, detail=detail)


def _filtered_response_headers(response: httpx.Response) -> dict:
    headers = {key: value for key, value in response.headers.items()
               if key.lower() not in _HOP_BY_HOP}
    headers.setdefault("Cache-Control", "no-store")
    headers["X-Accel-Buffering"] = "no"
    return headers


async def proxy_chat(request: Request, config, known_models):
    """Forward one chat completion, streaming or not, and return the local response.

    After the body is read, ``route_model`` maps the public model id onto a
    platform (``qwenwork/`` prefix or Loomy, honouring panel aliases) and the
    upstream model name that is actually forwarded; each platform brings its
    own base URL, header template, session and billing semantics.
    """
    from core.upstreams import route_model

    payload = await read_json_body(request, int(config.get("max_request_bytes") or 32 * 1024 * 1024))
    check_model(config, payload.get("model"), known_models)
    route = route_model(payload.get("model"), config)
    if route is None:
        raise HTTPException(status_code=404, detail={"error": {
            "message": f"The model '{payload.get('model')}' is not supported by this gateway. See GET /v1/models.",
            "type": "invalid_request_error", "param": "model", "code": "model_not_found"}})
    platform, upstream_model = route
    spec = PLATFORMS[platform]
    session = config.get(spec["session_key"])
    if session is None:
        raise HTTPException(status_code=503, detail={"error": {
            "message": f"{spec['label']} 未启用或会话读取器未初始化", "type": "service_unavailable",
            "code": "session_unavailable"}})
    stream = payload.get("stream") is True
    if isinstance(upstream_model, str) and upstream_model and payload.get("model") != upstream_model:
        payload["model"] = upstream_model
    try:
        token = session.token()
    except SessionError as error:
        raise HTTPException(status_code=503, detail={"error": {
            "message": f"{spec['label']} 会话不可用：{error}", "type": "service_unavailable",
            "code": "session_unavailable"}}) from None
    # Attribute this request to the serving session before the audit record is closed.
    label_request(session)

    url = _chat_url(config, session, spec, platform)
    client = request.app.state.upstream.get(url)
    if client is None:
        raise HTTPException(status_code=503, detail={"error": {
            "message": "上游客户端尚未就绪", "type": "service_unavailable"}})
    headers = _forward_headers(request, token, platform=platform)
    timeout = httpx.Timeout(float(config.get("request_timeout") or 600),
                            connect=float(config.get("connect_timeout") or 20))
    body = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8")

    if not stream:
        try:
            response = await client.post(url, headers=headers, content=body, timeout=timeout)
        except httpx.HTTPError as error:
            raise HTTPException(status_code=502, detail={"error": {
                "message": f"上游请求失败：{type(error).__name__}", "type": "upstream_error"}}) from None
        if response.status_code >= 400:
            raise _upstream_error(response)
        try:
            data = credit_from_usage(response.json()) if spec["credit"] else response.json()
        except (ValueError, UnicodeDecodeError, RecursionError):
            raise HTTPException(status_code=502, detail={"error": {
                "message": "上游返回了无法解析的响应", "type": "upstream_error"}}) from None
        return JSONResponse(data, headers={"Cache-Control": "no-store"})

    return await _stream_chat(request, client, url, headers, body, timeout, credit=spec["credit"])


async def _stream_chat(request: Request, client, url, headers, body, timeout, *, credit=True):
    """Stream the upstream SSE verbatim, lifting points_consumed on the way through."""
    started = time.monotonic()
    try:
        upstream = client.stream("POST", url, headers=headers, content=body, timeout=timeout)
        response = await upstream.__aenter__()
    except httpx.HTTPError as error:
        raise HTTPException(status_code=502, detail={"error": {
            "message": f"上游请求失败：{type(error).__name__}", "type": "upstream_error"}}) from None
    if response.status_code >= 400:
        await response.aread()
        await upstream.__aexit__(None, None, None)
        raise _upstream_error(response)

    async def relay():
        buffer = bytearray()
        try:
            async for chunk in response.aiter_bytes():
                if await request.is_disconnected():
                    break
                buffer.extend(chunk)
                # Only rewrite a complete trailing line so a split chunk cannot corrupt JSON.
                while True:
                    newline = buffer.find(b"\n")
                    if newline == -1:
                        break
                    line = bytes(buffer[:newline + 1])
                    del buffer[:newline + 1]
                    yield _rewrite_line(line, credit=credit)
            if buffer:
                yield _rewrite_line(bytes(buffer), credit=credit)
        finally:
            await upstream.__aexit__(None, None, None)

    return StreamingResponse(relay(), status_code=response.status_code,
                             headers=_filtered_response_headers(response),
                             media_type=response.headers.get("content-type", "text/event-stream"))


def _rewrite_line(line: bytes, *, credit=True) -> bytes:
    """Add ``credit`` to one SSE ``data:`` line when the upstream reported points."""
    if not credit:
        return line
    stripped = line.strip()
    if not stripped.startswith(b"data:"):
        return line
    raw = stripped[5:].strip()
    if not raw or raw == b"[DONE]":
        return line
    try:
        payload = json.loads(raw)
    except (ValueError, UnicodeDecodeError, RecursionError):
        return line
    if not isinstance(payload, dict) or not isinstance(payload.get("usage"), dict):
        return line
    usage = payload["usage"]
    if "credit" in usage or "points_consumed" not in usage:
        return line
    value = usage.get("points_consumed")
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return line
    usage["credit"] = value
    ending = b"\r\n" if line.endswith(b"\r\n") else b"\n"
    return b"data: " + json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8") + ending
