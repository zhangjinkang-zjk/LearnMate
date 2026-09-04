<template>
  <section class="mindmap-preview surface" aria-label="章节知识结构">
    <header class="mindmap-preview__header">
      <div>
        <p class="eyebrow">结构化复习</p>
        <h2>{{ title || '本章知识结构' }}</h2>
      </div>
      <span class="mindmap-preview__hint">拖动画布查看分支</span>
    </header>
    <div ref="mapEl" class="mindmap-canvas" :class="{ 'is-hidden': errorText }"></div>
    <div v-if="errorText" class="mindmap-fallback">
      <strong>知识结构暂时按文本展示</strong>
      <pre>{{ fallbackText }}</pre>
    </div>
  </section>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import MindElixir from 'mind-elixir'
import 'mind-elixir/style.css'

const props = defineProps({
  content: { type: [String, Object, Array], default: '' },
  title: { type: String, default: '' },
})

const mapEl = ref(null)
const errorText = ref('')
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
  return { nodeData: normalizeNode(root), linkData: {}, direction: MindElixir.RIGHT }
}

async function renderMap() {
  await nextTick()
  if (!mapEl.value) return
  errorText.value = ''
  try {
    if (mind) { mind.destroy(); mind = null }
    mind = new MindElixir({
      el: mapEl.value,
      direction: MindElixir.RIGHT,
      editable: false,
      contextMenu: false,
      toolBar: false,
      keypress: false,
      draggable: true,
      mouseSelectionButton: 0,
      overflowHidden: false,
    })
    mind.init(toMindElixirData(props.content))
    requestAnimationFrame(() => { mind?.scaleFit?.(); mind?.toCenter?.() })
  } catch (error) {
    errorText.value = error?.message || '知识结构渲染失败'
  }
}

watch(() => [props.content, props.title], renderMap, { deep: true })
onMounted(renderMap)
onBeforeUnmount(() => { if (mind) { mind.destroy(); mind = null } })
</script>

<style scoped>
.mindmap-preview { display: grid; min-width: 0; overflow: hidden; border: 1px solid var(--line); border-radius: 7px; background: var(--paper); }
.mindmap-preview__header { display: flex; align-items: center; justify-content: space-between; gap: 14px; padding: 15px 18px; border-bottom: 1px solid var(--line); }
.mindmap-preview__header .eyebrow { margin-bottom: 4px; }
.mindmap-preview__header h2 { margin: 0; color: var(--ink); font-size: 17px; }
.mindmap-preview__hint { color: var(--muted); font-size: 10px; }
.mindmap-canvas { width: 100%; height: clamp(430px, calc(100vh - 310px), 680px); min-height: 430px; background: #f7faf5; }
.mindmap-canvas.is-hidden { display: none; }
.mindmap-preview :deep(.map-container) { background: #f7faf5; }
.mindmap-preview :deep(me-root > me-tpc) { border-radius: 6px; background: var(--accent-deep); color: #fff; font-weight: 800; }
.mindmap-preview :deep(me-tpc) { border: 1px solid #cbdac5; border-radius: 5px; background: #fff; color: var(--ink); box-shadow: 0 6px 18px rgba(30, 55, 38, .1); }
.mindmap-fallback { min-height: 430px; padding: 22px; color: var(--muted); }
.mindmap-fallback strong { color: var(--ink); font-size: 14px; }
.mindmap-fallback pre { max-height: 560px; margin: 14px 0 0; overflow: auto; white-space: pre-wrap; word-break: break-word; font: inherit; line-height: 1.7; }
@media (max-width: 680px) {
  .mindmap-preview__header { align-items: flex-start; flex-direction: column; }
  .mindmap-canvas { min-height: 360px; height: 480px; }
}
</style>
