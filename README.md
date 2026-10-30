# Hm2api —— 本地多平台模型网关

> 一个进程、一个端口（8788）、一把 key，把本机多个 AI 客户端的登录态转成 OpenAI 兼容 API。
> 当前平台：**讯飞 Loomy**、**千问办公（QwenWork CN）**。

- 架构说明：[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
- 平台与鉴权：[docs/PLATFORMS.md](docs/PLATFORMS.md)
- 凭据说明：[cred/README.md](cred/README.md)（整目录被 git 过滤）
- 快速启动：双击工作区的 `启动Hm2网关.lnk`（等价 `wscript 启动Hm2网关.vbs`）

## 从零开始（别人拿到这个仓库）

1. 装一次 [uv](https://docs.astral.sh/uv/)（Windows：`powershell -c "irm https://astral.sh/uv/install.ps1 | iex"`）。
2. **双击仓库根目录的 `启动Hm2网关.vbs`**（或无窗口不方便时双击 `start.cmd`）。
   首次运行会自动完成：建 `data/`、`cred/loomy/`、`cred/qwenwork/`、`logs/`，
   从 `.env.example` 生成 `.env`，**生成随机 API Key 并写回 `.env`**，安装依赖。
3. 打开 <http://127.0.0.1:8788/dashboard/>，概览页「接入信息」里就能看到
   **接口地址 / API Key / 模型名单**，点「复制」直接用。
4. 平台凭据：
   - 讯飞 Loomy：装桌面端并登录，网关会自动把它同步到 `cred/loomy/auth-session.json`。
   - 千问办公：`python src/scripts/qwenwork-login.py` 走一次设备码登录（7 天有效）。
5. 什么都失败时看 `logs/gateway.err.log`。

> 仓库里被过滤的只有本机数据：`.env`、`cred/**`（凭据本体）、`data/`、`logs/`、`.venv/`。
> 目录结构与说明文档都会随仓库下发，缺的目录启动时自动补。

---

# 平台一：讯飞 Loomy（桌面端 → OpenAI 兼容 API）

把本机 **Loomy 桌面端**已登录的账号，变成本机回环可用的 **OpenAI 兼容 API**。
上游为 `https://loomyad.xunfei.cn/api/v1`，鉴权使用 Loomy 桌面端 `auth-session.json` 里的会话令牌。

> **与 `codebuddy2api` 无关**：那是腾讯 WorkBuddy / CodeBuddy 的网关（`127.0.0.1:8787`）。
> 本目录是**独立的第二套网关**（`127.0.0.1:8788`），进程、数据、密钥、模型表全部隔离，两者可同时运行。

---

## 快速开始

### 方式一：双击（推荐）

桌面图标 **「启动Loomy网关」**（`启动Loomy网关.lnk`）→ `wscript.exe "D:\perca\subsapi\启动Loomy网关.vbs"`

- **完全无窗口**启动；已在运行则直接开面板；未运行则静默拉起、等 `/health` 通过后自动打开管理面板
- 图标起的进程**脱离任何会话**，关掉 DSH / 终端都不会把它带走
- ⚠️ 若直接双击 **`启动Loomy网关.vbs` 文件本体**，Windows 会弹一次「打开文件 - 安全警告」，**点一次「打开」即永久放行**（桌面图标走 `wscript.exe`，不会弹）

### 方式二：命令行

```powershell
powershell -ExecutionPolicy Bypass -File D:\perca\subsapi\scripts\start-loomy-gateway.ps1
```

幂等：已在运行不重启；重启加 `-Restart`；前台实时日志加 `-Foreground`。

### 前置条件

| 项 | 要求 |
|---|---|
| Loomy 桌面端 | **已安装并登录**（否则会话文件不存在，`/health` 会返回 `session: false`） |
| Python | 3.12+；本目录自带 `.venv`（由 `uv` 管理），无需手动装 |
| 端口 | `8788` 空闲 |

---

## 端点

| 端点 | 方法 | 说明 |
|---|---|---|
| `/health` | GET | 存活 + 会话状态 + 模型数 |
| `/v1/models` | GET | 模型表（OpenAI 格式，含 `context_length` / `max_output_tokens`） |
| `/v1/chat/completions` | POST | 对话，**流式 / 非流式**，OpenAI 协议 |
| `/v1/dashboard/billing/subscription` | GET | 兼容用余额占位 |
| `/dashboard` | GET | **管理面板** |
| `/dashboard/assets/{path}` | GET | 面板静态资源 |

推理接口需要请求头 `Authorization: Bearer <LOOMY2API_KEY>`。

---

## 管理面板

浏览器打开 **`http://127.0.0.1:8788/dashboard`**，登录口令＝`.env` 里的 `LOOMY2API_KEY`（会话 cookie 有效期 12 小时）。

面板四页：

| 页面 | 内容 |
|---|---|
| **概览** | 请求总量、成功率、Token 用量、**Loomy 积分消耗**、请求趋势、模型使用排行、Loomy 会话状态、模型目录 |
| **模型路由** | 模型清单与启停、自定义模型 |
| **日志审计** | 每次请求的模型 / 结果 / Token / 积分 / 耗时，可查详情、可清空 |
| **系统设置** | 上行参数（超时、限额等） |

**用量与花费看这里**，不必另做看板。

---

## 配置（`.env`）

| 键 | 默认 / 说明 |
|---|---|
| `LOOMY2API_BIND` | 监听地址，默认 `127.0.0.1` |
| `LOOMY2API_PORT` | 监听端口，默认 `8788` |
| `LOOMY2API_KEY` | **管理与推理密钥**（面板登录也用这一把） |
| `LOOMY2API_UPSTREAM` | Loomy 上游，默认 `https://loomyad.xunfei.cn/api/v1` |
| `LOOMY2API_SESSION_PATH` | 会话文件路径；**留空 = 自动探测** `C:\Users\Public\Loomy\<hash>\userData\auth-session.json` |
| `LOOMY2API_DATA_DIR` | 数据目录；**留空 = 本目录下 `data\`** |
| `LOOMY2API_ADMIN_CSRF` | 管理接口 CSRF 校验，默认开 |
| `LOOMY2API_ADMIN_ORIGINS` | 反代场景下的可信管理来源 |
| `LOOMY2API_MODEL_GUARD` | 模型能力预检 |
| `LOOMY2API_MAX_REQUEST_BYTES` | 上游请求体上限，默认 32 MiB |
| `LOOMY2API_MAX_INBOUND_BYTES` | 入站原始体上限，默认 64 MiB |
| `LOOMY2API_MAX_CONCURRENT` | 并发推理上限，默认 64 |

命令行参数（`--host` / `--port` / `--session-path` / `--data-dir` / `--upstream` 等）**优先于** `.env`。
其它代码默认值：请求超时 `600s`、连接超时 `20s`、模型目录 TTL `6h`、会话重载 `30s`、积分单价 `0.014 元`、审计保留 `30 天`。

> ⚠️ `.env` **必须 UTF-8 无 BOM，且只用 ASCII 可见字符** —— 带 BOM 会让 `uv` **静默丢弃整份配置**（服务照常起，只是配置全失效）。
> 写法：`[System.IO.File]::WriteAllText($p,$t,(New-Object System.Text.UTF8Encoding($false)))`

---

## Loomy 会话是怎么来的

- Loomy 桌面端把登录态存成 `auth-session.json`：`{session, userid, phone, updatedAt}` —— **明文**，`session` 是 32 字符的**不透明令牌**（不是 JWT）。
- 配置根目录规则：`C:\Users\Public\Loomy\<sha256(USERNAME)[:12]>`（本机为 `1019b8cbdb56`）。
- 网关**只读**该文件，按 TTL（`--session-reload-seconds`，默认 30s）+ 文件 mtime 变化自动重读；面板「Loomy 会话」卡片可点「重新加载」手动刷新。
- 上游**只需要** `Authorization: Bearer <session>`（实测 `token` / `traceparent` / `loomy-version` 等头都可选）。
- 桌面端重新登录后，网关**下一个请求自动拿到新令牌，不用重启**。

---

## 目录结构

```
converter.py                 入口：FastAPI 路由 + 启动/关闭 + 命令行参数
app/
  settings.py                配置 schema、校验与解析
  loomy_session.py           会话文件读取（TTL + mtime）
  model_catalog.py           上游模型表（TTL + SQLite 持久化）
  upstream_proxy.py          对话代理（流式逐行透传；points_consumed → credit）
  inference_auth.py          推理接口鉴权
  inference_resources.py     上游 HTTP 客户端生命周期
  admin_api.py               管理接口（/admin/*）
  admin_auth.py              登录会话 + CSRF
  gateway_management.py      管理面板页面与业务逻辑
  audit_store.py             审计库（SQLite requests 表）
  control_store.py           控制库（模型路由等，revision 乐观锁）
  state_store.py             键值状态（sessions / catalog 命名空间）
  session_labels.py          审计标签（profile=loomy、凭证指纹）
  inbound_limits.py          入站体积 / 并发限额
  runtime.py                 运行期依赖注入
  observability.py           日志与可观测
web/
  index.html                 面板入口
  dist/                      实际服务的构建产物（index.html + assets/{app.css,app.js,favicon.svg}）
                             ⚠️ 无构建步骤 —— 直接手写的静态 SPA，改完刷新即可
data/
  logs.sqlite3               审计库（请求记录）
  control.sqlite3            控制库（模型、设置、密钥）
```

---

## 已知限制

- ⚠️ **`spark-x` 长上下文会返回空回复**：它宣称 1M 上下文，**实际硬边界就是 262144** —— 26.18 万 token 正常，26.21 万就返回 `finish_reason=length` + `completion_tokens=0`（一个字都不吐）。
  **长会话别用它**；用 `DeepSeek-V4.1-Flash` 或 `qwen3.8-flash`（26 万 token 下实测 2.7s / 2.5s）。
- ⚠️ **模型 id 大小写敏感**：`DeepSeek-V4.1-Flash`（大写 D / F）、`Kimi-k2.6`（大写 K）。请照抄 `/v1/models` 返回的 `id`。
- `Kimi-k2.6` 真实上限也是 `262144`，超出时上游返 **HTTP 400**。
- 上游模型表里的图片模型（`Hy-Image-3.5-preview`、`doubao-seedream-5-lite`、`qwen-image-3.0-pro`）**不适用于对话端点**。
- `auto` 是 Loomy 自己的自动路由模型，`/v1/models` 不报它的上下文长度。

---

## 排错

| 现象 | 处理 |
|---|---|
| `/health` 返回 `session: false` | Loomy 桌面端未登录 / 会话文件不在 → 打开 Loomy 登录一次 |
| `/v1/models` 返回空 `data: []` | 目录未刷新 → 面板「模型目录」点「立即刷新目录」；或确认会话有效 |
| 面板打不开 | 网关没起 → 跑启动脚本，再看 `logs\loomy-gateway.err.log` |
| 一路 401 | 请求头缺 `Authorization: Bearer <LOOMY2API_KEY>` |
| 回复内容是空的 | 很可能用了 `spark-x` 跑长上下文（见上）→ 换 `DeepSeek-V4.1-Flash` |
| 网关在跑但 DSH 没反应 | 先 F5；配置改动下一个请求生效，UI 可能要刷新 |

---

## 日志

| 文件 | 内容 |
|---|---|
| `D:\perca\subsapi\logs\loomy-gateway.out.log` | 标准输出 |
| `D:\perca\subsapi\logs\loomy-gateway.err.log` | **启动横幅在这里**（监听地址、上游、会话路径、数据目录、路由清单） |

停止：

```powershell
Stop-Process -Id (Get-NetTCPConnection -LocalPort 8788 -State Listen).OwningProcess -Force
```

---

## 接入 DSH

已配置好，路由名 **`loomy`**（显示名「Loomy 本地网关」），当前导出 7 个模型：

`auto`、`spark-x`、`DeepSeek-V4.1-Flash`、`Kimi-k2.6`、`GLM-5.3-Flash`、`qwen3.8-flash`、`MiniMax-M3`

| 项 | 值 |
|---|---|
| 配置文件 | `C:\Users\Htryone\.dsh\profiles\desktop\cordis.patch.yml` → `llm-pi-ai` → `providers.loomy` |
| 密钥引用 | `C:\Users\Htryone\.dsh\.credentials.yaml` 的 `refs.LOOMY2API_KEY`（**值必须带引号**成字符串） |

> DSH 的 `contextWindow` 是「静默溢出识别阈值」而非硬拦截：对「`stopReason=length` 且输出=0」的响应，**只有 `输入token ≥ contextWindow × 0.99` 才认作溢出**。所以给 `spark-x` 填它标称的 1048576 反而会让 DSH 认不出空回复、直接显示成空白；本机填的是 **250000**。

---

## 相关

- workbuddy 网关（腾讯，8787）→ [`../codebuddy2api/`](../codebuddy2api/)（其本地说明见 `../codebuddy2api/README.本地.md`）
- 本机运维记忆与踩坑总表 → [`../.DSH/memory/MEMORY.md`](../.DSH/memory/MEMORY.md)
- 文档索引 → [`../.DSH/start/README.md`](../.DSH/start/README.md)

---

## 第二个平台：千问办公（QwenWork CN）

同一个进程、同一个端口（8788）、同一把 key、同一个面板，同时服务两个平台：

| 平台 | 公开模型 id | 上游 | 计费语义 |
|---|---|---|---|
| Loomy（讯飞） | `auto`、`spark-x`、`DeepSeek-V4.1-Flash` 等（保持原样） | `https://loomyad.xunfei.cn/api/v1` | `usage.credit`（积分） |
| 千问办公 | `qwenwork/flash`、`qwenwork/pro`、`qwenwork/qwen3.8-max-preview` | `POST /api/desktop-sessions` 下发的 `base_url`（如 `https://api9.qwenwork.cn`） | 无积分字段；`qwenwork/` 前缀在转发前剥掉 |

### 鉴权（两段式，均为官方流程）

1. **登录 JWT（7 天）** —— 优先读**本仓库内** `credentials\qwenwork\session.json`
   （由 `scripts\qwenwork-login.py` 设备码 PKCE 登录生成，与桌面端互相独立）；
   该文件缺失或过期时，自动回退解密桌面端的 `auth-v2.dat`
   （Chromium os_crypt：`v10` + `Local State` 的 DPAPI 包裹 key + AES-256-GCM）。
2. **推理密钥（2 小时，自动滚动）** —— 用 JWT 调
   `POST https://gateway.qwenwork.cn/api/desktop-sessions {"session_id": <uuid>}`
   得到 `{access_token: "sk-mm-v1.…", base_url, expires_at_ms, ttl_ms}`；
   网关在到期前 5 分钟自动重新换取，**推理请求本身不需要任何签名**。

### 模型目录

`GET https://gateway.qwenwork.cn/api/desktop/chat-modes`（明文，JWT 鉴权），
网关按 `model_catalog_ttl` 缓存；`context_length` 取 `max_input_tokens`，
`capabilities` 取 `is_reasoning` / `is_vl`。

### 常用命令

```bash
# 重新做一次设备码登录（会打开浏览器，与桌面端账号一致）
python scripts/qwenwork-login.py
```

```bash
# 看双平台状态
curl --noproxy '*' http://127.0.0.1:8788/health
```

排错：`/health.platforms.qwenwork.inference_ready=false` 多半是 JWT 过期
（重新登录）或 `desktop-sessions` 换取失败（看 `logs\loomy-gateway.err.log`）。

### 已知边界

- 千问办公的 `qwenwork/` 模型**不做积分换算**（上游返回的是 token usage）；
  面板里该平台的「积分」列留空属正常。
- 该平台**不参与**面板的模型别名/启停规则（静态目录项，`managed=false`）。
- 免费版额度与限流由千问办公侧决定，网关只做透传，不做重试放大。
