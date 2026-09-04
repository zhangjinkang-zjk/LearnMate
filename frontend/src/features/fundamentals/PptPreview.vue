<template>
  <section v-if="slides.length" class="ppt-preview surface" aria-label="PPT 辅助材料">
    <article class="ppt-slide">
      <header class="ppt-slide__meta">
        <span>辅助材料 · 第 {{ activeIndex + 1 }} / {{ slides.length }} 页</span>
        <strong>{{ title || '章节要点' }}</strong>
      </header>

      <div class="ppt-slide__stage">
        <p class="ppt-slide__eyebrow">{{ currentSlide.kicker || `学习节点 ${activeIndex + 1}` }}</p>
        <h2>{{ currentSlide.title || title || `第 ${activeIndex + 1} 页` }}</h2>
        <ul v-if="slideLines.length" class="ppt-slide__content">
          <li v-for="(line, index) in slideLines" :key="`${activeIndex}-${index}`">{{ line }}</li>
        </ul>
        <p v-else class="ppt-slide__empty">这一页暂时没有可展示的要点。</p>
      </div>

      <aside v-if="currentSlide.notes" class="ppt-slide__notes">
        <span>讲解提示</span>
        <p>{{ currentSlide.notes }}</p>
      </aside>
    </article>

    <nav class="ppt-controls" aria-label="PPT 翻页">
      <button type="button" :disabled="activeIndex <= 0" @click="goToSlide(activeIndex - 1)">
        <ChevronLeft :size="16" />
        上一页
      </button>
      <div class="ppt-dots" aria-label="选择页面">
        <button
          v-for="(slide, index) in slides"
          :key="slide.index ?? index"
          type="button"
          :class="{ 'is-active': index === activeIndex }"
          :aria-label="`第 ${index + 1} 页`"
          :aria-current="index === activeIndex ? 'page' : undefined"
          @click="goToSlide(index)"
        ></button>
      </div>
      <button type="button" :disabled="activeIndex >= slides.length - 1" @click="goToSlide(activeIndex + 1)">
        下一页
        <ChevronRight :size="16" />
      </button>
    </nav>
  </section>

  <div v-else class="ppt-empty surface">
    <Presentation :size="24" />
    <strong>PPT 辅助材料还没有准备好</strong>
    <p>生成完成后会自动出现在这里，不影响先阅读主讲文档。</p>
  </div>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { ChevronLeft, ChevronRight, Presentation } from 'lucide-vue-next'

const props = defineProps({
  content: { type: [String, Object, Array], default: '' },
  title: { type: String, default: '' },
})

const activeIndex = ref(0)
const slides = computed(() => parseSlides(props.content, props.title))
const currentSlide = computed(() => slides.value[activeIndex.value] || slides.value[0] || {})
const slideLines = computed(() => {
  const value = currentSlide.value.bullets?.length ? currentSlide.value.bullets : currentSlide.value.text
  return String(value || '')
    .split(/\r?\n|[;；]/)
    .map((line) => line.replace(/^[-*•]\s+/, '').trim())
    .filter(Boolean)
})

function parseSlides(content, fallbackTitle) {
  if (!content) return []
  let parsed = content
  if (typeof content === 'string') {
    const text = content.trim()
    if (!text) return []
    try {
      parsed = JSON.parse(text.replace(/^```(?:json|markdown|md)?\s*/i, '').replace(/```$/i, '').trim())
    } catch {
      return parseMarkdownSlides(text, fallbackTitle)
    }
  }

  const list = Array.isArray(parsed)
    ? parsed
    : parsed?.slides || parsed?.pages || parsed?.items || parsed?.data?.slides || []
  if (!Array.isArray(list) || !list.length) {
    if (typeof parsed === 'object') return parseMarkdownSlides(String(parsed?.content || parsed?.markdown || ''), fallbackTitle)
    return []
  }
  return list.map((slide, index) => normalizeSlide(slide, index, fallbackTitle)).filter((slide) => slide.title || slide.text || slide.bullets.length)
}

function parseMarkdownSlides(text, fallbackTitle) {
  if (!text) return []
  const blocks = text
    .replace(/^```(?:json|markdown|md)?\s*/i, '')
    .replace(/```$/i, '')
    .split(/\n\s*---+\s*\n|(?=\n\s*#{1,3}\s+)/)
    .map((block) => block.trim())
    .filter(Boolean)
  return blocks.map((block, index) => {
    const lines = block.split(/\r?\n/).map((line) => line.trim()).filter(Boolean)
    const titleLine = lines.find((line) => /^#{1,3}\s+/.test(line)) || lines[0] || `第 ${index + 1} 页`
    const title = titleLine.replace(/^#{1,3}\s+/, '').replace(/^第?\s*\d+\s*[页章、.：:-]?\s*/, '').trim()
    const body = lines
      .filter((line) => line !== titleLine)
      .map((line) => line.replace(/^[-*•]\s+/, '').trim())
      .filter(Boolean)
    return { index, title: title || fallbackTitle || `第 ${index + 1} 页`, text: body.join('\n'), bullets: [], notes: '' }
  })
}

function normalizeSlide(slide, index, fallbackTitle) {
  if (typeof slide === 'string') return { index, title: `第 ${index + 1} 页`, text: slide, bullets: [], notes: '' }
  const bullets = Array.isArray(slide?.bullets) ? slide.bullets.map((item) => String(item || '').trim()).filter(Boolean) : []
  return {
    index,
    kicker: String(slide?.kicker || slide?.subtitle || '').trim(),
    title: String(slide?.title || slide?.heading || slide?.name || fallbackTitle || '').trim(),
    text: String(slide?.text || slide?.content || slide?.body || '').trim(),
    bullets,
    notes: String(slide?.notes || slide?.speaker_notes || '').trim(),
  }
}

function goToSlide(index) {
  activeIndex.value = Math.min(Math.max(0, index), Math.max(0, slides.value.length - 1))
}

watch(() => props.content, () => { activeIndex.value = 0 }, { deep: true })
</script>

<style scoped>
.ppt-preview { display: grid; gap: 12px; padding: 14px; }
.ppt-slide { display: grid; min-height: clamp(430px, calc(100vh - 270px), 700px); grid-template-rows: auto 1fr auto; overflow: hidden; border: 1px solid var(--line); border-radius: 7px; background: #fbfcfa; }
.ppt-slide__meta { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 14px 18px; border-bottom: 1px solid var(--line); color: var(--muted); font-size: 10px; }
.ppt-slide__meta strong { max-width: 54%; overflow: hidden; color: var(--accent-deep); text-overflow: ellipsis; white-space: nowrap; }
.ppt-slide__stage { display: grid; align-content: center; gap: 18px; width: min(760px, 88%); margin: 0 auto; padding: 34px 0; }
.ppt-slide__eyebrow { margin: 0; color: var(--accent-deep); font-size: 11px; font-weight: 800; letter-spacing: .08em; text-transform: uppercase; }
.ppt-slide h2 { max-width: 720px; margin: 0; color: var(--ink); font-size: clamp(25px, 3vw, 40px); line-height: 1.22; }
.ppt-slide__content { display: grid; gap: 12px; margin: 0; padding: 0; color: #34423a; font-size: clamp(14px, 1.5vw, 18px); line-height: 1.7; list-style: none; }
.ppt-slide__content li { position: relative; padding-left: 18px; }
.ppt-slide__content li::before { position: absolute; top: .72em; left: 0; width: 7px; height: 7px; border-radius: 50%; background: var(--accent); content: ''; }
.ppt-slide__empty { margin: 0; color: var(--muted); }
.ppt-slide__notes { margin: 0 18px 18px; padding: 11px 13px; border-left: 3px solid var(--accent); background: #f1f6eb; color: #415047; font-size: 11px; line-height: 1.6; }
.ppt-slide__notes span { color: var(--accent-deep); font-weight: 800; }
.ppt-slide__notes p { margin: 4px 0 0; }
.ppt-controls { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.ppt-controls > button { display: inline-flex; min-height: 32px; align-items: center; gap: 5px; padding: 0 9px; border: 1px solid var(--line); border-radius: 4px; background: var(--paper); color: var(--ink); font-size: 11px; }
.ppt-controls > button:hover:not(:disabled) { border-color: #b7c8ad; background: #f1f6eb; color: var(--accent-deep); }
.ppt-controls > button:disabled { cursor: not-allowed; opacity: .4; }
.ppt-dots { display: flex; min-width: 0; flex: 1; justify-content: center; flex-wrap: wrap; gap: 6px; }
.ppt-dots button { width: 8px; height: 8px; padding: 0; border: 0; border-radius: 50%; background: #cbd6ca; }
.ppt-dots button.is-active { background: var(--accent-deep); }
.ppt-empty { display: grid; min-height: clamp(430px, calc(100vh - 270px), 700px); place-items: center; align-content: center; gap: 9px; padding: 32px; color: var(--muted); text-align: center; }
.ppt-empty strong { color: var(--ink); font-size: 15px; }
.ppt-empty p { max-width: 340px; margin: 0; font-size: 11px; line-height: 1.6; }
@media (max-width: 680px) {
  .ppt-preview { padding: 8px; }
  .ppt-slide__stage { width: auto; padding: 28px 20px; }
  .ppt-slide__meta { align-items: flex-start; flex-direction: column; gap: 5px; }
  .ppt-slide__meta strong { max-width: 100%; }
  .ppt-slide__notes { margin: 0 20px 20px; }
}
</style>
