<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import Panel from '../components/Panel.vue'
import StatusBadge from '../components/StatusBadge.vue'
import { loadLogs, type LogsView } from '../services/logs'
import { clearLogDetails } from '../services/maintenance'
import { metric, platformLabel, text, when } from '../services/format'

const days = ref('7')
const platform = ref('all')
const view = ref<LogsView | null>(null)
const error = ref('')
const note = ref('')

async function load() {
  try {
    view.value = await loadLogs(days.value, platform.value)
    error.value = ''
  } catch (issue) {
    error.value = (issue as Error).message
  }
}

async function clearDetails() {
  if (!window.confirm('清空全部请求明细？统计汇总会保留，操作不可撤销。')) return
  try {
    await clearLogDetails()
    note.value = '已清空请求明细'
    await load()
  } catch (issue) {
    error.value = (issue as Error).message
  }
}

function exportCsv() {
  const rows = view.value?.rows ?? []
  if (!rows.length) {
    note.value = '当前没有可导出的记录'
    return
  }
  const header = ['时间', '平台', '公开模型', '上游模型', '结果', '状态码', '输入token', '输出token', '积分', '耗时ms']
  const body = rows.map((row) => [
    when(row.started_at), platformLabel(row.profile ?? 'loomy'), row.public_model ?? '', row.upstream_model ?? '',
    row.outcome ?? '', row.status_code ?? '', row.input_tokens ?? '', row.output_tokens ?? '',
    row.credit ?? '', row.duration_ms ?? '',
  ])
  const csv = [header, ...body].map((cells) => cells.map((cell) => `"${String(cell).replace(/"/g, '""')}"`).join(',')).join('\n')
  const url = URL.createObjectURL(new Blob([`\ufeff${csv}`], { type: 'text/csv;charset=utf-8' }))
  const link = document.createElement('a')
  link.href = url
  link.download = `hm2api-logs-${new Date().toISOString().slice(0, 10)}.csv`
  link.click()
  URL.revokeObjectURL(url)
}

watch([days, platform], load)
onMounted(load)
</script>

<template>
  <div class="page-title">
    <h1>日志审计</h1>
    <div class="actions">
      <select v-model="days">
        <option value="1">最近 1 天</option>
        <option value="7">最近 7 天</option>
        <option value="30">最近 30 天</option>
      </select>
      <select v-model="platform">
        <option value="all">全部平台</option>
        <option value="loomy">讯飞 Loomy</option>
        <option value="qwenwork">千问办公</option>
      </select>
      <button class="ghost" @click="load">刷新</button>
      <button class="ghost" @click="exportCsv">导出 CSV</button>
      <button class="ghost" @click="clearDetails">清空明细</button>
    </div>
  </div>

  <div v-if="error" class="notice warning">{{ error }}</div>
  <div v-if="note" class="notice">{{ note }}</div>

  <Panel title="请求明细" :hint="view ? `${view.rows.length} 条` : ''">
    <div v-if="view && view.rows.length" class="table-wrap">
      <table>
        <thead>
          <tr><th>时间</th><th>平台</th><th>模型</th><th>结果</th><th>Token</th><th>耗时</th></tr>
        </thead>
        <tbody>
          <tr v-for="(row, index) in view.rows" :key="row.id ?? index">
            <td class="mono">{{ when(row.started_at) }}</td>
            <td>{{ platformLabel(row.profile ?? 'loomy') }}</td>
            <td class="mono">{{ text(row.public_model ?? row.upstream_model) }}</td>
            <td>
              <StatusBadge
                :text="text(row.outcome)"
                :kind="row.outcome === 'ok' ? 'good' : row.outcome ? 'warn' : undefined"
              />
            </td>
            <td>{{ metric(row.total_tokens) }}</td>
            <td>{{ row.duration_ms != null ? `${row.duration_ms} ms` : '—' }}</td>
          </tr>
        </tbody>
      </table>
    </div>
    <div v-else class="empty">暂无记录</div>
  </Panel>
</template>
