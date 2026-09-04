<template>
  <div class="app-shell">
    <aside class="app-sidebar" :class="{ 'is-open': sidebarOpen }">
      <div class="brand-lockup">
        <span class="brand-mark">LM</span>
        <span class="brand-name">LearnMate</span>
      </div>

      <div class="sidebar-section">
        <p class="sidebar-label">学习主线</p>
        <nav class="sidebar-nav" aria-label="学习主线">
          <RouterLink v-for="item in primaryNavigation" :key="item.to" :to="item.to" class="sidebar-link">
            <component :is="item.icon" :size="17" stroke-width="1.8" />
            <span>{{ item.label }}</span>
          </RouterLink>
        </nav>
      </div>

      <div class="sidebar-section sidebar-section--secondary">
        <p class="sidebar-label">工具</p>
        <nav class="sidebar-nav" aria-label="学习工具">
          <RouterLink v-for="item in secondaryNavigation" :key="item.to" :to="item.to" class="sidebar-link">
            <component :is="item.icon" :size="17" stroke-width="1.8" />
            <span>{{ item.label }}</span>
          </RouterLink>
        </nav>
      </div>

      <div class="sidebar-footer">
        <RouterLink v-for="item in utilityNavigation" :key="item.to" :to="item.to" class="sidebar-link">
          <component :is="item.icon" :size="17" stroke-width="1.8" />
          <span>{{ item.label }}</span>
        </RouterLink>
        <div class="profile-chip">
          <span class="profile-avatar">学</span>
          <span class="profile-copy"><strong>我的学习者</strong><small>学习进行中</small></span>
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
        <div class="header-actions"><span class="status-dot"></span><span>学习状态已同步</span></div>
      </header>
      <section class="page-container"><slot /></section>
    </main>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'
import { useRoute } from 'vue-router'
import { primaryNavigation, secondaryNavigation, utilityNavigation } from '@/shared/config/navigation'

const route = useRoute()
const sidebarOpen = ref(false)
const allNavigation = [...primaryNavigation, ...secondaryNavigation, ...utilityNavigation]
const currentTitle = computed(() => allNavigation.find((item) => route.path.startsWith(item.to))?.label || '学习概览')
</script>
