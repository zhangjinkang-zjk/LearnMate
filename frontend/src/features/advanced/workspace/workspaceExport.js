// 工作区导出：把当前工作区整个（或它的某一棵子树）打成一个 .zip 下载下来。
//
// 这里只做两件事：**算清楚包里每一条叫什么、装什么**（`planExport`），然后**压出来**
// （`buildZipBytes`）。读界面状态（busy / notice / 当前打开的文件）是调用方的事 ——
// 这样这一整块能在 node 里直接跑，不用起浏览器（见 frontend/tmp/export-check.mjs）。
//
// 下面三件事都和安全或"看起来对了其实不对"有关，逐个说清楚。

// 带 `.js`：这个模块要能被 `frontend/tmp/export-check.mjs` 直接 import 跑自检，
// 而 node 的 ESM 不认无扩展名（vite 认）。同目录其它文件是无扩展名的，但那些不进 node。
import { downloadBlob, isDirectoryEntry } from './localWorkspace.js'

const DEFAULT_WRAPPER = 'workspace'

// ── 1. `entry.path` 不能盲信（zip-slip）─────────────────────────────
// `createEntry` 会挡 `.` / `..`，但 `renameEntry` 把新名字直接交给 `relocate`，那里只查
// 重名和"放进它自己里"——**改名成 `..` 是能过的**；草稿恢复（`workspaceDraft.fromDraft`）
// 也不校验。带 `../` 的 zip key 是经典的 zip-slip：解压工具会照着写，写到目标目录外面去。
// 所以导出这一侧自己必须挡，不能指望上游永远干净。
const WINDOWS_ILLEGAL = /[\\/:*?"<>|]/g
// Windows 保留设备名。叫 `CON` 的文件在 Windows 上根本建不出来（`CON.txt` 同样不行），
// 所以只要**主名**命中就躲开。
const RESERVED_NAMES = new Set([
  'con', 'prn', 'aux', 'nul',
  'com1', 'com2', 'com3', 'com4', 'com5', 'com6', 'com7', 'com8', 'com9',
  'lpt1', 'lpt2', 'lpt3', 'lpt4', 'lpt5', 'lpt6', 'lpt7', 'lpt8', 'lpt9',
])

// 清洗**单个**路径段。返回空串表示这一段不该存在（`..`、`.`、或者洗完全是空的）。
function sanitizeSegment(segment) {
  const raw = String(segment ?? '').trim()
  if (!raw || raw === '.' || raw === '..') return ''
  let name = raw.replace(WINDOWS_ILLEGAL, '_')
  // Windows 不允许路径段以点或空格结尾（`a.` 和 `a ` 都会被静默改掉，改成什么由系统说了算）
  name = name.replace(/[. ]+$/, '')
  if (!name) return ''
  if (RESERVED_NAMES.has(name.split('.')[0].toLowerCase())) name = `_${name}`
  return name
}

// 清洗一条相对路径，逐段过。任何一段被清掉，整条路径就短一截 —— 这正是我们要的：
// `../../etc/passwd` 会退化成 `etc/passwd`，落在包里面，而不是包外面。
function cleanRelativePath(path) {
  return String(path ?? '')
    .split('/')
    .map(sanitizeSegment)
    .filter(Boolean)
    .join('/')
}

// ── 2. 子树导出要把目标前缀剥掉 ────────────────────────────────────
// 工作区里的 `entry.path` 一律是**相对根**的（`app/routers/orders.py`）。导出 `app` 时
// 若直接拿原路径当 zip key，会得到 `app/app/routers/orders.py` —— 测试能过，包是错的。
//
// 注意**不能**复用 CodeWorkspace 里那个 `isUnder`：空前缀时它算的是
// `path === '' || path.startsWith('/')`，而工作区路径没有前导斜杠，结果是一条都选不中。
// 这里空前缀走 `whole` 分支，不经过这个函数。
function isInside(path, prefix) {
  return path === prefix || path.startsWith(`${prefix}/`)
}

/**
 * 算出这个 zip 里该有哪些条目。纯函数，不改入参。
 *
 * @param {Array} entries    工作区条目（形状见 localWorkspace 的 makeEntry）
 * @param {string} targetPath `''` 表示整个工作区；否则是某个目录的路径
 * @param {string} rootName   工作区根的名字（打开文件夹 / 目录导入时才有）
 * @returns {{ wrapper: string, fileName: string, files: Array<{key: string, text: string, isDirectory: boolean}> }}
 */
export function planExport(entries, targetPath, rootName) {
  const whole = !targetPath
  // 包里**永远套一层同名文件夹**。不套的话把 `fastapi-demo.zip` 解到"下载"目录里，
  // `app/`、`scripts/`、`docs/` 会直接散在下载目录里，和别的东西混在一起。
  const wrapper = (whole
    ? sanitizeSegment(rootName)
    : sanitizeSegment(String(targetPath).split('/').pop())) || DEFAULT_WRAPPER

  const files = []
  const taken = new Set()
  for (const entry of entries) {
    if (!whole && !isInside(entry.path, targetPath)) continue
    // 子树的根目录自己：外层文件夹就是它，不用再套一层
    if (!whole && entry.path === targetPath) continue
    const cleaned = cleanRelativePath(whole ? entry.path : entry.path.slice(targetPath.length + 1))
    if (!cleaned) continue

    // 只有**显式**的目录条目才写目录项。从路径推出来的目录（kind 是 undefined）不写 ——
    // 解压时子文件的路径自然会把它建出来。显式的那些是"没有子文件也仍然存在"的空目录，
    // 不写就真的没了。
    const directory = isDirectoryEntry(entry)
    const key = `${wrapper}/${cleaned}${directory ? '/' : ''}`
    // 清洗之后可能撞名（`a:b.py` 和 `a_b.py` 会洗成同一个），撞了就只留先到的
    if (taken.has(key)) continue
    taken.add(key)
    // 文件正文取 `entry.text` —— 它包含**还没保存的编辑**。导出不是"保存"，但它必须
    // 反映你眼前看到的东西，否则会出现"我明明改了，导出来还是旧的"。
    files.push({ key, text: directory ? '' : String(entry.text ?? ''), isDirectory: directory })
  }
  return { wrapper, fileName: `${wrapper}.zip`, files }
}

// 刻意**不**在这里过一遍 `isSecretFile`：导入侧靠它挡 `.env` / 密钥，但导出侧再挡一次
// 意味着**静默丢文件**。工作区里能看到的文件就是学生自己的东西，丢一个不吭声比导出
// 一个他自己写的 `.env` 更糟。以后别顺手把过滤补上。

const encoder = new TextEncoder()

// 压缩。**用异步版**：同步的 `zipSync` 跑在主线程上不能重绘，`busy` 那颗转圈根本画不
// 出来 —— 界面直接冻住，而 busy 是这个功能唯一的反馈。异步版走 Web Worker，几十毫秒的
// 启动开销在 8MB 面前可以忽略（工作区上限 400 文件 / 8MB）。
export async function buildZipBytes(files) {
  // fflate 用**动态** import（monacoSetup.js 那套约定）：高级学习页在路由里是静态引入的，
  // 静态 import 会把 fflate 塞进主入口 chunk —— 每个连登录页的人都得先下它十几 KB，
  // 而绝大多数人这一次根本不导出。放进函数里就只在真的点导出时取，反正这里本来就是异步的。
  const { zip } = await import('fflate')
  const input = {}
  for (const file of files) input[file.key] = encoder.encode(file.text)
  return new Promise((resolve, reject) => {
    zip(input, { level: 6 }, (error, data) => (error ? reject(error) : resolve(data)))
  })
}

/**
 * 打包并触发下载。返回结果描述，调用方负责把它说给用户听。
 *
 * @returns {Promise<{ok: true, fileName: string, fileCount: number} | {ok: false, reason: string}>}
 */
export async function exportWorkspaceZip(entries, targetPath, rootName) {
  const plan = planExport(entries, targetPath, rootName)
  if (!plan.files.length) return { ok: false, reason: '这里还没有可以导出的文件' }
  const bytes = await buildZipBytes(plan.files)
  downloadBlob(plan.fileName, new Blob([bytes], { type: 'application/zip' }))
  return { ok: true, fileName: plan.fileName, fileCount: plan.files.filter((file) => !file.isDirectory).length }
}
