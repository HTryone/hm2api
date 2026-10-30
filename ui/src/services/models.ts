/** 模型路由页数据服务。 */
import { call } from '../api'
import type { ModelInventory, ModelRow } from '../types'

export interface ModelsView {
  revision: number
  rows: ModelRow[]
  loomyCount: number
  qwenworkCount: number
}

export async function loadModels(): Promise<ModelsView> {
  const data = await call<ModelInventory>('/models')
  const rows = Array.isArray(data.models) ? data.models : []
  return {
    revision: data.revision ?? 0,
    rows,
    loomyCount: rows.filter((row) => (row.platform ?? 'loomy') === 'loomy').length,
    qwenworkCount: rows.filter((row) => row.platform === 'qwenwork').length,
  }
}

export async function toggleModel(id: string, revision: number, enabled: boolean) {
  return call(`/models/${encodeURIComponent(id)}`, { method: 'PUT', body: { revision, enabled } })
}
