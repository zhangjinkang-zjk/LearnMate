// 打开本机文件的能力分两级，这里把差异吃掉，上层只看见一个 "工作区"。
//
// - `fsa`（Chromium 系）：File System Access API，能真正打开文件夹、编辑、**原地保存回磁盘**。
//   Firefox 和 Safari 拿不到这个能力，而且不是"还没做"——两家官方明确拒绝
//   （Mozilla 立场 harmful、WebKit 立场 oppose），也没有 polyfill 能补。
// - `import`（其余浏览器）：`<input type="file" webkitdirectory>` 或拖拽，**只读**，
//   丢空目录，保存退化成"下载一份副本"。
//
// 所以 UI 上但凡涉及"写回磁盘"的动作，都要按 mode 换名字和后果，不能装作一样。

export const WORKSPACE_MODE = { FSA: 'fsa', IMPORT: 'import' }

export function detectWorkspaceMode() {
  return typeof window !== 'undefined' && typeof window.showDirectoryPicker === 'function'
    ? WORKSPACE_MODE.FSA
    : WORKSPACE_MODE.IMPORT
}

// 上限不是保守，是必需：约 17000 个文件的目录在 Chrome 上实测 10 次只有约 2 次能完整返回
// （GoogleChromeLabs/browser-fs-access#32）。宁可在几千个文件以内稳定，也不要"偶尔打不开"。
export const MAX_FILES = 400
export const MAX_FILE_BYTES = 256 * 1024
export const MAX_TOTAL_BYTES = 8 * 1024 * 1024

// 这些目录里的文件对学习任务没有意义，而且数量能轻易把上面的上限吃光。
const SKIP_DIRECTORIES = new Set([
  'node_modules', '.git', '__pycache__', '.venv', 'venv', 'env',
  'dist', 'build', '.next', '.nuxt', 'target', '.idea', '.pytest_cache', '.mypy_cache',
])

// 只读文本类文件。二进制读进来是乱码，白占额度。
const TEXT_EXTENSIONS = new Set([
  'py', 'js', 'mjs', 'cjs', 'jsx', 'ts', 'tsx', 'vue', 'html', 'htm', 'css', 'scss', 'less',
  'md', 'markdown', 'txt', 'json', 'yaml', 'yml', 'toml', 'ini', 'cfg', 'conf',
  'sh', 'bash', 'zsh', 'bat', 'ps1', 'sql', 'xml', 'csv', 'go', 'rs', 'java', 'c', 'h', 'cpp', 'hpp',
])

// 凭据类文件一律不读进浏览器。用户很可能就是在自己的项目目录里点"打开文件夹"，
// 而这个目录里往往就有 .env —— 读进来等于把 key 放进了前端内存和后续的请求体里。
// 只放行那几个不含密钥的空模板（学员常需要照着改）。
const SAFE_ENV_TEMPLATES = new Set(['.env.example', '.env.sample', '.env.template'])
const SECRET_NAMES = new Set(['id_rsa', 'id_dsa', 'id_ecdsa', 'id_ed25519'])
const SECRET_EXTENSIONS = new Set(['pem', 'key', 'p12', 'pfx', 'keystore'])

export function isSecretFile(name) {
  const lower = String(name || '').toLowerCase()
  if (!lower || SAFE_ENV_TEMPLATES.has(lower)) return false
  if (lower === '.env' || lower.startsWith('.env.')) return true
  if (SECRET_NAMES.has(lower)) return true
  return SECRET_EXTENSIONS.has(lower.includes('.') ? lower.split('.').pop() : '')
}

export function isReadablePath(path) {
  const name = String(path || '').split('/').pop() || ''
  if (!name || isSecretFile(name)) return false
  const extension = name.includes('.') ? name.split('.').pop().toLowerCase() : ''
  return TEXT_EXTENSIONS.has(extension)
}

// 条目有两种：文件，和目录。
// 目录原本不占条目 —— 它只是路径里的层级，靠 `buildTree` 从 `/` 推出来。这套表示法
// 表达不了**空目录**：新建一个空的、或者打开的本机项目里本来就有空目录，都会直接消失。
// 所以显式新建的目录会带 kind，其余从路径推出来的目录仍然不带（它们一定有子文件）。
export const ENTRY_KIND = { FILE: 'file', DIRECTORY: 'directory' }

function makeEntry(path, { kind = ENTRY_KIND.FILE, handle = null, file = null, text = '' } = {}) {
  const name = String(path).split('/').pop() || path
  return { path, name, kind, handle, file, text, dirty: false }
}

export function isDirectoryEntry(entry) {
  return entry?.kind === ENTRY_KIND.DIRECTORY
}

// 把 "tools/search.py" 拆成 [`tools`] 和 `search.py`。空段（连续斜杠、首尾斜杠）丢掉。
export function splitEntryPath(path) {
  const segments = String(path || '').split('/').map((segment) => segment.trim()).filter(Boolean)
  const name = segments.pop() || ''
  return { directories: segments, name }
}

// 从底下的路径集合里挑一个没被占用的名字（新建目录时用）。
export function uniqueEntryPath(takenPaths, base) {
  const taken = new Set(takenPaths)
  if (!taken.has(base)) return base
  let index = 2
  while (taken.has(`${base}-${index}`)) index += 1
  return `${base}-${index}`
}

// ── 在磁盘上新建 ─────────────────────────────────────────────────
// 中间目录会按需建出来（`mkdir -p` 的语义），因为输入 `tools/search.py` 时 `tools`
// 往往还不存在。没有 rootHandle（没打开文件夹、或降级模式）时返回 null —— 调用方
// 据此决定这条只活在本次会话里。

async function resolveDirectory(rootHandle, directories) {
  let cursor = rootHandle
  for (const segment of directories) cursor = await cursor.getDirectoryHandle(segment, { create: true })
  return cursor
}

export async function createDirectoryOnDisk(rootHandle, directories) {
  if (!rootHandle) return null
  return resolveDirectory(rootHandle, directories)
}

export async function createFileOnDisk(rootHandle, directories, name, text = '') {
  if (!rootHandle) return null
  const directory = await resolveDirectory(rootHandle, directories)
  const handle = await directory.getFileHandle(name, { create: true })
  const writable = await handle.createWritable()
  await writable.write(text)
  await writable.close()
  return handle
}

// 找**已经存在**的目录，不做创建。路径不存在时返回 null —— 调用方据此判断
// "这个名字在磁盘上没有"，而不是稀里糊涂建一串空目录出来。
async function findDirectory(rootHandle, directories) {
  let cursor = rootHandle
  for (const segment of directories) {
    try {
      cursor = await cursor.getDirectoryHandle(segment)
    } catch {
      return null
    }
  }
  return cursor
}

async function copyDirectory(source, target) {
  for await (const [name, handle] of source.entries()) {
    if (handle.kind === 'directory') {
      await copyDirectory(handle, await target.getDirectoryHandle(name, { create: true }))
      continue
    }
    const file = await handle.getFile()
    const writable = await (await target.getFileHandle(name, { create: true })).createWritable()
    await writable.write(file)
    await writable.close()
  }
}

// 改名 / 移动一个条目。`from`/`to` 都是相对根的工作区路径。
//
// 文件走 `FileSystemFileHandle.move()`：实机确认它存在，而且是原地原子改名。
// **目录没有这个方法**（`FileSystemDirectoryHandle.move` 实测是 undefined），
// 只能整棵拷到新位置、全部成功之后再删旧的 —— 中途失败时旧目录原封不动，
// 代价是留一份拷了一半的新目录，报错里会说清楚。
export async function moveEntryOnDisk(rootHandle, fromPath, toPath) {
  if (!rootHandle) return false
  const from = splitEntryPath(fromPath)
  const to = splitEntryPath(toPath)
  const fromDir = await findDirectory(rootHandle, from.directories)
  if (!fromDir) return false
  const toDir = await resolveDirectory(rootHandle, to.directories)

  const sourceFile = await fromDir.getFileHandle(from.name).catch(() => null)
  if (sourceFile) {
    await sourceFile.move(toDir, to.name)
    return true
  }
  const sourceDir = await fromDir.getDirectoryHandle(from.name).catch(() => null)
  if (!sourceDir) return false
  const target = await toDir.getDirectoryHandle(to.name, { create: true })
  await copyDirectory(sourceDir, target)
  await fromDir.removeEntry(from.name, { recursive: true })
  return true
}

export async function deleteEntryOnDisk(rootHandle, path) {
  if (!rootHandle) return false
  const { directories, name } = splitEntryPath(path)
  const parent = await findDirectory(rootHandle, directories)
  if (!parent) return false
  // recursive 对文件也安全：没有子项时它就是个普通删除。省得先判断类型再分支 ——
  // 多一个分支就多一条"判断错了会怎样"的路。
  await parent.removeEntry(name, { recursive: true })
  return true
}

// ── FSA 分支：能写回磁盘 ─────────────────────────────────────────

export async function openDirectoryFromDisk() {
  const root = await window.showDirectoryPicker({ mode: 'readwrite' })
  const entries = []
  const budget = { files: 0, bytes: 0, truncated: false }
  // 路径按文件夹**内部**的相对路径存（不带根目录名），这样 FSA 和降级分支的
  // 文件树形状一致，切换来源时树不会整体多/少一层。
  await collectDirectory(root, '', entries, budget)
  // 把根句柄一并带出去：新建目录/文件时要靠它落盘（见 createDirectoryOnDisk）。
  return { mode: WORKSPACE_MODE.FSA, rootName: root.name, rootHandle: root, entries, truncated: budget.truncated }
}

export async function openFilesFromDisk() {
  const handles = await window.showOpenFilePicker({ multiple: true })
  const entries = []
  for (const handle of handles) {
    const file = await handle.getFile()
    if (!isReadablePath(handle.name) || file.size > MAX_FILE_BYTES) continue
    entries.push(makeEntry(handle.name, { handle, file, text: await file.text() }))
  }
  return { mode: WORKSPACE_MODE.FSA, rootName: '', entries, truncated: false }
}

async function collectDirectory(directoryHandle, prefix, entries, budget) {
  for await (const [name, handle] of directoryHandle.entries()) {
    if (budget.files >= MAX_FILES || budget.bytes >= MAX_TOTAL_BYTES) { budget.truncated = true; return }
    const path = prefix ? `${prefix}/${name}` : name
    if (handle.kind === 'directory') {
      if (SKIP_DIRECTORIES.has(name) || name.startsWith('.')) continue
      await collectDirectory(handle, path, entries, budget)
      continue
    }
    if (!isReadablePath(path)) continue
    const file = await handle.getFile()
    if (file.size > MAX_FILE_BYTES) continue
    const text = await file.text()
    budget.files += 1
    budget.bytes += text.length
    entries.push(makeEntry(path, { handle, file, text }))
  }
}

// 原地写回。只有 `fsa` 模式有这一步。
export async function writeEntryToDisk(entry, text) {
  if (!entry?.handle) throw new Error('这个文件不是从本机打开的，无法写回')
  const writable = await entry.handle.createWritable()
  await writable.write(text)
  await writable.close()
}

// ── 降级分支：只读 ───────────────────────────────────────────────

// 同时接住三种来源：`<input webkitdirectory>`、`<input multiple>`、拖拽的 DataTransfer。
// 它们都只是 FileList / File[]，差别在 `webkitRelativePath` 有没有值。
export async function importFromFileList(fileList) {
  const files = Array.from(fileList || [])
  const entries = []
  let bytes = 0
  let truncated = false
  for (const file of files) {
    if (entries.length >= MAX_FILES || bytes >= MAX_TOTAL_BYTES) { truncated = true; break }
    const path = file.webkitRelativePath || file.name
    if (path.split('/').some((segment) => SKIP_DIRECTORIES.has(segment))) continue
    if (!isReadablePath(path) || file.size > MAX_FILE_BYTES) continue
    const text = await file.text()
    bytes += text.length
    entries.push(makeEntry(path, { file, text }))
  }
  const rootName = entries[0]?.path.includes('/') ? entries[0].path.split('/')[0] : ''
  return {
    mode: WORKSPACE_MODE.IMPORT,
    rootName,
    entries: entries.map((entry) => (rootName && entry.path.startsWith(`${rootName}/`)
      ? makeEntry(entry.path.slice(rootName.length + 1), { file: entry.file, text: entry.text })
      : entry)),
    truncated,
  }
}

// 降级模式下的"保存"：下载一份副本，原文件不动。
export function downloadEntry(entry, text) {
  const blob = new Blob([text], { type: 'text/plain;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = entry?.name || 'untitled.txt'
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
  // 立刻 revoke 会让部分浏览器的下载中断，挪到下一轮宏任务
  window.setTimeout(() => URL.revokeObjectURL(url), 0)
}

export function createBlankEntry(path = 'untitled.py', extra = {}) {
  return makeEntry(path, { text: '', ...extra })
}

export function createBlankDirectory(path, extra = {}) {
  return makeEntry(path, { kind: ENTRY_KIND.DIRECTORY, ...extra })
}
