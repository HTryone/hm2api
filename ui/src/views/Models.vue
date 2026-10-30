<script setup lang="ts">
import { onMounted, ref } from 'vue'
import Panel from '../components/Panel.vue'
import StatusBadge from '../components/StatusBadge.vue'
import { loadModels, toggleModel, type ModelsView } from '../services/models'
import { syncModels } from '../services/maintenance'
import { platformLabel, text } from '../services/format'

const view = ref<ModelsView | null>(null)
const error = ref('')
const note = ref('')
const busy = ref(false)
const syncing = ref(false)

async function load() {
  try {
    view.value = await loadModels()
    error.value = ''
  } catch (issue) {
    error.value = (issue as Error).message
  }
}

async function toggle(id: string, enabled: boolean) {
  if (!view.value) return
  busy.value = true
  try {
    await toggleModel(id, view.value.revision, enabled)
    await load()
  } catch (issue) {
    error.value = (issue as Error).message
  } finally {
    busy.value = false
  }
}

async function syncNow() {
  syncing.value = true
  note.value = ''
  try {
    const result = await syncModels()
    const parts = [
      `讯飞 Loomy ${result.loomy.count} 个`,
      `千问办公 ${result.qwenwork.count} 个`,
    ]
    const added = [...result.loomy.added, ...result.qwenwork.added]
    const removed = [...result.loomy.removed, ...result.qwenwork.removed]
    note.value =
      `已从上游同步：${parts.join(' · ')}` +
      (added.length ? `；新增 ${added.join('、')}` : '；无新增') +
      (removed.length ? `；上游已下线 ${removed.join('、')}` : '')
    await load()
  } catch (issue) {
    error.value = (issue as Error).message
  } finally {
    syncing.value = false
  }
}

onMounted(load)
</script>

<template>
  <div class="page-title">
    <h1>模型路由</h1>
    <div class="actions">
      <span v-if="view" class="note">Loomy {{ view.loomyCount }} · 千问办公 {{ view.qwenworkCount }}</span>
      <button class="ghost" @click="load">刷新</button>
      <button class="primary" :disabled="syncing" @click="syncNow">
        {{ syncing ? '同步中…' : '同步模型' }}
      </button>
    </div>
  </div>

  <div v-if="error" class="notice warning">{{ error }}</div>
  <div v-if="note" class="notice">{{ note }}</div>

  <Panel title="模型清单" :hint="view ? `共 ${view.rows.length} 个 · 数据来自上游账号，自动更新` : ''">
    <div v-if="view && view.rows.length" class="table-wrap">
      <table>
        <thead>
          <tr><th>对外 ID</th><th>平台</th><th>名称</th><th>类型</th><th>状态</th><th>操作</th></tr>
        </thead>
        <tbody>
          <tr v-for="row in view.rows" :key="row.id">
            <td class="mono">{{ text(row.public_id ?? row.id) }}</td>
            <td>{{ platformLabel(row.platform ?? 'loomy') }}</td>
            <td>{{ text(row.name) }}</td>
            <td>{{ text(row.type) }}</td>
            <td>
              <StatusBadge :text="row.enabled === false ? '已停用' : '启用'" :kind="row.enabled === false ? 'warn' : 'good'" />
              <span v-if="row.available === false" class="note"> · 上游已无</span>
            </td>
            <td>
              <span v-if="row.managed === false" class="note">静态目录</span>
              <button v-else class="ghost" :disabled="busy" @click="toggle(row.id, row.enabled === false)">
                {{ row.enabled === false ? '启用' : '停用' }}
              </button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
    <div v-else class="empty">暂无模型</div>
  </Panel>
</template>
