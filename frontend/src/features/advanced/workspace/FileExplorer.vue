<template>
  <nav class="file-explorer" aria-label="工作区文件">
    <ul class="file-explorer__list">
      <li v-for="node in visibleNodes" :key="node.path">
        <button
          v-if="node.type === 'dir'"
          type="button"
          class="file-row file-row--dir"
          :style="{ paddingLeft: `${8 + node.depth * 13}px` }"
          :aria-expanded="expanded.has(node.path)"
          @click="toggle(node.path)"
        >
          <component :is="expanded.has(node.path) ? ChevronDown : ChevronRight" :size="13" />
          <Folder :size="13" />
          <span>{{ node.name }}</span>
        </button>
        <button
          v-else
          type="button"
          class="file-row"
          :class="{ 'is-active': node.path === activePath }"
          :style="{ paddingLeft: `${8 + node.depth * 13}px` }"
          :aria-current="node.path === activePath ? 'true' : undefined"
          @click="emit('select', node.path)"
        >
          <FileText :size="13" />
          <span>{{ node.name }}</span>
          <span v-if="dirtyPaths.has(node.path)" class="file-row__dirty" title="有未保存的修改">•</span>
        </button>
      </li>
    </ul>
    <p v-if="!entries.length" class="file-explorer__empty">还没有打开任何文件。</p>
  </nav>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { ChevronDown, ChevronRight, FileText, Folder } from 'lucide-vue-next'

const props = defineProps({
  entries: { type: Array, default: () => [] },
  activePath: { type: String, default: '' },
})
const emit = defineEmits(['select'])

const expanded = ref(new Set())
const dirtyPaths = computed(() => new Set(props.entries.filter((entry) => entry.dirty).map((entry) => entry.path)))

// 平铺成一条扁列表再渲染：省掉递归组件，展开状态也只是一组路径字符串，
// 打开新目录时不用重建整棵树。
const tree = computed(() => buildTree(props.entries))
const visibleNodes = computed(() => flatten(tree.value, new Set()))

function buildTree(entries) {
  const root = { type: 'dir', name: '', path: '', children: new Map() }
  for (const entry of entries) {
    const segments = String(entry.path).split('/').filter(Boolean)
    let cursor = root
    segments.forEach((segment, index) => {
      const isFile = index === segments.length - 1
      const path = segments.slice(0, index + 1).join('/')
      if (isFile) {
        cursor.children.set(path, { type: 'file', name: segment, path })
        return
      }
      if (!cursor.children.has(path)) {
        cursor.children.set(path, { type: 'dir', name: segment, path, children: new Map() })
      }
      cursor = cursor.children.get(path)
    })
  }
  return root
}

// 目录排在文件前面，同类按名字排 —— 和任何编辑器一致，不用额外解释
function sortedChildren(map) {
  return Array.from(map.values()).sort((a, b) => {
    if (a.type !== b.type) return a.type === 'dir' ? -1 : 1
    return a.name.localeCompare(b.name, 'zh-CN')
  })
}

function flatten(node, carry) {
  const out = []
  for (const child of sortedChildren(node.children || new Map())) {
    out.push({ ...child, depth: carry.size })
    if (child.type === 'dir' && expanded.value.has(child.path)) {
      out.push(...flatten(child, new Set([...carry, child.path])))
    }
  }
  return out
}

function toggle(path) {
  const next = new Set(expanded.value)
  if (next.has(path)) next.delete(path)
  else next.add(path)
  expanded.value = next
}

// 打开一个新目录时默认展开到一级，否则用户面对的是几个折叠的文件夹名
watch(() => props.entries, (entries) => {
  if (!entries.length || expanded.value.size) return
  const topLevel = new Set()
  for (const entry of entries) {
    const first = String(entry.path).split('/')[0]
    if (first && first !== entry.path) topLevel.add(first)
  }
  expanded.value = topLevel
})
</script>

<style scoped>
.file-explorer { min-height: 0; overflow-y: auto; padding: 6px 0 12px; }
.file-explorer__list { margin: 0; padding: 0; list-style: none; }
.file-row { display: flex; width: 100%; min-width: 0; align-items: center; gap: 6px; padding: 5px 8px; border: 0; background: transparent; color: var(--ink); font-size: 12px; line-height: 1.4; text-align: left; cursor: pointer; }
.file-row > span:not(.file-row__dirty) { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.file-row:hover { background: #f1f6eb; }
.file-row:focus-visible { outline: 2px solid var(--accent-deep); outline-offset: -2px; }
.file-row.is-active { background: #e8f2de; color: var(--accent-deep); font-weight: 700; }
.file-row--dir { color: var(--muted); font-weight: 700; }
.file-row--dir svg:first-child { flex: 0 0 auto; color: #9aa79c; }
.file-row--dir svg:nth-child(2) { flex: 0 0 auto; color: var(--accent-deep); }
.file-row__dirty { flex: 0 0 auto; color: var(--accent-deep); font-size: 15px; line-height: 1; }
.file-explorer__empty { margin: 10px 12px; color: var(--muted); font-size: 11px; line-height: 1.6; }
</style>
