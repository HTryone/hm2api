<script setup lang="ts">
import StatusBadge from './StatusBadge.vue'
import { platformLabel, seconds, text, when } from '../services/format'
import type { PlatformView } from '../types'

defineProps<{ platforms: Array<{ key: string; view: PlatformView }> }>()
const emit = defineEmits<{ (event: 'reload', key: string): void }>()

function lines(key: string, view: PlatformView): string[] {
  if (key === 'qwenwork') {
    return [
      `登录来源 ${text(view.jwt_source)}`,
      `推理密钥 ${view.key_expires_in_seconds != null ? seconds(view.key_expires_in_seconds) : '—'}`,
      `上游 ${text(view.base_url)}`,
      `上次读取 ${when(view.loaded_at)}`,
    ]
  }
  return [
    `账号 ${text(view.phone)}`,
    `指纹 ${text(view.token_fingerprint)}`,
    `来源 ${text(view.source)}`,
    `会话文件 ${text(view.path)}`,
  ]
}
</script>

<template>
  <div v-if="platforms.length">
    <div v-for="entry in platforms" :key="entry.key" class="plat">
      <div class="plat-head">
        <strong>{{ platformLabel(entry.key) }}</strong>
        <StatusBadge
          :text="entry.view.present ? '已连接' : '不可用'"
          :kind="entry.view.present ? 'good' : 'bad'"
        />
        <button class="ghost" @click="emit('reload', entry.key)">重读</button>
      </div>
      <div class="plat-body">
        <span v-for="line in lines(entry.key, entry.view)" :key="line" class="ellipsis mono" :title="line">
          {{ line }}
        </span>
      </div>
    </div>
  </div>
  <div v-else class="empty">暂无平台凭据</div>
</template>
