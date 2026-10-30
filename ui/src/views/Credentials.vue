<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'
import QRCode from 'qrcode'
import Panel from '../components/Panel.vue'
import StatusBadge from '../components/StatusBadge.vue'
import { loadCredentials, loginStatus, reloadSession, startLogin, type CredentialRow, type LoginState } from '../services/credentials'
import { checkAllCredentials, type CheckResult } from '../services/maintenance'
import { call } from '../api'
import { text, when } from '../services/format'

const rows = ref<CredentialRow[]>([])
const error = ref('')
const note = ref('')
const dialog = ref(false)
const active = ref<CredentialRow | null>(null)
const state = ref<LoginState>({ state: 'idle', message: '', auth_url: '' })
const qr = ref('')
const checks = ref<Record<string, CheckResult>>({})
const checking = ref(false)
let timer: number | null = null

async function load() {
  try {
    rows.value = (await loadCredentials()).platforms
    error.value = ''
  } catch (issue) {
    error.value = (issue as Error).message
  }
}

async function renderQr(url: string) {
  if (!url) {
    qr.value = ''
    return
  }
  try {
    qr.value = await QRCode.toDataURL(url, { width: 220, margin: 1 })
  } catch {
    qr.value = ''
  }
}

function stopPolling() {
  if (timer !== null) {
    window.clearInterval(timer)
    timer = null
  }
}

async function openLogin(row: CredentialRow) {
  active.value = row
  dialog.value = true
  state.value = { state: 'idle', message: '正在向千问办公申请授权链接…', auth_url: '' }
  try {
    state.value = await startLogin(row.platform)
    await renderQr(state.value.auth_url ?? '')
    if (state.value.state === 'manual') return
    stopPolling()
    timer = window.setInterval(async () => {
      try {
        const next = await loginStatus()
        state.value = { ...state.value, ...next }
        if (next.state === 'success') {
          stopPolling()
          await load()
          await checkOne(row.platform)
          note.value = '登录成功，凭据已入库并已通过检测。'
        } else if (next.state === 'failed') {
          stopPolling()
        }
      } catch (issue) {
        state.value = { ...state.value, state: 'failed', message: (issue as Error).message }
        stopPolling()
      }
    }, 2000)
  } catch (issue) {
    state.value = { state: 'failed', message: (issue as Error).message || '启动登录失败' }
  }
}

function closeDialog() {
  dialog.value = false
  stopPolling()
}

async function copyUrl() {
  if (state.value.auth_url) await navigator.clipboard.writeText(state.value.auth_url).catch(() => undefined)
}

async function refresh(row: CredentialRow) {
  try {
    await reloadSession(row.platform)
    await load()
    note.value = `${row.label} 会话已重新读取`
  } catch (issue) {
    error.value = (issue as Error).message
  }
}

async function checkOne(platform: string) {
  try {
    const result = await call<CheckResult>(`/credentials/${platform}/check`, { method: 'POST' })
    checks.value = { ...checks.value, [platform]: result }
  } catch (issue) {
    checks.value = {
      ...checks.value,
      [platform]: { platform, ok: false, models: 0, elapsed_ms: 0, error: (issue as Error).message },
    }
  }
}

async function checkAll() {
  checking.value = true
  try {
    const { results } = await checkAllCredentials()
    const map: Record<string, CheckResult> = {}
    for (const item of results) map[item.platform] = item
    checks.value = map
    note.value = results.every((r) => r.ok) ? '检测完成：所有平台凭据均可用' : '检测完成：有平台不可用，见下方说明'
  } catch (issue) {
    error.value = (issue as Error).message
  } finally {
    checking.value = false
  }
}

onMounted(load)
onBeforeUnmount(stopPolling)
</script>

<template>
  <div class="page-title">
    <h1>凭证管理</h1>
    <div class="actions">
      <button class="ghost" :disabled="checking" @click="checkAll">{{ checking ? '检测中…' : '全部检测' }}</button>
      <button class="ghost" @click="load">刷新</button>
    </div>
  </div>

  <div v-if="error" class="notice warning">{{ error }}</div>
  <div v-if="note" class="notice">{{ note }}</div>

  <Panel title="平台凭证" hint="凭据存在仓库 cred/&lt;平台&gt;/，已过滤不入库">
    <div class="cred-list">
      <div v-for="row in rows" :key="row.platform" class="cred-card">
        <div class="cred-head">
          <strong>{{ row.label }}</strong>
          <StatusBadge :text="row.present ? '已入库' : '未添加'" :kind="row.present ? 'good' : 'warn'" />
          <span class="mono note">{{ row.platform }}</span>
        </div>
        <dl class="fields">
          <dt>账号</dt><dd>{{ text(row.account) }}</dd>
          <dt>指纹</dt><dd class="mono">{{ text(row.fingerprint) }}</dd>
          <dt>凭据文件</dt><dd class="mono ellipsis" :title="text(row.path)">{{ text(row.path) }}</dd>
          <dt>来源</dt><dd>{{ text(row.source) }}</dd>
        </dl>
        <p v-if="checks[row.platform]" class="note">
          <StatusBadge
            :text="checks[row.platform].ok ? `可用 · ${checks[row.platform].models} 个模型 · ${checks[row.platform].elapsed_ms}ms` : '不可用'"
            :kind="checks[row.platform].ok ? 'good' : 'bad'"
          />
          <span v-if="checks[row.platform].error"> · {{ checks[row.platform].error }}</span>
        </p>
        <p v-if="row.error" class="error">{{ row.error }}</p>
        <div class="actions" style="margin-top: 8px">
          <button class="primary" @click="openLogin(row)">添加凭证</button>
          <button class="ghost" @click="checkOne(row.platform)">检测</button>
          <button class="ghost" @click="refresh(row)">重读</button>
        </div>
      </div>
    </div>
  </Panel>

  <div v-if="dialog" class="modal-mask" @click.self="closeDialog">
    <div class="modal">
      <header class="modal-head">
        <h2>添加凭证 · {{ active?.label }}</h2>
        <button class="ghost" @click="closeDialog">关闭</button>
      </header>

      <template v-if="state.state === 'manual'">
        <p class="note">{{ state.message }}</p>
      </template>

      <template v-else>
        <p class="note">{{ state.message || '等待授权…' }}</p>
        <div class="qr-wrap">
          <img v-if="qr" :src="qr" alt="登录二维码" />
          <div v-else class="qr-placeholder">二维码生成中…</div>
        </div>
        <p class="note">用手机扫码，或点下面的链接在浏览器里完成授权（已尝试自动打开）。</p>
        <div class="url-row">
          <span class="mono ellipsis" :title="state.auth_url">{{ state.auth_url || '—' }}</span>
          <button class="ghost" @click="copyUrl">复制链接</button>
          <a v-if="state.auth_url" :href="state.auth_url" target="_blank" rel="noreferrer">
            <button class="ghost">打开</button>
          </a>
        </div>
        <p class="note">
          状态：{{ state.state === 'success' ? '已登录并入库' : state.state === 'failed' ? '失败' : '等待授权' }}
          <span v-if="state.finished_at"> · {{ when(state.finished_at) }}</span>
        </p>
      </template>
    </div>
  </div>
</template>
