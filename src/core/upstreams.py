"""Registry of the platforms served behind this single gateway.

Each entry binds: which CONFIG key holds the session provider, which settings
key holds the upstream base URL (static) or whether the base URL comes from the
session (dynamic, e.g. the MaaS host handed out per session), how the request
headers are built, and whether the ``points_consumed -> credit`` rewriting
applies.

Public model ids of the second platform carry the ``qwenwork/`` prefix so the
two platforms can never collide (Loomy already exports ``qwen3.8-flash``); the
prefix is stripped again before forwarding upstream.
"""
from __future__ import annotations

import uuid

QWENWORK_PREFIX = "qwenwork/"


def _loomy_headers(token: str) -> dict:
    # Kept identical to the historical CLIENT_HEADERS in upstream_proxy.py.
    from core.http.upstream_proxy import session_headers
    return session_headers(token)


def _qwenwork_headers(token: str) -> dict:
    """MaaS bearer is a plain OpenAI key; only a request id is added."""
    return {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
        "X-Request-Id": str(uuid.uuid4()),
    }


PLATFORMS = {
    "loomy": {
        "label": "Loomy（讯飞）",
        "session_key": "loomy_session",
        "url_key": "upstream_base_url",
        "headers_for": _loomy_headers,
        "credit": True,
        "catalog": "remote",
        "dynamic_base": False,
        "chat_path": "chat/completions",
    },
    "qwenwork": {
        "label": "千问办公（QwenWork CN）",
        "session_key": "qwenwork_session",
        "url_key": "qwenwork_upstream_base_url",
        "headers_for": _qwenwork_headers,
        "credit": False,
        "catalog": "session",
        "dynamic_base": True,
        "chat_path": "v1/chat/completions",
    },
}


def qwenwork_enabled(config) -> bool:
    return bool(config.get("qwenwork_enabled"))


def qwenwork_session(config):
    return config.get("qwenwork_session")


def public_models(config):
    """Model rows contributed by platforms whose catalogue lives on the session."""
    from platforms.qwenwork.session import SessionError

    rows = []
    session = qwenwork_session(config)
    if session is not None and qwenwork_enabled(config):
        try:
            rows.extend(session.catalog())
        except SessionError:
            rows.extend(session.cached_catalog() if hasattr(session, "cached_catalog") else [])
    return rows


def public_ids(config):
    return {item["id"] for item in public_models(config)}


def route_model(model, config):
    """Resolve a request's public model id to (platform, upstream model id).

    Returns None when nothing matches; HTTP semantics stay with ``check_model``.
    """
    if isinstance(model, str) and model.startswith(QWENWORK_PREFIX):
        if not qwenwork_enabled(config) or qwenwork_session(config) is None:
            return None
        upstream = model[len(QWENWORK_PREFIX):]
        for item in public_models(config):
            if item["id"] == model:
                return "qwenwork", item.get("upstream_id") or upstream
        return "qwenwork", upstream
    # Loomy: honour panel aliases by restoring public_id -> upstream_id.
    control = config.get("control_store")
    rules = control.snapshot()["models"] if control is not None else {}
    rule = rules.get(model)
    if rule is None:
        for candidate in rules.values():
            if candidate.get("public_id") == model:
                rule = candidate
                break
    if rule is not None:
        if rule.get("enabled") is False:
            return None
        return "loomy", rule.get("upstream_id") or model
    return "loomy", model
