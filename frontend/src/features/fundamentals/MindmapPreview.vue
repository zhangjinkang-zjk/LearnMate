<template>
  <section ref="previewEl" class="mindmap-preview surface" aria-label="章节知识结构">
    <header class="mindmap-preview__header">
      <div>
        <p class="eyebrow">结构化复习</p>
        <h2>{{ title || '本章知识结构' }}</h2>
      </div>
    </header>
    <div class="mindmap-preview__toolbar" aria-label="知识结构视图控制">
      <button type="button" title="缩小" aria-label="缩小" :disabled="!isMapReady" @click="changeZoom(-0.12)"><ZoomOut :size="18" /></button>
      <button type="button" title="适配画布" aria-label="适配画布" :disabled="!isMapReady" @click="fitMapToViewport"><LocateFixed :size="18" /></button>
      <button type="button" title="放大" aria-label="放大" :disabled="!isMapReady" @click="changeZoom(0.12)"><ZoomIn :size="18" /></button>
      <span class="mindmap-preview__toolbar-divider" aria-hidden="true"></span>
      <button type="button" :title="isFullscreen ? '退出全屏预览' : '全屏预览'" :aria-label="isFullscreen ? '退出全屏预览' : '全屏预览'" @click="toggleFullscreen">
        <Minimize2 v-if="isFullscreen" :size="18" />
        <Maximize2 v-else :size="18" />
      </button>
    </div>
    <div ref="mapEl" class="mindmap-canvas" :class="{ 'is-hidden': errorText }"></div>
    <div v-if="errorText" class="mindmap-fallback">
      <strong>知识结构暂时按文本展示</strong>
      <pre>{{ fallbackText }}</pre>
    </div>
  </section>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { LocateFixed, Maximize2, Minimize2, ZoomIn, ZoomOut } from 'lucide-vue-next'
import MindElixir from 'mind-elixir'
import 'mind-elixir/style.css'

const props = defineProps({
  content: { type: [String, Object, Array], default: '' },
  title: { type: String, default: '' },
})

const mapEl = ref(null)
const previewEl = ref(null)
const errorText = ref('')
const isFullscreen = ref(false)
const isMapReady = ref(false)
let mind = null
let nodeIndex = 0

const fallbackText = computed(() => {
  if (typeof props.content === 'string') return props.content
  try { return JSON.stringify(props.content, null, 2) } catch { return '' }
})

function parseContent(value) {
  if (!value) return { topic: props.title || '知识结构', children: [] }
  if (typeof value === 'object') return value
  const text = String(value).trim()
  try {
    return JSON.parse(text.replace(/^```(?:json|markdown|md)?\s*/i, '').replace(/```$/i, '').trim())
  } catch {
    const lines = text.split(/\r?\n/).map((line) => line.replace(/^[-*\d.\s#]+/, '').trim()).filter(Boolean)
    return { topic: props.title || '知识结构', children: lines.map((topic) => ({ topic, children: [] })) }
  }
}

function normalizeNode(node, parent = null) {
  if (typeof node === 'string') {
    nodeIndex += 1
    return { id: `mind-${nodeIndex}`, topic: node, parent, expanded: true, children: [] }
  }
  const children = Array.isArray(node?.children) ? node.children : Array.isArray(node?.nodes) ? node.nodes : []
  nodeIndex += 1
  const normalized = {
    id: String(node?.id || `mind-${nodeIndex}`),
    topic: String(node?.topic || node?.title || node?.name || node?.label || node?.text || props.title || '知识结构'),
    parent,
    expanded: node?.expanded !== false,
    children: [],
  }
  normalized.children = children.map((child) => normalizeNode(child, normalized.id))
  return normalized
}

function toMindElixirData(value) {
  const parsed = parseContent(value)
  const root = Array.isArray(parsed)
    ? { topic: props.title || '知识结构', children: parsed }
    : parsed?.nodeData || parsed?.root || parsed?.mindmap || parsed?.data || parsed
  nodeIndex = 0
  return { nodeData: normalizeNode(root), linkData: {}, direction: MindElixir.SIDE }
}

function fitMapToViewport() {
  requestAnimationFrame(() => {
    mind?.scaleFit?.()
    mind?.toCenter?.()
  })
}

function changeZoom(amount) {
  if (!mind?.scale) return
  const currentScale = Number(mind.scaleVal) || 1
  mind.scale(Math.min(2.4, Math.max(0.35, currentScale + amount)))
}

async function renderMap() {
  await nextTick()
  if (!mapEl.value) return
  errorText.value = ''
  isMapReady.value = false
  try {
    if (mind) { mind.destroy(); mind = null }
    mind = new MindElixir({
      el: mapEl.value,
      direction: MindElixir.SIDE,
      editable: false,
      contextMenu: false,
      toolBar: false,
      keypress: false,
      draggable: true,
      mouseSelectionButton: 0,
      overflowHidden: false,
    })
    mind.init(toMindElixirData(props.content))
    isMapReady.value = true
    fitMapToViewport()
  } catch (error) {
    isMapReady.value = false
    errorText.value = error?.message || '知识结构渲染失败'
  }
}

watch(() => [props.content, props.title], renderMap, { deep: true })
function syncFullscreenState() {
  isFullscreen.value = document.fullscreenElement === previewEl.value
  fitMapToViewport()
}

async function toggleFullscreen() {
  if (document.fullscreenElement) {
    await document.exitFullscreen()
    return
  }
  await previewEl.value?.requestFullscreen()
}

onMounted(() => {
  document.addEventListener('fullscreenchange', syncFullscreenState)
  void renderMap()
})
onBeforeUnmount(() => {
  document.removeEventListener('fullscreenchange', syncFullscreenState)
  if (mind) { mind.destroy(); mind = null }
})
</script>

<style scoped>
.mindmap-preview { position: relative; display: grid; min-width: 0; overflow: hidden; border: 1px solid var(--line); border-radius: 7px; background: var(--paper); }
.mindmap-preview__header { display: flex; align-items: center; justify-content: space-between; gap: 14px; padding: 15px 18px; border-bottom: 1px solid var(--line); }
.mindmap-preview__header .eyebrow { margin-bottom: 4px; }
.mindmap-preview__header h2 { margin: 0; color: var(--ink); font-size: 17px; }
.mindmap-preview__toolbar { position: absolute; z-index: 5; top: 126px; right: 18px; display: flex; align-items: center; gap: 4px; padding: 5px; border: 1px solid rgba(63, 91, 49, .24); border-radius: 6px; background: rgba(255, 255, 255, .94); box-shadow: 0 8px 20px rgba(30, 55, 38, .14); }.mindmap-preview__toolbar button { display: grid; width: 34px; height: 34px; place-items: center; border: 0; border-radius: 4px; background: transparent; color: var(--ink); }.mindmap-preview__toolbar button:hover:not(:disabled) { background: var(--soft); color: var(--accent-deep); }.mindmap-preview__toolbar button:disabled { cursor: not-allowed; opacity: .42; }.mindmap-preview__toolbar button:focus-visible { outline: 2px solid var(--accent-deep); outline-offset: 2px; }.mindmap-preview__toolbar-divider { width: 1px; height: 22px; margin: 0 2px; background: var(--line); }
.mindmap-canvas { width: 100%; height: clamp(420px, calc(100vh - 320px), 620px); min-height: 420px; background: #f7faf5; }
.mindmap-canvas.is-hidden { display: none; }
.mindmap-preview :deep(.map-container) { background: #f7faf5; }
.mindmap-preview :deep(me-root > me-tpc) { border-radius: 6px; background: var(--accent-deep); color: #fff; font-weight: 800; }
.mindmap-preview :deep(me-tpc) { border: 1px solid #cbdac5; border-radius: 5px; background: #fff; color: var(--ink); box-shadow: 0 6px 18px rgba(30, 55, 38, .1); }
.mindmap-fallback { min-height: 430px; padding: 22px; color: var(--muted); }
.mindmap-fallback strong { color: var(--ink); font-size: 14px; }
.mindmap-fallback pre { max-height: 560px; margin: 14px 0 0; overflow: auto; white-space: pre-wrap; word-break: break-word; font: inherit; line-height: 1.7; }
.mindmap-preview:fullscreen { width: 100vw; height: 100vh; border: 0; border-radius: 0; }.mindmap-preview:fullscreen .mindmap-canvas { height: calc(100vh - 64px); min-height: 0; }
@media (max-width: 680px) {
  .mindmap-preview__header { align-items: flex-start; flex-direction: column; }
  .mindmap-preview__toolbar { top: 112px; right: 12px; }
  .mindmap-canvas { min-height: 390px; height: 500px; }
}
</style>
