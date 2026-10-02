<template>
  <div class="resource-content">
    <PptPreview v-if="resource.resource_type === 'ppt'" :content="resource.content" />
    <MindmapPreview v-else-if="resource.resource_type === 'mindmap'" :content="resource.content" />
    <audio v-else-if="resource.resource_type === 'audio' && safeUrl" :src="safeUrl" controls preload="metadata" aria-label="资源音频" />
    <video v-else-if="isVideoFile" :src="safeUrl" controls preload="metadata" aria-label="资源视频" />
    <img v-else-if="resource.resource_type === 'image' && safeUrl" :src="safeUrl" :alt="resource.topic || '学习资源图片'" />
    <MarkdownDocument v-else :content="resource.content || ''" :title="resource.topic" :show-title="false" :annotatable="false" />
    <a v-if="safeUrl" class="button button--quiet resource-file" :href="safeUrl" target="_blank" rel="noopener noreferrer">打开资源文件 ↗</a>
  </div>
</template>
<script setup>
import { computed } from 'vue'
import MarkdownDocument from '@/features/fundamentals/MarkdownDocument.vue'
import PptPreview from '@/features/fundamentals/PptPreview.vue'
import MindmapPreview from '@/features/fundamentals/MindmapPreview.vue'
import { resolveResourceFileUrl } from '@/shared/api/resourceUrls'
const props = defineProps({ resource: { type: Object, required: true } })
const safeUrl = computed(() => resolveResourceFileUrl(props.resource.file_url))
const isVideoFile = computed(() => props.resource.resource_type === 'video' && /\.(mp4|webm|ogg)(?:\?|$)/i.test(safeUrl.value))
</script>
<style scoped>
.resource-content { min-width:0; overflow-wrap:anywhere; }
.resource-file { margin-top:16px; }
.resource-content > audio, .resource-content > video, .resource-content > img { display:block; max-width:100%; width:100%; }
</style>
