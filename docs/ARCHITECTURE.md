# 架构：Hm2api 一个网关、多平台

```
converter.py            # 入口：装配 CONFIG、挂路由与中间件、起 uvicorn
core/                   # 与平台无关的机制
  upstreams.py          # 平台注册表：session_key / url_key / headers_for / credit / catalog / dynamic_base
  upstream_proxy.py     # 按平台选 URL、头模板、计费改写；public_id → upstream_id 还原
  session_provider.py   # 会话提供者契约（SessionError）
  model_catalog.py(旧)  # 已迁至 platforms/loomy/catalog.py
  settings.py / state_store.py / control_store.py / audit_store.py
  admin_api.py / admin_auth.py / gateway_management.py / inbound_limits.py
  inference_auth.py / inference_resources.py / observability.py / request_context.py / runtime.py / session_labels.py
platforms/
  loomy/session.py      # 讯飞 Loomy：读桌面端 auth-session.json（仓库内 cred/loomy 为同步副本）
  loomy/catalog.py      # 讯飞 Loomy：/models 远程目录 + 6 小时缓存
  qwenwork/session.py   # 千问办公：设备码 JWT → desktop-sessions 换 2h maas key；目录 /api/desktop/chat-modes
scripts/qwenwork-login.py  # 设备码 PKCE 登录（写 cred/qwenwork/session.json）
cred/<平台>/            # 凭据 + README（整目录被 git 过滤）
web/dist/               # 手写静态 SPA（无构建步骤）
```

## 请求路径
1. `POST /v1/chat/completions` → `core.inference_auth` 校验同一把 key
2. `core.upstream_proxy.proxy_chat` 读 body → `route_model()` 判定平台（`qwenwork/` 前缀或 Loomy）
3. 取该平台的 session → `token()`（Loomy 读文件；千问办公按需换 maas key）
4. 拼 URL：静态 base（settings）或 `dynamic_base`（千问办公用 session 给的 base_url）
5. 转发；`credit` 仅对 Loomy 生效（`points_consumed → credit`）
6. 审计按 `profile = 平台名` 记录，面板据此分平台展示

## 加一个新平台
1. 新建 `platforms/<名>/session.py`，实现 `platform` / `token()` / `describe()` / `reload()`
2. `core/upstreams.py` 的 `PLATFORMS` 加一条（必要时 `dynamic_base` / `credit`）
3. `converter.py` 初始化该 session；`/v1/models` 与 `/health` 自动带上
4. `cred/<名>/` 放凭据 + README；面板会自动多出一行平台
