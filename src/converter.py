"""Hm2api —— 一个本地网关，两个平台：Loomy（讯飞）+ 千问办公（QwenWork CN）。

把本机桌面端已登录账号的模型能力转成本机回环可用的 OpenAI 兼容 API。
上游按模型 id 分流：不带前缀的走 Loomy（目录、别名规则、积分语义不变），
``qwenwork/`` 前缀走千问办公（凭据取自桌面端 safeStorage 存储）。
与 codebuddy2api 的分工：那个网关走腾讯 WorkBuddy / CodeBuddy 的订阅，
本网关走 Loomy 与千问办公的登录会话。两者互不影响，各自独立进程、独立数据目录。
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import time

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from starlette.concurrency import run_in_threadpool

from core.http import runtime
from core.admin.admin_api import install_admin
from core.audit.audit_store import AuditStore
from core.config.control_store import ControlStore
from core.admin.gateway_management import Management, install_pages
from core.http.inbound_limits import ConcurrencyLimitMiddleware, InboundBodyLimitMiddleware
from core.auth.inference_auth import InferenceAuthMiddleware
from core.http.inference_resources import inference_lifespan
from core.config.paths import data_dir as repo_data_dir, env_file as repo_env_file, ui_dist as repo_ui_dist
from core.auth.session_provider import SessionError
from platforms.loomy.session import LoomySession, default_session_path
from platforms.loomy.catalog import ModelCatalog
from core.audit.observability import AuditMiddleware
from platforms.qwenwork.session import QwenworkSession
from core.http.request_context import RequestContextMiddleware
from core.config.settings import SCHEMA, apply_persisted_settings
from core.http.upstream_proxy import check_model, proxy_chat, upstream_url

APP_VERSION = "0.2.0"

CONFIG = {}

app = FastAPI(title="hm2api", version=APP_VERSION, lifespan=inference_lifespan)


def _loomy_public_ids():
    """Model ids the Loomy side accepts: raw catalogue ids plus panel alias public ids."""
    control = CONFIG.get("control_store")
    ids = set()
    if control is not None:
        ids |= {rule.get("public_id") for rule in control.snapshot()["models"].values() if rule.get("public_id")}
    return ids


def _known_model_ids():
    """The guard set for check_model; None keeps the historical lenient behaviour
    while the Loomy catalogue is unavailable (routing below still gates qwenwork)."""
    catalog = CONFIG.get("model_catalog")
    if catalog is None or not catalog.ids():
        return None
    known = set(catalog.ids())
    known |= _loomy_public_ids()
    known |= {row["id"] for row in _qwenwork_rows()}
    return known or None


def _qwenwork_rows():
    """Model rows from the qwenwork platform; never raises (dashboard stays usable)."""
    from core.auth.session_provider import SessionError

    session = CONFIG.get("qwenwork_session")
    if session is None:
        return []
    try:
        return session.catalog(ttl=int(CONFIG.get("model_catalog_ttl") or 21600))
    except SessionError:
        return session.cached_catalog()


def _platform_model_count(rows):
    return len(rows)


@app.get("/")
def index():
    """根路径直接进面板，避免看到 Not Found。"""
    return RedirectResponse("/dashboard/", status_code=307)


@app.get("/v1")
@app.get("/v1/")
def v1_index():
    """有人把 base url 直接粘进浏览器时会看到这个说明，而不是 Not Found。"""
    platforms = {}
    try:
        catalog = CONFIG.get("model_catalog")
        platforms["loomy"] = len(catalog.ids()) if catalog is not None else 0
    except Exception:
        platforms["loomy"] = 0
    if CONFIG.get("qwenwork_session") is not None:
        try:
            platforms["qwenwork"] = len(_qwenwork_rows())
        except Exception:
            platforms["qwenwork"] = 0
    return {
        "service": "hm2api",
        "version": APP_VERSION,
        "message": "这是 OpenAI 兼容网关的根路径；OpenAI SDK 请把 base_url 设成 .../v1，请求打到下面的端点。",
        "endpoints": {
            "models": "/v1/models",
            "chat_completions": "/v1/chat/completions",
            "health": "/health",
            "dashboard": "/dashboard/",
        },
        "auth": "Authorization: Bearer <API Key>（面板「接入信息」里可直接复制）",
        "platforms": platforms,
    }


@app.get("/health")
def health():
    session = CONFIG.get("loomy_session")
    view = session.describe() if session is not None else {"present": False}
    catalog = CONFIG.get("model_catalog")
    loomy_count = catalog.snapshot()["count"] if catalog is not None else 0
    qwenwork_rows = _qwenwork_rows()
    platforms = {"loomy": {"session": bool(view.get("present")), "models": loomy_count}}
    qwenwork = CONFIG.get("qwenwork_session")
    if qwenwork is not None:
        # Refresh the short-lived MaaS key first so /health never reports a stale expiry.
        try:
            qwenwork.token()
        except SessionError:
            pass
        qview = qwenwork.describe()
        platforms["qwenwork"] = {"session": bool(qview.get("present")),
                                 "models": _platform_model_count(qwenwork_rows),
                                 "inference_ready": bool(qview.get("inference_ready")),
                                 "base_url": qview.get("base_url"),
                                 "expires_in_seconds": qview.get("key_expires_in_seconds")}
    return {"status": "ok", "version": APP_VERSION, "session": bool(view.get("present")),
            "models": loomy_count + _platform_model_count(qwenwork_rows), "platforms": platforms}


@app.get("/v1/models")
async def list_models():
    catalog = CONFIG.get("model_catalog")
    if catalog is not None and catalog.stale():
        await catalog.refresh()
    control = CONFIG.get("control_store")
    rules = control.snapshot()["models"] if control is not None else {}
    data = []
    for item in (catalog.details() if catalog is not None else []):
        rule = rules.get(item["id"], {})
        if rule.get("enabled") is False:
            continue
        data.append({"id": rule.get("public_id") or item["id"], "object": "model",
                     "created": item.get("created") or 1700000000, "owned_by": item.get("owned_by") or "loomy",
                     "name": item.get("name"), "type": item.get("type"),
                     "context_length": item.get("context_length"),
                     "max_output_tokens": item.get("max_output_tokens"),
                     "capabilities": item.get("capabilities"),
                     "reasoning_efforts": item.get("reasoning_efforts"),
                     "is_default": item.get("is_default", False),
                     "platform": "loomy"})
    for item in _qwenwork_rows():
        data.append({"id": item["id"], "object": "model",
                     "created": item.get("created") or 1700000000, "owned_by": "qwenwork",
                     "name": item.get("name"), "type": item.get("type"),
                     "context_length": item.get("context_length"),
                     "max_output_tokens": item.get("max_output_tokens"),
                     "capabilities": item.get("capabilities"),
                     "reasoning_efforts": item.get("reasoning_efforts"),
                     "is_default": item.get("is_default", False),
                     "platform": "qwenwork"})
    return {"object": "list", "data": data}


@app.post("/v1/chat/completions")
async def chat_completions(request: Request):
    catalog = CONFIG.get("model_catalog")
    if catalog is not None and catalog.stale():
        await catalog.refresh()
    return await proxy_chat(request, CONFIG, _known_model_ids())


@app.get("/v1/dashboard/billing/subscription")
def billing_subscription():
    return {"hard_limit_usd": None, "soft_limit_usd": None, "system_hard_limit_usd": None,
            "note": "本网关按 Loomy 积分计费（qwenwork/ 前缀模型由千问办公订阅承担、无积分字段）；金额需按积分单价换算，请以 /admin/dashboard 的 credit 为准。"}


def managed_data_dir() -> Path:
    return Path(CONFIG.get("data_dir") or repo_data_dir())


def load_startup_env():
    """Load .env without overriding already-exported variables; report which keys came from it."""
    path = repo_env_file()
    if not path.is_file():
        return set()
    try:
        raw = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return set()
    if raw.startswith("\ufeff"):
        sys.stderr.write("[env] .env 带 BOM，已忽略；请以 UTF-8 无 BOM 重写。\n")
        return set()
    before = set(os.environ)
    load_dotenv(path, override=False)
    return {key for key in os.environ if key not in before}


def _boolean_arg(value):
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("1", "true", "yes", "on")


def _positive_int(value):
    number = int(value)
    if number <= 0:
        raise argparse.ArgumentTypeError("必须是正整数")
    return number


def _nonnegative_int(value):
    number = int(value)
    if number < 0:
        raise argparse.ArgumentTypeError("必须是非负整数")
    return number


def ensure_layout():
    """从零启动自举：建目录、生成 .env、缺密钥就生成并写回 .env（别人拉仓库双击即可）。"""
    import re
    import secrets

    from core.config.paths import repo_root

    root = repo_root()
    for rel in ("data", "cred/loomy", "cred/qwenwork", "logs"):
        try:
            (root / rel).mkdir(parents=True, exist_ok=True)
        except OSError:
            pass

    env = root / ".env"
    created = False
    if not env.is_file():
        example = root / ".env.example"
        template = example.read_text(encoding="utf-8") if example.is_file() else ""
        template = template.replace("loomy2api 运行时配置", "Hm2api 运行时配置").replace(
            "留空默认 loomy2api/data", "留空默认 data/")
        try:
            env.write_text(template, encoding="utf-8", newline="\n")
            created = True
        except OSError:
            return

    try:
        text = env.read_text(encoding="utf-8")
    except OSError:
        return
    match = re.search(r"(?m)^LOOMY2API_KEY=(.*)$", text)
    if match and not match.group(1).strip():
        key = "hm2-" + secrets.token_urlsafe(24)
        text = text[: match.start(1)] + key + text[match.end(1):]
        try:
            env.write_text(text, encoding="utf-8", newline="\n")
        except OSError:
            return
        print(f"首次启动：已生成 API Key 并写入 .env → {key}")
    elif created:
        print("首次启动：已根据 .env.example 生成 .env")


def initialize(args, parser, dotenv_keys):
    """Build the stores before the server accepts traffic."""
    data_dir = Path(args.data_dir).resolve() if args.data_dir else repo_data_dir()
    data_dir.mkdir(parents=True, exist_ok=True)
    CONFIG["data_dir"] = data_dir
    control = ControlStore(data_dir / "control.sqlite3")
    CONFIG["control_store"] = control
    CONFIG["state_store"] = control.state
    CONFIG.update({key: getattr(args, key) for key in SCHEMA if hasattr(args, key)})
    explicit = set()
    options = parser._option_string_actions
    for argument in sys.argv[1:]:
        if argument.startswith("--"):
            flag = argument.split("=", 1)[0]
            matches = [flag] if flag in options else [name for name in options if name.startswith(flag)]
            if len(matches) == 1:
                explicit.add(options[matches[0]].dest)
    apply_persisted_settings(CONFIG, explicit=explicit)
    CONFIG["api_key"] = args.api_key or CONFIG.get("api_key")
    session_path = Path(args.session_path).resolve() if args.session_path else default_session_path()
    CONFIG["loomy_session"] = LoomySession(session_path, ttl=CONFIG["session_reload_seconds"])
    CONFIG["model_catalog"] = ModelCatalog(CONFIG, CONFIG["loomy_session"])
    CONFIG["model_catalog"].load_from_state()
    if CONFIG.get("qwenwork_enabled", True):
        appdata_dir = CONFIG.get("qwenwork_appdata_dir") or None
        CONFIG["qwenwork_session"] = QwenworkSession(appdata_dir, ttl=CONFIG["session_reload_seconds"])
    # Warm the sessions once at startup so /health and the dashboard are truthful immediately.
    try:
        CONFIG["loomy_session"].token()
    except SessionError as error:
        sys.stderr.write(f"[session] Loomy 会话暂不可用：{error}\n")
    qwenwork = CONFIG.get("qwenwork_session")
    if qwenwork is not None:
        try:
            qwenwork.token()
        except SessionError as error:
            sys.stderr.write(f"[session] 千问办公凭据暂不可用：{error}\n")
    try:
        CONFIG["audit_store"] = AuditStore(data_dir / "logs.sqlite3", max_bytes=CONFIG["audit_max_bytes"],
                                           retention_days=CONFIG["audit_retention_days"],
                                           preview_limit=CONFIG["audit_diagnostic_bytes"])
    except (OSError, ValueError, RuntimeError) as error:
        sys.stderr.write(f"[audit] 日志库不可用：{type(error).__name__}；请检查目录权限。\n")
        raise SystemExit(1)
    CONFIG["management"] = Management(sys.modules[__name__])
    app.state.config = CONFIG
    return control


def install():
    install_admin(app, CONFIG, CONFIG["management"])
    app.add_middleware(AuditMiddleware, config=CONFIG)
    app.add_middleware(InboundBodyLimitMiddleware, config=CONFIG)
    app.add_middleware(ConcurrencyLimitMiddleware, config=CONFIG)
    app.add_middleware(InferenceAuthMiddleware, config=CONFIG)
    app.add_middleware(RequestContextMiddleware, config=CONFIG)
    ui_origin = (CONFIG.get("ui_origin") or "").strip()
    if ui_origin:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=[ui_origin],
            allow_credentials=True,
            allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
            allow_headers=["Authorization", "Content-Type", "X-CSRF-Token", "Accept"],
        )
    ui_dir = CONFIG.get("ui_dir")
    install_pages(app, ui_dir if ui_dir is not None else str(repo_ui_dist()), origin=ui_origin)


def close():
    for key in ("audit_store", "control_store"):
        store = CONFIG.get(key)
        if store is not None:
            store.close()


def main():
    ensure_layout()
    dotenv_keys = set() if any(arg in ("-h", "--help") for arg in sys.argv[1:]) else load_startup_env()
    ap = argparse.ArgumentParser(description="Loomy + 千问办公 -> OpenAI 兼容本地网关")
    ap.add_argument("--host", default="127.0.0.1", help="监听地址；覆盖 LOOMY2API_BIND")
    ap.add_argument("--port", type=int, default=8788, help="监听端口；覆盖 LOOMY2API_PORT")
    ap.add_argument("--api-key", default=os.environ.get("LOOMY2API_KEY", ""),
                    help="管理与推理密钥；未配置时首次本地交互启动生成并保存")
    ap.add_argument("--session-path", default=os.environ.get("LOOMY2API_SESSION_PATH") or None,
                    metavar="PATH", help="Loomy 会话文件；默认自动推导")
    ap.add_argument("--data-dir", default=os.environ.get("LOOMY2API_DATA_DIR") or None,
                    metavar="PATH", help="数据目录；默认 hm2api/data")
    ap.add_argument("--upstream", default=os.environ.get("LOOMY2API_UPSTREAM", "https://loomyad.xunfei.cn/api/v1"),
                    metavar="URL", help="Loomy 上游接口地址")
    ap.add_argument("--admin-csrf", type=_boolean_arg, nargs="?", const=True,
                    default=os.environ.get("LOOMY2API_ADMIN_CSRF", "true"),
                    help="管理 Origin/CSRF 校验，默认 true")
    ap.add_argument("--admin-allowed-origins", default=os.environ.get("LOOMY2API_ADMIN_ORIGINS"),
                    metavar="ORIGINS", help="额外信任的管理页来源（逗号分隔）")
    ap.add_argument("--request-timeout", type=_positive_int, default=600, metavar="SECONDS",
                    help="上游请求超时，默认 600 秒")
    ap.add_argument("--connect-timeout", type=_positive_int, default=20, metavar="SECONDS",
                    help="上游连接超时，默认 20 秒")
    ap.add_argument("--model-catalog-ttl", type=_nonnegative_int, default=6 * 3600, metavar="SECONDS",
                    help="模型表缓存有效期，默认 21600 秒")
    ap.add_argument("--no-model-guard", action="store_true",
                    help="关闭表外模型本地拦截；默认拦截")
    ap.add_argument("--session-reload-seconds", type=_nonnegative_int, default=30, metavar="SECONDS",
                    help="会话文件重读间隔，默认 30 秒；0 表示只在文件变化时重读")
    ap.add_argument("--max-request-bytes", type=_positive_int, default=32 * 1024 * 1024, metavar="BYTES",
                    help="请求体字节上限，默认 32 MiB")
    ap.add_argument("--max-inbound-bytes", type=_positive_int, default=64 * 1024 * 1024, metavar="BYTES",
                    help="入站原始请求体字节上限，默认 64 MiB")
    ap.add_argument("--max-concurrent", type=_nonnegative_int, default=64, metavar="N",
                    help="推理并发上限，默认 64；0 不限制")
    ap.add_argument("--credit-price-cny", type=float, default=0.014, metavar="PRICE",
                    help="积分折算单价（元/积分），默认 0.014")
    ap.add_argument("--audit-max-bytes", type=_positive_int, default=256 * 1024 * 1024, metavar="BYTES",
                    help="审计明细预算，默认 256 MiB")
    ap.add_argument("--audit-retention-days", type=_positive_int, default=30, metavar="DAYS",
                    help="审计明细保留天数，默认 30")
    ap.add_argument("--audit-diagnostic-bytes", type=_nonnegative_int, default=8192, metavar="BYTES",
                    help="失败诊断最大字节，默认 8192")
    args = ap.parse_args()

    initialize(args, ap, dotenv_keys)
    if not CONFIG.get("api_key"):
        CONFIG["api_key"] = _generate_key(CONFIG)
        sys.stderr.write(f"[key] 已生成并保存管理密钥；请在面板登录时使用：{CONFIG['api_key']}\n")
    CONFIG["admin_csrf"] = args.admin_csrf
    CONFIG["admin_allowed_origins"] = args.admin_allowed_origins or ""
    try:
        install()
    except Exception as error:
        close()
        sys.stderr.write(f"[startup] 管理接口安装失败：{type(error).__name__}: {error}\n")
        raise SystemExit(1) from None

    import uvicorn

    sys.stderr.write(f"\n✅ 监听 http://{args.host}:{args.port}（Loomy + 千问办公双上游）\n")
    sys.stderr.write(f"   WebUI     : http://{args.host}:{args.port}/dashboard\n")
    sys.stderr.write(f"   上游      : {CONFIG['upstream_base_url']}\n")
    sys.stderr.write(f"   会话文件  : {CONFIG['loomy_session'].path}\n")
    qwenwork = CONFIG.get("qwenwork_session")
    if qwenwork is not None:
        sys.stderr.write(f"   千问办公  : {CONFIG['qwenwork_upstream_base_url']}（凭据目录 {qwenwork.dir}）\n")
    else:
        sys.stderr.write("   千问办公  : 已停用（qwenwork_enabled=false）\n")
    sys.stderr.write(f"   数据目录  : {CONFIG['data_dir']}\n")
    sys.stderr.write("   GET  /v1/models\n")
    sys.stderr.write("   POST /v1/chat/completions\n")
    sys.stderr.write("   GET  /health\n")
    sys.stderr.write("按 Ctrl+C 退出。\n\n")
    try:
        uvicorn.run(app, host=args.host, port=args.port, log_level="info", access_log=False)
    finally:
        close()


def _generate_key(config):
    """Create and persist a management key once, so the UI has a stable login."""
    import secrets
    store = config["state_store"]
    with store.transaction():
        row = store._db.execute("SELECT value FROM gateway_secrets WHERE name='default_api_key'").fetchone()
        if row is not None:
            return row[0]
        key = "loomy-" + secrets.token_hex(16)
        store._db.execute("INSERT INTO gateway_secrets(name,value,announced) VALUES('default_api_key',?,0)", (key,))
        return key


if __name__ == "__main__":
    main()
