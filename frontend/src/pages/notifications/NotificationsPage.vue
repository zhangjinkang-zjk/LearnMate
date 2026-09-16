<template>
  <div>
    <PageTitle eyebrow="通知" title="不会错过重要进展" description="这里会显示学习任务、路径和系统提醒。" />
    <section class="notification-panel surface">
      <header class="notification-toolbar">
        <span>{{ unreadLabel }}</span>
        <button v-if="unreadCount > 0" class="notification-action" type="button" :disabled="isMarkingAll" @click="markAllRead">全部标为已读</button>
      </header>

      <div v-if="isLoading" class="notification-state">正在读取通知…</div>
      <div v-else-if="errorMessage" class="notification-state notification-state--error" role="alert">
        <span>{{ errorMessage }}</span>
        <button class="notification-action" type="button" @click="load">重试</button>
      </div>
      <div v-else-if="!notifications.length" class="notification-state">还没有收到通知。学习路径解锁、资源生成完成时这里会有提醒。</div>

      <template v-else>
        <button
          v-for="item in notifications"
          :key="item.id"
          class="notification-row"
          :class="{ 'is-unread': !item.is_read, 'is-linked': Boolean(item.target_url) }"
          type="button"
          @click="openItem(item)"
        >
          <span class="notification-dot" :class="{ 'is-new': !item.is_read }"></span>
          <div class="notification-copy">
            <strong>{{ item.title }}</strong>
            <p v-if="item.content">{{ item.content }}</p>
          </div>
          <time :datetime="item.created_at || undefined">{{ formatTime(item.created_at) }}</time>
        </button>
      </template>
    </section>
  </div>
</template>
<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import PageTitle from '@/shared/ui/PageTitle.vue'
import { notificationApi } from '@/shared/api/notificationApi'

const router = useRouter()
const notifications = ref([])
const unreadCount = ref(0)
const isLoading = ref(true)
const isMarkingAll = ref(false)
const errorMessage = ref('')

const unreadLabel = computed(() => (
  unreadCount.value > 0 ? `${unreadCount.value} 条未读` : '没有未读消息'
))

// 通知是"多久之前"的信息，相对时间比绝对时间戳更有用；超过一周再退回日期。
function formatTime(value) {
  if (!value) return ''
  const created = new Date(value)
  if (Number.isNaN(created.getTime())) return ''
  const minutes = Math.floor((Date.now() - created.getTime()) / 60000)
  if (minutes < 1) return '刚刚'
  if (minutes < 60) return `${minutes} 分钟前`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours} 小时前`
  const days = Math.floor(hours / 24)
  if (days < 7) return `${days} 天前`
  return `${created.getMonth() + 1} 月 ${created.getDate()} 日`
}

async function load() {
  isLoading.value = true
  errorMessage.value = ''
  try {
    const data = await notificationApi.list()
    notifications.value = data.items
    unreadCount.value = data.unreadCount
  } catch (error) {
    errorMessage.value = error?.response?.data?.detail || error?.message || '暂时读不到通知，请稍后重试。'
  } finally {
    isLoading.value = false
  }
}

// 路由用的是 hash 模式，直接给 <a href="/learning/..."> 会离开 SPA，
// 所以跳转统一走 router.push；外链才交给浏览器新开。
function followTarget(target) {
  const url = String(target || '').trim()
  if (!url) return
  if (/^https?:\/\//i.test(url)) {
    window.open(url, '_blank', 'noopener,noreferrer')
    return
  }
  router.push(url)
}

async function openItem(item) {
  followTarget(item.target_url)
  if (item.is_read) return
  // 先本地标已读再发请求：点开一条通知还要等一个往返才变色会很别扭，
  // 失败了也只是下一次加载时回退成未读。
  item.is_read = true
  unreadCount.value = Math.max(0, unreadCount.value - 1)
  try {
    await notificationApi.markRead(item.id)
  } catch {
    item.is_read = false
    unreadCount.value += 1
  }
}

async function markAllRead() {
  if (isMarkingAll.value) return
  isMarkingAll.value = true
  try {
    await notificationApi.markAllRead()
    notifications.value = notifications.value.map((item) => ({ ...item, is_read: true }))
    unreadCount.value = 0
  } catch (error) {
    errorMessage.value = error?.response?.data?.detail || error?.message || '标记已读失败，请重试。'
  } finally {
    isMarkingAll.value = false
  }
}

onMounted(load)
</script>
<style scoped>
.notification-panel { max-width:820px; }

.notification-toolbar { display:flex; align-items:center; justify-content:space-between; gap:12px; padding:16px 22px; border-bottom:1px solid var(--line); color:var(--muted); font-size:12px; }
.notification-action { padding:5px 10px; border:1px solid var(--line); border-radius:6px; background:transparent; color:inherit; font:inherit; font-weight:700; cursor:pointer; }
.notification-action:hover:not(:disabled) { border-color:var(--accent); color:var(--ink); }
.notification-action:disabled { cursor:wait; opacity:.6; }

.notification-row { display:grid; width:100%; grid-template-columns:10px minmax(0,1fr) auto; align-items:start; gap:14px; padding:20px 22px; border:0; border-bottom:1px solid var(--line); background:transparent; color:inherit; font:inherit; text-align:left; text-decoration:none; }
.notification-row:last-child { border-bottom:0; }
.notification-row.is-linked { cursor:pointer; }
.notification-row.is-linked:hover { background:var(--soft); }
.notification-row.is-unread strong { font-weight:800; }
.notification-copy strong { font-size:14px; }
.notification-copy p { margin:6px 0 0; color:var(--muted); font-size:12px; line-height:1.6; }
.notification-row time { color:var(--muted); font-size:11px; white-space:nowrap; }
.notification-dot { width:8px; height:8px; margin-top:5px; border-radius:50%; background:#cdd6cf; }
.notification-dot.is-new { background:var(--accent); }

.notification-state { display:grid; gap:12px; justify-items:start; padding:22px; color:var(--muted); font-size:12px; line-height:1.7; }
.notification-state--error { color:#8a4c43; }
</style>
