<template>
  <section class="workspace" @dragover.prevent @drop.prevent="onDrop">
    <header class="workspace__bar">
      <div class="workspace__group">
        <button class="button button--quiet" type="button" :disabled="busy" @click="openFolder">
          <FolderOpen :size="14" />{{ folderLabel }}
        </button>
        <button class="button button--quiet" type="button" :disabled="busy" @click="openFiles">
          <FilePlus2 :size="14" />打开文件
        </button>
        <!-- 上次打开过文件夹、句柄还在，但浏览器要求重新授权。权限只能在这个点击里要，
             所以不能自动恢复 —— 少了这个按钮，学生每次进来都得重新找一遍目录。 -->
        <button v-if="pendingFolder" class="button button--quiet" type="button" :disabled="busy" @click="restoreFolder">
          <FolderOpen :size="14" />恢复上次的文件夹{{ pendingFolder.name ? `「${pendingFolder.name}」` : '' }}
        </button>
        <!-- 清空**只清工作区，绝不动磁盘**（理由见 clearWorkspace）。按钮长得和旁边那些
             无害的按钮一样，所以它必须自己把"再点一次"这一步说出来，而不是点下去就执行。 -->
        <button
          class="button button--quiet workspace__clear"
          :class="{ 'is-armed': clearArmed }"
          type="button"
          :disabled="busy || !canClear"
          :title="canClear ? '把这个工作区从页面上清掉（本机文件不会动）' : '工作区已经是空的'"
          @click="armClear"
        >
          <Eraser :size="14" />{{ clearLabel }}
        </button>
      </div>
      <div class="workspace__group">
        <span v-if="rootName" class="workspace__root" :title="rootName">{{ rootName }}</span>
        <button class="button button--quiet" type="button" :disabled="!activeEntry || busy" @click="saveActive">
          <Download v-if="!canWriteBack" :size="14" /><Save v-else :size="14" />{{ saveLabel }}
        </button>
        <button class="button button--quiet" type="button" :disabled="busy" @click="toggleExplorer">
          <PanelLeft :size="14" />{{ explorerOpen ? '收起文件' : '展开文件' }}
        </button>
      </div>
    </header>

    <p v-if="notice" class="workspace__notice" role="status">{{ notice }}</p>
    <p v-if="errorMessage" class="workspace__notice workspace__notice--error" role="status">{{ errorMessage }}</p>

    <div ref="bodyRef" class="workspace__body" :class="{ 'is-explorer-hidden': !showExplorer, 'is-resizing': explorerDragging }" :style="bodyStyle">
      <aside v-if="showExplorer" class="workspace__explorer">
        <FileExplorer
          :entries="entries"
          :active-path="activePath"
          @select="selectPath"
          @create="createEntry"
          @rename="renameEntry"
          @delete="deleteEntry"
          @move="moveEntry"
        />
      </aside>

      <!-- 拖这条改文件面板的宽度。交互和右边那条（对话区）一样：指针捕获、双击复位、
           键盘左右键也能调 —— 只想微调、或者手上是触控板的时候，拖拽是条不好走的路。 -->
      <div
        v-if="showExplorer"
        class="workspace__splitter"
        role="separator"
        aria-orientation="vertical"
        aria-label="拖动调整文件面板的宽度"
        :aria-valuenow="Math.round(explorerWidth)"
        :aria-valuemin="EXPLORER_MIN_WIDTH"
        :aria-valuemax="EXPLORER_MAX_WIDTH"
        tabindex="0"
        @pointerdown="startExplorerDrag"
        @keydown="onExplorerKey"
        @dblclick="resetExplorerWidth"
      >
        <span class="workspace__splitter-grip" aria-hidden="true"></span>
      </div>

      <div class="workspace__main">
        <div v-if="tabs.length" class="workspace__tabs" role="tablist">
          <button
            v-for="tab in tabs"
            :key="tab.path"
            type="button"
            role="tab"
            class="workspace__tab"
            :class="{ 'is-active': tab.path === activePath }"
            :aria-selected="tab.path === activePath"
            @click="selectPath(tab.path)"
          >
            <span>{{ tab.name }}</span>
            <span v-if="tab.dirty" class="workspace__tab-dirty">•</span>
            <span class="workspace__tab-close" role="button" aria-label="关闭" @click.stop="closeTab(tab.path)">×</span>
          </button>
        </div>

        <div v-if="activeEntry" class="workspace__editor">
          <CodeEditor :model-value="activeEntry.text" :path="activeEntry.path" @update:model-value="onEditorInput" @save="saveActive" />
        </div>
        <!-- 这里是空画布的说明，不是第二个工具栏：打开/新建/下副本都只在上面那一条里出现。
             原来这三个按钮在上面的工具栏里各有一份，等于把同一排按钮画了两遍。 -->
        <div v-else class="workspace__empty">
          <FileCode2 :size="22" />
          <h2>{{ emptyTitle }}</h2>
          <p>{{ emptyHint }}</p>
          <p class="workspace__empty-note">也可以把文件或文件夹直接拖到这里。</p>
        </div>
      </div>
    </div>

    <!-- 降级分支的两个入口：全浏览器可用，但只能读。见 localWorkspace.js 开头的说明。 -->
    <input ref="directoryInput" class="workspace__input" type="file" webkitdirectory multiple @change="onDirectoryPicked" />
    <input ref="fileInput" class="workspace__input" type="file" multiple @change="onFilesPicked" />
  </section>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { Download, Eraser, FileCode2, FilePlus2, FolderOpen, PanelLeft, Save } from 'lucide-vue-next'
import CodeEditor from './CodeEditor.vue'
import FileExplorer from './FileExplorer.vue'
import {
  WORKSPACE_MODE,
  createBlankDirectory,
  createBlankEntry,
  createDirectoryOnDisk,
  createFileOnDisk,
  deleteEntryOnDisk,
  detectWorkspaceMode,
  downloadEntry,
  folderPermission,
  importFromFileList,
  isDirectoryEntry,
  isReadablePath,
  moveEntryOnDisk,
  openDirectoryFromDisk,
  openFilesFromDisk,
  readDirectoryFromHandle,
  requestFolderPermission,
  splitEntryPath,
  writeEntryToDisk,
} from './localWorkspace'
import { DESIGN_DOC_PATH, mergeDocSection } from './designDoc'
import { buildWorkspaceSnapshot } from './workspaceSnapshot'
import { fromDraft, toDraft } from './workspaceDraft'
import {
  EXPLORER_DEFAULT_WIDTH,
  EXPLORER_MAX_WIDTH,
  EXPLORER_MIN_WIDTH,
  EXPLORER_STEP,
  EXPLORER_STEP_LARGE,
  EXPLORER_WIDTH_KEY,
  clampExplorerWidth,
} from './workspaceExplorerLayout'
import {
  deleteDraft,
  deleteFolderHandle,
  readDraft,
  readFolderHandle,
  writeDraft,
  writeFolderHandle,
} from '@/shared/storage/workspaceDraftStore'

// 草稿按 (路径, 节点) 存，由页面算好传进来 —— 组件自己不认识路由。
// 页面还没有任务时传空串，这时不存草稿（没地方归属）。
const props = defineProps({
  draftKey: { type: String, default: '' },
})

const mode = ref('')
const rootName = ref('')
// 打开过的本机文件夹句柄。新建目录/文件要靠它落盘 —— 没有它（没打开文件夹、
// 或降级模式）新建的东西只写内存，靠下面的草稿兜住（见 persistDraftNow）。
const rootHandle = ref(null)
// 上次打开过、句柄还在、但**权限要重新问**的文件夹。不为 null 时工具栏上多一个
// 「恢复上次的文件夹」按钮 —— 权限不能在页面加载时自动要（见 localWorkspace）。
const pendingFolder = ref(null)
const entries = ref([])
const openPaths = ref([])
const activePath = ref('')
const busy = ref(false)
const notice = ref('')
const errorMessage = ref('')
const explorerOpen = ref(true)
const directoryInput = ref(null)
const fileInput = ref(null)
let noticeTimer = 0

// ── 文件面板的宽度 ─────────────────────────────────────────────
// 区间和夹取规则在 workspaceExplorerLayout.js（纯函数，单独验；理由也写在那儿）。
const bodyRef = ref(null)
const explorerWidth = ref(readStoredExplorerWidth())
const explorerDragging = ref(false)
let bodyResizeObserver = null

// 两个概念要分开，混起来会出现「用 Chrome 拖了个文件进来，'打开文件夹' 按钮就改名成
// '选择文件夹'」这种自降能力的现象：
//   - canUseFsa：这台**浏览器**能不能读写磁盘 → 决定"打开文件夹"这个动作怎么走
//   - isFsa   ：**当前这个工作区**是怎么来的 → 决定保存是写回磁盘还是下载
const canUseFsa = computed(() => detectWorkspaceMode() === WORKSPACE_MODE.FSA)
const isFsa = computed(() => mode.value === WORKSPACE_MODE.FSA)
// 目录不是能打开的东西 —— 少了这个过滤，点目录会把它塞进标签页并当成空文件渲染。
const activeEntry = computed(() => (
  entries.value.find((entry) => entry.path === activePath.value && !isDirectoryEntry(entry)) || null
))
// 只有"从本机文件夹里打开、且拿得到句柄"的文件才谈得上写回磁盘；
// 拖进来的、新建的、降级模式打开的，一律走下载。
const canWriteBack = computed(() => isFsa.value && Boolean(activeEntry.value?.handle))
const folderLabel = computed(() => (canUseFsa.value ? '打开文件夹' : '选择文件夹'))
// 常驻（可收起）。以前是 entries 为空就整块藏起来，那样空工作区连新建入口都没有 ——
// 而新建入口现在住在资源管理器自己的标题栏里。
const showExplorer = computed(() => explorerOpen.value)
const saveLabel = computed(() => (canWriteBack.value ? '保存到本机' : '下载副本'))
const tabs = computed(() => openPaths.value
  .map((path) => entries.value.find((entry) => entry.path === path))
  .filter(Boolean))
const emptyTitle = computed(() => (entries.value.length ? '选一个文件开始' : '打开代码，开始这次实践'))
// ── 清空工作区 ───────────────────────────────────────────────
// **这个按钮只清工作区，绝不动磁盘 —— 这是它能不能存在的前提。**
// FSA 模式下的文件就是学生**本机上那个真实项目**的文件（`openFolder` 走的是
// `showDirectoryPicker`，句柄能原地写回）。一个叫「清空」的按钮如果顺手调
// `deleteEntryOnDisk`，等于在这一排无害按钮中间放一颗"删掉我的工程"，
// 而它长得和`打开文件`一模一样。真删错了没有回收站、也没有撤销。
//
// 所以这里做的事只有一件：把工作区**忘掉** —— 条目、标签、根句柄、草稿、
// 以及存在 IndexedDB 里的文件夹句柄。磁盘上一个字节都不碰。
// 这件事必须在提示里说出来，不能让学生自己猜"我的文件还在不在"。
const canClear = computed(() => entries.value.length > 0 || Boolean(rootName.value))
const clearLabel = computed(() => (clearArmed.value ? '再点一次' : '清空文件'))

// 二次确认做在按钮自己身上（第一次点变「再点一次」，4 秒没跟手动就自己撤销）。
// **不用 `window.confirm`**：原生弹窗在 iframe / 部分环境下会被直接吃掉（返回值恒为
// false），那样"点了却没反应"比没有确认更糟；也不用 `FileExplorer` 那种行内确认 ——
// 那个是长在右键菜单某一行里的，这里没有"行"可长。
const clearArmed = ref(false)
let clearTimer = 0

function disarmClear() {
  window.clearTimeout(clearTimer)
  clearArmed.value = false
}

function armClear() {
  if (busy.value || !canClear.value) return
  if (clearArmed.value) {
    disarmClear()
    clearWorkspace()
    return
  }
  clearArmed.value = true
  window.clearTimeout(clearTimer)
  clearTimer = window.setTimeout(() => { clearArmed.value = false }, 4000)
}

async function clearWorkspace() {
  const count = entries.value.length
  const hadFolder = Boolean(rootName.value)
  busy.value = true
  try {
    // **存下来的文件夹句柄也要忘掉。** 只清内存的话，下次进页面
    // `restoreFolderIfPermitted` 会把它原样恢复回来（Chrome 的「每次访问都允许」和
    // PWA 安装态直接静默恢复），"清空了"就成了一句空话。
    // 这两个调用自己不会抛（见 `workspaceDraftStore` 开头），所以不需要 try。
    await deleteFolderHandle()
    deleteDraft(props.draftKey)
  } finally {
    // `mode` 也要清：它决定「保存」那颗按钮是写回磁盘还是下载副本，
    // 留着一个已经不存在的来源，下一次打开文件前它会先撒一次谎。
    mode.value = ''
    rootName.value = ''
    rootHandle.value = null
    pendingFolder.value = null
    entries.value = []
    openPaths.value = []
    activePath.value = ''
    errorMessage.value = ''
    busy.value = false
  }
  setNotice(hadFolder
    ? `已清空工作区（${count} 个文件）。本机文件夹里的文件一个都没动，随时可以再打开。`
    : `已清空工作区（${count} 个文件）。`)
}

const emptyHint = computed(() => (canUseFsa.value
  ? '只读取文本类文件，单个不超过 256KB。凭据文件（.env、密钥）不会读进来。'
  : '当前浏览器不支持直接读写本机文件夹（Firefox、Safari 都不支持，也没有替代方案）。这里导入的文件是只读的，保存时会下载一份副本；用 Chrome 或 Edge 打开可以原地保存回磁盘。'))

function setNotice(text) {
  notice.value = text
  window.clearTimeout(noticeTimer)
  noticeTimer = window.setTimeout(() => { notice.value = '' }, 5000)
}

function applyWorkspace(result) {
  mode.value = result.mode
  rootName.value = result.rootName || ''
  // 只有真正打开本机文件夹才拿得到句柄；打开单个文件、拖拽导入都没有根，
  // 此时新建的东西只活在会话里（旧的根句柄必须清掉，否则会往上一次的目录里写）
  rootHandle.value = result.rootHandle || null
  entries.value = result.entries
  const first = result.entries.find((entry) => !isDirectoryEntry(entry))?.path || ''
  openPaths.value = first ? [first] : []
  activePath.value = first
  errorMessage.value = ''
  if (rootHandle.value) {
    // 句柄记下来，下次进页面不用重新选文件夹（权限还得再要一次，见 requestFolderPermission）。
    writeFolderHandle(rootHandle.value)
    pendingFolder.value = null
    // 文件已经真的落在磁盘上了，草稿让位 —— 留一份内存副本只会制造
    // "磁盘是新版、草稿是旧版"的二义性，而两者我们分不出谁该赢。
    deleteDraft(props.draftKey)
  }
  if (result.truncated) {
    setNotice('文件太多，只打开了前一部分。想看完整个工程请把这个文件夹分成更小的目录。')
  } else if (result.entries.length) {
    setNotice(`已打开 ${result.entries.length} 个文件。`)
  } else {
    setNotice('这个位置没有找到可以打开的文本代码文件。')
  }
}

async function openFolder() {
  if (busy.value) return
  if (detectWorkspaceMode() !== WORKSPACE_MODE.FSA) { directoryInput.value?.click(); return }
  busy.value = true
  try {
    applyWorkspace(await openDirectoryFromDisk())
  } catch (error) {
    // 用户点"取消"会抛 AbortError，那不是错误，别弹提示
    if (error?.name !== 'AbortError') errorMessage.value = `打开文件夹失败：${error?.message || error}`
  } finally {
    busy.value = false
  }
}

async function openFiles() {
  if (busy.value) return
  if (detectWorkspaceMode() !== WORKSPACE_MODE.FSA) { fileInput.value?.click(); return }
  busy.value = true
  try {
    applyWorkspace(await openFilesFromDisk())
  } catch (error) {
    if (error?.name !== 'AbortError') errorMessage.value = `打开文件失败：${error?.message || error}`
  } finally {
    busy.value = false
  }
}

async function onDirectoryPicked(event) {
  await importFiles(event.target.files)
  event.target.value = ''
}

async function onFilesPicked(event) {
  await importFiles(event.target.files)
  event.target.value = ''
}

async function onDrop(event) {
  if (busy.value || !event.dataTransfer?.files?.length) return
  const first = event.dataTransfer.files[0]
  // 拖进来的目录在浏览器里拿不到内容（entries 只给空壳），只能明确拒绝，
  // 而不是"打开成功但一个文件也没有"
  if (!isReadablePath(first.webkitRelativePath || first.name)) return
  await importFiles(event.dataTransfer.files)
}

async function importFiles(fileList) {
  busy.value = true
  try {
    applyWorkspace(await importFromFileList(fileList))
  } catch (error) {
    errorMessage.value = `读取文件失败：${error?.message || error}`
  } finally {
    busy.value = false
  }
}

function selectPath(path) {
  if (entries.value.some((entry) => entry.path === path && isDirectoryEntry(entry))) return
  if (!openPaths.value.includes(path)) openPaths.value = [...openPaths.value, path]
  activePath.value = path
}

// ── 重命名 / 删除 / 移动 ─────────────────────────────────────────
// 只有两件事要做：改磁盘，和改内存里的路径。磁盘那步靠 rootHandle 判断 ——
// 没有它（没打开文件夹、或降级模式）就说明这些条目只活在这一屏里，动内存就够了。

function parentPathOf(path) {
  const cut = String(path).lastIndexOf('/')
  return cut === -1 ? '' : path.slice(0, cut)
}

function isUnder(path, prefix) {
  return path === prefix || path.startsWith(`${prefix}/`)
}

function relocatePath(path, from, to) {
  if (path === from) return to
  return path.startsWith(`${from}/`) ? to + path.slice(from.length) : path
}

// 一棵子树搬家：条目、已打开的标签页、当前选中项，三处都得跟着改，漏一个就会出现
// "标签页还在，但编辑器找不到这个文件了"。
function rewritePaths(from, to) {
  entries.value = entries.value.map((entry) => {
    const next = relocatePath(entry.path, from, to)
    return next === entry.path ? entry : { ...entry, path: next, name: next.split('/').pop() || next }
  })
  openPaths.value = openPaths.value.map((path) => relocatePath(path, from, to))
  activePath.value = relocatePath(activePath.value, from, to)
}

async function relocate(from, to, verb) {
  if (from === to) return
  if (isUnder(to, from)) { setNotice(`不能把「${from}」放进它自己里面`); return }
  if (entries.value.some((entry) => entry.path === to)) { setNotice(`已经有 ${to} 了`); return }
  busy.value = true
  try {
    // 磁盘上找不到就照常改内存 —— 可能是只在会话里存在的条目
    if (rootHandle.value) await moveEntryOnDisk(rootHandle.value, from, to)
    rewritePaths(from, to)
    setNotice(rootHandle.value ? `已${verb}为 ${to}` : `已${verb}为 ${to}。当前没有打开本机文件夹，磁盘上的东西没动。`)
  } catch (error) {
    setNotice(`${verb}失败：${error?.message || error}`)
  } finally {
    busy.value = false
  }
}

function renameEntry({ path, name }) {
  const parent = parentPathOf(path)
  return relocate(path, parent ? `${parent}/${name}` : name, '改名')
}

function moveEntry({ from, to }) {
  const name = String(from).split('/').pop()
  return relocate(from, to ? `${to}/${name}` : name, '移动')
}

async function deleteEntry({ path, isDirectory }) {
  const label = isDirectory ? '文件夹' : '文件'
  busy.value = true
  try {
    if (rootHandle.value) await deleteEntryOnDisk(rootHandle.value, path)
    entries.value = entries.value.filter((entry) => !isUnder(entry.path, path))
    openPaths.value = openPaths.value.filter((item) => !isUnder(item, path))
    if (isUnder(activePath.value, path)) activePath.value = openPaths.value[openPaths.value.length - 1] || ''
    setNotice(rootHandle.value
      ? `已从本机删除${label} ${path}`
      : `已移除${label} ${path}（它只在本次会话里，磁盘上没有东西可删）`)
  } catch (error) {
    setNotice(`删除失败：${error?.message || error}`)
  } finally {
    busy.value = false
  }
}

function closeTab(path) {
  const next = openPaths.value.filter((item) => item !== path)
  openPaths.value = next
  if (activePath.value === path) activePath.value = next[next.length - 1] || ''
}

// 输入里的中间目录也补成条目，否则资源管理器里看不到它们 —— 空目录没有别的依据
// 证明自己存在（见 FileExplorer.buildTree）。
function addMissingDirectories(directories) {
  const missing = []
  directories.forEach((_, index) => {
    const path = directories.slice(0, index + 1).join('/')
    if (entries.value.some((entry) => entry.path === path)) return
    if (missing.some((entry) => entry.path === path)) return
    missing.push(createBlankDirectory(path))
  })
  if (missing.length) entries.value = [...entries.value, ...missing]
}

// `parent` 是资源管理器算好的落点（选中的目录，或选中文件所在的目录）。
// 名字里仍允许带 `/`：`tools/search.py` 会在 parent 底下再补出 tools。
async function createEntry({ kind, name, parent }) {
  const { directories, name: leaf } = splitEntryPath(name)
  if (!leaf) return
  if ([...directories, leaf].some((segment) => segment === '.' || segment === '..')) {
    setNotice('名字里不能出现 . 或 ..')
    return
  }
  const segments = parent ? [parent, ...directories] : directories
  const path = [...segments, leaf].join('/')
  if (entries.value.some((entry) => entry.path === path)) {
    setNotice(`已经有 ${path} 了`)
    return
  }
  // 没打开任何来源时也要能新建，否则"先建个目录再放文件"这条路走不通
  if (!mode.value) mode.value = detectWorkspaceMode()
  busy.value = true
  try {
    addMissingDirectories(segments)
    if (kind === 'directory') {
      const handle = await createDirectoryOnDisk(rootHandle.value, [...segments, leaf])
      entries.value = [...entries.value, createBlankDirectory(path, handle ? { handle } : {})]
      // 落没落盘要说清楚：这两者的后果差很远，不能装作一样（见 localWorkspace 开头）
      setNotice(handle
        ? `已在本机新建文件夹 ${path}`
        : `已新建文件夹 ${path}。当前没有打开本机文件夹，它只存在于这次会话里。`)
    } else {
      const handle = await createFileOnDisk(rootHandle.value, segments, leaf)
      entries.value = [...entries.value, createBlankEntry(path, handle ? { handle } : {})]
      selectPath(path)
      setNotice(handle
        ? `已在本机新建 ${path}`
        : `已新建 ${path}。当前没有打开本机文件夹，保存时会下载一份副本。`)
    }
  } catch (error) {
    setNotice(`新建失败：${error?.message || error}`)
  } finally {
    busy.value = false
  }
}

function onEditorInput(value) {
  const entry = activeEntry.value
  if (!entry) return
  entry.text = value
  entry.dirty = true
}

async function saveActive() {
  const entry = activeEntry.value
  if (!entry || busy.value) return
  if (!canWriteBack.value) {
    downloadEntry(entry, entry.text)
    entry.dirty = false
    setNotice(isFsa.value ? '这个文件不在本机文件夹里，已下载一份副本。' : '当前浏览器无法写回本机，已下载一份副本。')
    return
  }
  busy.value = true
  try {
    await writeEntryToDisk(entry, entry.text)
    entry.dirty = false
    setNotice(`已保存回 ${entry.path}`)
  } catch (error) {
    errorMessage.value = `保存失败：${error?.message || error}`
  } finally {
    busy.value = false
  }
}

// ── 教练写方案 ───────────────────────────────────────────────
// 教练谈定一节就写一节（合并规则见 designDoc.js）。**这是这套 IDE 里唯一一个由 AI 发起、
// 直接落到学生文件上的写入**，所以有两件事必须说清：写进了哪个文件、有没有真的落盘。
// 没打开本机文件夹时它只活在这一屏里 —— 和「新建文件」那条路一样如实说，不能装作一样。
// 拿到一份文件的条目；没有就顺带在本机和工作区里都建出来（缺的目录一起补）。
//
// 建文件这件事有两处要用（教练写方案、拉框架文档），抽出来是因为**它错起来是无声的**：
// 差别在 `handle` 有没有拿到 —— 拿到才落盘，没拿到就只活在这一屏里。
async function ensureEntry(path) {
  const existing = entries.value.find((item) => item.path === path && !isDirectoryEntry(item))
  if (existing) return existing
  if (!mode.value) mode.value = detectWorkspaceMode()
  const { directories, name: leaf } = splitEntryPath(path)
  addMissingDirectories(directories)
  const handle = await createFileOnDisk(rootHandle.value, directories, leaf)
  const entry = createBlankEntry(path, handle ? { handle } : {})
  entries.value = [...entries.value, entry]
  return entry
}

// 落盘。返回有没有真的写回本机 —— 没打开文件夹时它只活在这一屏里，调用方要如实说。
async function persistEntry(entry) {
  if (!isFsa.value || !entry.handle) return false
  await writeEntryToDisk(entry, entry.text)
  entry.dirty = false
  return true
}

async function writeDocSection(section, content) {
  const title = String(section || '').trim()
  const body = String(content || '').trim()
  if (!title || !body) return { ok: false, reason: '这一节没有内容' }

  busy.value = true
  try {
    const entry = await ensureEntry(DESIGN_DOC_PATH)
    entry.text = mergeDocSection(entry.text, title, body)
    entry.dirty = true
    selectPath(entry.path)
    const saved = await persistEntry(entry)
    setNotice(saved
      ? `教练把「${title}」写进了 ${DESIGN_DOC_PATH}`
      : `教练把「${title}」写进了 ${DESIGN_DOC_PATH}（没打开本机文件夹，它只存在于这次会话里）`)
    return { ok: true }
  } catch (error) {
    return { ok: false, reason: `${DESIGN_DOC_PATH} 写入失败：${error?.message || error}` }
  } finally {
    busy.value = false
  }
}

// 框架官方文档：一次十几份，写进 docs/框架文档/<框架名>/ 下面。
//
// 抬头写的必须是**抓下来的那一刻**，不是"写文件的那一刻"。服务端有缓存，一页可能是
// 好几天前抓的 —— 两个都写"现在"的话，学生以为手里是刚拉的。
//
// 服务端只给 ISO 8601（UTC），**成句的显示在这里做**：`new Date()` 解析出来就是学生
// 自己的墙上时间；让服务端拼字符串会因时区差一天（见后端 reference_docs.py 的说明）。
// 拿不到时间戳（老数据、异常）才退回"现在"。
//
// **不自动跳到某一份。** 拉文档是教练在对话中途做的，学生可能正看着自己的代码；
// 硬切走他正在读的文件比"没反应"更烦。文件在资源管理器里，他自己会点。
function frameworkDocText(file) {
  const stamp = file.fetched_at ? new Date(file.fetched_at) : new Date()
  const shown = Number.isNaN(stamp.getTime()) ? new Date().toLocaleString() : stamp.toLocaleString()
  const lines = [`# ${file.title}`, '']
  if (file.url) lines.push(`> 来源：${file.url}`)
  lines.push(`> 抓取时间：${shown}`)
  // 服务端说这一页没抓干净时要写在抬头里 —— 不然学生看到一屏 `<span style="...">`
  // 会以为文档本身长这样，或者以为是自己打开的方式不对。
  if (file.note) lines.push(`> ⚠️ ${file.note}`)
  lines.push('', String(file.markdown || '').trim())
  return `${lines.join('\n').replace(/\s+$/, '')}\n`
}

async function writeFrameworkDocs(dir, files) {
  const list = (Array.isArray(files) ? files : []).filter((file) => String(file?.path || '').trim())
  if (!dir || !list.length) return { ok: false, reason: '没有要写的文档' }

  const written = []
  const failed = []
  busy.value = true
  try {
    for (const file of list) {
      const relative = String(file.path).trim()
      try {
        const entry = await ensureEntry(`${dir}/${relative}`)
        entry.text = frameworkDocText(file)
        entry.dirty = true
        await persistEntry(entry)
        written.push(entry.path)
      } catch (error) {
        // 一份写不动不该让剩下十几份都不写 —— 逐份记下来，最后一起说
        failed.push(`${relative}：${error?.message || error}`)
      }
    }
  } finally {
    busy.value = false
  }
  if (written.length) {
    setNotice(`官方文档已放进 ${dir}/（${written.length} 篇）${failed.length ? `，有 ${failed.length} 篇没写成` : ''}`)
  }
  return { ok: written.length > 0, written, failed }
}

function toggleExplorer() { explorerOpen.value = !explorerOpen.value }

function readStoredExplorerWidth() {
  try {
    const raw = window.localStorage.getItem(EXPLORER_WIDTH_KEY)
    return raw === null ? EXPLORER_DEFAULT_WIDTH : clampExplorerWidth(Number(raw))
  } catch {
    // 隐私模式等场景下 localStorage 会直接抛异常，退回默认宽度即可
    return EXPLORER_DEFAULT_WIDTH
  }
}

function persistExplorerWidth() {
  try {
    window.localStorage.setItem(EXPLORER_WIDTH_KEY, String(Math.round(explorerWidth.value)))
  } catch {
    // 存不下只是下次进来回到默认宽度，不影响本次拖动
  }
}

function bodyWidth() {
  return bodyRef.value?.getBoundingClientRect().width || 0
}

// 指针捕获，不挂 window：指针移出拖拽条（甚至移出窗口）事件仍然回到它，组件卸载时
// 监听随之消失。整段拖拽按**容器左边缘**换算宽度，所以中途改窗口大小也不会跑偏。
function startExplorerDrag(event) {
  const container = bodyRef.value
  if (!container || event.button !== 0) return
  const rect = container.getBoundingClientRect()
  if (!rect.width) return
  const handle = event.currentTarget
  explorerDragging.value = true
  handle.setPointerCapture?.(event.pointerId)

  const onMove = (moveEvent) => {
    explorerWidth.value = clampExplorerWidth(moveEvent.clientX - rect.left, rect.width)
  }
  const onEnd = () => {
    explorerDragging.value = false
    handle.releasePointerCapture?.(event.pointerId)
    handle.removeEventListener('pointermove', onMove)
    handle.removeEventListener('pointerup', onEnd)
    handle.removeEventListener('pointercancel', onEnd)
    persistExplorerWidth()
  }

  handle.addEventListener('pointermove', onMove)
  handle.addEventListener('pointerup', onEnd)
  handle.addEventListener('pointercancel', onEnd)
}

function onExplorerKey(event) {
  const step = event.shiftKey ? EXPLORER_STEP_LARGE : EXPLORER_STEP
  if (event.key === 'ArrowLeft') explorerWidth.value = clampExplorerWidth(explorerWidth.value - step, bodyWidth())
  else if (event.key === 'ArrowRight') explorerWidth.value = clampExplorerWidth(explorerWidth.value + step, bodyWidth())
  else if (event.key === 'Home') explorerWidth.value = EXPLORER_DEFAULT_WIDTH
  else return
  event.preventDefault()
  persistExplorerWidth()
}

function resetExplorerWidth() {
  explorerWidth.value = EXPLORER_DEFAULT_WIDTH
  persistExplorerWidth()
}

// 容器变窄时把面板跟着收回来 —— 拖动右边那条分隔条、或者改窗口大小都会改这块的宽度，
// 而面板宽度是像素定死的，不收就会一直吃着编辑器的位置。
function watchBodyWidth() {
  const container = bodyRef.value
  if (!container || typeof ResizeObserver === 'undefined') return
  bodyResizeObserver = new ResizeObserver(() => {
    const next = clampExplorerWidth(explorerWidth.value, container.getBoundingClientRect().width)
    // 只在真的变了才写：observer 回调里改布局，条件写松了容易自己把自己再触发一遍。
    if (next !== explorerWidth.value) explorerWidth.value = next
  })
  bodyResizeObserver.observe(container)
}

const bodyStyle = computed(() => ({ '--explorer-w': `${Math.round(explorerWidth.value)}px` }))

// 给对话教练的工作区快照。**故意做成"发送时拉取"，不是响应式数据**：正文随每次击键
// 变（见 onEditorInput），做成响应式 prop 会让对话组件每敲一个字符就重渲染一次、
// 并且每敲一次都白建一遍快照；而快照只在"按下发送那一刻"有意义。
// 所以这里只暴露一个纯读函数，由页面持有、对话在拼请求时才调它。
//   别"顺手"把它改成响应式数据 —— 那会把这条热路径的开销原样带回来。
function readSnapshot() {
  return buildWorkspaceSnapshot({
    entries: entries.value,
    openPaths: openPaths.value,
    activePath: activePath.value,
    rootName: rootName.value,
  })
}

// 工作区改动过几次。**只回答一个问题**："上次发给教练之后，学生改过没有？"
//
// 它和 readSnapshot 是配套的两件事，别合成一件：快照贵（要排序几百份文件、读正文），
// 所以只在按下发送那一刻取一次；这个计数器便宜（一个整数），可以跟着每次改动走。
// 上面那条注释防的是"为了问一句'教练拿到的是不是最新的'就去建一份快照" —— 有了这个
// 计数器，那个问题就能用 O(1) 回答，不必走那条热路径。
//
// **切标签也算一次改动**：active_path 一变，教练的视角就变了（当前文件在权重里是 +100，
// 而且它单独占快照里那个 40000 字符的额度）。
const revision = ref(0)

defineExpose({ readSnapshot, revision, writeDocSection, writeFrameworkDocs })

// ── 草稿：没打开本机文件夹时，新建的东西不该随组件一起消失 ──────────────
//
// 这块工作区过去只活在组件的 ref 里，而组件会被「重新同步」（loading 把整页
// 换掉）和路由跳转卸载 —— 学生人还在页面上，文件就没了。现在写进 IndexedDB。
//
// **只在没有本机文件夹时存。** 有文件夹时文件本来就落盘了，再存一份只会制造
// "磁盘是新版、草稿是旧版"的二义性（applyWorkspace 里打开文件夹时会清掉草稿）。
// 代价：FSA 模式下"改了一半没保存就切走"仍然会丢 —— 那条路要靠提醒，
// 不靠草稿（beforeunload 已经在拦 dirty 的文件）。

const PERSIST_DEBOUNCE_MS = 800
let persistTimer = 0

function persistDraftNow() {
  window.clearTimeout(persistTimer)
  if (!props.draftKey || rootHandle.value) return
  // 空工作区不存：那等于给每个进来逛一眼的学生都写一条空草稿，
  // 下次进来还会弹一句"已恢复上次的草稿（0 个文件）"。
  if (!entries.value.length) { deleteDraft(props.draftKey); return }
  writeDraft(props.draftKey, toDraft({
    entries: entries.value,
    openPaths: openPaths.value,
    activePath: activePath.value,
    rootName: rootName.value,
  }))
}

function schedulePersistDraft() {
  if (!props.draftKey || rootHandle.value) return
  window.clearTimeout(persistTimer)
  persistTimer = window.setTimeout(persistDraftNow, PERSIST_DEBOUNCE_MS)
}

// 深度侦听而不是在每个改动点手动调用：改动点有七八个（新建/删除/重命名/移动/
// 关标签/切标签/编辑器输入），漏掉任何一个都是"悄悄不保存"，而那是查不出来的。
// 代价是每次击键走一遍遍历 —— 几十个条目、几百 KB，可忽略。
//
// `revision` 挂在这同一个侦听上，而不是另起一个：要数的就是同一批改动点，
// 再养一个深度侦听只是把那次遍历多跑一遍。注意要在 schedulePersistDraft **之前** ——
// 那个函数在 FSA 模式（拿到了真实文件夹句柄）下会直接 return，摆它后面就等于
// 最常用的那种工作区反而数不到。
watch([entries, openPaths, activePath, rootName], () => {
  revision.value += 1
  schedulePersistDraft()
}, { deep: true })

function applyRestoredWorkspace({ rootName: name, entries: rows, openPaths: paths, activePath: active }) {
  mode.value = detectWorkspaceMode()
  rootName.value = name
  // 恢复出来的条目**没有句柄** —— 草稿是纯文本，不连磁盘（见 workspaceDraft 开头）。
  // 所以 canWriteBack 自然为 false，保存会走"下载副本"，按钮文案也会照实说。
  rootHandle.value = null
  entries.value = rows
  openPaths.value = paths
  activePath.value = active
  errorMessage.value = ''
}

async function restoreFolderIfPermitted() {
  const handle = await readFolderHandle()
  if (!handle) return
  const state = await folderPermission(handle)
  if (state === 'granted') {
    // 「每次访问都允许」和 PWA 安装态会走到这里，可以静默恢复。
    // 读整个目录可能要几秒（几百个文件），所以要把 busy 打上 —— 否则这段时间工具栏
    // 看起来是可点的，学生点了「打开文件夹」就会和这次恢复撞在一起。
    busy.value = true
    try {
      await applyRestoredFolder(handle)
    } finally {
      busy.value = false
    }
    return
  }
  if (state === 'prompt') { pendingFolder.value = { handle, name: handle.name || '' }; return }
  // 用户明确拒绝过：别再问，句柄也别留着占地方
  await deleteFolderHandle()
}

async function applyRestoredFolder(handle) {
  try {
    applyWorkspace(await readDirectoryFromHandle(handle))
    return true
  } catch (error) {
    errorMessage.value = `恢复上次的文件夹失败：${error?.message || error}`
    return false
  }
}

// 这个函数**本身**就是那个用户手势 —— requestPermission 只能在这里面调。
async function restoreFolder() {
  const pending = pendingFolder.value
  if (!pending || busy.value) return
  busy.value = true
  try {
    if (!await requestFolderPermission(pending.handle)) {
      setNotice('没有拿到文件夹权限。可以重新点「打开文件夹」再选一次。')
      return
    }
    await applyRestoredFolder(pending.handle)
  } finally {
    busy.value = false
  }
}

async function restoreDraft() {
  if (!props.draftKey) return
  // 文件夹已经恢复成功了就别再叠一份草稿上去 —— 那是两种不同性质的东西
  // （磁盘上的 vs 只在该浏览器里的），混在一起学生会分不清哪个能写回。
  if (entries.value.length || rootHandle.value) return
  const restored = fromDraft(await readDraft(props.draftKey))
  if (!restored) return
  applyRestoredWorkspace(restored)
  setNotice(`已恢复上次没保存的 ${restored.fileCount} 个文件。它们不再连着磁盘，保存时会下载副本。`)
}

onMounted(async () => {
  // 存档里的宽度只按绝对上限卡过，这里拿到真实容器宽度再校一次 —— 上次是在一个
  // 很宽的窗口里拖的，现在窗口小了，那个宽度会直接把编辑器挤没。
  watchBodyWidth()
  await restoreFolderIfPermitted()
  // 恢复文件夹失败时不要再叠一份草稿：那会把 errorMessage 抹掉（applyRestoredWorkspace
  // 会清它），学生就看不到"上次的文件夹没恢复成"这件事，只会发现文件对不上。
  if (errorMessage.value) return
  await restoreDraft()
})

onBeforeUnmount(() => {
  window.clearTimeout(noticeTimer)
  window.clearTimeout(clearTimer)
  bodyResizeObserver?.disconnect()
  bodyResizeObserver = null
  // 卸载前把最后一次改动落盘：定时器可能正好还没到点，而那一次改动就是学生
  // 最后写的那几行。clearTimeout 必须在 persistDraftNow 里面，它自己会清。
  persistDraftNow()
})

// 离开页面前提醒未保存的修改 —— 本机文件被改了一半就切走，用户不会知道白改了
function warnOnLeave(event) {
  if (entries.value.some((entry) => entry.dirty)) event.preventDefault()
  return undefined
}
window.addEventListener('beforeunload', warnOnLeave)
onBeforeUnmount(() => window.removeEventListener('beforeunload', warnOnLeave))
</script>

<style scoped>
/* 竖排用 flex 不用 grid-template-rows: auto auto minmax(0,1fr)：那三行是**按位置**给的，
   而提示条（.workspace__notice）是可选的 —— 它不在时，主体就落到第二行 auto 上，
   第三行留空，编辑器被压成一行高（实测 16px）。flex 只认"谁是剩下的那个"，不受影响。 */
.workspace { position: relative; display: flex; min-width: 0; min-height: 0; height: 100%; flex-direction: column; overflow: hidden; border: 1px solid rgba(63, 91, 49, .28); border-radius: 14px; background: var(--paper); box-shadow: 0 8px 24px rgba(45, 40, 92, .07); }
.workspace__bar { display: flex; flex: 0 0 auto; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 10px; padding: 11px 14px; border-bottom: 1px solid var(--line); background: #fbfcfa; }
.workspace__group { display: flex; align-items: center; gap: 7px; }
.workspace__bar .button { gap: 6px; padding: 6px 11px; font-size: 12px; }

/* 「再点一次」那一档。用仓库里已有的那支警示色（`FileExplorer` 的删除菜单项用的
   就是 #a2452a / #fdf1ec），不新开一个红 —— 全站只有一个"这一步是破坏性的"的表示。 */
.workspace__clear.is-armed { border-color: #e3c3b6; background: #fdf1ec; color: #a2452a; font-weight: 800; }
.workspace__clear.is-armed:hover { border-color: #d3a999; background: #fbe8df; color: #8f3a22; }
.workspace__root { max-width: 190px; overflow: hidden; color: var(--muted); font-size: 11px; text-overflow: ellipsis; white-space: nowrap; }
.workspace__notice { position: absolute; z-index: 8; right: 12px; bottom: 12px; left: 12px; margin: 0; padding: 7px 11px; border: 1px solid #d7e3c9; border-radius: 8px; background: #f4f8ed; box-shadow: 0 10px 24px rgba(31, 49, 40, .12); color: var(--accent-deep); font-size: 11px; line-height: 1.6; pointer-events: none; }
.workspace__notice--error { background: #fdf4f0; color: #954e38; }
.workspace__body { display: grid; min-height: 0; flex: 1 1 auto; grid-template-columns: var(--explorer-w, 210px) 6px minmax(0, 1fr); }
.workspace__body.is-explorer-hidden { grid-template-columns: minmax(0, 1fr); }
/* **`display: flex` 是修滚动的关键，不是装饰。** 这里原来是块级盒子，里面的
   `.file-explorer` 高度按内容长，长过 aside 就被 `overflow: hidden` 直接切掉 ——
   文件一多，列表下半截既够不到、**连滚动条都不出现**。aside 的高度是确定的（它是
   网格项，被行拉伸），换成 flex 之后 `align-items: stretch`（默认值）就把这条确定
   高度交给了 FileExplorer，它内部那层 `overflow-y: auto` 才真正生效。 */
.workspace__explorer { display: flex; min-width: 0; min-height: 0; overflow: hidden; border-right: 1px solid var(--line); background: #fbfcfa; }
.workspace__main { display: grid; min-width: 0; min-height: 0; grid-template-rows: auto minmax(0, 1fr); }
/* 文件面板的拖拽条。和右边那条（对话区）同一种交互，只是更细 —— 它分的是工作区
   内部，不该像分主次内容那样显眼。 */
.workspace__splitter { display: grid; place-items: center; cursor: col-resize; background: transparent; }
.workspace__splitter-grip { width: 2px; height: 100%; border-radius: 99px; background: var(--line); transition: background .15s ease; }
.workspace__splitter:hover .workspace__splitter-grip,
.workspace__splitter:focus-visible .workspace__splitter-grip { background: var(--accent); }
.workspace__body.is-resizing { cursor: col-resize; user-select: none; }
.workspace__body.is-resizing .workspace__splitter-grip { background: var(--accent); }
.workspace__tabs { display: flex; min-width: 0; gap: 2px; overflow-x: auto; border-bottom: 1px solid var(--line); background: #fbfcfa; }
.workspace__tab { display: flex; flex: 0 0 auto; align-items: center; gap: 6px; padding: 7px 9px 7px 12px; border: 0; border-right: 1px solid var(--line); background: transparent; color: var(--muted); font-size: 11px; cursor: pointer; }
.workspace__tab:hover { background: #f1f6eb; }
.workspace__tab.is-active { background: var(--paper); color: var(--ink); font-weight: 700; box-shadow: inset 0 -2px 0 var(--accent-deep); }
.workspace__tab-dirty { color: var(--accent-deep); font-size: 15px; line-height: 1; }
.workspace__tab-close { padding: 0 2px; border-radius: 4px; color: var(--muted); font-size: 14px; line-height: 1; }
.workspace__tab-close:hover { background: #e8efdf; color: var(--accent-deep); }
.workspace__editor { min-width: 0; min-height: 0; }
.workspace__empty { display: grid; place-content: center; justify-items: center; gap: 7px; padding: 24px 26px; color: var(--muted); text-align: center; }
.workspace__empty svg { color: var(--accent-deep); }
.workspace__empty h2 { margin: 2px 0 0; color: var(--ink); font-size: 15px; }
.workspace__empty p { max-width: 460px; margin: 0; font-size: 12px; line-height: 1.75; }
.workspace__empty-note { color: #9aa79c; font-size: 11px; }
.workspace__input { position: absolute; width: 1px; height: 1px; overflow: hidden; clip-path: inset(50%); }
@media (max-width: 1180px) {
  /* 这一档没有地方放文件面板，整块让给编辑器。拖拽条要跟着一起收 —— 面板都 hidden 了，
     还剩一条 6px 的空白列杵在那儿，看着像布局坏了。 */
  .workspace__body { grid-template-columns: minmax(0, 1fr); }
  .workspace__explorer,
  .workspace__splitter { display: none; }
}
</style>
