<template>
  <article class="lesson-document surface" :class="{ 'lesson-document--wide': wide, 'lesson-document--paged': paginate, 'lesson-document--without-title': !showTitle }">
    <header class="lesson-document__header">
      <div class="lesson-document__meta">
        <span>第 {{ chapterNumber }} 章</span>
        <span>{{ paginate ? `第 ${currentPage + 1} / ${pageCount} 页 · ${pageEstimatedMinutes} 分钟` : `${estimatedMinutes} 分钟阅读` }}</span>
      </div>
      <h1 v-if="showTitle">{{ title }}</h1>
      <div v-if="tags.length" class="lesson-tags" aria-label="本章知识点">
        <span v-for="tag in tags" :key="tag">{{ tag }}</span>
      </div>
    </header>

    <Transition name="page-turn" mode="out-in">
      <div v-if="content" :key="`page-${currentPage}`" class="markdown-body document-page" v-html="renderedContent"></div>
      <div v-else key="empty" class="document-empty">
        <FileText :size="24" stroke-width="1.5" />
        <strong>本章文档还没有准备好</strong>
        <p>{{ emptyMessage }}</p>
      </div>
    </Transition>

    <nav v-if="paginate" class="document-pagination" aria-label="文档分页">
      <button type="button" :disabled="currentPage === 0" @click="goToPage(currentPage - 1)">
        <ChevronLeft :size="15" />
        上一页
      </button>
      <span aria-live="polite"><strong>{{ currentPage + 1 }}</strong><i>/</i>{{ pageCount }}</span>
      <div class="document-pagination__actions">
        <button type="button" :disabled="currentPage >= pageCount - 1" @click="goToPage(currentPage + 1)">
          下一页
          <ChevronRight :size="15" />
        </button>
        <slot name="pagination-action" :is-last-page="currentPage >= pageCount - 1" />
      </div>
    </nav>
  </article>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { ChevronLeft, ChevronRight, FileText } from 'lucide-vue-next'
import { renderMarkdown } from '@/shared/lib/markdown'

const props = defineProps({
  title: { type: String, default: '' },
  content: { type: String, default: '' },
  tags: { type: Array, default: () => [] },
  chapterNumber: { type: Number, default: 1 },
  emptyMessage: { type: String, default: '系统会围绕当前节点生成完整讲解。' },
  wide: { type: Boolean, default: false },
  paginate: { type: Boolean, default: false },
  showTitle: { type: Boolean, default: true },
})

const currentPage = ref(0)
const pages = computed(() => props.paginate ? splitDocumentPages(props.content, props.title) : [props.content])
const pageCount = computed(() => Math.max(1, pages.value.length))
const currentPageContent = computed(() => pages.value[currentPage.value] || '')
const renderedContent = computed(() => renderMarkdown(currentPageContent.value))
const estimatedMinutes = computed(() => Math.max(3, Math.ceil(props.content.replace(/\s/g, '').length / 420)))
const pageEstimatedMinutes = computed(() => Math.max(1, Math.ceil(currentPageContent.value.replace(/\s/g, '').length / 420)))

function normalizeHeading(value) {
  return String(value || '').toLowerCase().replace(/[\s·:：、，,。！？!?/\\_\-]+/g, '')
}

function isFenceLine(line) {
  return /^\s*(```|~~~)/.test(line)
}

function splitDocumentPages(source, title) {
  const text = String(source || '').replace(/\r\n?/g, '\n').trim()
  if (!text) return ['']

  const lines = text.split('\n')
  const pages = []
  let current = []
  let inFence = false
  let hasSectionHeading = false
  let seenTopHeading = false

  const pushCurrent = () => {
    const page = current.join('\n').trim()
    if (page) pages.push(page)
    current = []
  }

  lines.forEach((line) => {
    if (isFenceLine(line)) {
      inFence = !inFence
      current.push(line)
      return
    }

    const sectionHeading = !inFence && /^##(?!#)\s+/.test(line)
    if (sectionHeading) {
      hasSectionHeading = true
      pushCurrent()
    }

    // The article header already presents the node title. Drop the first
    // Markdown H1 when it repeats that same title, even if the generator
    // placed a short preamble before it.
    if (!inFence && /^#(?!#)\s+/.test(line) && !seenTopHeading) {
      seenTopHeading = true
      const heading = line.replace(/^#\s+/, '').trim()
      if (normalizeHeading(heading) === normalizeHeading(title)) return
    }
    current.push(line)
  })
  pushCurrent()

  if (!hasSectionHeading || pages.length <= 1) return [pages[0] || text]
  return pages
}

function goToPage(page) {
  const nextPage = Math.min(Math.max(0, page), pageCount.value - 1)
  if (nextPage === currentPage.value) return
  currentPage.value = nextPage
  window.scrollTo({ top: 0, behavior: 'smooth' })
}

watch(() => [props.content, props.title, props.paginate], () => {
  currentPage.value = 0
})
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
.lesson-document--without-title .lesson-document__header { padding-top: 17px; padding-bottom: 15px; }
.lesson-document--without-title .lesson-tags { margin-top: 0; }
.lesson-document--paged .document-page { min-height: clamp(390px, calc(100vh - 350px), 640px); padding-bottom: 36px; }
.lesson-document--paged .document-page :deep(h2:first-child) { margin-top: 0; padding-top: 0; border-top: 0; font-size: 26px; }
.document-pagination { display: flex; align-items: center; justify-content: space-between; gap: 14px; padding: 12px 24px; border-top: 1px solid var(--line); background: #fbfcfa; }
.document-pagination button { display: inline-flex; min-height: 32px; align-items: center; gap: 6px; padding: 0 9px; border: 1px solid var(--line); border-radius: 4px; background: var(--paper); color: var(--ink); font-size: 11px; }
.document-pagination button:hover:not(:disabled) { border-color: #b7c8ad; background: #f1f6eb; color: var(--accent-deep); }
.document-pagination button:focus-visible { outline: 2px solid var(--accent-deep); outline-offset: 2px; }
.document-pagination button:disabled { cursor: not-allowed; opacity: .4; }
.document-pagination > span { display: inline-flex; align-items: center; gap: 6px; color: var(--muted); font-size: 11px; }
.document-pagination > span strong { color: var(--ink); font-size: 14px; }
.document-pagination > span i { font-style: normal; color: #a5aea7; }
.document-pagination__actions { display: inline-flex; align-items: center; gap: 8px; }
.document-pagination__action { border-color: var(--ink) !important; background: var(--ink) !important; color: #fff !important; font-weight: 800; }
.document-pagination__action:hover:not(:disabled) { background: #345447 !important; }
.page-turn-enter-active, .page-turn-leave-active { transition: opacity .16s ease, transform .18s ease; }
.page-turn-enter-from { opacity: 0; transform: translateX(14px); }
.page-turn-leave-to { opacity: 0; transform: translateX(-14px); }
@media (max-width: 680px) {
  .lesson-document__header { padding: 22px 20px; }
  .lesson-document__meta { align-items: flex-start; flex-direction: column; gap: 6px; }
  .markdown-body { padding: 28px 20px 48px; font-size: 14px; }
  .document-pagination { padding: 10px 14px; }
}
</style>
