<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { routes } from './router'
import { restore, signIn, signOut, type AuthState } from './services/session'

const auth = ref<AuthState>({ status: 'checking', error: '' })
const apiKey = ref('')
const route = useRoute()

const navItems = computed(() => routes.filter((item) => item.meta?.label))

async function submit() {
  auth.value = await signIn(apiKey.value.trim())
  apiKey.value = ''
}

async function leave() {
  auth.value = await signOut()
}

onMounted(async () => {
  auth.value = await restore()
})
</script>

<template>
  <div v-if="auth.status === 'checking'" class="login">
    <div class="card panel">正在校验登录态…</div>
  </div>

  <div v-else-if="auth.status === 'anonymous'" class="login">
    <div class="card panel">
      <h1>Hm2api 网关管理</h1>
      <p class="note">
        输入 API Key（<span class="mono">.env</span> 里的 LOOMY2API_KEY，也是调用模型用的那把）
      </p>
      <div class="row">
        <input v-model="apiKey" type="password" placeholder="API Key" @keyup.enter="submit" />
        <button class="primary" @click="submit">登录</button>
      </div>
      <p v-if="auth.error" class="error">{{ auth.error }}</p>
    </div>
  </div>

  <div v-else class="shell">
    <aside class="sidebar">
      <div class="brand">
        <span class="brand-icon">◕</span>
        <span class="brand-text">Hm2api<small>多平台网关工作台</small></span>
      </div>
      <nav class="nav">
        <router-link
          v-for="item in navItems"
          :key="item.path"
          :to="item.path"
          :class="{ active: route.path === item.path }"
        >
          {{ item.meta.label }}
        </router-link>
      </nav>
      <div class="side-foot">
        <button class="ghost" @click="leave">退出登录</button>
      </div>
    </aside>
    <main class="main">
      <router-view />
    </main>
  </div>
</template>
