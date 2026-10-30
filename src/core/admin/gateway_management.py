"""Management views over the Loomy session and catalogue, without ever returning the token."""
from __future__ import annotations

import time
from pathlib import Path

from fastapi import Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from starlette.staticfiles import StaticFiles


class Management:
    def __init__(self, gateway):
        self.gateway = gateway
        self.CONFIG = gateway.CONFIG

    def __getattr__(self, name):
        return getattr(self.gateway, name)

    # -- session -------------------------------------------------------------
    def _session(self, platform="loomy"):
        from core.upstreams import PLATFORMS
        spec = PLATFORMS.get(platform)
        if spec is None:
            return None
        return self.CONFIG.get(spec["session_key"])

    def session_path(self, platform="loomy"):
        session = self._session(platform)
        return str(session.path) if session is not None and getattr(session, "path", None) else (
            str(session.dir) if session is not None and getattr(session, "dir", None) else None)

    def session_view(self, platform="loomy"):
        session = self._session(platform)
        if session is None:
            return {"present": False, "error": "会话读取器未初始化（平台未启用）", "path": None}
        try:
            return session.describe()
        except Exception:
            return {"present": False, "error": "会话状态读取失败", "path": self.session_path(platform)}

    def reload_session(self, platform="loomy"):
        session = self._session(platform)
        if session is None:
            return {"present": False, "error": "会话读取器未初始化（平台未启用）", "path": None}
        try:
            return session.reload()
        except Exception as error:
            return {**session.describe(), "present": False, "error": str(error)}

    # -- catalogue -----------------------------------------------------------
    def catalog_view(self):
        catalog = self.CONFIG.get("model_catalog")
        if catalog is None:
            return {"models": {}, "count": 0, "error": "模型目录未初始化", "fetched_at": None, "ttl": 0}
        return catalog.snapshot()

    async def refresh_catalog(self):
        catalog = self.CONFIG.get("model_catalog")
        if catalog is None:
            return {"ok": False, "error": "模型目录未初始化"}
        snapshot = await catalog.refresh(force=True)
        return {"ok": True, **snapshot}

    def known_models(self):
        catalog = self.CONFIG.get("model_catalog")
        return sorted(catalog.ids()) if catalog is not None else []

    # -- models --------------------------------------------------------------
    def model_inventory(self):
        """Merge both platforms' models with the local rules so the UI sees one row per model."""
        from core.upstreams import qwenwork_enabled, public_models
        control = self.CONFIG.get("control_store")
        rules = control.snapshot()["models"] if control is not None else {}
        catalog = self.CONFIG.get("model_catalog")
        facts = {item["id"]: item for item in (catalog.details() if catalog is not None else [])}
        rows = []
        for source in sorted(set(facts) | set(rules)):
            fact = facts.get(source, {"id": source, "name": source, "type": "chat"})
            rule = rules.get(source, {"public_id": source, "upstream_id": source, "custom": False,
                                      "enabled": True, "keep_original": False})
            rows.append({**fact, **rule, "id": source, "available": source in facts,
                         "is_default": fact.get("is_default", False),
                         "platform": "loomy", "managed": True})
        if qwenwork_enabled(self.CONFIG):
            for item in public_models(self.CONFIG):
                rows.append({**item, "public_id": item["id"], "upstream_id": item["upstream_id"],
                             "custom": False, "enabled": True, "keep_original": False,
                             "available": True, "is_default": False,
                             "platform": "qwenwork", "managed": False})
        return {"revision": control.snapshot()["revision"] if control is not None else 0,
                "models": rows, "catalog": self.catalog_view()}

    # -- health --------------------------------------------------------------
    def health_view(self):
        from core.upstreams import qwenwork_enabled
        session = self.session_view("loomy")
        catalog = self.catalog_view()
        result = {"session": session, "catalog": {"count": catalog.get("count"),
                                                  "fetched_at": catalog.get("fetched_at"),
                                                  "error": catalog.get("error")},
                  "platforms": {"loomy": {"session": session.get("present"),
                                          "models": catalog.get("count")}}}
        if qwenwork_enabled(self.CONFIG):
            qview = self.session_view("qwenwork")
            result["platforms"]["qwenwork"] = {"session": qview.get("present"), "expires_in_seconds":
                                               qview.get("expires_in_seconds")}
            result["qwenwork_session"] = qview
        return result

    # -- settings ------------------------------------------------------------
    def apply_settings(self, values):
        from core.qwenwork_session import QwenworkSession
        restart = {"host", "port", "loomy_session_path", "upstream_base_url",
                   "qwenwork_upstream_base_url", "qwenwork_appdata_dir"}
        catalog = self.CONFIG.get("model_catalog")
        for key, value in values.items():
            if key in restart:
                continue
            self.CONFIG[key] = value
        if "model_catalog_ttl" in values and catalog is not None:
            catalog.ttl = int(values["model_catalog_ttl"])
        if "qwenwork_enabled" in values:
            if values["qwenwork_enabled"]:
                if self.CONFIG.get("qwenwork_session") is None:
                    appdata_dir = self.CONFIG.get("qwenwork_appdata_dir") or None
                    self.CONFIG["qwenwork_session"] = QwenworkSession(
                        appdata_dir, ttl=self.CONFIG.get("session_reload_seconds", 30))
            else:
                self.CONFIG.pop("qwenwork_session", None)


def install_pages(app, directory, origin=None):
    """Frontend is a separate project (ui/).

    directory falsy → 不托管任何前端文件，/dashboard 直接指向独立前端 origin。
    """
    root = Path(directory).resolve() if directory else None
    fallback_origin = (origin or "").rstrip("/") or None
    pages = {"", "models", "logs", "settings", "credentials", "login"}
    assets = StaticFiles(directory=root / "assets", check_dir=False)

    @app.api_route("/dashboard/assets/{asset_path:path}", methods=["GET", "HEAD"], include_in_schema=False)
    async def dashboard_asset(asset_path: str, request: Request):
        if "\x00" in asset_path:
            return JSONResponse({"detail": "Not Found"}, status_code=404)
        response = await assets.get_response(asset_path, request.scope)
        response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    @app.api_route("/dashboard", methods=["GET", "HEAD"], include_in_schema=False)
    def dashboard_redirect():
        """前端用相对路径引资源，必须带尾斜杠，否则 /dashboard 会被当成文件。"""
        return RedirectResponse("/dashboard/", status_code=308)

    @app.api_route("/dashboard/", methods=["GET", "HEAD"], include_in_schema=False)
    @app.api_route("/dashboard/{page:path}", methods=["GET", "HEAD"], include_in_schema=False)
    def dashboard_page(page=""):
        if page == "assets" or page.startswith("assets/"):
            return JSONResponse({"detail": "Not Found"}, status_code=404)
        if page not in pages:
            if Path(page).suffix:
                return JSONResponse({"detail": "Not Found"}, status_code=404)
            return RedirectResponse("/dashboard", status_code=302)
        if root is None:
            if fallback_origin:
                return RedirectResponse(fallback_origin, status_code=302)
            return JSONResponse({"detail": "前端未托管（HM2API_UI_DIR 为空）且未配置 HM2API_UI_ORIGIN。"},
                                status_code=503, headers={"Cache-Control": "no-store"})
        target = root / "index.html"
        if not target.is_file():
            return JSONResponse({"detail": "面板文件缺失：ui/dist/index.html 不存在（前端是独立静态项目，无需构建）。API 服务不受影响。"},
                                status_code=503, headers={"Cache-Control": "no-store"})
        return FileResponse(target, headers={"Cache-Control": "no-store",
                                             "X-Content-Type-Options": "nosniff",
                                             "Referrer-Policy": "same-origin"})

    @app.api_route("/{path:path}", methods=["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
                   include_in_schema=False)
    def page_fallback(path=""):
        if path.split("/", 1)[0] in {"v1", "admin", "health"} or Path(path).suffix:
            return JSONResponse({"detail": "Not Found"}, status_code=404)
        return RedirectResponse("/dashboard", status_code=302)
