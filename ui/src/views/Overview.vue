<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import Panel from '../components/Panel.vue'
import ConnectBar from '../components/ConnectBar.vue'
import StatsCards from '../components/StatsCards.vue'
import TrendChart from '../components/TrendChart.vue'
import RankTable from '../components/RankTable.vue'
import PlatformList from '../components/PlatformList.vue'
import ModelChips from '../components/ModelChips.vue'
import StatusBadge from '../components/StatusBadge.vue'
import { call } from '../api'
import { loadOverview, type OverviewModel } from '../services/dashboard'
import { bytes, metric, percent, text, when } from '../services/format'

const days = ref('7')
const granularity = ref('auto')
const loading = ref(false)
const error = ref('')
const view = ref<OverviewModel | null>(null)
const copied = ref('')

async function load() {
  loading.value = true
  error.value = ''
  try {
    view.value = await loadOverview(days.value, granularity.value)
  } catch (issue) {
    error.value = (issue as Error).message
  } finally {
    loading.value = false
  }
}

async function copy(value: string) {
  try {
    await navigator.clipboard.writeText(value)
    copied.value = value
    window.setTimeout(() => (copied.value = ''), 1200)
  } catch {
    copied.value = ''
  }
}

async function reloadSession(key: string) {
  await call(`/${key}/session/reload`, { method: 'POST' })
  await load()
}

async function refreshCatalog() {
  await call('/loomy/catalog/refresh', { method: 'POST' }).catch(() => undefined)
  await load()
}

watch([days, granularity], load)
onMounted(load)
</script>

<template>
  <div class="page-title">
    <h1>运行概览</h1>
    <div class="actions">
      <select v-model="days">
        <option value="1">最近 1 天</option>
        <option value="7">最近 7 天</option>
        <option value="30">最近 30 天</option>
        <option value="90">最近 90 天</option>
      </select>
      <select v-model="granularity">
        <option value="auto">自动粒度</option>
        <option value="hour">按小时</option>
        <option value="day">按天</option>
      </select>
      <button @click="load">刷新</button>
    </div>
  </div>

  <div v-if="error" class="notice warning">{{ error }}</div>
  <div v-if="view?.degraded" class="notice warning">统计可能不完整，请检查日志存储状态。</div>

  <template v-if="view">
    <ConnectBar
      :items="[
        { label: '接口地址 Base URL', value: text(view.connect.base_url) },
        { label: 'API Key', value: text(view.connect.api_key) },
        { label: '模型清单', value: text(view.connect.models_url) },
        { label: '面板地址', value: text(view.connect.dashboard) },
      ]"
      @copy="copy"
    />

    <StatsCards
      :items="[
        { label: '请求总量', value: metric(view.summary.requests) },
        { label: '成功率', value: percent(view.summary.successRate) },
        { label: 'Token 用量', value: metric(view.summary.tokens) },
        { label: '讯飞 Loomy 积分', value: metric(view.summary.credit) },
      ]"
    />

    <div class="overview">
      <div class="col">
        <Panel title="请求趋势" :hint="`最近 ${days} 天 · UTC 自然日`">
          <TrendChart :series="view.series" :peak="view.peak" />
        </Panel>
        <Panel title="模型使用排行" :hint="`前 ${view.rank.length} 名`">
          <RankTable :rows="view.rank" :total="view.rank.length" />
        </Panel>
      </div>
      <div class="col">
        <Panel title="平台状态">
          <PlatformList :platforms="view.platforms" @reload="reloadSession" />
        </Panel>
        <Panel title="目录与存储">
          <div class="pair">
            <div>
              <div class="mini-title">模型目录</div>
              <dl class="fields">
                <dt>上游模型数</dt><dd>{{ metric(view.data.catalog?.count) }}</dd>
                <dt>最近拉取</dt><dd>{{ when(view.data.catalog?.fetched_at) }}</dd>
                <dt>缓存秒数</dt><dd>{{ metric(view.data.catalog?.ttl) }}</dd>
              </dl>
              <div class="actions" style="margin-top: 8px">
                <button class="ghost" @click="refreshCatalog">刷新目录</button>
              </div>
            </div>
            <div>
              <div class="mini-title">日志存储</div>
              <StatusBadge
                :text="view.data.storage?.degraded ? '采集降级' : '正常'"
                :kind="view.data.storage?.degraded ? 'bad' : 'good'"
              />
              <dl class="fields" style="margin-top: 6px">
                <dt>明细</dt>
                <dd>{{ bytes(view.data.storage?.logical_bytes) }} / {{ bytes(view.data.storage?.max_bytes) }}</dd>
                <dt>数据库</dt><dd>{{ bytes(view.data.storage?.db_bytes) }}</dd>
                <dt>保留</dt><dd>{{ metric(view.data.storage?.retention_days) }} 天</dd>
              </dl>
            </div>
          </div>
        </Panel>
      </div>
    </div>

    <Panel title="可对接模型（点一下复制 ID）" :hint="`${view.models.length} 个`">
      <ModelChips :models="view.models" @copy="copy" />
    </Panel>

    <p class="note">
      更新于 {{ when(view.data.generated_at) }}<span v-if="copied"> · 已复制：{{ copied }}</span>
    </p>
  </template>
  <div v-else-if="loading" class="empty">加载中…</div>
</template>
