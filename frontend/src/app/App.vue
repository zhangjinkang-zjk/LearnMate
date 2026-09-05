<template>
  <RouterView v-slot="{ Component, route }">
    <component :is="route.meta.layout === 'immersive' ? Component : AppShell">
      <component :is="Component" />
    </component>
    <RobertAssistant v-if="route.path.startsWith('/learning/')" />
  </RouterView>
  <AgentWorkflowDrawer :state="workflowState" />
</template>

<script setup>
import AppShell from '@/layouts/AppShell.vue'
import AgentWorkflowDrawer from '@/features/agent/AgentWorkflowDrawer.vue'
import RobertAssistant from '@/features/xiaozhi/RobertAssistant.vue'
import { workflowState } from '@/entities/agent/agentWorkflowState'
</script>
