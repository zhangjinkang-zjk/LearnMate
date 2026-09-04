<template>
  <div class="app-shell">
    <aside class="app-sidebar" :class="{ 'is-open': sidebarOpen }">
      <div class="brand-lockup">
        <span class="brand-name">LearnMate</span>
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
          <RouterLink class="header-icon-button" to="/notifications" title="通知" aria-label="通知">
            <Bell :size="17" stroke-width="1.8" />
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
import { computed, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Bell, ClipboardList, LogOut, Moon, Sun } from 'lucide-vue-next'
import { allNavigation, learningNavigationGroups, primaryNavigation, secondaryNavigation, utilityNavigation } from '@/shared/config/navigation'
import { clearAuthSession } from '@/shared/auth/session'

const route = useRoute()
const router = useRouter()
const sidebarOpen = ref(false)
const currentTitle = computed(() => allNavigation.find((item) => route.path.startsWith(item.to))?.label || '学习概览')
const displayName = computed(() => localStorage.getItem('learnmate_username') || '我的学习者')
const avatarLetter = computed(() => displayName.value.trim().slice(0, 1).toUpperCase() || '学')
const isDarkMode = ref(localStorage.getItem('learnmate_theme') === 'dark')

if (isDarkMode.value) document.documentElement.classList.add('is-dark')

function toggleTheme() {
  isDarkMode.value = !isDarkMode.value
  localStorage.setItem('learnmate_theme', isDarkMode.value ? 'dark' : 'light')
  document.documentElement.classList.toggle('is-dark', isDarkMode.value)
}

async function logout() {
  clearAuthSession()
  sidebarOpen.value = false
  await router.replace({ name: 'login' })
}
</script>
