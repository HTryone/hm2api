"""Explicitly installed management API for the Loomy gateway; importing has no side effects."""
from __future__ import annotations

from collections import OrderedDict
import threading
import time

from fastapi import HTTPException, Request
from starlette.concurrency import run_in_threadpool
from starlette.responses import JSONResponse, Response

from core.auth.admin_auth import AdminAuth, AdminMiddleware, COOKIE_NAME, SESSION_TTL, error_response, same_origin
from core.config.control_store import ConflictError, validate_model
from core.config.settings import SCHEMA, resolve_settings, validate_settings

CLEAR_CONFIRMATION = "清空全部日志与统计"


async def _body(request, maximum=65536, *, allow_empty=False):
    data = bytearray()
    async for chunk in request.stream():
        data.extend(chunk)
        if len(data) > maximum:
            raise ValueError("请求体超过大小限制")
    if allow_empty and not data:
        return {}
    try:
        import json
        value = json.loads(data)
    except (ValueError, UnicodeError, RecursionError):
        raise ValueError("请求体必须是有效 JSON 对象") from None
    if not isinstance(value, dict):
        raise ValueError("请求体必须是 JSON 对象")
    return value


def _unbind_requested(query: str) -> bool:
    for pair in (query or "").split("&"):
        key, _, value = pair.partition("=")
        if key == "unbind" and value.lower() in ("1", "true", "on", "yes"):
            return True
    return False


def install_admin(app, config, management):
    """Install management routes using the configured stores and the live Loomy session."""
    if getattr(app.state, "admin_installed", False):
        return app.state.admin_auth
    control, audit = config["control_store"], config["audit_store"]
    auth = AdminAuth(config)
    auth.reconcile()
    mutation_lock = threading.RLock()
    config["admin_mutation_lock"] = mutation_lock
    oauth_tasks = OrderedDict()

    def event(action, details=None):
        try:
            audit.event("admin", action, details)
        except Exception:
            # AuditStore owns its degraded state; audit failure must not leak secrets.
            pass

    def known_models():
        return management.known_models()

    def settings_result():
        items = resolve_settings(config)
        items.append({"key": "session_path", "value": management.session_path(),
                      "stored": None, "source": "startup", "mode": "startup", "type": "path",
                      "label": "Loomy 会话文件", "locked": True})
        return {"revision": control.snapshot()["revision"], "items": items,
                "audit": audit.storage(), "session": auth.storage()}

    def audit_settings(values):
        mapping = {"audit_max_bytes": "max_bytes", "audit_retention_days": "retention_days",
                   "audit_diagnostic_bytes": "preview_limit"}
        return {mapping[key]: value for key, value in values.items() if key in mapping}

    async def dispatch(request):
        return None

    app.add_middleware(AdminMiddleware, auth=auth, dispatch=dispatch)
    app.state.admin_auth = auth
    app.state.admin_installed = True

    def route(method, path):
        def decorate(function):
            async def guarded(request: Request):
                try:
                    return await function(request)
                except ConflictError:
                    return error_response(409, "配置已更新，请刷新后重试")
                except HTTPException as exc:
                    return error_response(exc.status_code, "管理操作不符合当前状态，请刷新后重试")
                except ValueError:
                    return error_response(400, "请求参数、配置或策略无效，请检查类型、范围及冲突")
                except Exception:
                    return error_response(500, "管理操作失败，请检查存储状态后重试")

            guarded.__name__ = function.__name__
            app.add_api_route(path, guarded, methods=[method])
            return function
        return decorate

    from platforms.qwenwork.login import DeviceLogin

    device_login = DeviceLogin()

    def credentials_view():
        rows = []
        for platform, label, can_login in (("loomy", "讯飞 Loomy", False), ("qwenwork", "千问办公", True)):
            view = management.session_view(platform) or {}
            rows.append({
                "platform": platform,
                "label": label,
                "present": bool(view.get("present")),
                "path": view.get("path"),
                "source": view.get("source"),
                "desktop_path": view.get("desktop_path"),
                "account": view.get("phone") or view.get("account"),
                "fingerprint": view.get("token_fingerprint"),
                "error": view.get("error"),
                "can_login": can_login,
                "login_state": device_login.status().get("state") if platform == "qwenwork" else "manual",
            })
        return rows

    async def check_platform(platform):
        """真打一次上游：能拿到模型清单说明这把凭据当前可用。"""
        started = time.time()
        try:
            if platform == "qwenwork":
                session = management.CONFIG.get("qwenwork_session")
                if session is None:
                    return {"ok": False, "models": 0, "elapsed_ms": 0, "error": "千问办公平台未启用"}
                rows = await run_in_threadpool(lambda: session.catalog(ttl=0, force=True))
                count = len(rows or [])
            else:
                catalog = management.CONFIG.get("model_catalog")
                if catalog is None:
                    return {"ok": False, "models": 0, "elapsed_ms": 0, "error": "Loomy 目录未初始化"}
                await catalog.refresh(force=True)
                count = len(catalog.ids())
            elapsed = int((time.time() - started) * 1000)
            return {"ok": count > 0, "models": count, "elapsed_ms": elapsed,
                    "error": None if count else "上游返回空模型表（凭据可能已失效）"}
        except Exception as error:  # noqa: BLE001 - 检测结果要回给面板
            return {"ok": False, "models": 0, "elapsed_ms": int((time.time() - started) * 1000),
                    "error": str(error)[:300] or "检测失败"}

    @route("POST", "/admin/credentials/loomy/check")
    async def credentials_loomy_check(request):
        return JSONResponse(await check_platform("loomy"))

    @route("POST", "/admin/credentials/qwenwork/check")
    async def credentials_qwenwork_check(request):
        return JSONResponse(await check_platform("qwenwork"))

    @route("GET", "/admin/credentials")
    async def credentials_get(request):
        return JSONResponse({"platforms": await run_in_threadpool(credentials_view)})

    @route("GET", "/admin/credentials/qwenwork/login/status")
    async def credentials_qwenwork_status(request):
        state = device_login.status()
        if state.get("state") == "success":
            try:
                management.reload_session("qwenwork")
            except Exception:
                pass
        return JSONResponse(state)

    @route("POST", "/admin/credentials/qwenwork/login")
    async def credentials_qwenwork_login(request):
        try:
            return JSONResponse(await run_in_threadpool(device_login.start))
        except Exception as error:  # noqa: BLE001
            return error_response(500, f"启动登录失败：{error}")

    @route("POST", "/admin/credentials/loomy/login")
    async def credentials_loomy_login(request):
        return JSONResponse({
            "state": "manual",
            "message": "请在 Loomy 桌面端完成登录；网关会自动把会话同步到 cred/loomy/auth-session.json，然后在面板点「重读」。",
            "auth_url": "",
        })

    @route("POST", "/admin/models/sync")
    async def models_sync(request):
        """立刻从上游拉一次模型列表，并回报新增/消失的模型（网关侧自动同步，这里只是马上做一次）。"""
        catalog = management.CONFIG.get("model_catalog")
        qwen = management.CONFIG.get("qwenwork_session")

        before_loomy = set(catalog.ids()) if catalog is not None else set()
        before_qwen = set()
        if qwen is not None:
            try:
                before_qwen = {row["id"] for row in (qwen.cached_catalog() or [])}
            except Exception:
                before_qwen = set()

        try:
            if catalog is not None:
                await catalog.refresh(force=True)
            after_loomy = set(catalog.ids()) if catalog is not None else set()
        except Exception as error:  # noqa: BLE001
            return error_response(502, f"Loomy 目录刷新失败：{error}")

        after_qwen = before_qwen
        if qwen is not None:
            try:
                rows = await run_in_threadpool(lambda: qwen.catalog(ttl=0, force=True))
                after_qwen = {row["id"] for row in (rows or [])}
            except Exception:
                after_qwen = before_qwen

        def summary(before, after):
            return {
                "count": len(after),
                "added": sorted(after - before),
                "removed": sorted(before - after),
            }

        return JSONResponse({
            "ok": True,
            "loomy": summary(before_loomy, after_loomy),
            "qwenwork": summary(before_qwen, after_qwen),
        })

    @route("POST", "/admin/credentials/check-all")
    async def credentials_check_all(request):
        return JSONResponse({
            "results": [
                {"platform": "loomy", **(await check_platform("loomy"))},
                {"platform": "qwenwork", **(await check_platform("qwenwork"))},
            ]
        })

    @route("GET", "/admin/connect")
    async def connect_info(request):
        """对外接入信息：接口地址、密钥、模型名单（面板直接展示，不做隐藏）。"""
        host = str(config.get("host") or "127.0.0.1")
        port = int(config.get("port") or 8788)
        public_host = "127.0.0.1" if host in ("", "0.0.0.0", "::") else host
        base = f"http://{public_host}:{port}"
        models = []
        try:
            inventory = management.model_inventory()
            for entry in inventory.get("models", []) if isinstance(inventory, dict) else inventory:
                models.append({
                    "id": entry.get("public_id") or entry.get("id") or "",
                    "upstream_id": entry.get("upstream_id") or entry.get("id") or "",
                    "name": entry.get("name") or "",
                    "platform": entry.get("platform") or "",
                    "enabled": entry.get("enabled") is not False,
                })
        except Exception:
            models = []
        return JSONResponse({
            "base_url": base + "/v1",
            "chat_url": base + "/v1/chat/completions",
            "models_url": base + "/v1/models",
            "dashboard": base + "/dashboard/",
            "api_key": str(config.get("api_key") or ""),
            "models": models,
        })

    @route("POST", "/admin/session")
    async def session_login(request):
        if auth.csrf_enabled() and not same_origin(request, auth.allowed_origins()):
            return error_response(403, "登录请求 Origin 校验失败")
        data = await _body(request, 8192)
        result, status = auth.login(request, data.get("api_key"))
        if not result:
            return error_response(status, "登录尝试过多，请稍后重试" if status == 429 else "API key 无效")
        sid, session = result
        response = JSONResponse({"authenticated": True, "csrf_token": session["csrf_token"]})
        response.set_cookie(COOKIE_NAME, sid, max_age=SESSION_TTL, httponly=True,
                            secure=request.url.scheme == "https", samesite="strict", path="/admin")
        return response

    @route("GET", "/admin/session")
    async def session_get(request):
        _, session = auth.session(request)
        return JSONResponse({"authenticated": bool(session or auth.header_identity(request)),
                             "csrf_token": session["csrf_token"] if session else None})

    @route("DELETE", "/admin/session")
    async def session_delete(request):
        if not auth.logout(request):
            event("session.revoke_failed", {"code": "session_storage_unavailable"})
            return error_response(503, "会话未能持久撤销，请检查管理目录权限后重试")
        response = JSONResponse({"authenticated": False})
        response.delete_cookie(COOKIE_NAME, path="/admin", httponly=True, samesite="strict",
                               secure=request.url.scheme == "https")
        return response

    # -- settings ------------------------------------------------------------
    @route("GET", "/admin/settings")
    async def settings_get(request):
        return JSONResponse(await run_in_threadpool(settings_result))

    @route("PATCH", "/admin/settings")
    async def settings_patch(request):
        body = await _body(request)
        values = validate_settings(body.get("values"))
        locked = {item["key"] for item in resolve_settings(config) if item["locked"]}
        if values.keys() & locked:
            raise ValueError("配置由 CLI 或环境变量锁定，请修改启动来源")

        def apply():
            with mutation_lock:
                control.update_settings(values, body.get("revision"))
                hot = {key: value for key, value in values.items() if SCHEMA[key]["mode"] == "hot"}
                if audit_settings(hot):
                    configured = audit.configure(**audit_settings(hot))
                    if isinstance(configured, dict) and configured.get("ok") is False:
                        return error_response(503, "配置已保存，但尚未应用；请检查审计存储后重试或重启")
                management.apply_settings(hot)
                config.update(hot)
                config.setdefault("settings_sources", {}).update({key: "management" for key in hot})
            for key in values:
                event("settings.updated", {"code": key})
            return JSONResponse(settings_result())

        return await run_in_threadpool(apply)

    # -- Loomy session -------------------------------------------------------
    @route("GET", "/admin/loomy/session")
    async def loomy_session_get(request):
        return JSONResponse(management.session_view("loomy"))

    @route("POST", "/admin/loomy/session/reload")
    async def loomy_session_reload(request):
        result = await run_in_threadpool(management.reload_session, "loomy")
        event("loomy.session_reloaded", {"code": "ok" if result.get("present") else "unavailable"})
        return JSONResponse(result)

    @route("POST", "/admin/loomy/catalog/refresh")
    async def loomy_catalog_refresh(request):
        result = await management.refresh_catalog()
        if isinstance(result, Response):
            return result
        return JSONResponse(result)

    # -- QwenWork session ----------------------------------------------------
    @route("GET", "/admin/qwenwork/session")
    async def qwenwork_session_get(request):
        return JSONResponse(management.session_view("qwenwork"))

    @route("POST", "/admin/qwenwork/session/reload")
    async def qwenwork_session_reload(request):
        result = await run_in_threadpool(management.reload_session, "qwenwork")
        event("qwenwork.session_reloaded", {"code": "ok" if result.get("present") else "unavailable"})
        return JSONResponse(result)

    # -- models --------------------------------------------------------------
    @route("GET", "/admin/models")
    async def models_get(request):
        def build_models():
            with mutation_lock:
                return JSONResponse(management.model_inventory())

        return await run_in_threadpool(build_models)

    def checked_rule(source, data, *, creating=False):
        if source.startswith("qwenwork/"):
            raise ValueError("千问办公模型是静态目录项，不支持规则编辑")
        if "custom" in data:
            raise ValueError("custom 是只读字段")
        existing = control.snapshot()["models"].get(source, {})
        if creating and (not data.get("public_id") or not data.get("upstream_id")):
            raise ValueError("对外 ID 和上游模型 ID 均不能为空")
        values = {"upstream_id": existing.get("upstream_id", source), **data,
                  "custom": True if creating else existing.get("custom", False)}
        return validate_model(source, values, control.snapshot()["models"], known_models())

    @route("POST", "/admin/models")
    async def models_create(request):
        body = await _body(request)
        source = body.get("source")
        if not isinstance(source, str):
            raise ValueError("source 必须是字符串")
        rule = checked_rule(source, body, creating=True)
        control.update_model(source, rule, body.get("revision"), known_models())
        event("model.created", {"model": source})
        return JSONResponse(await run_in_threadpool(management.model_inventory))

    @route("PUT", "/admin/models/{source}")
    async def models_update(request):
        body = await _body(request)
        source = request.path_params["source"]
        if source not in control.snapshot()["models"] and source not in known_models():
            raise ValueError("模型不存在")
        rule = checked_rule(source, body)
        control.update_model(source, rule, body.get("revision"), known_models())
        event("model.updated", {"model": source})
        return JSONResponse(await run_in_threadpool(management.model_inventory))

    @route("DELETE", "/admin/models/{source}")
    async def models_delete(request):
        body = await _body(request, allow_empty=True)
        source = request.path_params["source"]
        control.delete_model(source, body.get("revision"))
        event("model.deleted", {"model": source})
        return JSONResponse(await run_in_threadpool(management.model_inventory))

    # -- logs ----------------------------------------------------------------
    @route("GET", "/admin/logs")
    async def logs_get(request):
        params = request.query_params
        kind = params.get("kind", "request")
        if kind not in ("request", "runtime", "admin"):
            raise ValueError("日志 kind 无效")
        try:
            limit = int(params.get("limit", "50"))
        except ValueError:
            raise ValueError("limit 必须为整数") from None
        if not 1 <= limit <= 200:
            raise ValueError("limit 必须为 1 至 200")
        filters = {key: params[key] for key in ("model", "profile", "credential", "status", "search") if key in params}
        if any(len(value) > 256 for value in filters.values()) or len(params.get("cursor", "")) > 2048:
            raise ValueError("日志筛选参数过长")
        result = await run_in_threadpool(audit.list_records, kind, limit, params.get("cursor"), **filters)
        if result.get("degraded"):
            return error_response(503, "日志暂时无法读取，请检查审计存储状态")
        return JSONResponse(result)

    @route("GET", "/admin/logs/{record_id}")
    async def logs_detail(request):
        result = await run_in_threadpool(audit.get_request, request.path_params["record_id"])
        if result is None and (await run_in_threadpool(audit.storage)).get("degraded"):
            return error_response(503, "请求明细暂时无法确认，请检查审计存储状态")
        return JSONResponse(result) if result is not None else error_response(404, "请求明细不存在或已清理")

    @route("POST", "/admin/logs/clear")
    async def logs_clear(request):
        body = await _body(request, 8192)
        scope = body.get("scope")
        if scope not in ("details", "all"):
            raise ValueError("清理范围必须为 details 或 all")
        if scope == "all" and (body.get("confirmation") != CLEAR_CONFIRMATION or not auth.check_key(body.get("api_key"))):
            return error_response(403, "全部清理需要确认文本及当前 API key")
        result = await run_in_threadpool(audit.clear, scope)
        if isinstance(result, dict) and result.get("ok") is False:
            return error_response(503, "日志清理未完成，请检查审计存储状态")
        return JSONResponse(result)

    # -- dashboard -----------------------------------------------------------
    @route("GET", "/admin/dashboard")
    async def dashboard_get(request):
        try:
            days = int(request.query_params.get("days", "7"))
        except ValueError:
            raise ValueError("days 必须为 1、7、30 或 90") from None
        if days not in (1, 7, 30, 90):
            raise ValueError("days 必须为 1、7、30 或 90")
        granularity = request.query_params.get("granularity", "auto")
        if granularity not in ("auto", "hour", "day"):
            raise ValueError("granularity 必须为 auto、hour 或 day")

        def build_dashboard():
            result = audit.dashboard(days, granularity=granularity)
            if result.get("degraded"):
                return error_response(503, "统计暂时无法读取，不能确认当前数值；请检查审计存储状态")
            result.setdefault("health", management.health_view())
            result.setdefault("storage", audit.storage())
            result.setdefault("generated_at", time.time())
            result.setdefault("range", {"days": days})
            result["session"] = management.session_view("loomy")
            result["qwenwork_session"] = management.session_view("qwenwork") \
                if management.CONFIG.get("qwenwork_session") is not None else None
            host = str(config.get("host") or "127.0.0.1")
            port = int(config.get("port") or 8788)
            public_host = "127.0.0.1" if host in ("", "0.0.0.0", "::") else host
            base = f"http://{public_host}:{port}"
            result["connect"] = {
                "base_url": base + "/v1",
                "chat_url": base + "/v1/chat/completions",
                "models_url": base + "/v1/models",
                "dashboard": base + "/dashboard/",
                "api_key": str(config.get("api_key") or ""),
                "models": [
                    {"id": e.get("public_id") or e.get("id") or "", "name": e.get("name") or "",
                     "platform": e.get("platform") or "", "enabled": e.get("enabled") is not False}
                    for e in (management.model_inventory() or {}).get("models", [])
                ],
            }
            result["platforms"] = {
                "loomy": management.session_view("loomy"),
                "qwenwork": management.session_view("qwenwork"),
            }
            result["catalog"] = management.catalog_view()
            return result

        result = await run_in_threadpool(build_dashboard)
        return result if isinstance(result, Response) else JSONResponse(result)

    return auth
