<template>
  <div class="resource-content">
    <PptPreview v-if="resource.resource_type === 'ppt'" :content="resource.content" />
    <MindmapPreview v-else-if="resource.resource_type === 'mindmap'" :content="resource.content" />
    <MarkdownDocument v-else :content="resource.content || ''" :title="resource.topic" :show-title="false" :annotatable="false" />
    <a v-if="safeUrl" class="button button--quiet resource-file" :href="safeUrl" target="_blank" rel="noopener noreferrer">打开资源文件 ↗</a>
  </div>
</template>
<script setup>
import { computed } from 'vue'
import MarkdownDocument from '@/features/fundamentals/MarkdownDocument.vue'
import PptPreview from '@/features/fundamentals/PptPreview.vue'
import MindmapPreview from '@/features/fundamentals/MindmapPreview.vue'
const props = defineProps({ resource: { type: Object, required: true } })
const safeUrl = computed(() => {
  const value = String(props.resource.file_url || '').trim()
  return /^https?:\/\//i.test(value) ? value : ''
})
</script>
<style scoped>
.resource-content { min-width:0; overflow-wrap:anywhere; }
.resource-file { margin-top:16px; }
</style>
