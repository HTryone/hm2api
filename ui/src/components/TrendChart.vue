<script setup lang="ts">
import type { SeriesRow } from '../types'

const props = defineProps<{ series: SeriesRow[]; peak: number }>()

function height(row: SeriesRow): number {
  const count = Number(row.requests) || 0
  return Math.max(2, Math.round((count / Math.max(1, props.peak)) * 120))
}
</script>

<template>
  <div v-if="series.length">
    <div class="spark">
      <i
        v-for="row in series"
        :key="row.date"
        :class="{ zero: !row.requests }"
        :style="{ height: height(row) + 'px' }"
        :title="`${row.date} · ${row.requests ?? 0} 次`"
      />
    </div>
    <p class="note">{{ series[0]?.date }} → {{ series[series.length - 1]?.date }}</p>
  </div>
  <div v-else class="empty">暂无请求记录</div>
</template>
