"""Public management settings for the Loomy gateway; never reads or writes .env files."""
from __future__ import annotations

import math
import os
import re
from urllib.parse import urlsplit


def normalize_allowed_origins(value):
    """Normalize a comma/space separated origin list; bare hosts default to HTTPS."""
    entries = [entry for entry in re.split(r"[\s,]+", value.strip()) if entry]
    if len(entries) > 32:
        raise ValueError("admin_allowed_origins: 来源数量超出上限")
    normalized = []
    for entry in entries:
        candidate = entry if "://" in entry else f"https://{entry}"
        try:
            parts = urlsplit(candidate)
            port = parts.port
        except ValueError:
            raise ValueError(f"admin_allowed_origins: 来源无效 {entry!r}") from None
        if (parts.scheme not in ("http", "https") or not parts.hostname
                or parts.username is not None or parts.password is not None
                or parts.path not in ("", "/") or parts.query or parts.fragment
                or (port is not None and not 1 <= port <= 65535)):
            raise ValueError(f"admin_allowed_origins: 来源无效 {entry!r}")
        host = f"[{parts.hostname}]" if ":" in parts.hostname else parts.hostname
        default_port = 443 if parts.scheme == "https" else 80
        origin = f"{parts.scheme}://{host}" + (f":{port}" if port is not None and port != default_port else "")
        if origin not in normalized:
            normalized.append(origin)
    return ",".join(normalized)


def normalize_base_url(value):
    """Accept only an absolute http(s) origin plus optional path, without credentials."""
    text = str(value or "").strip().rstrip("/")
    if not text:
        raise ValueError("上游地址不能为空")
    parts = urlsplit(text)
    if (parts.scheme not in ("http", "https") or not parts.hostname
            or parts.username is not None or parts.password is not None
            or parts.query or parts.fragment):
        raise ValueError("上游地址必须是有效的 http(s) 地址")
    return text


def _item(default, type_, label, *, mode="hot", env=None, minimum=None, maximum=None,
          choices=None, sensitive=False, allow_empty=False, max_length=255, validator=None):
    value = {"default": default, "type": type_, "label": label, "mode": mode,
             "env": env, "sensitive": sensitive}
    if minimum is not None:
        value["min"] = minimum
    if maximum is not None:
        value["max"] = maximum
    if choices is not None:
        value["choices"] = choices
    if allow_empty:
        value["allow_empty"] = True
    if max_length != 255:
        value["max_length"] = max_length
    if validator is not None:
        value["validator"] = validator
    return value


SCHEMA = {
    "host": _item("127.0.0.1", "string", "监听地址", mode="restart", env="LOOMY2API_BIND"),
    "port": _item(8788, "integer", "监听端口", mode="restart", env="LOOMY2API_PORT", minimum=1, maximum=65535),
    "api_key": _item(None, "secret", "管理与推理密钥", mode="startup", env="LOOMY2API_KEY", sensitive=True),
    "loomy_session_path": _item(None, "path", "Loomy 会话文件", mode="startup",
                                env="LOOMY2API_SESSION_PATH", sensitive=True),
    "ui_dir": _item(None, "string", "前端产物目录（留空=不托管，走独立前端）", mode="startup",
                    env="HM2API_UI_DIR", allow_empty=True, max_length=1000),
    "ui_origin": _item("http://127.0.0.1:5199", "string", "独立前端来源（跨域放行）",
                       env="HM2API_UI_ORIGIN", allow_empty=True, max_length=500,
                       validator=normalize_base_url),
    "upstream_base_url": _item("https://loomyad.xunfei.cn/api/v1", "string", "上游接口地址",
                               env="LOOMY2API_UPSTREAM", validator=normalize_base_url),
    "admin_allowed_origins": _item("", "string", "管理页额外信任来源", env="LOOMY2API_ADMIN_ORIGINS",
                                   allow_empty=True, max_length=2000, validator=normalize_allowed_origins),
    "request_timeout": _item(600, "integer", "上游请求超时（秒）", minimum=5, maximum=86400),
    "connect_timeout": _item(20, "integer", "上游连接超时（秒）", minimum=1, maximum=600),
    "model_catalog_ttl": _item(21600, "integer", "模型目录缓存秒数", minimum=0, maximum=31536000),
    "model_guard": _item(True, "boolean", "表外模型拦截"),
    "session_reload_seconds": _item(30, "integer", "会话文件重读间隔（秒）", minimum=0, maximum=86400),
    "max_request_bytes": _item(32 * 1024 * 1024, "integer", "请求字节上限", env="LOOMY2API_MAX_REQUEST_BYTES",
                               minimum=1, maximum=1024 ** 3),
    "max_inbound_bytes": _item(64 * 1024 * 1024, "integer", "入站原始请求体字节上限",
                               env="LOOMY2API_MAX_INBOUND_BYTES", minimum=1, maximum=1024 ** 3),
    "max_concurrent": _item(64, "integer", "推理并发上限（0 不限制）",
                            env="LOOMY2API_MAX_CONCURRENT", minimum=0, maximum=10000),
    "audit_max_bytes": _item(256 * 1024 * 1024, "integer", "审计明细预算", minimum=1024 ** 2, maximum=1024 ** 4),
    "audit_retention_days": _item(30, "integer", "审计明细保留天数", minimum=1, maximum=36500),
    "audit_diagnostic_bytes": _item(8192, "integer", "失败诊断最大字节", minimum=0, maximum=8192),
    "credit_price_cny": _item(0.014, "number", "积分单价（元/积分）", minimum=0),
    # -- second platform: 千问办公（QwenWork CN），并进同一进程/同一密钥/同一面板 --
    "qwenwork_enabled": _item(True, "boolean", "启用千问办公平台"),
    "qwenwork_upstream_base_url": _item("https://gateway.qwenwork.cn/model/v1", "string",
                                        "千问办公上游接口地址", env="QWENWORK2API_UPSTREAM",
                                        validator=normalize_base_url),
    "qwenwork_appdata_dir": _item(None, "string", "千问办公数据目录（auth-v2.dat/Local State 所在）",
                                  mode="startup", env="QWENWORK2API_APPDATA", allow_empty=True,
                                  max_length=1000),
}


def validate_settings(values):
    if not isinstance(values, dict):
        raise ValueError("values 必须是对象")
    clean = {}
    for key, value in values.items():
        spec = SCHEMA.get(key)
        if spec is None or spec["sensitive"]:
            raise ValueError("未知或启动来源锁定的配置项")
        kind = spec["type"]
        valid = ((kind == "boolean" and type(value) is bool)
                 or (kind == "integer" and type(value) is int)
                 or (kind == "number" and type(value) in (int, float) and math.isfinite(value))
                 or (kind == "string" and isinstance(value, str)
                     and (spec.get("allow_empty") or 0 < len(value))
                     and len(value) <= spec.get("max_length", 255)
                     and not any(ord(c) < 32 for c in value)))
        if not valid:
            raise ValueError(f"{key}: 类型或值无效")
        if "min" in spec and value < spec["min"] or "max" in spec and value > spec["max"]:
            raise ValueError(f"{key}: 超出允许范围")
        if "choices" in spec and value not in spec["choices"]:
            raise ValueError(f"{key}: 不支持的选项")
        if spec.get("validator"):
            value = spec["validator"](value)
        clean[key] = value
    return clean


def apply_persisted_settings(config, explicit=(), environ=None):
    """Resolve startup precedence after CLI parsing; config holds parsed CLI values."""
    environ = os.environ if environ is None else environ
    saved = config["control_store"].snapshot()["settings"] if config.get("control_store") else {}
    sources = dict(config.get("settings_sources", {}))
    for key, spec in SCHEMA.items():
        if key in explicit:
            sources[key] = "cli"
        elif spec["env"] and spec["env"] in environ:
            sources[key] = "environment"
            if not spec["sensitive"]:
                raw = environ[spec["env"]]
                if spec["type"] == "boolean":
                    if raw.lower() not in ("1", "0", "true", "false", "yes", "no", "on", "off"):
                        raise ValueError(f"{key}: 环境变量布尔值无效")
                    raw = raw.lower() in ("1", "true", "yes", "on")
                elif spec["type"] == "integer":
                    raw = int(raw)
                elif spec["type"] == "number":
                    raw = float(raw)
                config.update(validate_settings({key: raw}))
        elif key in saved:
            config[key] = saved[key]
            sources[key] = "management"
        else:
            if key not in config or config[key] is None:
                config[key] = spec["default"]
            sources.setdefault(key, "default")
    config["settings_sources"] = sources
    return config


def resolve_settings(config):
    saved = config["control_store"].snapshot()["settings"] if config.get("control_store") else {}
    sources = config.get("settings_sources", {})
    result = []
    for key, spec in SCHEMA.items():
        source = sources.get(key, "default")
        locked = spec["sensitive"] or source in ("cli", "environment", "env", "dotenv")
        item = {"key": key,
                "value": None if spec["sensitive"] else (config[key] if config.get(key) is not None else spec["default"]),
                "stored": None if spec["sensitive"] else saved.get(key), "source": source,
                "mode": spec["mode"], "type": spec["type"], "label": spec["label"], "locked": locked}
        item.update({field: spec[field] for field in ("choices", "min", "max") if field in spec})
        result.append(item)
    return result
