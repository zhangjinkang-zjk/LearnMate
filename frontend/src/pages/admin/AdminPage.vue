<template>
  <div class="admin-page">
    <PageTitle eyebrow="管理中心" title="让学习空间有序运行" description="审核学习资源、管理账号，关注用户学习并推送适合的内容。" />
    <nav class="admin-tabs" aria-label="管理功能"><RouterLink v-for="tab in tabs" :key="tab.key" :to="{ name: 'admin', query: { tab: tab.key } }" :class="{ 'is-active': activeTab === tab.key }" :aria-current="activeTab === tab.key ? 'page' : undefined"><component :is="tab.icon" :size="17" />{{ tab.label }}</RouterLink></nav>
    <ResourceManagement v-if="activeTab === 'resources'" />
    <AccountManagement v-else :key="activeTab" :view="activeTab" />
  </div>
</template>
<script setup>
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import { Files, Users, ChartNoAxesCombined, Send } from 'lucide-vue-next'
import PageTitle from '@/shared/ui/PageTitle.vue'
import ResourceManagement from '@/features/admin/ResourceManagement.vue'
import AccountManagement from '@/features/admin/AccountManagement.vue'
import '@/shared/styles/admin.css'
const route = useRoute()
const tabs = [
  { key: 'resources', label: '资源审核', icon: Files },
  { key: 'accounts', label: '账号管理', icon: Users },
  { key: 'activity', label: '活跃度', icon: ChartNoAxesCombined },
  { key: 'push', label: '资源推送', icon: Send },
]
const activeTab = computed(() => tabs.some(tab => tab.key === route.query.tab) ? route.query.tab : 'resources')
</script>
