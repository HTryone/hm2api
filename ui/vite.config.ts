import { fileURLToPath, URL } from 'node:url'
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// 后端把前端挂在 /dashboard/ 下；用真实路径路由，刷新/直达深链都由后端回退到 index.html。
export default defineConfig({
  base: '/dashboard/',
  plugins: [vue()],
  resolve: {
    alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) },
  },
  build: {
    outDir: 'dist',
    emptyOutDir: true,
    chunkSizeWarningLimit: 900,
  },
  server: {
    port: 5199,
    proxy: {
      '/admin': 'http://127.0.0.1:8788',
      '/v1': 'http://127.0.0.1:8788',
    },
  },
})
