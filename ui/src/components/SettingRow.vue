<script setup lang="ts">
import StatusBadge from './StatusBadge.vue'
import { describe, isAdvanced } from '../services/settings'
import { text } from '../services/format'
import type { SettingItem } from '../types'

const props = defineProps<{ item: SettingItem }>()
const emit = defineEmits<{ (event: 'change', key: string, value: unknown): void }>()

const sourceLabels: Record<string, string> = {
  cli: '命令行', environment: '环境变量', env: '环境变量', dotenv: '.env 文件',
  management: '管理界面', default: '默认值', startup: '启动来源', internal: '内置',
}
const modeLabels: Record<string, string> = {
  hot: '即时生效', restart: '重启后生效', startup: '启动时设置', readonly: '只读',
}

function display(): string {
  const value = props.item.value
  if (value === null || value === undefined || value === '') return '跟随默认'
  return text(value)
}
</script>

<template>
  <div class="setting">
    <div class="setting-label">
      <strong>{{ item.label }}</strong>
      <span class="mono key">{{ item.key }}</span>
      <span v-if="describe(item.key)" class="desc">{{ describe(item.key) }}</span>
      <span class="tags">
        <StatusBadge :text="sourceLabels[item.source ?? ''] ?? '未知来源'" />
        <StatusBadge
          :text="modeLabels[item.mode ?? ''] ?? '生效方式未知'"
          :kind="item.mode === 'hot' ? 'good' : 'warn'"
        />
        <StatusBadge v-if="item.locked" text="锁定" kind="warn" />
      </span>
    </div>
    <div class="setting-value">
      <span v-if="item.locked" class="note">启动配置中修改</span>
      <label v-else-if="item.type === 'boolean'" class="check">
        <input
          type="checkbox"
          :checked="item.value === true"
          @change="emit('change', item.key, ($event.target as HTMLInputElement).checked)"
        />
        {{ item.value === true ? '开启' : '关闭' }}
      </label>
      <span v-else-if="item.type === 'path' || item.type === 'paths'" class="mono ellipsis" :title="display()">
        {{ display() }}
      </span>
      <input
        v-else
        :type="item.type === 'integer' || item.type === 'number' ? 'number' : 'text'"
        :value="text(item.value)"
        @input="emit('change', item.key, item.type === 'string' ? ($event.target as HTMLInputElement).value : Number(($event.target as HTMLInputElement).value))"
      />
      <span v-if="isAdvanced(item.key)" class="adv-tag">高级</span>
    </div>
  </div>
</template>
