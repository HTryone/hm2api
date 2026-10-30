/** 概览页数据服务：取数 + 归一化，组件只管渲染。 */
import { call } from '../api'
import type { DashboardData, ConnectModel, ConnectInfo, ModelRankRow, PlatformView, SeriesRow } from '../types'

export interface OverviewModel {
  data: DashboardData
  summary: { requests: number | null; successRate: number | null; tokens: number | null; credit: number | null }
  series: SeriesRow[]
  peak: number
  rank: ModelRankRow[]
  platforms: Array<{ key: string; view: PlatformView }>
  connect: ConnectInfo
  models: ConnectModel[]
  degraded: boolean
}

function asRecord<T>(value: unknown): T {
  return (value && typeof value === 'object' ? value : {}) as T
}

export async function loadOverview(days: string, granularity: string): Promise<OverviewModel> {
  const data = await call<DashboardData>(`/dashboard?days=${days}&granularity=${granularity}`)
  const summary = asRecord<DashboardData['summary']>(data.summary)
  const series = Array.isArray(data.series) ? data.series : []
  const rank = Array.isArray(data.models) ? data.models : []
  const connect = asRecord<ConnectInfo>(data.connect)
  const platforms = Object.entries(asRecord<Record<string, PlatformView>>(data.platforms)).map(([key, view]) => ({
    key,
    view: asRecord<PlatformView>(view),
  }))

  const peak = series.reduce((max, row) => Math.max(max, Number(row.requests) || 0), 1)

  return {
    data,
    summary: {
      requests: summary.requests ?? null,
      successRate: summary.success_rate ?? null,
      tokens: summary.total_tokens ?? null,
      credit: summary.credit ?? null,
    },
    series,
    peak,
    rank: rank.slice(0, 8),
    platforms,
    connect,
    models: Array.isArray(connect.models) ? connect.models.filter((m) => m && m.enabled !== false) : [],
    degraded: data.degraded === true || data.storage?.degraded === true,
  }
}
