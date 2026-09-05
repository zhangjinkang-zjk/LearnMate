import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import tailwindcss from '@tailwindcss/vite'
import path from 'path'

const rawBackendTarget = process.env.VITE_API_BASE_URL?.trim() || ''
const backendTarget = /^https?:\/\//i.test(rawBackendTarget)
  ? rawBackendTarget.replace(/\/+$/, '')
  : 'http://127.0.0.1:2221'
const proxyTarget = {
  target: backendTarget,
  changeOrigin: true,
  secure: true,
  headers: {
    'ngrok-skip-browser-warning': 'true',
  },
}

export default defineConfig({
  plugins: [vue(), tailwindcss()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  server: {
    host: '0.0.0.0',
    port: 5173,
    strictPort: true,
    // 允许通过 ngrok 预览开发环境，但不开放任意 Host，避免 DNS 重绑定风险。
    allowedHosts: ['.ngrok-free.app', '.ngrok-free.dev'],
    proxy: {
      '/static': proxyTarget,
      '/ai_chat': proxyTarget,
      '/ai_portrait': proxyTarget,
      '/path': proxyTarget,
      '/learning_path': proxyTarget,
      '/learning': proxyTarget,
      '/resource': proxyTarget,
      '/image': proxyTarget,
      '/knowledge': proxyTarget,
      '/user': proxyTarget,
      '/admin': proxyTarget,
      '/exam': proxyTarget,
      '/video': proxyTarget,
      '/study': proxyTarget,
      '/study-room': proxyTarget,
      '/mock-classroom': proxyTarget,
      '/presentation': proxyTarget,
      '/notification': proxyTarget,
      '/annotation': proxyTarget,
      '/debug': proxyTarget,
      '/api/agents': proxyTarget,
    },
  }
})
