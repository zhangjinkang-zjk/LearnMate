<template>
  <RouterView v-slot="{ Component, route }">
    <component :is="route.meta.layout === 'immersive' ? Component : AppShell">
      <component :is="Component" />
    </component>
  </RouterView>
  <XiaozhiAssistant />
  <AgentWorkflowDrawer :state="workflowState" />
</template>

<script setup>
import AppShell from '@/layouts/AppShell.vue'
import AgentWorkflowDrawer from '@/features/agent/AgentWorkflowDrawer.vue'
import XiaozhiAssistant from '@/features/xiaozhi/XiaozhiAssistant.vue'
import { workflowState } from '@/entities/agent/agentWorkflowState'
</script>
