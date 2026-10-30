"""Loomy（讯飞）会话提供者。

规则（只有一条主线，不再多头读）：

* **唯一工作副本**：`cred/loomy/auth-session.json`（本仓库内，git 已过滤）。
  网关永远只读它。
* **同步源**（可选）：桌面端 `C:\\Users\\Public\\Loomy\\<hash>\\userData\\auth-session.json`。
  仅当它比工作副本新时，才把内容原子复制进工作副本；工作副本缺失时也用它做首次导入。
* 桌面端重新登录 → 下次刷新时自动同步进来，**不需要重启网关**。
* 会话令牌是不透明 32 字符串（非 JWT），这里不解析任何 claims。
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import threading
import time

from core.config.paths import cred_dir
from core.auth.session_provider import SessionError

__all__ = ["SessionError", "LoomySession", "default_session_path", "credential_path", "legacy_desktop_path"]

SESSION_FILENAME = "auth-session.json"
_SESSION_TOKEN = re.compile(r"\A[A-Za-z0-9_-]{8,512}\Z")
_MAX_SESSION_BYTES = 64 * 1024


# ---------------------------------------------------------------- 路径解析

def user_hash(username: str | None = None) -> str:
    """复刻桌面端的每用户配置目录后缀。"""
    name = os.environ.get("USERNAME") or os.environ.get("USER") or "" if username is None else username
    return hashlib.sha256(str(name).encode("utf-8")).hexdigest()[:12]


def legacy_desktop_path(username: str | None = None) -> Path | None:
    """桌面端自己的落盘位置（仅作同步源）。"""
    if os.name != "nt":
        return None
    return Path("C:/Users/Public/Loomy") / user_hash(username) / "userData" / SESSION_FILENAME


def credential_path() -> Path:
    """本仓库内的工作副本：cred/loomy/auth-session.json。"""
    return cred_dir("loomy") / SESSION_FILENAME


def default_session_path(username: str | None = None) -> Path:
    """对外语义：网关读哪个文件 —— 永远是仓库里那份。"""
    return credential_path()


# ---------------------------------------------------------------- 读取

def _read_json(path: Path):
    """有界读取 + 拒绝符号链接与超大文件。"""
    try:
        info = path.lstat()
    except FileNotFoundError:
        raise SessionError(f"Loomy 会话文件不存在：{path}") from None
    if not os.path.isfile(path) or os.path.islink(path):
        raise SessionError(f"Loomy 会话文件不是普通文件：{path}")
    if info.st_size > _MAX_SESSION_BYTES:
        raise SessionError("Loomy 会话文件超出大小上限")
    try:
        raw = path.read_bytes()
    except OSError as error:
        raise SessionError(f"无法读取 Loomy 会话文件：{type(error).__name__}") from None
    try:
        return json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError, RecursionError):
        raise SessionError("Loomy 会话文件不是有效 JSON") from None


def _write_json_atomic(path: Path, document) -> None:
    """同目录临时文件 + 替换，避免读到写了一半的内容。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temp = tempfile.mkstemp(dir=str(path.parent), prefix=".auth-", suffix=".tmp")
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(document, stream, ensure_ascii=False, indent=2)
        os.replace(temp, path)
    except BaseException:
        try:
            os.unlink(temp)
        except OSError:
            pass
        raise


def _mtime(path: Path | None) -> float:
    if path is None:
        return 0.0
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


# ---------------------------------------------------------------- 提供者

class LoomySession:
    """一份缓存快照：按 TTL 与文件变化刷新；工作副本在仓库内。"""

    platform = "loomy"

    def __init__(self, path=None, desktop_path=None, *, ttl=30, clock=time.time):
        self.path = Path(path) if path else credential_path()
        self.desktop_path = Path(desktop_path) if desktop_path else legacy_desktop_path()
        self.ttl = max(0, int(ttl))
        self._clock = clock
        self._lock = threading.RLock()
        self._token = ""
        self._userid = ""
        self._phone = ""
        self._updated_at = 0.0
        self._file_mtime = 0.0
        self._loaded_at = 0.0
        self._source = ""
        self._error = None

    # -- 对外 ---------------------------------------------------------------
    def describe(self):
        """给管理接口看的、不含令牌的视图。"""
        with self._lock:
            self._sync_from_desktop()
            return {
                "path": str(self.path),
                "desktop_path": str(self.desktop_path) if self.desktop_path else None,
                "source": self._source or None,
                "present": bool(self._token),
                "userid": self._userid or None,
                "phone": self._phone or None,
                "updated_at": self._updated_at or None,
                "file_mtime": self._file_mtime or None,
                "loaded_at": self._loaded_at or None,
                "ttl": self.ttl,
                "error": self._error,
                "token_fingerprint": self._fingerprint(),
            }

    def token(self):
        with self._lock:
            now = self._clock()
            stale = self.ttl and (now - self._loaded_at) >= self.ttl
            if not self._token or stale or self._file_changed():
                self._reload(now)
            if not self._token:
                raise SessionError(self._error or "Loomy 会话不可用")
            return self._token

    def reload(self):
        with self._lock:
            self._reload(self._clock())
            if not self._token:
                raise SessionError(self._error or "Loomy 会话不可用")
            return self.describe()

    # -- 内部 ---------------------------------------------------------------
    def _fingerprint(self):
        if not self._token:
            return None
        return hashlib.sha256(self._token.encode("utf-8")).hexdigest()[:12]

    def _file_changed(self):
        return max(_mtime(self.path), _mtime(self.desktop_path)) != self._file_mtime

    def _sync_from_desktop(self) -> bool:
        """桌面端更新过就复制进工作副本；工作副本缺失时用它首次导入。"""
        if self.desktop_path is None or not self.desktop_path.is_file():
            return False
        desktop_mtime = _mtime(self.desktop_path)
        if self.path.is_file() and _mtime(self.path) >= desktop_mtime:
            return False
        try:
            _write_json_atomic(self.path, _read_json(self.desktop_path))
            return True
        except (SessionError, OSError):
            return False

    def _reload(self, now):
        self._loaded_at = now
        synced = self._sync_from_desktop()
        if not self.path.is_file():
            self._token = ""
            self._source = ""
            self._error = (f"工作副本不存在：{self.path}；"
                           "请确认 Loomy 桌面端已登录（会自动导入），或手动放入该文件")
            return
        try:
            document = _read_json(self.path)
        except SessionError as error:
            self._token = ""
            self._error = str(error)
            return
        if not isinstance(document, dict):
            self._token = ""
            self._error = "Loomy 会话文件结构无效"
            return
        token = document.get("session")
        if not isinstance(token, str) or not _SESSION_TOKEN.fullmatch(token.strip()):
            self._token = ""
            self._error = "Loomy 会话文件缺少有效的 session 字段"
            return
        self._token = token.strip()
        self._userid = str(document.get("userid") or "").strip()
        self._phone = str(document.get("phone") or "").strip()
        try:
            self._updated_at = float(document.get("updatedAt") or 0) / 1000.0
        except (TypeError, ValueError):
            self._updated_at = 0.0
        self._file_mtime = max(_mtime(self.path), _mtime(self.desktop_path))
        self._source = "desktop-sync" if synced else "repo"
        self._error = None
