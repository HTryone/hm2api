<script setup lang="ts">
import { metric, text } from '../services/format'
import type { ModelRankRow } from '../types'

defineProps<{ rows: ModelRankRow[]; total: number }>()
</script>

<template>
  <div v-if="rows.length" class="table-wrap">
    <table>
      <thead>
        <tr><th>模型</th><th>请求</th><th>Token</th><th>积分</th></tr>
      </thead>
      <tbody>
        <tr v-for="(row, index) in rows" :key="row.model ?? index">
          <td>{{ String(index + 1).padStart(2, '0') }} <strong>{{ text(row.model) }}</strong></td>
          <td>{{ metric(row.requests) }}</td>
          <td>{{ metric(row.total_tokens) }}</td>
          <td>{{ metric(row.credit) }}</td>
        </tr>
      </tbody>
    </table>
  </div>
  <div v-else class="empty">尚无模型请求记录</div>
</template>
