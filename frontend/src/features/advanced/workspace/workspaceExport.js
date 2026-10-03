// 工作区导出：把条目打包成一个 zip 下载。除了最后那一次 `downloadBlob`，这里全是纯函数，
// 所以这个模块能直接丢进 node 跑自检（仓库外有脚本，见 README 之外的说明）。
//
// 三件事必须说清楚：
//
// 1. 导出的是**工作区里的内容**，不是磁盘上的目录树。FSA 模式下学生可能改了一堆还没保存，
//    那些编辑就在 `entry.text` 里 —— 去读磁盘会把他刚写的东西悄悄丢掉。反过来，只读模式
//    （拖进来、`webkitdirectory` 导入）本来就只有这一份，两边一致。
// 2. 目录结构要保住，**包括空目录**（显式新建的目录带 kind，见 localWorkspace）。
// 3. 落进 zip 的键必须是清洗过的相对路径。`..`、绝对路径、盘符这些东西一旦进了归档，
//    解压时能写到目标目录之外 —— 清洗规则见 `sanitizeSegment`。
//
// 带 `.js` 扩展名：node 的 ESM 不认无扩展名（vite 认），而这个模块要能被仓库外的脚本
// 直接 import 跑自检。同目录其它文件没有扩展名，但它们不进 node。

import { downloadBlob, isDirectoryEntry } from './localWorkspace.js'

// 拿不到根目录名时（拖拽导入、只打开了几个文件）的兜底顶层文件夹名
const DEFAULT_WRAPPER = 'workspace'

// Windows 上不允许出现在文件名里的字符。浏览器下载的 zip 大多最后是在 Windows 上解开的，
// 一个 `:` 会让资源管理器解不出、或者把名字截断 —— 那是"下载成功了但里面不对劲"。
const WINDOWS_ILLEGAL = /[\\/:*?"<>|]/g

// Windows 的保留设备名。判断按**第一段**（`con.txt` 也中招），这是 Windows 自己的规则。
// 用 `_` 前缀让开，而不是把名字丢掉 —— 名字还在，学生认得出是哪个文件。
const RESERVED_NAMES = new Set([
  'con', 'prn', 'aux', 'nul',
  'com1', 'com2', 'com3', 'com4', 'com5', 'com6', 'com7', 'com8', 'com9',
  'lpt1', 'lpt2', 'lpt3', 'lpt4', 'lpt5', 'lpt6', 'lpt7', 'lpt8', 'lpt9',
])

// 清洗一段路径。返回空串表示这一段不能要（`.`、`..`、或者清洗完变成空的）。
function sanitizeSegment(raw) {
  let name = String(raw ?? '').trim()
  if (!name || name === '.' || name === '..') return ''
  name = name.replace(WINDOWS_ILLEGAL, '_')
  // Windows 会吞掉结尾的点和空格：那边 `a.` 和 `a` 是同一个名字。归档里留着 `a.` 不会报错，
  // 而是解出来静默变成 `a` —— 于是和另一个真叫 `a` 的文件撞在一起，谁覆盖谁看解压顺序。
  name = name.replace(/[. ]+$/, '')
  // 上面那步可能把整段削空（`...` → ``），也可能削成 `.` / `..`，都得再判一次
  if (!name || name === '.' || name === '..') return ''
  const stem = name.split('.')[0].toLowerCase()
  return RESERVED_NAMES.has(stem) ? `_${name}` : name
}

// 一条相对路径，逐段清洗。空段直接丢掉 —— 它没有信息，留着只会变成 `//`。
export function cleanRelativePath(path) {
  return String(path ?? '')
    .split('/')
    .map(sanitizeSegment)
    .filter(Boolean)
    .join('/')
}

// 这个工作区路径是不是在 `prefix` 底下。**不复用 `CodeWorkspace` 里那个 `isUnder`**：
// 那里允许空前缀表示"整棵工作区"，而它的写法（`path === prefix || path.startsWith(...)`）
// 对空串会退化成 `path === '' || path.startsWith('/')`，任何真实路径都不成立 ——
// 拿它判"空前缀"会一条都匹配不上。这里把"空 = 全都算"写成显式分支。
function isInside(path, prefix) {
  if (!prefix) return true
  return path === prefix || path.startsWith(`${prefix}/`)
}

/**
 * 算出要写进 zip 的东西。**不压缩、不下载**，纯计算 —— 这样能被直接断言。
 *
 * @param {Array}  entries     工作区条目
 * @param {string} targetPath  空串 = 整个工作区；否则是某个文件夹（资源管理器右键那个）
 * @param {string} rootName    工作区根目录名，用作 zip 里的顶层文件夹
 * @returns {{ wrapper: string, fileName: string, files: Array<{key: string, text: string, isDirectory: boolean}> }}
 */
export function planExport(entries, targetPath, rootName) {
  const root = cleanRelativePath(targetPath)
  // 顶层文件夹名：导出某个文件夹时用**那个文件夹自己的名字**，不是工作区根名。
  // 否则右键 `tools` 导出会得到一个叫 `myproject.zip`、里面却没有 `tools` 这一层的包，
  // 解出来和他的其它东西混在一起。
  const wrapper = sanitizeSegment(root ? root.split('/').pop() : rootName) || DEFAULT_WRAPPER

  const files = []
  const seen = new Set()
  for (const entry of entries) {
    const path = String(entry?.path ?? '')
    if (!isInside(path, root)) continue
    // `path === root` 时这里得到空串，于是被一起丢掉 —— 被导出的那个文件夹自己的条目不用
    // 单列成一条，它就是顶层文件夹本身（wrapper），由底下那些路径带出来。
    const relative = cleanRelativePath(root ? path.slice(root.length + 1) : path)
    if (!relative) continue
    const key = `${wrapper}/${relative}`
    // 清洗会让不同的原名撞到一起（`a:b` 和 `a?b` 都是 `a_b`）。先到先得、后面的丢掉：
    // 写成覆盖等于静默少一个文件，而这里是唯一一处能发现它的地方。
    if (seen.has(key)) continue
    seen.add(key)
    files.push({
      key,
      // **用 entry.text**，不是去读文件：那是编辑器里的当前内容，含还没保存到磁盘的修改
      text: String(entry?.text ?? ''),
      isDirectory: isDirectoryEntry(entry),
    })
  }
  return { wrapper, fileName: `${wrapper}.zip`, files }
}

const encoder = new TextEncoder()

/**
 * 打包成 zip 字节。
 *
 * fflate 走**动态** import（和 monacoSetup.js 同一套约定）：高级学习页在路由里是静态引入的，
 * 静态 import 会把 fflate 拖进主入口 chunk，而这个功能大多数人一次都不会用。
 */
export async function buildZipBytes(files) {
  const { zip } = await import('fflate')
  const input = {}
  for (const file of files) {
    // 目录的键必须以 `/` 结尾才会被写成目录项。少了它，空目录会变成一个 0 字节的**文件**，
    // 解压出来是个叫 `tools/sub` 的怪东西 —— 名字看着对，双击却打不开。
    input[file.isDirectory ? `${file.key}/` : file.key] = encoder.encode(file.text)
  }
  return new Promise((resolve, reject) => {
    zip(input, { level: 6 }, (error, data) => (error ? reject(error) : resolve(data)))
  })
}

/**
 * 导出并下载。**结果返回给调用方**，不在这里弹提示 —— 只有 CodeWorkspace 知道提示该写哪儿。
 */
export async function exportWorkspaceZip(entries, targetPath, rootName) {
  const { fileName, files } = planExport(entries, targetPath, rootName)
  // 只有目录、没有文件时不给空包：那种 zip 解出来是个空文件夹，学生只会以为导出坏了。
  const fileCount = files.filter((file) => !file.isDirectory).length
  if (!fileCount) {
    return {
      ok: false,
      reason: cleanRelativePath(targetPath)
        ? '这个文件夹里没有可以导出的文件'
        : '工作区还是空的，没有可以导出的文件',
    }
  }
  downloadBlob(fileName, new Blob([await buildZipBytes(files)], { type: 'application/zip' }))
  return { ok: true, fileName, fileCount }
}
