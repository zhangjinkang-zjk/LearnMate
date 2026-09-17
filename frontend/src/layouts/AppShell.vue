<template>
  <div class="app-shell">
    <aside class="app-sidebar" :class="{ 'is-open': sidebarOpen }">
      <div class="brand-lockup">
        <RouterLink class="brand-name" to="/" aria-label="返回首页">LearnMate</RouterLink>
      </div>

      <div class="sidebar-nav-dock">
        <div class="sidebar-section">
          <p class="sidebar-label">学习主线</p>
          <nav class="sidebar-nav" aria-label="学习主线">
            <RouterLink v-for="item in primaryNavigation" :key="item.to" :to="item.to" class="sidebar-link">
              <component :is="item.icon" :size="17" stroke-width="1.8" />
              <span>{{ item.label }}</span>
            </RouterLink>
          </nav>
        </div>

        <div v-for="group in learningNavigationGroups" :key="group.label" class="sidebar-section sidebar-nav-group">
          <p class="sidebar-group-label">{{ group.label }}</p>
          <nav class="sidebar-nav" :aria-label="group.label">
            <RouterLink v-for="item in group.items" :key="item.to" :to="item.to" class="sidebar-link">
              <component :is="item.icon" :size="17" stroke-width="1.8" />
              <span>{{ item.label }}</span>
            </RouterLink>
          </nav>
        </div>

        <div class="sidebar-section sidebar-section--secondary">
          <p class="sidebar-label">资料</p>
          <nav class="sidebar-nav" aria-label="资料工具">
            <RouterLink v-for="item in secondaryNavigation" :key="item.to" :to="item.to" class="sidebar-link">
              <component :is="item.icon" :size="17" stroke-width="1.8" />
              <span>{{ item.label }}</span>
            </RouterLink>
          </nav>
        </div>
      </div>

      <button
        class="sidebar-workflow-launcher"
        type="button"
        title="查看智能体工作流"
        aria-label="查看智能体工作流"
        :aria-expanded="workflowState.open"
        @click="setWorkflowOpen(!workflowState.open)"
      >
        <Workflow :size="18" stroke-width="1.8" />
        <span>智能体流程</span>
        <i v-if="isWorkflowActive" aria-hidden="true"></i>
      </button>

      <div class="sidebar-footer">
        <RouterLink v-for="item in utilityNavigation" :key="item.to" :to="item.to" class="sidebar-link">
          <component :is="item.icon" :size="17" stroke-width="1.8" />
          <span>{{ item.label }}</span>
        </RouterLink>
        <div class="profile-chip">
          <span class="profile-copy"><strong>{{ displayName }}</strong><small>学习进行中</small></span>
          <button class="logout-button" type="button" title="退出登录" aria-label="退出登录" @click="logout">
            <LogOut :size="15" stroke-width="1.8" />
          </button>
        </div>
      </div>
    </aside>

    <div v-if="sidebarOpen" class="sidebar-backdrop" @click="sidebarOpen = false"></div>
    <main class="app-content">
      <header class="app-header">
        <button class="menu-button" type="button" aria-label="打开导航" @click="sidebarOpen = !sidebarOpen">☰</button>
        <div class="header-context">
          <span class="header-kicker">学习空间</span>
          <span class="header-divider">/</span>
          <span>{{ currentTitle }}</span>
        </div>
        <div class="header-actions">
          <RouterLink class="header-icon-button" to="/notifications" :title="notificationTitle" :aria-label="notificationTitle">
            <Bell :size="17" stroke-width="1.8" />
            <i v-if="unreadNotifications > 0" class="header-unread-badge" aria-hidden="true">{{ unreadNotifications > 99 ? '99+' : unreadNotifications }}</i>
          </RouterLink>
          <button class="header-icon-button" type="button" :title="isDarkMode ? '开启亮色模式' : '开启深色模式'" :aria-label="isDarkMode ? '开启亮色模式' : '开启深色模式'" :aria-pressed="isDarkMode" @click="toggleTheme">
            <Moon v-if="!isDarkMode" :size="17" stroke-width="1.8" />
            <Sun v-else :size="17" stroke-width="1.8" />
          </button>
          <RouterLink class="header-icon-button" to="/planner" title="计划本" aria-label="计划本">
            <ClipboardList :size="17" stroke-width="1.8" />
          </RouterLink>
          <RouterLink class="header-avatar" to="/profile" title="个人信息" aria-label="个人信息">
            {{ avatarLetter }}
          </RouterLink>
        </div>
      </header>
      <section
        class="page-container"
        :class="{ 'page-container--workspace': route.meta.contentLayout === 'workspace' }"
      >
        <slot />
      </section>
    </main>
  </div>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Bell, ClipboardList, LogOut, Moon, Sun, Workflow } from 'lucide-vue-next'
import { allNavigation, learningNavigationGroups, primaryNavigation, secondaryNavigation, utilityNavigation } from '@/shared/config/navigation'
import { clearAuthSession } from '@/shared/auth/session'
import { setWorkflowOpen, workflowState } from '@/entities/agent/agentWorkflowState'
import { notificationApi } from '@/shared/api/notificationApi'

const route = useRoute()
const router = useRouter()
const sidebarOpen = ref(false)
const unreadNotifications = ref(0)
const notificationTitle = computed(() => (
  unreadNotifications.value > 0 ? `通知（${unreadNotifications.value} 条未读）` : '通知'
))

// 通知由后端在学习路径解锁、资源生成完成时写入。铃铛这里只读一个计数，
// 每次路由跳转刷新一次，成本是一次 count 查询，避免让红点长期停在过期状态。
async function refreshUnreadNotifications() {
  if (!localStorage.getItem('token')) {
    unreadNotifications.value = 0
    return
  }
  try {
    unreadNotifications.value = await notificationApi.unreadCount()
  } catch {
    // 计数读不到不该影响页面本身，保持上一次的值即可。
  }
}
watch(() => route.fullPath, refreshUnreadNotifications, { immediate: true })
const currentTitle = computed(() => allNavigation.find((item) => route.path.startsWith(item.to))?.label || '学习概览')
const displayName = computed(() => localStorage.getItem('learnmate_username') || '我的学习者')
const avatarLetter = computed(() => displayName.value.trim().slice(0, 1).toUpperCase() || '学')
const isDarkMode = ref(localStorage.getItem('learnmate_theme') === 'dark')
const isWorkflowActive = computed(() => ['running', 'reviewing', 'retrying', 'saving'].includes(workflowState.nodes?.[workflowState.activeAgentId]?.status))

if (isDarkMode.value) document.documentElement.classList.add('is-dark')

function toggleTheme() {
  isDarkMode.value = !isDarkMode.value
  localStorage.setItem('learnmate_theme', isDarkMode.value ? 'dark' : 'light')
  document.documentElement.classList.toggle('is-dark', isDarkMode.value)
}

async function logout() {
  clearAuthSession()
  sidebarOpen.value = false
  await router.replace({ name: 'home' })
}
</script>
