<script setup lang="ts">
import { computed } from 'vue'
import { platformLabel, text } from '../services/format'
import type { ConnectModel } from '../types'

const props = defineProps<{ models: ConnectModel[] }>()
const emit = defineEmits<{ (event: 'copy', id: string): void }>()

/** 按平台分组，顺序固定：讯飞 Loomy 在前，千问办公在后。 */
const groups = computed(() => {
  const buckets = new Map<string, ConnectModel[]>()
  for (const model of props.models) {
    const key = model.platform || 'loomy'
    const list = buckets.get(key) ?? []
    list.push(model)
    buckets.set(key, list)
  }
  const order = ['loomy', 'qwenwork']
  return [...buckets.entries()]
    .sort((a, b) => order.indexOf(a[0]) - order.indexOf(b[0]))
    .map(([key, models]) => ({ key, label: platformLabel(key), models }))
})
</script>

<template>
  <div v-if="models.length" class="model-groups">
    <section v-for="group in groups" :key="group.key" class="model-group">
      <div class="model-group-head">
        <strong>{{ group.label }}</strong>
        <span class="note">{{ group.models.length }} 个 · 点模型复制 ID</span>
      </div>
      <div class="chips">
        <button
          v-for="model in group.models"
          :key="model.id"
          class="chip"
          @click="emit('copy', model.id)"
        >
          <span class="cname">{{ text(model.name) }}</span>
          <span class="cid mono">{{ text(model.id) }}</span>
        </button>
      </div>
    </section>
  </div>
  <div v-else class="empty">模型清单为空，去「模型路由」页刷新目录</div>
</template>
