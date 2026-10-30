<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import Panel from '../components/Panel.vue'
import SettingRow from '../components/SettingRow.vue'
import { loadSettings, saveSettings, type SettingsView } from '../services/settings'

const view = ref<SettingsView | null>(null)
const showAdvanced = ref(localStorage.getItem('hm2api.showAdvanced') === '1')
const pending = ref<Record<string, unknown>>({})
const error = ref('')
const saving = ref(false)

const dirtyCount = computed(() => Object.keys(pending.value).length)

async function load() {
  try {
    view.value = await loadSettings(showAdvanced.value)
    pending.value = {}
    error.value = ''
  } catch (issue) {
    error.value = (issue as Error).message
  }
}

function changed(key: string, value: unknown) {
  const next = { ...pending.value }
  next[key] = value
  pending.value = next
}

function toggleAdvanced() {
  localStorage.setItem('hm2api.showAdvanced', showAdvanced.value ? '1' : '0')
  load()
}

async function save() {
  if (!view.value || !dirtyCount.value) return
  saving.value = true
  try {
    await saveSettings(view.value.revision, pending.value)
    await load()
  } catch (issue) {
    error.value = (issue as Error).message
  } finally {
    saving.value = false
  }
}

onMounted(load)
</script>

<template>
  <div class="page-title">
    <h1>系统设置</h1>
    <div class="actions">
      <label class="check">
        <input v-model="showAdvanced" type="checkbox" @change="toggleAdvanced" />
        显示高级项
      </label>
      <button @click="load">重新读取</button>
    </div>
  </div>

  <div class="notice">
    带「启动时设置 / 重启后生效」的项需要重启服务；标「高级」的是技术参数，不懂就别动。
  </div>
  <div v-if="error" class="notice warning">{{ error }}</div>

  <div v-if="view" class="settings-grid">
    <Panel
      v-for="group in view.groups"
      :key="group.title"
      :title="group.title"
      :hint="`${group.items.length} 项`"
    >
      <div class="settings-list">
        <SettingRow v-for="item in group.items" :key="item.key" :item="item" @change="changed" />
      </div>
    </Panel>
  </div>

  <div class="save-bar">
    <span class="note">{{ dirtyCount ? `${dirtyCount} 项待保存` : '没有待保存的更改' }}</span>
    <button class="primary" :disabled="!dirtyCount || saving" @click="save">
      {{ saving ? '保存中…' : '保存更改' }}
    </button>
  </div>
</template>
