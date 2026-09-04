<template>
  <main class="login-page">
    <section class="login-panel surface">
      <RouterLink class="back-link" to="/"><span aria-hidden="true">←</span> 返回首页</RouterLink>
      <p class="eyebrow">LearnMate · {{ isRegistering ? '注册' : '登录' }}</p>
      <h1>{{ isRegistering ? '创建你的学习账号' : '登录你的学习空间' }}</h1>
      <p class="intro">{{ isRegistering ? '创建账号后即可保存学习定向、诊断记录和学习进度。' : '登录后，系统才能保存你的学习定向、诊断记录和学习进度。' }}</p>
      <form class="login-form" @submit.prevent="submit">
        <label><span>用户名</span><input v-model.trim="username" autocomplete="username" required placeholder="输入用户名" /></label>
        <label v-if="isRegistering"><span>邮箱</span><input v-model.trim="email" type="email" autocomplete="email" required placeholder="用于接收注册验证码" /></label>
        <label v-if="isRegistering" class="code-field"><span>邮箱验证码</span><div class="code-row"><input v-model.trim="emailCode" inputmode="numeric" autocomplete="one-time-code" maxlength="6" pattern="[0-9]{6}" required placeholder="输入 6 位验证码" /><button class="code-button" type="button" :disabled="isSendingCode || codeCountdown > 0 || !email" @click="sendCode">{{ isSendingCode ? '发送中…' : codeCountdown > 0 ? `${codeCountdown}s 后重发` : '获取验证码' }}</button></div></label>
        <label><span>密码</span><input v-model="password" type="password" autocomplete="current-password" required placeholder="输入密码" /></label>
        <label v-if="isRegistering"><span>确认密码</span><input v-model="confirmPassword" type="password" autocomplete="new-password" required placeholder="再次输入密码" /></label>
        <p v-if="errorMessage" class="error-message">{{ errorMessage }}</p>
        <button class="button button--primary" type="submit" :disabled="isSubmitting">{{ isSubmitting ? (isRegistering ? '注册中…' : '登录中…') : (isRegistering ? '注册并继续' : '登录并继续') }}</button>
      </form>
      <button class="mode-toggle" type="button" @click="toggleMode">{{ isRegistering ? '已有账号？返回登录' : '还没有账号？创建账号' }}</button>
    </section>
  </main>
</template>

<script setup>
import { onBeforeUnmount, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { authApi } from '@/shared/api/authApi'

const route = useRoute()
const router = useRouter()
const username = ref('')
const email = ref('')
const emailCode = ref('')
const password = ref('')
const confirmPassword = ref('')
const isRegistering = ref(false)
const isSubmitting = ref(false)
const isSendingCode = ref(false)
const codeCountdown = ref(0)
let codeTimer
const errorMessage = ref('')

async function submit() {
  if (isSubmitting.value) return
  isSubmitting.value = true
  errorMessage.value = ''
  try {
    if (isRegistering.value && password.value !== confirmPassword.value) {
      throw new Error('两次输入的密码不一致')
    }
    const data = isRegistering.value
      ? await authApi.registerByEmail(username.value, email.value, password.value, emailCode.value)
      : await authApi.login(username.value, password.value)
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

function toggleMode() {
  isRegistering.value = !isRegistering.value
  email.value = ''
  emailCode.value = ''
  password.value = ''
  confirmPassword.value = ''
  errorMessage.value = ''
  stopCodeCountdown()
}

async function sendCode() {
  if (isSendingCode.value || codeCountdown.value > 0 || !email.value) return
  isSendingCode.value = true
  errorMessage.value = ''
  try {
    await authApi.sendEmailCode(email.value)
    codeCountdown.value = 60
    codeTimer = window.setInterval(() => {
      codeCountdown.value -= 1
      if (codeCountdown.value <= 0) stopCodeCountdown()
    }, 1000)
  } catch (error) {
    errorMessage.value = error.message || '验证码发送失败，请稍后重试'
  } finally {
    isSendingCode.value = false
  }
}

function stopCodeCountdown() {
  if (codeTimer) {
    window.clearInterval(codeTimer)
    codeTimer = undefined
  }
  codeCountdown.value = 0
}

onBeforeUnmount(stopCodeCountdown)
</script>

<style scoped>
.login-page { display: grid; min-height: 100vh; place-items: center; padding: 24px; background: var(--stage); }.login-panel { width: min(430px, 100%); padding: 34px; }.back-link { display: inline-flex; align-items: center; gap: 8px; margin-bottom: 56px; color: var(--muted); font-size: 12px; text-decoration: none; }.back-link:hover { color: var(--accent-deep); }.login-panel h1 { margin: 0; font-size: clamp(28px, 5vw, 38px); line-height: 1.2; }.intro { margin: 13px 0 30px; color: var(--muted); font-size: 13px; line-height: 1.75; }.login-form { display: grid; gap: 17px; }.login-form label { display: grid; gap: 7px; }.login-form label span { color: var(--muted); font-size: 12px; }.login-form input { width: 100%; min-height: 42px; padding: 0 12px; border: 1px solid var(--line); border-radius: 5px; background: #fbfcfa; color: var(--ink); outline: none; font-size: 13px; }.login-form input:focus { border-color: var(--accent-deep); }.code-row { display: grid; grid-template-columns: 1fr auto; gap: 8px; }.code-button { width: auto !important; min-width: 108px; margin-top: 0 !important; padding: 0 12px; border: 1px solid var(--line); border-radius: 5px; background: #eef2eb; color: var(--accent-deep); font-size: 12px; }.login-form button:disabled { cursor: wait; opacity: .55; }.error-message { margin: -3px 0 0; color: #a66b47; font-size: 12px; }
.mode-toggle { display: block; margin: 18px auto 0; border: 0; background: transparent; color: var(--accent-deep); cursor: pointer; font-size: 12px; }
</style>
