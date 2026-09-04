<template>
  <main class="login-page">
    <section class="login-panel surface">
      <RouterLink class="back-link" to="/"><span aria-hidden="true">←</span> 返回首页</RouterLink>
      <p class="eyebrow">LearnMate · 登录</p>
      <h1>登录你的学习空间</h1>
      <p class="intro">登录后，系统才能保存你的学习定向、诊断记录和学习进度。</p>
      <form class="login-form" @submit.prevent="submit">
        <label><span>用户名</span><input v-model.trim="username" autocomplete="username" required placeholder="输入用户名" /></label>
        <label><span>密码</span><input v-model="password" type="password" autocomplete="current-password" required placeholder="输入密码" /></label>
        <p v-if="errorMessage" class="error-message">{{ errorMessage }}</p>
        <button class="button button--primary" type="submit" :disabled="isSubmitting">{{ isSubmitting ? '登录中…' : '登录并继续' }}</button>
      </form>
    </section>
  </main>
</template>

<script setup>
import { ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { authApi } from '@/shared/api/authApi'

const route = useRoute()
const router = useRouter()
const username = ref('')
const password = ref('')
const isSubmitting = ref(false)
const errorMessage = ref('')

async function submit() {
  if (isSubmitting.value) return
  isSubmitting.value = true
  errorMessage.value = ''
  try {
    const data = await authApi.login(username.value, password.value)
    localStorage.setItem('token', data.token)
    if (data.username) localStorage.setItem('learnmate_username', data.username)
    const redirect = typeof route.query.redirect === 'string' && route.query.redirect.startsWith('/') ? route.query.redirect : '/learning/overview'
    await router.replace(redirect)
  } catch (error) {
    errorMessage.value = error.message || '登录失败，请稍后重试'
  } finally {
    isSubmitting.value = false
  }
}
</script>

<style scoped>
.login-page { display: grid; min-height: 100vh; place-items: center; padding: 24px; background: var(--stage); }.login-panel { width: min(430px, 100%); padding: 34px; }.back-link { display: inline-flex; align-items: center; gap: 8px; margin-bottom: 56px; color: var(--muted); font-size: 12px; text-decoration: none; }.back-link:hover { color: var(--accent-deep); }.login-panel h1 { margin: 0; font-size: clamp(28px, 5vw, 38px); line-height: 1.2; }.intro { margin: 13px 0 30px; color: var(--muted); font-size: 13px; line-height: 1.75; }.login-form { display: grid; gap: 17px; }.login-form label { display: grid; gap: 7px; }.login-form label span { color: var(--muted); font-size: 12px; }.login-form input { width: 100%; min-height: 42px; padding: 0 12px; border: 1px solid var(--line); border-radius: 5px; background: #fbfcfa; color: var(--ink); outline: none; font-size: 13px; }.login-form input:focus { border-color: var(--accent-deep); }.login-form button { width: 100%; margin-top: 5px; }.login-form button:disabled { cursor: wait; opacity: .55; }.error-message { margin: -3px 0 0; color: #a66b47; font-size: 12px; }
</style>
