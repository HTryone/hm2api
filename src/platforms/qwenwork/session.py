"""QwenWork (千问办公) credential + inference-endpoint provider.

Two-stage auth, both official:

1. **Login JWT** (7 days). Sources, in order:
   * ``cred/qwenwork/session.json`` produced by ``scripts/qwenwork-login.py``
     (device-code PKCE flow, independent of the desktop app);
   * the desktop app's ``auth-v2.dat`` (Chromium os_crypt: ``v10`` + AES-256-GCM,
     key from ``Local State``'s ``os_crypt.encrypted_key`` wrapped by DPAPI).
2. **Short-lived MaaS key** (2 h): ``POST {gateway}/api/desktop-sessions`` with the
   JWT returns ``{access_token, base_url, expires_at_ms, ttl_ms}``.  That key is a
   plain OpenAI bearer (``sk-mm-v1.…``) against ``base_url`` — no request signing.

``token()`` returns the MaaS access token (what the proxy puts in ``Authorization``)
and ``base_url`` is the upstream origin to use for this platform; both are refreshed
proactively well before expiry.
"""
from __future__ import annotations

import base64
import ctypes
import hashlib
import json
import os
from pathlib import Path
import threading
import time
import urllib.error
import urllib.request
import uuid

from core.config.paths import cred_dir
from core.auth.session_provider import SessionError

GATEWAY = "https://gateway.qwenwork.cn"
DESKTOP_SESSIONS = "/api/desktop-sessions"
CHAT_MODES = "/api/desktop/chat-modes"
MODEL_PREFIX = "qwenwork/"
CATALOG_TTL = 600
_REFRESH_MARGIN_MS = 5 * 60 * 1000
_MAX_BLOB_BYTES = 1024 * 1024
_AUTH_FILES = ("auth-v2.dat",)
_APP_HEADERS = {
    "X-QwenWork-Version": "1.4.0",
    "X-QwenWork-Release-Version": "1.4.0-26102705",
    "X-QwenWork-Build": "26102705",
    "X-QwenWork-Platform": "win32",
    "X-QwenWork-Arch": "x64",
    "X-QwenWork-Channel": "stable",
    "X-QwenWork-App-Mode": "standard",
}


def default_appdata_dir() -> Path | None:
    base = os.environ.get("APPDATA")
    return Path(base) / "QwenWorkCN" if base else None


def default_credential_dir() -> Path:
    """``<repo>/cred/qwenwork`` — the git-ignored per-platform credential folder."""
    return cred_dir("qwenwork")


class _DataBlob(ctypes.Structure):
    _fields_ = [("cbData", ctypes.c_uint32), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _dpapi_unprotect(blob: bytes) -> bytes:
    kernel32, crypt32 = ctypes.windll.kernel32, ctypes.windll.crypt32
    inp = _DataBlob(len(blob), ctypes.create_string_buffer(blob, len(blob)))
    out = _DataBlob()
    if not crypt32.CryptUnprotectData(ctypes.byref(inp), None, None, None, None, 0, ctypes.byref(out)):
        raise OSError(f"CryptUnprotectData failed: {kernel32.GetLastError()}")
    try:
        return ctypes.string_at(out.pbData, out.cbData)
    finally:
        kernel32.LocalFree(out.pbData)


def _aes_gcm_decrypt(key: bytes, nonce: bytes, ciphertext_with_tag: bytes) -> bytes:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    return AESGCM(key).decrypt(nonce, ciphertext_with_tag, None)


def _fingerprint(value: str) -> str | None:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:12] if value else None


class QwenworkSession:
    """Login JWT + short-lived MaaS bearer, refreshed on demand."""

    platform = "qwenwork"

    def __init__(self, appdata_dir=None, credential_dir=None, *, ttl=30, clock=time.time):
        self.dir = Path(appdata_dir) if appdata_dir else default_appdata_dir()
        self.credential_dir = Path(credential_dir) if credential_dir else default_credential_dir()
        self.session_file = self.credential_dir / "session.json"
        self.ttl = max(0, int(ttl))
        self._clock = clock
        self._lock = threading.RLock()
        self._jwt = ""
        self._jwt_exp = 0.0
        self._jwt_source = ""
        self._key = ""
        self._base = ""
        self._key_exp_ms = 0.0
        self._loaded_at = 0.0
        self._error = None
        self._file_mtime = 0.0
        self._catalog_rows = []
        self._catalog_at = 0.0

    # -- public surface (mirrors LoomySession) -------------------------------
    def describe(self):
        with self._lock:
            if not self._jwt and not self._loaded_at:
                try:
                    self._load_jwt(self._clock())
                except SessionError:
                    pass
            now = self._clock()
            return {
                "path": str(self.session_file),
                "present": bool(self._jwt),
                "jwt_source": self._jwt_source or None,
                "jwt_fingerprint": _fingerprint(self._jwt),
                "jwt_expires_at": self._jwt_exp or None,
                "jwt_expires_in_seconds": int(self._jwt_exp - now) if self._jwt_exp else None,
                "inference_ready": bool(self._key and self._base),
                "base_url": self._base or None,
                "key_fingerprint": _fingerprint(self._key),
                "key_expires_at_ms": self._key_exp_ms or None,
                "key_expires_in_seconds": int((self._key_exp_ms / 1000) - now) if self._key_exp_ms else None,
                "ttl": self.ttl,
                "error": self._error,
                "token_fingerprint": _fingerprint(self._key or self._jwt),
            }

    @property
    def base_url(self) -> str:
        """Upstream origin for OpenAI-compatible calls (MaaS host, refreshed with the key)."""
        self.token()
        return self._base

    def token(self) -> str:
        """Return the MaaS bearer (``sk-mm-v1.…``), exchanging/refreshing as needed."""
        with self._lock:
            now = self._clock()
            if not self._jwt or self._jwt_exp and self._jwt_exp - now < 120 or self._jwt_file_changed():
                self._load_jwt(now)
            if not self._jwt:
                raise SessionError(self._error or "千问办公凭据不可用")
            expiry_ms = self._key_exp_ms
            if not self._key or not self._base or (expiry_ms and expiry_ms - _REFRESH_MARGIN_MS < now * 1000):
                self._exchange(now)
            if not self._key:
                raise SessionError(self._error or "千问办公推理密钥不可用")
            return self._key

    def reload(self):
        with self._lock:
            self._load_jwt(self._clock(), force=True)
            self._key = ""
            self._base = ""
            self._key_exp_ms = 0.0
            if not self._jwt:
                raise SessionError(self._error or "千问办公凭据不可用")
            self._exchange(self._clock())
            return self.describe()

    # -- credential loading ---------------------------------------------------
    def _jwt_file_changed(self):
        try:
            return self.session_file.stat().st_mtime != self._file_mtime
        except OSError:
            return False

    def _load_jwt(self, now, *, force=False):
        self._loaded_at = now
        # 1. our own device-flow login
        try:
            document = json.loads(self.session_file.read_text(encoding="utf-8"))
        except (OSError, ValueError, UnicodeDecodeError):
            document = None
        if isinstance(document, dict):
            token = document.get("token")
            if isinstance(token, str) and token.count(".") == 2 and len(token) > 200:
                self._apply_jwt(token, "device-flow")
                try:
                    self._file_mtime = self.session_file.stat().st_mtime
                except OSError:
                    self._file_mtime = 0.0
                return
        # 2. desktop app's stored session
        try:
            token = self._jwt_from_app()
        except SessionError as error:
            if not self._jwt:
                self._error = str(error)
                self._jwt = ""
            return
        if token:
            self._apply_jwt(token, "desktop-app")
            self._error = None

    def _apply_jwt(self, token, source):
        self._jwt = token
        self._jwt_source = source
        self._jwt_exp = self._exp_of(token)
        self._error = None

    @staticmethod
    def _exp_of(token):
        try:
            payload = token.split(".")[1]
            payload += "=" * (-len(payload) % 4)
            claims = json.loads(base64.urlsafe_b64decode(payload))
            value = claims.get("exp")
            return float(value) if isinstance(value, (int, float)) else 0.0
        except Exception:
            return 0.0

    def _jwt_from_app(self) -> str:
        if not self.dir or not self.dir.is_dir():
            raise SessionError("未找到千问办公数据目录（未安装或未登录）")
        local_state = self.dir / "Local State"
        auth_file = next((self.dir / name for name in _AUTH_FILES if (self.dir / name).is_file()), None)
        if auth_file is None:
            raise SessionError("桌面端未登录（缺少 auth-v2.dat），请先运行 scripts/qwenwork-login.py")
        try:
            state = json.loads(local_state.read_text(encoding="utf-8"))
            blob = base64.b64decode(state["os_crypt"]["encrypted_key"])
        except (OSError, ValueError, KeyError, UnicodeDecodeError) as error:
            raise SessionError(f"无法读取 Local State：{type(error).__name__}") from None
        if not blob.startswith(b"DPAPI"):
            raise SessionError("os_crypt key 不是 DPAPI 封装格式")
        raw = auth_file.read_bytes()
        if len(raw) > _MAX_BLOB_BYTES or not raw.startswith(b"v10"):
            raise SessionError("auth-v2.dat 不是 v10 加密格式")
        try:
            key = _dpapi_unprotect(blob[5:])
            document = json.loads(_aes_gcm_decrypt(key, raw[3:15], raw[15:]).decode("utf-8"))
        except SessionError:
            raise
        except Exception as error:
            raise SessionError(f"解密 auth-v2.dat 失败：{type(error).__name__}") from None
        token = document.get("token")
        if not isinstance(token, str) or token.count(".") != 2:
            raise SessionError("auth-v2.dat 中缺少可用 token")
        return token

    # -- MaaS key exchange ----------------------------------------------------
    def _headers(self):
        return {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self._jwt}",
            "User-Agent": "QoderWork",
            "X-Request-Id": str(uuid.uuid4()),
            **_APP_HEADERS,
        }

    def _exchange(self, now):
        body = json.dumps({"session_id": str(uuid.uuid4())}).encode("utf-8")
        request = urllib.request.Request(GATEWAY + DESKTOP_SESSIONS, data=body,
                                         headers=self._headers(), method="POST")
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", "replace")[:200]
            self._error = f"desktop-sessions 返回 HTTP {error.code}：{detail}"
            self._key = ""
            return
        except Exception as error:
            self._error = f"desktop-sessions 请求失败：{type(error).__name__}"
            self._key = ""
            return
        key = payload.get("access_token")
        base = payload.get("base_url")
        if not isinstance(key, str) or not key or not isinstance(base, str) or not base:
            self._error = "desktop-sessions 响应缺少 access_token/base_url"
            self._key = ""
            return
        self._key = key
        self._base = base.rstrip("/")
        expires = payload.get("expires_at_ms")
        self._key_exp_ms = float(expires) if isinstance(expires, (int, float)) else (
            now * 1000 + float(payload.get("ttl_ms") or 3600_000))
        self._error = None

    # -- catalogue ------------------------------------------------------------
    def cached_catalog(self):
        """Last successfully fetched rows (may be empty before the first fetch)."""
        with self._lock:
            return [dict(row) for row in self._catalog_rows]

    def catalog(self, *, ttl=None, force=False):
        """Return the desktop chat-modes catalogue as OpenAI-style model rows."""
        ttl = CATALOG_TTL if ttl is None else int(ttl)
        with self._lock:
            fresh = self._catalog_rows and (self._clock() - self._catalog_at) < ttl
            if fresh and not force:
                return [dict(row) for row in self._catalog_rows]
            if not self._jwt:
                self._load_jwt(self._clock())
            if not self._jwt:
                raise SessionError(self._error or "千问办公凭据不可用")
            jwt = self._jwt
        request = urllib.request.Request(GATEWAY + CHAT_MODES, headers=self._headers_with(jwt), method="GET")
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except Exception as error:
            raise SessionError(f"目录拉取失败：{type(error).__name__}") from None
        entries = payload.get("catalog") if isinstance(payload, dict) else None
        if not isinstance(entries, list):
            raise SessionError("目录结构无效")
        rows = []
        for item in entries:
            if not isinstance(item, dict) or item.get("enable") is False:
                continue
            key = item.get("key")
            if not isinstance(key, str) or not key:
                continue
            display = item.get("i18n", {}).get("display_name", {}) if isinstance(item.get("i18n"), dict) else {}
            name = display.get("zh") or display.get("en") or key
            context = item.get("max_input_tokens")
            efforts = ["low", "medium", "high"] if item.get("is_reasoning") else []
            rows.append({
                "id": MODEL_PREFIX + key,
                "upstream_id": key,
                "name": f"千问办公·{name}",
                "type": "chat",
                "protocol": "openai_chat",
                "owned_by": "qwenwork",
                "created": None,
                "is_default": item.get("is_default") is True,
                "context_length": int(context) if isinstance(context, (int, float)) else None,
                "max_output_tokens": None,
                "capabilities": {"reasoning": bool(item.get("is_reasoning")),
                                 "vision": bool(item.get("is_vl"))},
                "reasoning_efforts": efforts,
                "default_reasoning_effort": None,
                "price_factor": item.get("price_factor"),
            })
        if not rows:
            raise SessionError("目录为空")
        with self._lock:
            self._catalog_rows = rows
            self._catalog_at = self._clock()
        return [dict(row) for row in rows]

    def _headers_with(self, jwt):
        headers = self._headers()
        headers["Authorization"] = f"Bearer {jwt}"
        return headers
