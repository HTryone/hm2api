# ui —— 前端（Vue 3 + TypeScript + Vite）

- **Vue 组件只管展示**（props 进、事件出），**业务逻辑全在 `src/services/*.ts`**，视图层 `src/views/*.vue` 只做拼装。
- 与后端唯一的接口：`/admin/*`（管理）、`/v1/*`（推理）。同源时走相对路径；独立部署时可在 `index.html` 里设 `window.HM2API_API`。
- 路由用 `vue-router` 的 history 模式，基址 `/dashboard/`；后端把 `/dashboard/<page>` 回退到 `index.html`，所以**深链刷新不会丢页面**。

## 目录

```
src/
├── main.ts            入口（挂 router）
├── App.vue            外框：登录门 + 侧栏 + router-view
├── router.ts          路由表（/ /models /logs /settings）
├── api.ts             fetch 封装（CSRF、错误、登录态）
├── types.ts           后端返回结构（与 src/core/admin 对应）
├── services/          逻辑层：dashboard / models / logs / settings / session / format
├── components/        纯展示组件：Panel、StatusBadge、ConnectBar、StatsCards、TrendChart、
│                     RankTable、PlatformList、ModelChips、SettingRow
└── views/             页面：Overview、Models、Logs、Settings
```

## 开发

```bash
pnpm install
pnpm dev        # http://127.0.0.1:5199，/admin 与 /v1 自动代理到 8788
pnpm typecheck  # vue-tsc 类型检查
```

## 构建（产物已随仓库提交，普通用户不需要 Node）

```bash
pnpm build      # 输出到 dist/，资源路径为 /dashboard/assets/*
```

`dist/` 是**构建产物，不进仓库**（已在 `ui/.gitignore` 忽略）；后端直接托管 `dist/`，
所以新拉下来的仓库要先构建一次：`ui\build.cmd`（或 `pnpm install && pnpm build`）。
