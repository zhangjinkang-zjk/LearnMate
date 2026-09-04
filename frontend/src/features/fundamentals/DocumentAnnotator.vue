<template>
  <div class="document-annotator">
    <div v-if="annotatable" class="annotation-toolbar" aria-label="文档标注工具">
      <button type="button" :class="{ active: tool === 'highlight' }" @click="toggleTool('highlight')">
        <Highlighter :size="15" /> 荧光笔
      </button>
      <button type="button" :class="{ active: tool === 'note' }" @click="toggleTool('note')">
        <MessageSquarePlus :size="15" /> 添加笔记
      </button>
      <button type="button" :class="{ active: tool === 'erase' }" @click="toggleTool('erase')">
        <Eraser :size="15" /> 橡皮擦
      </button>
      <div v-if="tool === 'highlight'" class="annotation-colors" aria-label="选择标记颜色">
        <button v-for="color in colors" :key="color.value" type="button" :title="color.label" :class="{ active: activeColor === color.value }" :style="{ background: color.value }" @click="activeColor = color.value"></button>
      </div>
      <span class="annotation-hint">选中文本即可标记</span>
    </div>

    <div ref="bodyRef" class="annotation-body" @mouseup="scheduleSelection" @pointerup="scheduleSelection" @touchend="scheduleSelection" @keyup="scheduleSelection" @click="handleClick">
      <div v-html="decoratedHtml"></div>
    </div>

    <Teleport to="body">
      <div v-if="editor.visible" class="annotation-editor" :style="{ left: `${editor.x}px`, top: `${editor.y}px` }">
        <strong>{{ editor.mode === 'edit' ? '编辑笔记' : '添加笔记' }}</strong>
        <p>{{ editor.selectedText }}</p>
        <textarea v-model.trim="editor.note" rows="3" placeholder="写下这段内容的理解或疑问"></textarea>
        <div class="annotation-editor__actions">
          <button type="button" @click="closeEditor">取消</button>
          <button v-if="editor.mode === 'edit'" type="button" class="danger" @click="removeAnnotation">删除</button>
          <button type="button" class="primary" @click="saveAnnotation">保存</button>
        </div>
      </div>
    </Teleport>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, reactive, ref } from 'vue'
import { Eraser, Highlighter, MessageSquarePlus } from 'lucide-vue-next'

const props = defineProps({
  html: { type: String, default: '' },
  text: { type: String, default: '' },
  annotations: { type: Array, default: () => [] },
  page: { type: Number, default: 0 },
  annotatable: { type: Boolean, default: false },
})

const emit = defineEmits(['create', 'update', 'delete'])
const bodyRef = ref(null)
const tool = ref(props.annotatable ? 'highlight' : '')
const activeColor = ref('#ffe159')
const colors = [
  { value: '#ffe159', label: '黄色' },
  { value: '#b9e77b', label: '绿色' },
  { value: '#8edcff', label: '蓝色' },
  { value: '#ffc1d7', label: '粉色' },
]
const editor = reactive({ visible: false, mode: 'create', id: '', x: 0, y: 0, selectedText: '', note: '', position: null })
let selectionTimer = null
let lastSelectionKey = ''
let lastSelectionAt = 0

const normalized = computed(() => props.annotations
  .map((item) => {
    let position = item?.position
    if (typeof position === 'string') {
      try { position = JSON.parse(position) } catch { position = null }
    }
    return { ...item, id: item.id || item.annotation_id || item.annotationId, position: position || {} }
  })
  .filter((item) => item.position?.kind === 'text' && (item.position.page === undefined || Number(item.position.page) === props.page))
  .filter((item) => Number.isFinite(Number(item.position.start)) && Number.isFinite(Number(item.position.end)))
  .sort((a, b) => Number(a.position.start) - Number(b.position.start)))

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, (char) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[char]))
}

function decorateHtml(html) {
  if (!html || !normalized.value.length || typeof DOMParser === 'undefined') return html
  const doc = new DOMParser().parseFromString(`<body>${html}</body>`, 'text/html')
  const walker = doc.createTreeWalker(doc.body, NodeFilter.SHOW_TEXT)
  const nodes = []
  let offset = 0
  let node
  while ((node = walker.nextNode())) {
    nodes.push({ node, start: offset, end: offset + node.nodeValue.length })
    offset += node.nodeValue.length
  }
  nodes.forEach(({ node: textNode, start: nodeStart, end: nodeEnd }) => {
    const matches = normalized.value.map((annotation) => ({
      annotation,
      start: Math.max(Number(annotation.position.start), nodeStart),
      end: Math.min(Number(annotation.position.end), nodeEnd),
    })).filter((item) => item.end > item.start)
    if (!matches.length || !textNode.parentNode) return
    const value = textNode.nodeValue
    const fragment = doc.createDocumentFragment()
    let cursor = 0
    matches.forEach(({ annotation, start, end }) => {
      const localStart = start - nodeStart
      const localEnd = end - nodeStart
      if (localStart < cursor) return
      if (localStart > cursor) fragment.append(value.slice(cursor, localStart))
      const mark = doc.createElement('mark')
      mark.dataset.annotationId = String(annotation.id || '')
      const color = annotation.position.color || '#ffe159'
      mark.style.background = `linear-gradient(transparent 16%, ${color} 16%, ${color} 88%, transparent 88%)`
      mark.textContent = value.slice(localStart, localEnd)
      fragment.append(mark)
      cursor = localEnd
    })
    if (cursor < value.length) fragment.append(value.slice(cursor))
    textNode.replaceWith(fragment)
  })
  return doc.body.innerHTML
}

const decoratedHtml = computed(() => decorateHtml(props.html))

function toggleTool(nextTool) { tool.value = tool.value === nextTool ? '' : nextTool }
function closeEditor() { editor.visible = false }

function scheduleSelection() {
  if (selectionTimer) window.clearTimeout(selectionTimer)
  selectionTimer = window.setTimeout(handleSelection, 60)
}

function getOffset(root, targetNode, targetOffset) {
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT)
  let offset = 0
  let node
  while ((node = walker.nextNode())) {
    if (node === targetNode) return offset + targetOffset
    offset += node.textContent?.length || 0
  }
  return offset
}

function handleSelection() {
  if (!props.annotatable || !tool.value || !bodyRef.value) return
  const selection = window.getSelection()
  if (!selection || selection.isCollapsed || !selection.rangeCount) return
  const range = selection.getRangeAt(0)
  if (!bodyRef.value.contains(range.commonAncestorContainer)) return
  const selectedText = selection.toString().trim()
  if (!selectedText) return
  const start = getOffset(bodyRef.value, range.startContainer, range.startOffset)
  const end = getOffset(bodyRef.value, range.endContainer, range.endOffset)
  const selectionKey = `${Math.min(start, end)}:${Math.max(start, end)}:${tool.value}`
  if (selectionKey === lastSelectionKey && Date.now() - lastSelectionAt < 350) return
  lastSelectionKey = selectionKey
  lastSelectionAt = Date.now()
  const rect = range.getBoundingClientRect()
  const position = { kind: 'text', page: props.page, start: Math.min(start, end), end: Math.max(start, end), tool: tool.value, color: activeColor.value }
  if (tool.value === 'erase') {
    normalized.value.filter((annotation) => {
      const annotationStart = Number(annotation.position.start)
      const annotationEnd = Number(annotation.position.end)
      return annotationStart < Math.max(start, end) && annotationEnd > Math.min(start, end)
    }).forEach((annotation) => emit('delete', annotation.id))
    selection.removeAllRanges()
    return
  }
  if (tool.value === 'highlight') {
    emit('create', { selected_text: selectedText, note: '', note_text: '', position })
    selection.removeAllRanges()
    return
  }
  Object.assign(editor, { visible: true, mode: 'create', id: '', x: Math.max(12, Math.min(rect.left, window.innerWidth - 332)), y: rect.bottom + 8, selectedText, note: '', position })
}

function handleClick(event) {
  const mark = event.target.closest?.('[data-annotation-id]')
  if (!mark) return
  const annotation = normalized.value.find((item) => String(item.id) === mark.dataset.annotationId)
  if (!annotation) return
  const rect = mark.getBoundingClientRect()
  Object.assign(editor, { visible: true, mode: 'edit', id: annotation.id, x: Math.max(12, Math.min(rect.left, window.innerWidth - 332)), y: rect.bottom + 8, selectedText: annotation.selected_text || annotation.selectedText || '', note: annotation.note_text || annotation.note || '', position: annotation.position })
}

function saveAnnotation() {
  const payload = { selected_text: editor.selectedText, note: editor.note, note_text: editor.note, position: { ...(editor.position || {}), tool: 'note' } }
  if (editor.mode === 'edit') emit('update', editor.id, payload)
  else emit('create', payload)
  closeEditor()
}
function removeAnnotation() { if (editor.id) emit('delete', editor.id); closeEditor() }

onBeforeUnmount(() => {
  if (selectionTimer) window.clearTimeout(selectionTimer)
})
</script>

<style scoped>
.document-annotator { min-width: 0; }
.document-annotator.markdown-body { max-width: 940px; min-height: 0; margin: 0 auto; padding: 0; font-size: inherit; line-height: inherit; overflow: visible; }
.annotation-toolbar { display: flex; min-width: 0; min-height: 36px; align-items: center; gap: 8px; padding: 4px 10px; border-bottom: 1px solid var(--line); flex-wrap: wrap; }
.annotation-toolbar > button { display: inline-flex; flex: 0 0 auto; align-items: center; gap: 5px; min-height: 29px; padding: 0 10px; border: 1px solid var(--line); border-radius: 8px; background: #fff; color: var(--muted); font-size: 10px; font-weight: 800; white-space: nowrap; }
.annotation-toolbar button.active { border-color: #d4e58e; background: #f4f8df; color: #4d6937; }
.annotation-toolbar > button:nth-child(3).active { border-color: #e4c19b; background: #fff5e8; color: #9a6438; }
.annotation-colors { display: inline-flex; flex: 0 0 auto; gap: 5px; margin-left: 3px; }
.annotation-colors button { width: 17px; min-height: 17px; padding: 0; border: 2px solid #fff; border-radius: 50%; box-shadow: 0 0 0 1px var(--line); }
.annotation-colors button.active { box-shadow: 0 0 0 2px #617b4e; }
.annotation-hint { min-width: 0; max-width: 180px; flex: 0 1 auto; margin-left: 5px; color: var(--muted); font-size: 10px; line-height: 1.4; overflow-wrap: anywhere; text-align: left; }
.annotation-body { min-width: 0; max-width: 100%; padding: 38px clamp(24px, 5vw, 50px) 64px; overflow-x: hidden; color: #27312c; font-size: 15px; line-height: 1.9; overflow-wrap: anywhere; }
.annotation-body :deep(mark) { padding: 0 .06em; border-radius: 3px; color: inherit; cursor: pointer; }
.annotation-body :deep(mark[data-annotation-id]) { border-bottom: 2px solid rgba(83, 113, 62, .35); }
.annotation-editor { position: fixed; z-index: 1000; width: min(320px, calc(100vw - 28px)); padding: 14px; border: 1px solid #dce5dc; border-radius: 14px; background: #fff; box-shadow: 0 16px 38px rgba(31, 49, 40, .18); }
.annotation-editor strong { display: block; margin-bottom: 7px; color: #34513c; font-size: 13px; }
.annotation-editor p { max-height: 68px; margin: 0 0 9px; overflow: auto; color: var(--muted); font-size: 11px; line-height: 1.5; }
.annotation-editor textarea { width: 100%; resize: vertical; padding: 9px; border: 1px solid var(--line); border-radius: 9px; outline: none; color: var(--ink); font-size: 12px; }
.annotation-editor textarea:focus { border-color: #9ab66c; box-shadow: 0 0 0 3px rgba(154, 182, 108, .14); }
.annotation-editor__actions { display: flex; justify-content: flex-end; gap: 7px; margin-top: 9px; }
.annotation-editor__actions button { min-height: 30px; padding: 0 10px; border: 1px solid var(--line); border-radius: 8px; background: #fff; color: var(--muted); font-size: 11px; font-weight: 800; }
.annotation-editor__actions .primary { border-color: #b6d837; background: #b6d837; color: #1e3c34; }
.annotation-editor__actions .danger { color: #a45b4d; }
@media (max-width: 760px) { .annotation-toolbar { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); align-items: stretch; }.annotation-toolbar > button { width: 100%; justify-content: center; }.annotation-colors { grid-column: 1 / -1; }.annotation-hint { grid-column: 1 / -1; width: 100%; max-width: none; margin-left: 0; text-align: left; } }
@media (max-width: 420px) { .annotation-toolbar { grid-template-columns: 1fr; }.annotation-toolbar > button, .annotation-colors, .annotation-hint { grid-column: auto; }.annotation-toolbar > button { width: max-content; min-width: 132px; justify-content: flex-start; }.annotation-colors { justify-self: start; }.annotation-hint { width: 100%; } }
</style>
