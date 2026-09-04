<template>
  <article class="lesson-document surface" :class="{ 'lesson-document--wide': wide }">
    <header class="lesson-document__header">
      <div class="lesson-document__meta">
        <span>第 {{ chapterNumber }} 章</span>
        <span>{{ estimatedMinutes }} 分钟阅读</span>
      </div>
      <h1>{{ title }}</h1>
      <div v-if="tags.length" class="lesson-tags" aria-label="本章知识点">
        <span v-for="tag in tags" :key="tag">{{ tag }}</span>
      </div>
    </header>

    <div v-if="content" class="markdown-body" v-html="renderedContent"></div>
    <div v-else class="document-empty">
      <FileText :size="24" stroke-width="1.5" />
      <strong>本章文档还没有准备好</strong>
      <p>{{ emptyMessage }}</p>
    </div>
  </article>
</template>

<script setup>
import { computed } from 'vue'
import { FileText } from 'lucide-vue-next'
import { renderMarkdown } from '@/shared/lib/markdown'

const props = defineProps({
  title: { type: String, default: '' },
  content: { type: String, default: '' },
  tags: { type: Array, default: () => [] },
  chapterNumber: { type: Number, default: 1 },
  emptyMessage: { type: String, default: '系统会围绕当前节点生成完整讲解。' },
  wide: { type: Boolean, default: false },
})

const renderedContent = computed(() => renderMarkdown(props.content))
const estimatedMinutes = computed(() => Math.max(3, Math.ceil(props.content.replace(/\s/g, '').length / 420)))
</script>

<style scoped>
.lesson-document { min-width: 0; overflow: hidden; }
.lesson-document__header { padding: 28px clamp(24px, 5vw, 48px) 24px; border-bottom: 1px solid var(--line); background: #fbfcfa; }
.lesson-document__meta { display: flex; align-items: center; justify-content: space-between; gap: 16px; margin-bottom: 16px; color: var(--muted); font-size: 11px; }
.lesson-document h1 { max-width: 760px; margin: 0; color: var(--ink); font-size: clamp(25px, 3vw, 34px); line-height: 1.25; }
.lesson-tags { display: flex; flex-wrap: wrap; gap: 7px; margin-top: 18px; }
.lesson-tags span { padding: 5px 8px; border: 1px solid #dbe5d1; border-radius: 4px; background: #f1f6eb; color: var(--accent-deep); font-size: 10px; }
.markdown-body { max-width: 760px; min-height: 520px; margin: 0 auto; padding: 38px clamp(24px, 5vw, 50px) 64px; color: #27312c; font-size: 15px; line-height: 1.9; overflow-wrap: anywhere; }
.markdown-body :deep(h1) { margin: 0 0 26px; font-size: 29px; line-height: 1.3; }
.markdown-body :deep(h2) { margin: 42px 0 15px; padding-top: 10px; border-top: 1px solid var(--line); font-size: 22px; line-height: 1.4; }
.markdown-body :deep(h3) { margin: 30px 0 12px; color: #31513d; font-size: 17px; line-height: 1.5; }
.markdown-body :deep(p) { margin: 0 0 18px; }
.markdown-body :deep(ul), .markdown-body :deep(ol) { margin: 0 0 20px; padding-left: 24px; }
.markdown-body :deep(li) { margin: 7px 0; padding-left: 3px; }
.markdown-body :deep(blockquote) { margin: 24px 0; padding: 15px 18px; border-left: 3px solid var(--accent); background: #f5f8f1; color: #415047; }
.markdown-body :deep(code) { padding: 2px 5px; border-radius: 3px; background: #eef2ed; color: #274535; font-family: Consolas, "SFMono-Regular", monospace; font-size: .9em; }
.markdown-body :deep(pre) { overflow-x: auto; margin: 24px 0; padding: 18px; border-radius: 6px; background: #1f2a25; color: #edf4ea; line-height: 1.65; }
.markdown-body :deep(pre code) { padding: 0; background: transparent; color: inherit; }
.markdown-body :deep(table) { width: 100%; margin: 24px 0; border-collapse: collapse; font-size: 13px; }
.markdown-body :deep(th), .markdown-body :deep(td) { padding: 10px 12px; border: 1px solid var(--line); text-align: left; }
.markdown-body :deep(th) { background: #f1f4f0; }
.markdown-body :deep(a) { color: var(--accent-deep); text-underline-offset: 3px; }
.markdown-body :deep(img) { display: block; max-width: 100%; height: auto; margin: 24px auto; border-radius: 5px; }
.document-empty { display: grid; min-height: 520px; place-items: center; align-content: center; gap: 10px; padding: 40px; color: var(--muted); text-align: center; }
.document-empty strong { color: var(--ink); font-size: 16px; }
.document-empty p { max-width: 360px; margin: 0; font-size: 12px; line-height: 1.7; }
.lesson-document--wide .lesson-document__header > * { max-width: 940px; margin-right: auto; margin-left: auto; }
.lesson-document--wide .markdown-body { max-width: 940px; }
@media (max-width: 680px) {
  .lesson-document__header { padding: 22px 20px; }
  .lesson-document__meta { align-items: flex-start; flex-direction: column; gap: 6px; }
  .markdown-body { padding: 28px 20px 48px; font-size: 14px; }
}
</style>
