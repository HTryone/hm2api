"""Cache the Loomy model catalogue, mirroring the desktop client's ``GET /models`` call."""
from __future__ import annotations

import asyncio
import threading
import time

import httpx

from core.http.upstream_proxy import session_headers, upstream_url


class ModelCatalog:
    """One upstream catalogue snapshot, refreshed on a TTL with a non-fatal failure path."""

    def __init__(self, config, session, *, ttl=None):
        self.config = config
        self.session = session
        self.ttl = int(config.get("model_catalog_ttl") if ttl is None else ttl)
        self._lock = threading.RLock()
        self._models = {}
        self._fetched_at = 0.0
        self._error = None
        self._refresh_lock = None

    # -- reads ---------------------------------------------------------------
    def snapshot(self):
        with self._lock:
            return {"models": dict(self._models), "fetched_at": self._fetched_at or None,
                    "error": self._error, "ttl": self.ttl, "count": len(self._models)}

    def ids(self):
        with self._lock:
            return set(self._models)

    def details(self):
        with self._lock:
            return [dict(item) for item in self._models.values()]

    def stale(self):
        with self._lock:
            if not self._models:
                return True
            return bool(self.ttl) and (time.time() - self._fetched_at) >= self.ttl

    # -- persistence ---------------------------------------------------------
    def load_from_state(self):
        """Seed from SQLite so the dashboard is populated before the first upstream refresh."""
        store = self.config.get("state_store")
        if store is None:
            return
        try:
            document = store.get("catalog")
        except Exception:
            return
        if not isinstance(document, dict) or not isinstance(document.get("models"), dict):
            return
        with self._lock:
            self._models = document["models"]
            self._fetched_at = float(document.get("fetched_at") or 0)

    def _persist(self):
        store = self.config.get("state_store")
        if store is None:
            return
        with self._lock:
            document = {"version": 1, "models": dict(self._models), "fetched_at": self._fetched_at}
        try:
            store.put("catalog", document)
        except Exception:
            # A cache write failure must never replace the inference outcome.
            pass

    # -- refresh -------------------------------------------------------------
    async def refresh(self, *, force=False):
        """Fetch the catalogue; concurrent callers share a single upstream request."""
        if not force and not self.stale():
            return self.snapshot()
        if self._refresh_lock is None:
            self._refresh_lock = asyncio.Lock()
        async with self._refresh_lock:
            if not force and not self.stale():
                return self.snapshot()
            await self._fetch()
        return self.snapshot()

    async def _fetch(self):
        config = self.config
        url = upstream_url(config, "models")
        client = _client_for(url)
        if client is None:
            return
        try:
            token = self.session.token()
        except Exception as error:
            with self._lock:
                self._error = f"会话不可用：{error}"
            return
        timeout = httpx.Timeout(float(config.get("request_timeout") or 600),
                                connect=float(config.get("connect_timeout") or 20))
        try:
            response = await client.get(url, headers=session_headers(token), timeout=timeout)
        except httpx.HTTPError as error:
            with self._lock:
                self._error = f"上游请求失败：{type(error).__name__}"
            return
        if response.status_code >= 400:
            with self._lock:
                self._error = f"上游返回 HTTP {response.status_code}"
            return
        try:
            payload = response.json()
        except (ValueError, UnicodeDecodeError, RecursionError):
            with self._lock:
                self._error = "上游模型表不是有效 JSON"
            return
        entries = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(entries, list):
            with self._lock:
                self._error = "上游模型表结构无效"
            return
        models = {}
        for item in entries:
            if not isinstance(item, dict):
                continue
            model_id = item.get("id")
            if not isinstance(model_id, str) or not model_id:
                continue
            models[model_id] = {
                "id": model_id,
                "name": item.get("name") or model_id,
                "type": item.get("type") or "chat",
                "protocol": item.get("protocol") or "openai_chat",
                "owned_by": item.get("owned_by") or "loomy",
                "created": item.get("created"),
                "is_default": item.get("is_default_model") is True,
                "context_length": item.get("context_length"),
                "max_output_tokens": item.get("max_output_tokens"),
                "capabilities": item.get("capabilities") if isinstance(item.get("capabilities"), dict) else {},
                "reasoning_efforts": item.get("reasoning_efforts") if isinstance(item.get("reasoning_efforts"), list) else [],
                "default_reasoning_effort": item.get("default_reasoning_effort"),
            }
        with self._lock:
            self._models = models
            self._fetched_at = time.time()
            self._error = None
        self._persist()


def _client_for(url):
    """Reuse the loop-bound upstream client when the refresh runs inside the app loop."""
    from core.http import runtime
    return runtime.current_upstream_client(url)
