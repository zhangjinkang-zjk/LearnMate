import { defineConfig, loadEnv } from 'vite'
import vue from '@vitejs/plugin-vue'
import tailwindcss from '@tailwindcss/vite'
import path from 'path'

const rawBackendTarget = loadEnv(process.env.NODE_ENV || 'development', process.cwd(), '').VITE_API_BASE_URL?.trim() || ''
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

// Monaco 是按需加载的（见 src/features/advanced/workspace/monacoSetup.js），
// 而它走的是深层子路径而不是包名，依赖扫描容易漏。dev server 是在装 monaco 之前
// 起的话，会在运行时抛 `Failed to fetch dynamically imported module` —— 构建却是好的，
// 所以列在这里固定下来，别靠扫描。
const MONACO_MODULES = [
  'monaco-editor/editor/editor.api.js',
  'monaco-editor/languages/definitions/python/register.js',
  'monaco-editor/languages/definitions/javascript/register.js',
  'monaco-editor/languages/definitions/typescript/register.js',
  'monaco-editor/languages/definitions/markdown/register.js',
  'monaco-editor/languages/definitions/yaml/register.js',
  'monaco-editor/languages/definitions/shell/register.js',
  'monaco-editor/languages/definitions/sql/register.js',
  'monaco-editor/languages/definitions/html/register.js',
  'monaco-editor/languages/definitions/css/register.js',
  'monaco-editor/languages/definitions/dockerfile/register.js',
  'monaco-editor/languages/definitions/ini/register.js',
  'monaco-editor/languages/definitions/xml/register.js',
]

export default defineConfig({
  plugins: [vue(), tailwindcss()],
  optimizeDeps: {
    include: MONACO_MODULES,
  },
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
      '/presentation': proxyTarget,
      '/notification': proxyTarget,
      '/annotation': proxyTarget,
      '/debug': proxyTarget,
      '/api/agents': proxyTarget,
    },
  }
})
