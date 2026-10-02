<template>
  <div class="admin-page">
    <PageTitle eyebrow="管理中心" title="让学习空间有序运行" description="审核学习资源、管理账号，关注用户学习并推送适合的内容。" />
    <nav class="admin-tabs" aria-label="管理功能"><button v-for="tab in tabs" :key="tab.key" :class="{ 'is-active': activeTab === tab.key }" :aria-pressed="activeTab === tab.key" @click="activeTab = tab.key"><component :is="tab.icon" :size="17" />{{ tab.label }}</button></nav>
    <ResourceManagement v-if="activeTab === 'resources'" />
    <AccountManagement v-else />
  </div>
</template>
<script setup>
import { ref } from 'vue'
import { Files, Users } from 'lucide-vue-next'
import PageTitle from '@/shared/ui/PageTitle.vue'
import ResourceManagement from '@/features/admin/ResourceManagement.vue'
import AccountManagement from '@/features/admin/AccountManagement.vue'
import '@/shared/styles/admin.css'
const activeTab = ref('resources')
const tabs = [{ key: 'resources', label: '资源审核与管理', icon: Files }, { key: 'accounts', label: '账号与活跃度', icon: Users }]
</script>
