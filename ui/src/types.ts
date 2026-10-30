/** 后端 API 的 TypeScript 类型（与 src/core/admin 的返回结构对应） */

export interface PlatformView {
  present?: boolean
  error?: string | null
  path?: string | null
  desktop_path?: string | null
  source?: string | null
  phone?: string | null
  userid?: string | null
  account?: string | null
  jwt_source?: string | null
  base_url?: string | null
  key_expires_in_seconds?: number | null
  jwt_expires_in_seconds?: number | null
  token_fingerprint?: string | null
  loaded_at?: number | null
  models?: number
  inference_ready?: boolean
}

export interface ConnectModel {
  id: string
  name?: string
  platform?: string
  enabled?: boolean
}

export interface ConnectInfo {
  base_url?: string
  chat_url?: string
  models_url?: string
  dashboard?: string
  api_key?: string
  models: ConnectModel[]
}

export interface DashboardSummary {
  requests?: number
  success_rate?: number | null
  total_tokens?: number
  credit?: number
}

export interface SeriesRow {
  date?: string
  requests?: number
}

export interface ModelRankRow {
  model?: string
  requests?: number
  total_tokens?: number
  credit?: number
}

export interface CatalogView {
  count?: number
  fetched_at?: number | null
  ttl?: number
  error?: string | null
}

export interface StorageView {
  degraded?: boolean
  logical_bytes?: number
  max_bytes?: number
  db_bytes?: number
  wal_bytes?: number
  retention_days?: number
  pending_cleanup?: boolean
}

export interface DashboardData {
  summary?: DashboardSummary
  series?: SeriesRow[]
  models?: ModelRankRow[]
  platforms?: Record<string, PlatformView>
  catalog?: CatalogView
  storage?: StorageView
  connect?: ConnectInfo
  generated_at?: number
  degraded?: boolean
  range?: { days?: number; granularity?: string }
}

export interface ModelRow {
  id: string
  public_id?: string
  upstream_id?: string
  name?: string
  type?: string
  platform?: string
  enabled?: boolean
  managed?: boolean
  custom?: boolean
  available?: boolean
}

export interface ModelInventory {
  revision: number
  models: ModelRow[]
  catalog?: CatalogView
}

export interface LogRow {
  id?: number | string
  started_at?: number
  public_model?: string
  upstream_model?: string
  profile?: string
  outcome?: string
  status_code?: number
  input_tokens?: number
  output_tokens?: number
  total_tokens?: number
  credit?: number
  duration_ms?: number
}

export interface LogsPage {
  items: LogRow[]
  next_cursor?: string | null
  has_more?: boolean
}

export interface SettingItem {
  key: string
  label: string
  value: unknown
  stored?: unknown
  source?: string
  mode?: string
  type?: string
  locked?: boolean
}

export interface SettingsData {
  revision: number
  items: SettingItem[]
  audit?: Record<string, unknown>
  session?: Record<string, unknown>
}

export interface SessionState {
  authenticated?: boolean
  csrf_token?: string
}
