<template>
  <div>
    <PageTitle eyebrow="个人信息" title="你的 LearnMate" description="查看当前账户和学习身份信息。" />
    <section class="profile-panel surface">
      <div class="profile-hero">
        <div class="profile-large-avatar">{{ initial }}</div>
        <div><p class="profile-label">用户名</p><h2>{{ username }}</h2><p class="profile-muted">学习者账户</p></div>
      </div>
      <div class="profile-fields">
        <div><span>身份</span><strong>{{ identity }}</strong></div>
        <div><span>账户状态</span><strong>已连接</strong></div>
      </div>
    </section>
  </div>
</template>
<script setup>
import { computed } from 'vue'
import PageTitle from '@/shared/ui/PageTitle.vue'
const username = computed(() => localStorage.getItem('learnmate_username') || '我的学习者')
const identity = computed(() => localStorage.getItem('learnmate_identity') || '尚未选择')
const initial = computed(() => username.value.slice(0, 1).toUpperCase() || '学')
</script>
<style scoped>
.profile-panel { max-width: 760px; padding: 28px; }.profile-hero { display:flex; align-items:center; gap:16px; padding-bottom:24px; border-bottom:1px solid var(--line); }.profile-large-avatar { display:grid; width:64px; height:64px; place-items:center; border-radius:50%; background:var(--accent); color:#1e3c34; font-size:22px; font-weight:900; }.profile-label { margin:0 0 5px; color:var(--muted); font-size:11px; }.profile-hero h2 { margin:0; font-size:23px; }.profile-muted { margin:5px 0 0; color:var(--muted); font-size:12px; }.profile-fields { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:20px; padding-top:22px; }.profile-fields div { display:grid; gap:7px; }.profile-fields span { color:var(--muted); font-size:11px; }.profile-fields strong { color:var(--ink); font-size:14px; }
@media (max-width:560px) { .profile-panel { padding:20px; }.profile-fields { grid-template-columns:1fr; } }
</style>
