<template>
  <nav class="file-explorer" aria-label="工作区文件">
    <!-- 新建入口放在资源管理器自己的标题栏里（VS Code 同款），不是在整块工作区的工具栏上。
         而且它建在**当前选中的那个目录**里 —— 选中文件时就是它所在的目录，没选中才是根。 -->
    <div class="file-explorer__head">
      <span class="file-explorer__title">文件</span>
      <div class="file-explorer__head-actions">
        <button type="button" :title="`在 ${createTargetLabel} 中新建文件`" :aria-label="`在 ${createTargetLabel} 中新建文件`" @click="startCreate('file')"><FilePlus2 :size="14" /></button>
        <button type="button" :title="`在 ${createTargetLabel} 中新建文件夹`" :aria-label="`在 ${createTargetLabel} 中新建文件夹`" @click="startCreate('directory')"><FolderPlus :size="14" /></button>
      </div>
    </div>

    <ul
      ref="listEl"
      class="file-explorer__list"
      :class="{ 'is-dropping-root': dropTarget === ROOT_TARGET }"
      @pointerdown="onListPointerDown"
    >
      <li
        v-for="node in visibleNodes"
        :key="node.path"
        class="file-explorer__item"
        :data-path="node.path"
        :class="{
          'is-dragging': dragPath === node.path,
          'is-drop-target': dropTarget === node.path,
        }"
      >
        <!-- 落点必须写成字。缩进能表达层级，表达不了"那个被折叠了、或者根本没注意到的目录"，
             而点目录 = 建在它里面、点文件 = 建在它旁边，规则本身就随行变。不写出来只能靠猜。 -->
        <p v-if="node.pending" class="file-explorer__where">在 {{ createTargetLabel }} 中新建</p>
        <!-- 输入框长在树里、就长在目标目录底下（VS Code 同款），而不是另起一栏。 -->
        <form v-if="node.pending" class="file-row file-row--editing" :style="{ paddingLeft: `${8 + node.depth * 13}px` }" @submit.prevent="confirmCreate()">
          <component :is="node.type === 'dir' ? Folder : FileText" :size="13" />
          <input
            ref="createInput"
            v-model="createDraft"
            class="file-row__input"
            :placeholder="node.type === 'dir' ? '文件夹名' : '文件名'"
            aria-label="新名字"
            @keydown.esc.prevent="cancelCreate()"
            @blur="confirmCreate()"
          />
        </form>

        <form v-else-if="renamingPath === node.path" class="file-row file-row--editing" :style="{ paddingLeft: `${8 + node.depth * 13}px` }" @submit.prevent="confirmRename()">
          <component :is="node.type === 'dir' ? Folder : FileText" :size="13" />
          <input
            ref="renameInput"
            v-model="renameDraft"
            class="file-row__input"
            aria-label="新名字"
            @keydown.esc.prevent="cancelRename()"
            @blur="confirmRename()"
          />
        </form>

        <template v-else>
          <button
            v-if="node.type === 'dir'"
            type="button"
            class="file-row file-row--dir"
            :class="{ 'is-create-target': node.path === createTarget }"
            :style="{ paddingLeft: `${8 + node.depth * 13}px` }"
            :aria-expanded="expanded.has(node.path)"
            :title="node.path"
            @click="toggle(node.path)"
            @contextmenu.prevent="openMenu(node, $event)"
            @keydown.f2.prevent="startRename(node)"
            @keydown.delete.prevent="askDelete(node)"
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
            :title="node.path"
            @click="selectFile(node.path)"
            @contextmenu.prevent="openMenu(node, $event)"
            @keydown.f2.prevent="startRename(node)"
            @keydown.delete.prevent="askDelete(node)"
          >
            <FileText :size="13" />
            <span>{{ node.name }}</span>
            <span v-if="dirtyPaths.has(node.path)" class="file-row__dirty" title="有未保存的修改">•</span>
          </button>

        </template>
      </li>
    </ul>

    <p v-if="!entries.length && !creating" class="file-explorer__empty">还没有文件。用上面的按钮新建，或者拖文件进来。</p>
    <p v-if="dragging" class="file-explorer__hint">{{ dropTarget ? '松手移动到这里' : '拖到某个文件夹上' }}</p>
    <!-- 右键菜单。Teleport 到 body 是必须的：资源管理器是 overflow:hidden、列表还是
         overflow-y:auto，留在里面的话靠边的行弹出来会被直接裁掉一半。 -->
    <Teleport to="body">
      <ul
        v-if="menu"
        ref="menuEl"
        class="file-menu"
        role="menu"
        :style="{ left: `${menu.x}px`, top: `${menu.y}px` }"
      >
        <template v-if="confirmingDelete !== menu.path">
          <template v-if="menu.isDirectory">
            <li><button type="button" role="menuitem" @click="createInMenu('file')">在此新建文件</button></li>
            <li><button type="button" role="menuitem" @click="createInMenu('directory')">在此新建文件夹</button></li>
            <li><button type="button" role="menuitem" @click="exportFromMenu">导出这个文件夹</button></li>
            <li class="file-menu__divider" role="separator"></li>
          </template>
          <li><button type="button" role="menuitem" @click="renameFromMenu">重命名<span class="file-menu__key">F2</span></button></li>
          <li><button type="button" role="menuitem" class="is-danger" @click="confirmingDelete = menu.path">删除<span class="file-menu__key">Del</span></button></li>
        </template>
        <!-- 二次确认走行内，不用 window.confirm：原生弹窗在 iframe / 部分环境下会被
             直接吃掉（返回值恒为 false），那样"点了删除却什么也没发生"。 -->
        <template v-else>
          <li class="file-menu__confirm">删除「{{ menu.name }}」？</li>
          <li class="file-menu__confirm-actions">
            <button type="button" class="is-danger" @click="deleteFromMenu">删除</button>
            <button type="button" @click="confirmingDelete = ''">取消</button>
          </li>
        </template>
      </ul>
    </Teleport>
  </nav>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { ChevronDown, ChevronRight, FilePlus2, FileText, Folder, FolderPlus } from 'lucide-vue-next'
import { ENTRY_KIND } from './localWorkspace'

const props = defineProps({
  entries: { type: Array, default: () => [] },
  activePath: { type: String, default: '' },
})
const emit = defineEmits(['select', 'create', 'rename', 'delete', 'move', 'exportFolder'])

// 拖到列表空白处 = 移到根目录，用这个哨兵值表示（空字符串要留给"没有目标"）
const ROOT_TARGET = '__root__'
const DRAG_THRESHOLD = 5
// 新建输入框那一行占位用的假路径，不会和真实文件重名（真名字里不可能有这种字符）
const PENDING_PATH = '\u0000pending'

const expanded = ref(new Set())
const dirtyPaths = computed(() => new Set(props.entries.filter((entry) => entry.dirty).map((entry) => entry.path)))

const listEl = ref(null)
// 右键菜单。带屏幕坐标（fixed 定位），而不是挂在某一行下面 —— 它要被 Teleport 出去。
const menu = ref(null)
const menuEl = ref(null)
const confirmingDelete = ref('')
// 最后一次点过的行。点目录时它决定"新建到哪儿"，点文件时只是记录。
const focusedPath = ref('')
const renamingPath = ref('')
const renameDraft = ref('')
const renameInput = ref(null)
// { kind: 'file' | 'directory', parent: '' } —— parent 是空串表示建在根目录
const creating = ref(null)
const createDraft = ref('')
const createInput = ref(null)

// 拖动用指针事件而不是 HTML5 dragstart/drop：分隔条那套已经证明可控，而且放置目标
// 是我自己命中的（elementFromPoint），不必依赖浏览器对 draggable 的隐式规则。
const dragPath = ref('')
const dropTarget = ref('')
const dragging = computed(() => Boolean(dragPath.value))
let dragFromY = 0
let pendingPath = ''

// 平铺成一条扁列表再渲染：省掉递归组件，展开状态也只是一组路径字符串，
// 打开新目录时不用重建整棵树。
const tree = computed(() => buildTree(props.entries))

// 新建输入框不是树的节点，是**插进去的一行**：位置就在目标目录的第一个子项那里。
// 找不到目标目录（它被折叠了）就退到列表最前面，至少别让输入框消失。
const visibleNodes = computed(() => {
  const nodes = flatten(tree.value, new Set())
  if (!creating.value) return nodes
  const pendingType = creating.value.kind === 'directory' ? 'dir' : 'file'
  const parent = creating.value.parent
  if (!parent) return [{ type: pendingType, name: '', path: PENDING_PATH, depth: 0, pending: true }, ...nodes]
  const index = nodes.findIndex((node) => node.path === parent)
  if (index === -1) return [{ type: pendingType, name: '', path: PENDING_PATH, depth: 0, pending: true }, ...nodes]
  const next = [...nodes]
  next.splice(index + 1, 0, { type: pendingType, name: '', path: PENDING_PATH, depth: nodes[index].depth + 1, pending: true })
  return next
})

function isDirectoryPath(path) {
  if (!path) return false
  return props.entries.some((entry) => entry.path === path && entry.kind === ENTRY_KIND.DIRECTORY)
    || props.entries.some((entry) => entry.path.startsWith(`${path}/`))
}

function parentOf(path) {
  const cut = String(path || '').lastIndexOf('/')
  return cut === -1 ? '' : path.slice(0, cut)
}

// "新建会落到哪儿"——唯一出处。它同时驱动三件事：落点、目标行的可见标记、
// 标题栏按钮的说明文字。以前这个判断散在 currentDirectory() 里，用户看不见，
// 而且规则随行类型变（点目录=建在它里面，点文件=建在它旁边），只能靠猜。
const createTarget = computed(() => {
  if (focusedPath.value && isDirectoryPath(focusedPath.value)) return focusedPath.value
  if (!props.activePath) return ''
  return isDirectoryPath(props.activePath) ? props.activePath : parentOf(props.activePath)
})
const createTargetLabel = computed(() => (createTarget.value ? `${createTarget.value}/` : '根目录'))

function currentDirectory() {
  return createTarget.value
}

function buildTree(entries) {
  const root = { type: 'dir', name: '', path: '', children: new Map() }
  for (const entry of entries) {
    const segments = String(entry.path).split('/').filter(Boolean)
    // 显式新建的目录自己就是节点，哪怕一个子文件都没有 —— 它不像从路径推出来的
    // 那些目录，没有"因为我下面有文件所以我存在"这层依据。
    const isDirectoryEntry = entry.kind === ENTRY_KIND.DIRECTORY
    let cursor = root
    segments.forEach((segment, index) => {
      const isLeaf = index === segments.length - 1
      const path = segments.slice(0, index + 1).join('/')
      if (isLeaf && !isDirectoryEntry) {
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
  focusedPath.value = path
  const next = new Set(expanded.value)
  if (next.has(path)) next.delete(path)
  else next.add(path)
  expanded.value = next
}

function selectFile(path) {
  focusedPath.value = path
  emit('select', path)
}

function expand(path) {
  if (!path || expanded.value.has(path)) return
  expanded.value = new Set([...expanded.value, path])
}

// 菜单贴着指针弹，但要夹在视口里 —— 贴着右/下边缘的行上右键，菜单会有一半在屏幕外。
//
// **先把菜单渲染出来量一次真实尺寸，再定坐标**，不用写死的估值：菜单项是按行类型增减的
// （目录多三项），写死的高度每加一项就得跟着改一次，改漏了就是"菜单贴底时下面两项点不到"。
// 量不到（还没渲染、或者被 `display:none` 掉）就退回原坐标：宁可贴边，不要看不见。
function openMenu(node, event) {
  menu.value = {
    path: node.path,
    name: node.name,
    isDirectory: node.type === 'dir',
    x: event.clientX,
    y: event.clientY,
  }
  confirmingDelete.value = ''
  nextTick(() => {
    const element = menuEl.value
    if (!element?.offsetWidth || !menu.value) return
    menu.value = {
      ...menu.value,
      x: Math.max(4, Math.min(event.clientX, window.innerWidth - element.offsetWidth - 8)),
      y: Math.max(4, Math.min(event.clientY, window.innerHeight - element.offsetHeight - 8)),
    }
  })
}

function closeMenu() {
  menu.value = null
  confirmingDelete.value = ''
}

// 点菜单外面就收起来。挂在 document 的捕获阶段，这样不管点在树上、编辑器上还是
// 面板外面都能收掉；点在菜单自己里面则放行。
function onDocumentPointerDown(event) {
  if (menuEl.value?.contains(event.target)) return
  closeMenu()
}

watch(menu, (value) => {
  if (value) {
    document.addEventListener('pointerdown', onDocumentPointerDown, true)
    window.addEventListener('keydown', onMenuEscape, true)
  } else {
    document.removeEventListener('pointerdown', onDocumentPointerDown, true)
    window.removeEventListener('keydown', onMenuEscape, true)
  }
})

function onMenuEscape(event) {
  if (event.key === 'Escape') closeMenu()
}

function createInMenu(kind) {
  const parent = menu.value?.path || ''
  closeMenu()
  startCreate(kind, parent)
}

function renameFromMenu() {
  const node = nodeOf(menu.value?.path)
  closeMenu()
  if (node) startRename(node)
}

// 打包这个文件夹（内容由 CodeWorkspace 决定，这里只报"哪个文件夹"）。菜单项只在目录上出现，
// 所以不用再判一次类型 —— 判了也只是把上面 v-if 的规则抄第二遍。
function exportFromMenu() {
  const path = menu.value?.path
  closeMenu()
  if (!path) return
  emit('exportFolder', { path })
}

function deleteFromMenu() {
  const path = menu.value?.path
  const isDirectory = Boolean(menu.value?.isDirectory)
  closeMenu()
  if (!path) return
  emit('delete', { path, isDirectory })
}

// 键盘那条路（F2 / Delete）手上只有路径，得反查节点
function nodeOf(path) {
  return visibleNodes.value.find((node) => node.path === path) || null
}

function askDelete(node) {
  openMenu(node, { clientX: window.innerWidth / 2, clientY: window.innerHeight / 2 })
  confirmingDelete.value = node.path
}

// ── 新建 ────────────────────────────────────────────────────────

function startCreate(kind, parent) {
  closeMenu()
  cancelRename()
  const target = parent === undefined ? currentDirectory() : String(parent || '')
  creating.value = { kind, parent: target }
  createDraft.value = ''
  expand(target)
  // 目标目录的祖先也要展开，否则插进去的那一行在折叠的目录里，等于没显示
  const segments = target.split('/').filter(Boolean)
  segments.slice(0, -1).forEach((_, index) => expand(segments.slice(0, index + 1).join('/')))
  // 滚进视野是必须的：目标目录可能在列表下面，甚至是被折叠后刚展开的，
  // 输入框出现了却在视野外，等于"指向"没传达出去。
  nextTick(() => {
    const input = createInput.value?.[0]
    input?.focus()
    input?.scrollIntoView({ block: 'nearest' })
  })
}

function cancelCreate() {
  creating.value = null
  createDraft.value = ''
}

// blur 和 submit 都会走到这里，所以先清状态再发事件：第二次进来时 creating 已是 null。
function confirmCreate() {
  const pending = creating.value
  const name = createDraft.value.trim()
  if (!pending) return
  cancelCreate()
  if (!name) return
  emit('create', { kind: pending.kind, name, parent: pending.parent })
}

// ── 改名 / 删除 ──────────────────────────────────────────────────

function startRename(node) {
  closeMenu()
  cancelCreate()
  renamingPath.value = node.path
  renameDraft.value = node.name
  nextTick(() => { renameInput.value?.[0]?.focus(); renameInput.value?.[0]?.select() })
}

function cancelRename() {
  renamingPath.value = ''
  renameDraft.value = ''
}

// blur 和 submit 都会走到这里（回车提交后失焦会再来一次），所以先清状态再发事件：
// 第二次进来时 renamingPath 已经是空的，直接返回。
function confirmRename() {
  const path = renamingPath.value
  const name = renameDraft.value.trim()
  if (!path) return
  cancelRename()
  if (!name || name === path.split('/').pop()) return
  emit('rename', { path, name })
}



// ── 拖动 ────────────────────────────────────────────────────────

function pathOfEvent(event) {
  const item = event.target instanceof Element ? event.target.closest('[data-path]') : null
  return item?.dataset?.path || ''
}

function onListPointerDown(event) {
  if (event.button !== 0) return
  // 只排除行内动作（⋯ 按钮、弹出菜单、输入框）。
  // 注意**不能**写成 `closest('button')` —— 文件行自己就是个按钮，那样等于谁都拖不动。
  if (event.target instanceof Element && event.target.closest('input, form')) return
  const path = pathOfEvent(event)
  if (!path || path === PENDING_PATH) return
  pendingPath = path
  dragFromY = event.clientY
  window.addEventListener('pointermove', onPointerMove)
  window.addEventListener('pointerup', onPointerUp)
  window.addEventListener('pointercancel', onPointerUp)
}

function onPointerMove(event) {
  if (!dragPath.value) {
    // 超过阈值才算拖动，否则每次点击都会闪一下"拖动中"
    if (Math.abs(event.clientY - dragFromY) < DRAG_THRESHOLD) return
    dragPath.value = pendingPath
    closeMenu()
  }
  dropTarget.value = resolveDropTarget(event.clientX, event.clientY)
}

function onPointerUp() {
  window.removeEventListener('pointermove', onPointerMove)
  window.removeEventListener('pointerup', onPointerUp)
  window.removeEventListener('pointercancel', onPointerUp)
  const from = dragPath.value
  const to = dropTarget.value
  dragPath.value = ''
  dropTarget.value = ''
  pendingPath = ''
  if (!from || !to) return
  emit('move', { from, to: to === ROOT_TARGET ? '' : to })
}

// 落点由坐标反查，而不是靠 dragover 冒泡：这样"指针在一个文件行上"也能落到它所在的
// 目录里（照 VS Code 的手感），而不是变成"这里不能放"。
function resolveDropTarget(x, y) {
  const el = document.elementFromPoint(x, y)
  if (!el || !listEl.value?.contains(el)) return ''
  const item = el.closest('[data-path]')
  if (!item) return ROOT_TARGET
  const path = item.dataset.path
  const node = visibleNodes.value.find((n) => n.path === path)
  if (!node) return ''
  const target = node.type === 'dir' ? path : (node.path === PENDING_PATH ? '' : parentOf(path))
  return isDescendant(target, dragPath.value) ? '' : target
}

// 不能把目录拖进它自己或它的子孙里 —— 那会把整棵子树从树里摘掉
function isDescendant(candidate, ancestor) {
  if (!ancestor || candidate === undefined) return false
  return candidate === ancestor || candidate.startsWith(`${ancestor}/`)
}

// 当前文件的上层目录一律展开。少了这个，新建 tools/search.py 之后它成了活动标签页，
// 树里却看不见 —— 建出来的东西自己不在树里，用户只能以为没建成。
function revealPath(path) {
  if (!path) return
  const segments = String(path).split('/').filter(Boolean)
  if (segments.length < 2) return
  const next = new Set(expanded.value)
  let changed = false
  segments.slice(0, -1).forEach((_, index) => {
    const dir = segments.slice(0, index + 1).join('/')
    if (next.has(dir)) return
    next.add(dir)
    changed = true
  })
  if (changed) expanded.value = next
}

watch(() => props.activePath, revealPath, { immediate: true })

watch(() => props.entries, (entries) => {
  if (!entries.length || expanded.value.size) return
  const topLevel = new Set()
  for (const entry of entries) {
    const first = String(entry.path).split('/')[0]
    if (first && first !== entry.path) topLevel.add(first)
  }
  expanded.value = topLevel
})

onBeforeUnmount(() => {
  document.removeEventListener('pointerdown', onDocumentPointerDown, true)
  window.removeEventListener('keydown', onMenuEscape, true)
  window.removeEventListener('pointermove', onPointerMove)
  window.removeEventListener('pointerup', onPointerUp)
  window.removeEventListener('pointercancel', onPointerUp)
})
</script>

<style scoped>
/* `flex: 1 1 auto` + `min-width: 0` 是为了**跟着父级给的宽度走**，不是装饰：面板宽度
   现在由外面那条拖拽条决定，这里要是按内容定宽，长路径会把面板撑过它那一列、被父级
   的 overflow: hidden 切掉。高度则由父级的 align-items: stretch 交下来（见
   CodeWorkspace 的 .workspace__explorer）—— 少了那一环，里面这层
   `overflow-y: auto` 永远不会触发，文件一多就既滚不动也够不着。 */
.file-explorer { position: relative; display: flex; min-width: 0; min-height: 0; flex: 1 1 auto; flex-direction: column; overflow: hidden; }
.file-explorer__head { display: flex; flex: 0 0 auto; align-items: center; justify-content: space-between; gap: 8px; padding: 7px 8px 7px 11px; border-bottom: 1px solid var(--line); color: var(--muted); }
.file-explorer__title { font-size: 10px; font-weight: 800; letter-spacing: .12em; text-transform: uppercase; }
.file-explorer__head-actions { display: flex; gap: 2px; }
.file-explorer__head-actions button { display: grid; width: 22px; height: 22px; place-items: center; border: 1px solid transparent; border-radius: 5px; background: transparent; color: var(--muted); }
.file-explorer__head-actions button:hover { border-color: var(--line); background: #fff; color: var(--accent-deep); }
/* 列表自己滚，标题栏不动 */
.file-explorer__list { min-height: 0; flex: 1; margin: 0; padding: 4px 0; overflow-y: auto; list-style: none; }
.file-explorer__item { position: relative; display: flex; align-items: center; }
/* 新建输入框那一行要能显示两行（"在 X 中新建" + 输入框），所以竖排 */
.file-explorer__item:has(.file-explorer__where) { flex-direction: column; align-items: stretch; }
.file-explorer__where { margin: 0; padding: 5px 10px 3px; color: var(--muted); font-size: 10px; line-height: 1.4; }
.file-row { display: flex; min-width: 0; flex: 1; align-items: center; gap: 6px; padding: 5px 8px; border: 0; background: transparent; color: var(--ink); font-size: 12px; line-height: 1.4; text-align: left; cursor: pointer; }
.file-row > span:not(.file-row__dirty) { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.file-row:hover { background: #f1f6eb; }
.file-row:focus-visible { outline: 2px solid var(--accent-deep); outline-offset: -2px; }
.file-row.is-active { background: #e8f2de; color: var(--accent-deep); font-weight: 700; }
/* 新建会落到哪个目录 —— 常驻可见，不是只在新建时才出现。用户点目录只是展开/收起，
   却同时改了落点，不给标记的话"我到底要建在哪儿"只能靠猜。 */
.file-row--dir.is-create-target { box-shadow: inset 2px 0 0 var(--accent-deep); }
.file-row--dir { color: var(--muted); font-weight: 700; }
.file-row--dir svg:first-child { flex: 0 0 auto; color: #9aa79c; }
.file-row--dir svg:nth-child(2) { flex: 0 0 auto; color: var(--accent-deep); }
.file-row__dirty { flex: 0 0 auto; color: var(--accent-deep); font-size: 15px; line-height: 1; }

/* 行内编辑（改名 / 新建）：整行变成一个输入框，位置不动，缩进跟着层级走 */
.file-row--editing { gap: 6px; padding-top: 3px; padding-bottom: 3px; background: #f1f6eb; }
.file-row--editing svg { flex: 0 0 auto; color: var(--accent-deep); }
.file-row__input { min-width: 0; flex: 1; padding: 2px 6px; border: 1px solid var(--accent-deep); border-radius: 6px; background: #fff; color: var(--ink); font-size: 12px; outline: none; }


/* 拖动中的行变淡，落点行整条描边 —— 只靠光标形状的话，落点是哪个目录根本看不出来 */
.file-explorer__item.is-dragging { opacity: .45; }
.file-explorer__item.is-drop-target .file-row { background: #e8f2de; box-shadow: inset 0 0 0 2px var(--accent-deep); }
.file-explorer__list.is-dropping-root { box-shadow: inset 0 0 0 2px var(--accent-deep); }
/* 浮层而不是 sticky：sticky 会占位把行往下挤，更糟的是它盖在指针底下，
   让 elementFromPoint 每次都命中提示条自己 —— 落点判定直接失效（实测踩过）。 */
.file-explorer__hint { position: absolute; right: 8px; bottom: 8px; left: 8px; padding: 5px 9px; border: 1px solid #d7e3c9; border-radius: 6px; background: #f3f8ea; color: var(--accent-deep); font-size: 11px; pointer-events: none; }

/* ── 右键菜单（Teleport 到 body，所以这里是全局坐标） ──────────────
   VS Code 的做法：行上什么都不放，操作全在右键菜单里。行尾挂一个 ⋯ 在 210px 的
   面板里就是纯噪音，而且它是绝对定位的，长文件名会从下面穿过去。 */
.file-menu { position: fixed; z-index: 60; display: grid; width: max-content; min-width: 150px; gap: 2px; margin: 0; padding: 5px; border: 1px solid var(--line); border-radius: 10px; background: var(--paper); box-shadow: 0 16px 34px rgba(31, 49, 40, .18); list-style: none; }
.file-menu button { display: flex; width: 100%; align-items: center; justify-content: space-between; gap: 14px; padding: 6px 9px; border: 0; border-radius: 6px; background: transparent; color: var(--ink); font-size: 12px; text-align: left; }
.file-menu button:hover { background: #f1f6eb; color: var(--accent-deep); }
.file-menu button.is-danger:hover { background: #fdf1ec; color: #a2452a; }
.file-menu__key { color: var(--muted); font-size: 10px; }
.file-menu__divider { height: 1px; margin: 3px 4px; background: var(--line); }
.file-menu__confirm { padding: 5px 9px 2px; color: var(--ink); font-size: 11px; line-height: 1.5; overflow-wrap: anywhere; }
.file-menu__confirm-actions { display: flex; gap: 4px; }
.file-menu__confirm-actions button { justify-content: center; }
.file-menu__confirm-actions .is-danger { color: #a2452a; }
.file-explorer__empty { margin: 10px 12px; color: var(--muted); font-size: 11px; line-height: 1.6; }
</style>
