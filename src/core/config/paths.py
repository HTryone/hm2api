"""仓库内路径的统一解析点。

层级：<repo>/src/core/config/paths.py
→ parents[0]=config, [1]=core, [2]=src, [3]=repo（仓库根）。
其它模块不要再自己数 __file__ 的层数。
"""
from __future__ import annotations

from pathlib import Path


def repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def data_dir() -> Path:
    return repo_root() / "data"


def ui_dist() -> Path:
    """前端产物目录（独立项目 ui/）。"""
    return repo_root() / "ui" / "dist"


def web_dist() -> Path:  # 兼容旧名
    return ui_dist()


def cred_dir(platform: str) -> Path:
    return repo_root() / "cred" / platform


def env_file() -> Path:
    return repo_root() / ".env"
