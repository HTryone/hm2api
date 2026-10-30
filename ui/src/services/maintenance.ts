/** 维护动作：同步上游模型、批量检测、清理日志。 */
import { call } from '../api'

export interface PlatformSyncSummary {
  count: number
  added: string[]
  removed: string[]
}

export interface SyncResult {
  ok: boolean
  loomy: PlatformSyncSummary
  qwenwork: PlatformSyncSummary
}

export async function syncModels(): Promise<SyncResult> {
  return call<SyncResult>('/models/sync', { method: 'POST' })
}

export interface CheckResult {
  platform: string
  ok: boolean
  models: number
  elapsed_ms: number
  error?: string | null
}

export async function checkAllCredentials(): Promise<{ results: CheckResult[] }> {
  return call<{ results: CheckResult[] }>('/credentials/check-all', { method: 'POST' })
}

export async function clearLogDetails() {
  return call('/logs/clear', { method: 'POST', body: { scope: 'details' } })
}
