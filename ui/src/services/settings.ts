/** 系统设置页数据服务：分组、通俗说明、高级项与保存逻辑。 */
import { call } from '../api'
import type { SettingItem, SettingsData } from '../types'

export const DESCRIPTIONS: Record<string, string> = {
  host: '网关监听地址。只给本机用就保持 127.0.0.1；要让局域网别的设备访问才改成 0.0.0.0。',
  port: '网关端口。模型接口是 http://127.0.0.1:<端口>/v1。改完需要重启。',
  api_key: '一把钥匙两用：面板登录口令 ＝ 调用 API 的 Bearer key。改完需要重启，调用方也要同步改。',
  ui_dir: '面板文件位置。留空自动用仓库里的 ui/dist。',
  ui_origin: '面板单独跑在别的端口时填那个地址，否则浏览器会拦跨域请求。',
  admin_allowed_origins: '额外允许访问面板的来源，多个用英文逗号分隔。不确定就留空。',
  loomy_session_path: '讯飞 Loomy 的登录态文件。仓库里 cred/loomy/auth-session.json 是唯一读源，桌面端重新登录会自动同步。',
  upstream_base_url: '讯飞 Loomy 的接口地址，官方没变就不用动。',
  model_catalog_ttl: '多久（秒）重新拉一次 Loomy 模型清单，默认 6 小时。',
  session_reload_seconds: '多久（秒）检查一次登录态文件有没有更新，默认 30 秒。',
  model_guard: '只允许调用已登记的模型，防止模型名写错。建议开启。',
  credit_price_cny: '1 积分折合多少元，只影响面板里折算金额的显示。',
  qwenwork_enabled: '是否启用千问办公平台。关掉后它的模型不再对外提供。',
  qwenwork_upstream_base_url: '千问办公的接口地址，官方没变就不用动。',
  qwenwork_appdata_dir: '千问办公桌面端的数据目录，只在找不到 cred/qwenwork/session.json 时才用。',
  request_timeout: '单个请求最多等多久（秒）才判超时。长文生成可调大。',
  connect_timeout: '连接上游最多等多久（秒）。网络慢时调大。',
  max_request_bytes: '单次请求体上限（字节）。要传大段文本或图片才需要调大。',
  max_inbound_bytes: '原始请求体上限（字节），比上面更靠前生效。',
  max_concurrent: '同时处理的请求数上限，0 表示不限制。',
  audit_max_bytes: '审计日志最多占多少字节，超了会分批清理旧记录。',
  audit_retention_days: '审计日志保留多少天，默认 30 天。',
  audit_diagnostic_bytes: '失败请求最多留存多少字节的诊断内容，0 表示不存。',
}

export const ADVANCED = new Set([
  'host', 'port', 'ui_dir', 'ui_origin', 'admin_allowed_origins',
  'loomy_session_path', 'upstream_base_url', 'model_catalog_ttl', 'session_reload_seconds',
  'credit_price_cny', 'qwenwork_upstream_base_url', 'qwenwork_appdata_dir',
  'connect_timeout', 'max_request_bytes', 'max_inbound_bytes', 'max_concurrent',
  'audit_max_bytes', 'audit_diagnostic_bytes',
])

const GROUPS: Array<[string, string[]]> = [
  ['服务与密钥', ['host', 'port', 'api_key', 'ui_dir', 'ui_origin', 'admin_allowed_origins']],
  ['平台 · 讯飞 Loomy', ['loomy_session_path', 'upstream_base_url', 'model_catalog_ttl', 'session_reload_seconds', 'model_guard', 'credit_price_cny']],
  ['平台 · 千问办公', ['qwenwork_enabled', 'qwenwork_upstream_base_url', 'qwenwork_appdata_dir']],
  ['上游与限流', ['request_timeout', 'connect_timeout', 'max_request_bytes', 'max_inbound_bytes', 'max_concurrent']],
  ['审计与存储', ['audit_max_bytes', 'audit_retention_days', 'audit_diagnostic_bytes']],
]

export interface SettingsGroup {
  title: string
  items: SettingItem[]
}

export interface SettingsView {
  revision: number
  groups: SettingsGroup[]
  total: number
  audit?: Record<string, unknown>
}

export async function loadSettings(showAdvanced: boolean): Promise<SettingsView> {
  const data = await call<SettingsData>('/settings')
  const items = Array.isArray(data.items) ? data.items : []
  const known = new Set(GROUPS.flatMap(([, keys]) => keys))
  const rest = items.filter((item) => !known.has(item.key))

  const groups: SettingsGroup[] = GROUPS.map(([title, keys]) => ({
    title,
    items: keys
      .map((key) => items.find((item) => item.key === key))
      .filter((item): item is SettingItem => Boolean(item))
      .filter((item) => showAdvanced || !ADVANCED.has(item.key)),
  })).filter((group) => group.items.length > 0)

  if (rest.length) {
    groups.push({
      title: '其他',
      items: rest.filter((item) => showAdvanced || !ADVANCED.has(item.key)),
    })
  }

  return { revision: data.revision ?? 0, groups, total: items.length, audit: data.audit }
}

export async function saveSettings(revision: number, values: Record<string, unknown>) {
  return call('/settings', { method: 'PATCH', body: { revision, values } })
}

export function describe(key: string): string {
  return DESCRIPTIONS[key] ?? ''
}

export function isAdvanced(key: string): boolean {
  return ADVANCED.has(key)
}
