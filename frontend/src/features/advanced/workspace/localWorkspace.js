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

function makeEntry(path, { handle = null, file = null, text = '' } = {}) {
  const name = String(path).split('/').pop() || path
  return { path, name, handle, file, text, dirty: false }
}

// ── FSA 分支：能写回磁盘 ─────────────────────────────────────────

export async function openDirectoryFromDisk() {
  const root = await window.showDirectoryPicker({ mode: 'readwrite' })
  const entries = []
  const budget = { files: 0, bytes: 0, truncated: false }
  // 路径按文件夹**内部**的相对路径存（不带根目录名），这样 FSA 和降级分支的
  // 文件树形状一致，切换来源时树不会整体多/少一层。
  await collectDirectory(root, '', entries, budget)
  return { mode: WORKSPACE_MODE.FSA, rootName: root.name, entries, truncated: budget.truncated }
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

export function createBlankEntry(path = 'untitled.py') {
  return makeEntry(path, { text: '' })
}
