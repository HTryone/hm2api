/** 日志审计页数据服务。 */
import { call } from '../api'
import type { LogRow, LogsPage } from '../types'

export interface LogsView {
  rows: LogRow[]
  hasMore: boolean
  cursor: string | null
  platforms: string[]
}

export async function loadLogs(days: string, platform: string, cursor?: string | null): Promise<LogsView> {
  const query = new URLSearchParams({ days, limit: '100' })
  if (cursor) query.set('cursor', cursor)
  const data = await call<LogsPage>(`/logs?${query.toString()}`)
  const rows = Array.isArray(data.items) ? data.items : []
  const filtered = platform === 'all' ? rows : rows.filter((row) => (row.profile ?? 'loomy') === platform)
  const platforms = Array.from(new Set(rows.map((row) => row.profile ?? 'loomy'))).sort()
  return { rows: filtered, hasMore: data.has_more === true, cursor: data.next_cursor ?? null, platforms }
}
