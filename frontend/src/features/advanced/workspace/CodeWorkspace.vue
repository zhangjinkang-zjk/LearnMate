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
        <button class="button button--quiet" type="button" :disabled="busy" @click="newFile">
          <FileCode2 :size="14" />新建
        </button>
      </div>
      <div class="workspace__group">
        <span v-if="rootName" class="workspace__root" :title="rootName">{{ rootName }}</span>
        <button class="button button--quiet" type="button" :disabled="!activeEntry || busy" @click="saveActive">
          <Download v-if="!canWriteBack" :size="14" /><Save v-else :size="14" />{{ saveLabel }}
        </button>
        <button v-if="entries.length" class="button button--quiet" type="button" :disabled="busy" @click="toggleExplorer">
          <PanelLeft :size="14" />{{ explorerOpen ? '收起文件' : '展开文件' }}
        </button>
      </div>
    </header>

    <p v-if="notice" class="workspace__notice" role="status">{{ notice }}</p>
    <p v-if="errorMessage" class="workspace__notice workspace__notice--error" role="status">{{ errorMessage }}</p>

    <div class="workspace__body" :class="{ 'is-explorer-hidden': !showExplorer }">
      <aside v-if="showExplorer" class="workspace__explorer">
        <FileExplorer :entries="entries" :active-path="activePath" @select="selectPath" />
      </aside>

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
import { computed, ref, onBeforeUnmount } from 'vue'
import { Download, FileCode2, FilePlus2, FolderOpen, PanelLeft, Save } from 'lucide-vue-next'
import CodeEditor from './CodeEditor.vue'
import FileExplorer from './FileExplorer.vue'
import {
  WORKSPACE_MODE,
  createBlankEntry,
  detectWorkspaceMode,
  downloadEntry,
  importFromFileList,
  isReadablePath,
  openDirectoryFromDisk,
  openFilesFromDisk,
  writeEntryToDisk,
} from './localWorkspace'

const mode = ref('')
const rootName = ref('')
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

// 两个概念要分开，混起来会出现「用 Chrome 拖了个文件进来，'打开文件夹' 按钮就改名成
// '选择文件夹'」这种自降能力的现象：
//   - canUseFsa：这台**浏览器**能不能读写磁盘 → 决定"打开文件夹"这个动作怎么走
//   - isFsa   ：**当前这个工作区**是怎么来的 → 决定保存是写回磁盘还是下载
const canUseFsa = computed(() => detectWorkspaceMode() === WORKSPACE_MODE.FSA)
const isFsa = computed(() => mode.value === WORKSPACE_MODE.FSA)
const activeEntry = computed(() => entries.value.find((entry) => entry.path === activePath.value) || null)
// 只有"从本机文件夹里打开、且拿得到句柄"的文件才谈得上写回磁盘；
// 拖进来的、新建的、降级模式打开的，一律走下载。
const canWriteBack = computed(() => isFsa.value && Boolean(activeEntry.value?.handle))
const folderLabel = computed(() => (canUseFsa.value ? '打开文件夹' : '选择文件夹'))
const showExplorer = computed(() => explorerOpen.value && entries.value.length > 0)
const saveLabel = computed(() => (canWriteBack.value ? '保存到本机' : '下载副本'))
const tabs = computed(() => openPaths.value
  .map((path) => entries.value.find((entry) => entry.path === path))
  .filter(Boolean))
const emptyTitle = computed(() => (entries.value.length ? '选一个文件开始' : '打开代码，开始这次实践'))
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
  entries.value = result.entries
  const first = result.entries[0]?.path || ''
  openPaths.value = first ? [first] : []
  activePath.value = first
  errorMessage.value = ''
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
  if (!openPaths.value.includes(path)) openPaths.value = [...openPaths.value, path]
  activePath.value = path
}

function closeTab(path) {
  const next = openPaths.value.filter((item) => item !== path)
  openPaths.value = next
  if (activePath.value === path) activePath.value = next[next.length - 1] || ''
}

function newFile() {
  const taken = new Set(entries.value.map((entry) => entry.path))
  let name = 'untitled.py'
  let index = 2
  while (taken.has(name)) { name = `untitled-${index}.py`; index += 1 }
  entries.value = [...entries.value, createBlankEntry(name)]
  selectPath(name)
  if (!mode.value) mode.value = detectWorkspaceMode()
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

function toggleExplorer() { explorerOpen.value = !explorerOpen.value }

onBeforeUnmount(() => window.clearTimeout(noticeTimer))

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
.workspace { display: flex; min-width: 0; min-height: 0; height: 100%; flex-direction: column; overflow: hidden; border: 1px solid rgba(63, 91, 49, .28); border-radius: 14px; background: var(--paper); box-shadow: 0 8px 24px rgba(45, 40, 92, .07); }
.workspace__bar { display: flex; flex: 0 0 auto; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 10px; padding: 11px 14px; border-bottom: 1px solid var(--line); background: #fbfcfa; }
.workspace__group { display: flex; align-items: center; gap: 7px; }
.workspace__bar .button { gap: 6px; padding: 6px 11px; font-size: 12px; }
.workspace__root { max-width: 190px; overflow: hidden; color: var(--muted); font-size: 11px; text-overflow: ellipsis; white-space: nowrap; }
.workspace__notice { flex: 0 0 auto; margin: 0; padding: 7px 14px; border-bottom: 1px solid var(--line); background: #f4f8ed; color: var(--accent-deep); font-size: 11px; line-height: 1.6; }
.workspace__notice--error { background: #fdf4f0; color: #954e38; }
.workspace__body { display: grid; min-height: 0; flex: 1 1 auto; grid-template-columns: 210px minmax(0, 1fr); }
.workspace__body.is-explorer-hidden { grid-template-columns: minmax(0, 1fr); }
.workspace__explorer { min-height: 0; overflow: hidden; border-right: 1px solid var(--line); background: #fbfcfa; }
.workspace__main { display: grid; min-width: 0; min-height: 0; grid-template-rows: auto minmax(0, 1fr); }
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
  .workspace__body { grid-template-columns: minmax(0, 1fr); }
  .workspace__explorer { display: none; }
}
</style>
