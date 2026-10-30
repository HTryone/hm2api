"""千问办公设备码登录（服务端版）：面板点「添加凭证」即可自动开浏览器、自动轮询。

流程：生成 PKCE → 授权链接（自动用默认浏览器打开）→ 轮询 deviceToken → 写 cred/qwenwork/session.json。
与 CLI 脚本 scripts/qwenwork-login.py 等价，但以状态机形式暴露给面板。
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

from core.config.paths import cred_dir

CLIENT_ID = "e883ade2-e6e3-4d6d-adf7-f92ceff5fdcb"
AUTH_BASE = "https://gateway.qwenwork.cn"
OPENAPI_BASE = "https://gateway.qwenwork.cn"
APP_VERSION = "1.4.0"
RELEASE_VERSION = "1.4.0-26102705"
BUILD = "26102705"
ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~"


def _client_headers() -> dict:
    return {
        "X-QwenWork-Version": APP_VERSION,
        "X-QwenWork-Release-Version": RELEASE_VERSION,
        "X-QwenWork-Build": BUILD,
        "X-QwenWork-Platform": "win32",
        "X-QwenWork-Arch": "x64",
        "X-QwenWork-Channel": "stable",
        "X-QwenWork-App-Mode": "standard",
    }


def _pkce() -> tuple[str, str]:
    length = 43 + secrets.randbelow(86)
    verifier = "".join(ALPHABET[secrets.randbelow(len(ALPHABET))] for _ in range(length))
    digest = hashlib.sha256(verifier.encode()).digest()
    return verifier, base64.urlsafe_b64encode(digest).decode().rstrip("=")


def _machine_id() -> str:
    try:
        return (Path.home() / ".qwenworkcn" / ".auth" / "machine_id").read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def _fingerprint(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()[:12] if value else ""


class DeviceLogin:
    """一次设备码登录的状态机；面板轮询 status()。"""

    def __init__(self, session_file: Path | None = None, timeout_s: int = 300):
        self.session_file = session_file or (cred_dir("qwenwork") / "session.json")
        self.timeout_s = timeout_s
        self._lock = threading.Lock()
        self._state = "idle"
        self._message = ""
        self._auth_url = ""
        self._started_at = 0.0
        self._finished_at = 0.0
        self._fingerprint = ""
        self._thread: threading.Thread | None = None

    # -- 对外 ---------------------------------------------------------------
    def status(self) -> dict:
        with self._lock:
            return {
                "state": self._state,
                "message": self._message,
                "auth_url": self._auth_url,
                "started_at": self._started_at or None,
                "finished_at": self._finished_at or None,
                "token_fingerprint": self._fingerprint or None,
            }

    def start(self, open_browser: bool = True) -> dict:
        with self._lock:
            if self._state == "waiting":
                return self.status()
            verifier, challenge = _pkce()
            nonce = str(uuid.uuid4())
            machine = _machine_id()
            query = (
                f"challenge={urllib.parse.quote(challenge)}&challenge_method=S256"
                f"&nonce={urllib.parse.quote(nonce)}&machine_id={urllib.parse.quote(machine)}"
                f"&client_id={CLIENT_ID}&redirect_uri=qwenwork-cn%3A%2F%2F"
            )
            self._auth_url = f"{AUTH_BASE}/device/selectAccounts?{query}"
            self._state = "waiting"
            self._message = "已在浏览器打开授权页，请选择账号完成授权"
            self._started_at = time.time()
            self._finished_at = 0.0
            self._fingerprint = ""

        if open_browser:
            try:
                os.startfile(self._auth_url)  # noqa: S606 - Windows 默认浏览器
            except Exception:
                pass

        self._thread = threading.Thread(
            target=self._run, args=(nonce, verifier, challenge), name="qwenwork-device-login", daemon=True
        )
        self._thread.start()
        return self.status()

    # -- 内部 ---------------------------------------------------------------
    def _set(self, state: str, message: str) -> None:
        with self._lock:
            self._state = state
            self._message = message
            if state in ("success", "failed"):
                self._finished_at = time.time()

    def _poll_once(self, nonce: str, verifier: str) -> dict | None:
        url = (
            f"{OPENAPI_BASE}/api/v1/deviceToken/poll?nonce={urllib.parse.quote(nonce)}"
            f"&verifier={urllib.parse.quote(verifier)}&challenge_method=S256"
        )
        request = urllib.request.Request(
            url,
            method="GET",
            headers={"Accept": "application/json", "X-Request-Id": str(uuid.uuid4()), **_client_headers()},
        )
        try:
            with urllib.request.urlopen(request, timeout=20) as response:  # noqa: S310
                body = json.loads(response.read().decode("utf-8"))
                return body if body.get("token") else None
        except urllib.error.HTTPError as error:
            if error.code == 409 or error.code in (404, 502, 503, 504):
                return None
            reason = error.headers.get("x-device-flow-failure-reason", "")
            raise RuntimeError(f"授权被拒：{error.code} {reason}".strip())
        except (urllib.error.URLError, TimeoutError, ValueError):
            return None

    def _run(self, nonce: str, verifier: str, challenge: str) -> None:
        deadline = time.time() + self.timeout_s
        try:
            while time.time() < deadline:
                body = self._poll_once(nonce, verifier)
                if body:
                    self._save(body, nonce, challenge)
                    return
                time.sleep(2)
            self._set("failed", f"{self.timeout_s // 60} 分钟内未完成授权，请重试")
        except Exception as error:  # noqa: BLE001 - 状态机需要把所有失败都反馈到面板
            self._set("failed", str(error) or "登录失败")

    def _save(self, body: dict, nonce: str, challenge: str) -> None:
        token = str(body.get("token") or "")
        record = {
            "token": token,
            "refresh_token": body.get("refresh_token") or "",
            "expires_at": body.get("expires_at") or body.get("expiresAt") or "",
            "refresh_token_expires_at": body.get("refresh_token_expires_at") or "",
            "nonce": nonce,
            "challenge": challenge,
            "client_id": CLIENT_ID,
            "login_device_id": _machine_id(),
            "machine_id": _machine_id(),
            "obtained_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "source": "device-flow",
        }
        self.session_file.parent.mkdir(parents=True, exist_ok=True)
        temp = self.session_file.with_suffix(".tmp")
        temp.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temp, self.session_file)
        with self._lock:
            self._fingerprint = _fingerprint(token)
        self._set("success", "登录成功，凭据已写入 cred/qwenwork/session.json")
