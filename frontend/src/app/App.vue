<template>
  <RouterView v-slot="{ Component, route }">
    <component :is="route.meta.layout === 'immersive' ? Component : AppShell">
      <component :is="Component" />
    </component>
  </RouterView>
  <XiaozhiAssistant />
</template>

<script setup>
import AppShell from '@/layouts/AppShell.vue'
import XiaozhiAssistant from '@/features/xiaozhi/XiaozhiAssistant.vue'
</script>
