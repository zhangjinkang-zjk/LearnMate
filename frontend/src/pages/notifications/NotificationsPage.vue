<template>
  <div>
    <PageTitle eyebrow="通知" title="不会错过重要进展" description="这里会显示学习任务、路径和系统提醒。" />
    <section class="notification-panel surface">
      <div v-for="item in notifications" :key="item.title" class="notification-row">
        <span class="notification-dot" :class="{ 'is-new': item.new }"></span>
        <div><strong>{{ item.title }}</strong><p>{{ item.copy }}</p></div>
        <time>{{ item.time }}</time>
      </div>
    </section>
  </div>
</template>
<script setup>
import PageTitle from '@/shared/ui/PageTitle.vue'
const notifications = [
  { title: '欢迎来到 LearnMate', copy: '完成身份选择后，我们会为你生成第一项学习任务。', time: '刚刚', new: true },
  { title: '学习路径已准备', copy: '你的学习概览会随着画像确认逐步更新。', time: '今天', new: false },
]
</script>
<style scoped>
.notification-panel { max-width:820px; }.notification-row { display:grid; grid-template-columns:10px minmax(0,1fr) auto; align-items:start; gap:14px; padding:20px 22px; border-bottom:1px solid var(--line); }.notification-row:last-child { border-bottom:0; }.notification-row strong { font-size:14px; }.notification-row p { margin:6px 0 0; color:var(--muted); font-size:12px; line-height:1.6; }.notification-row time { color:var(--muted); font-size:11px; }.notification-dot { width:8px; height:8px; margin-top:5px; border-radius:50%; background:#cdd6cf; }.notification-dot.is-new { background:var(--accent); }
</style>
