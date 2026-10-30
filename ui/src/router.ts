import { createRouter, createWebHistory } from 'vue-router'
import Overview from './views/Overview.vue'
import Models from './views/Models.vue'
import Logs from './views/Logs.vue'
import Credentials from './views/Credentials.vue'
import Settings from './views/Settings.vue'

// 后端把 /dashboard/<page> 统一回退到 index.html，所以真实路径刷新/直达都不会 404。
export const routes = [
  { path: '/', name: 'overview', component: Overview, meta: { label: '概览' } },
  { path: '/credentials', name: 'credentials', component: Credentials, meta: { label: '凭证管理' } },
  { path: '/models', name: 'models', component: Models, meta: { label: '模型路由' } },
  { path: '/logs', name: 'logs', component: Logs, meta: { label: '日志审计' } },
  { path: '/settings', name: 'settings', component: Settings, meta: { label: '系统设置' } },
  { path: '/:pathMatch(.*)*', redirect: '/' },
]

export const router = createRouter({
  history: createWebHistory('/dashboard/'),
  routes,
})
