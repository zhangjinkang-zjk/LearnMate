// 把学生的工作区压成一段**有字符上限**的文本，随每次对话推给后端，让对话教练能看见代码。
//
// 上限不是可有可无：工作区可能有几百个文件，全塞进请求里既慢又贵，还会把真正相关的
// 几份代码冲淡。所以这里做两件事——用一棵缩进树交代"有哪些文件"，再挑有限几份附上正文。
//
// 选谁、怎么排由 workspaceRelevance.js 决定；本文件只负责"按预算切出来"。
//
// 两个约束贯穿全文件：
//   1. 树必须保留换行。后端有个 _clip 会把换行压平成空格，前端这边再无意中压一次，
//      树就彻底废了。所以序列化一律字符串拼接 + slice，绝不 split/join 到空格上。
//   2. 同样的输入必须得到同样的输出。排序和截断都只依赖确定性规则，不依赖遍历顺序。

import { isDirectoryEntry } from './localWorkspace'
import { rankWorkspaceFiles } from './workspaceRelevance'

// 各段预算，字符口径。
//
// 2026-09-30 整体上调一个数量级（原来是 1500/3000/1200/2400/12）。旧档是按"带几份
// 代码片段当佐证"定的，但教练现在要真的**审核**代码 —— 3000 字符只够看一个 100 行的
// 文件，学生问"我这段对不对"，来的其实是文件的前四分之一。对话模型是 MiMo-V2.6-Flash
// （上下文 1M token、输入 $0.14/M），旧上限约占窗口的 0.2%，是我们自己把眼睛蒙上了。
//
// 新档按"一个中等项目的骨架 + 若干份完整源文件"定：极端情况 22 万字符 ≈ 7 万 token，
// 仍不到窗口的 10%，单轮成本在 $0.01 量级。真正决定"带哪几份"的仍是 workspaceRelevance
// 的相关性排序 —— 预算放宽不等于不分主次，只是不再把主次压到看不见的程度。
export const SNAPSHOT_LIMITS = {
  TREE_MAX_CHARS: 20000,
  ACTIVE_FILE_MAX_CHARS: 40000,
  OTHER_FILE_MAX_CHARS: 20000,
  OTHER_FILES_TOTAL_MAX_CHARS: 160000,
  MAX_SNAPSHOT_FILES: 40,
}

// 这段提示必须出现在界面上：把学生代码发出去是用户该知道的事，不能藏在代码注释里。
const CODE_SENDING_NOTICE = '代码会随对话发给模型厂商（.env 与密钥类文件不会被读取）。'

// ── 树的构建与渲染 ───────────────────────────────────────────────

// 用嵌套 Map 搭树。之所以不直接把 path 字符串列表甩出去：目录名在一棵树上只出现一次，
// 深层路径因此更省 token，而且"谁在谁下面"本身就是信息，扁平列表表达不出来。
function buildTreeRoot(entries) {
  const root = { type: 'dir', name: '', path: '', children: new Map() }
  for (const entry of entries) {
    const segments = String(entry.path || '').split('/').filter(Boolean)
    if (!segments.length) continue
    const isDirectory = isDirectoryEntry(entry)
    let cursor = root
    segments.forEach((segment, index) => {
      const path = segments.slice(0, index + 1).join('/')
      const isLeaf = index === segments.length - 1
      if (isLeaf && !isDirectory) {
        cursor.children.set(path, { type: 'file', name: segment, path })
        return
      }
      // 显式新建的空目录也要留着：它不像从路径推出来的目录那样"因为下面有文件所以存在"，
      // 没有它就等于学生建了个空文件夹、教练却以为没有。
      if (!cursor.children.has(path)) {
        cursor.children.set(path, { type: 'dir', name: segment, path, children: new Map() })
      }
      cursor = cursor.children.get(path)
    })
  }
  return root
}

// 同层排序**必须和学生眼前那棵资源管理器树一样**（见 FileExplorer.sortedChildren）：
// 目录优先，同类再按名字。这不是为了好看 —— 提示里会写"文件树较长，只显示了前 N 个"，
// 学生要能拿自己的资源管理器核对这句话；两边顺序不同，那句话就没法验证了。
function compareTreeNodes(a, b) {
  if (a.type !== b.type) return a.type === 'dir' ? -1 : 1
  return a.name.localeCompare(b.name, 'zh-CN')
}

// 展平成带缩进的行。两空格一级、目录结尾加 `/`：不用 ├─└│ 那类图元，
// 它们在等宽字体里占的宽度比信息本身还抢眼，纯噪音。
function flattenTreeLines(root) {
  const lines = []
  const walk = (node, depth) => {
    const children = Array.from(node.children?.values() || []).sort(compareTreeNodes)
    for (const child of children) {
      const label = child.type === 'dir' ? `${child.name}/` : child.name
      lines.push({ text: `${'  '.repeat(depth)}${label}`, type: child.type })
      if (child.type === 'dir') walk(child, depth + 1)
    }
  }
  walk(root, 0)
  return lines
}

// 整棵树里的文件总数（不含目录），截断前统计，用来告诉界面"实际有多少"。
function countTreeFiles(node) {
  let total = 0
  for (const child of node.children?.values() || []) {
    total += child.type === 'file' ? 1 : countTreeFiles(child)
  }
  return total
}

// 按**整行**截断，不在行中间砍。半行在树里读不出层级，反而是误导。
// 代价是可能超一点额度，所以第一行无条件保留：宁可多十几字符，也不要因为一个超长
// 文件名就让整棵树变成空字符串。
function truncateTreeLines(lines, maxChars) {
  const kept = []
  let used = 0
  for (const line of lines) {
    const cost = kept.length ? line.text.length + 1 : line.text.length // +1 是行间换行
    if (kept.length && used + cost > maxChars) break
    kept.push(line)
    used += cost
  }
  return { lines: kept, truncated: kept.length < lines.length }
}

// ── 附正文文件的选取 ─────────────────────────────────────────────

// 当前文件无条件第一份（学生正看着它，最该被教练看见），其余按 rankWorkspaceFiles
// 的顺序取。其余文件的额度用"剩余池"递减：每附一份，就从池子里扣掉实际用掉的字符，
// 而不是每份各自和 OTHER_FILE_MAX_CHARS 比 —— 各自比的话，11 份各 1200 字就是
// 13200 字，合计上限形同虚设。
function selectSnapshotFiles({ entryByPath, activeFilePath, openPaths, limits }) {
  const files = []

  if (activeFilePath) {
    files.push(sliceFileContent(entryByPath.get(activeFilePath), limits.ACTIVE_FILE_MAX_CHARS))
  }

  const ranked = rankWorkspaceFiles({
    entries: Array.from(entryByPath.values()),
    openPaths,
    activePath: activeFilePath,
  })

  let remainingPool = limits.OTHER_FILES_TOTAL_MAX_CHARS
  for (const item of ranked) {
    if (item.path === activeFilePath) continue
    if (files.length >= limits.MAX_SNAPSHOT_FILES) break
    // 池子空了就到此为止。空文件理论上是零成本，但为它破例会让"还剩多少额度"
    // 这套判断多出一个分支，得不偿失。
    if (remainingPool <= 0) break
    const text = String(item.text ?? '')
    // 装不下就**整份跳过**，不切半份：半截文件比没有文件更坏 —— 教练会照着前半段下结论，
    // 而问题常常正藏在他没看到的那半段里。跳过之后继续看下一份，排序里靠后的短文件仍然
    // 进得来，池子的尾巴不会被一份长文件独吞。
    // 反过来，池子还够一份单份上限时就照旧切一刀并标 truncated —— 那是"文件本身太长"，
    // 有明确声明，教练知道自己在看开头。
    if (text.length > remainingPool && remainingPool < limits.OTHER_FILE_MAX_CHARS) continue
    const cap = Math.min(limits.OTHER_FILE_MAX_CHARS, remainingPool)
    const sliced = text.slice(0, cap)
    files.push({ path: item.path, text: sliced, truncated: text.length > cap })
    remainingPool -= sliced.length
  }

  return files
}

// 空文件也照样收进来：'它是空的'和'我们没看到它'是两回事，学生说'我写好了'
// 而教练以为文件不存在，会给出完全错误的判断。
function sliceFileContent(entry, cap) {
  const text = String(entry?.text ?? '')
  return { path: entry.path, text: text.slice(0, cap), truncated: text.length > cap }
}

// ── 对外接口 ─────────────────────────────────────────────────────

// 返回结构里每个键名都是契约，界面按它渲染，不要改名或增删。
// options 只覆盖 SNAPSHOT_LIMITS 里的预算，方便将来调档或测试收紧。
export function buildWorkspaceSnapshot({ entries, openPaths, activePath, rootName } = {}, options = {}) {
  const source = Array.isArray(entries) ? entries : []
  // 没有工作区时连树都没有，给界面一个明确的 available:false 比给一堆空字段好判断。
  if (!source.length) return { available: false }

  const limits = { ...SNAPSHOT_LIMITS, ...options }
  const openList = Array.isArray(openPaths) ? openPaths : []

  const fileEntries = source.filter((entry) => entry && !isDirectoryEntry(entry))
  const filePaths = new Set(fileEntries.map((entry) => entry.path))
  const entryByPath = new Map(fileEntries.map((entry) => [entry.path, entry]))
  // 目录不是能打开的东西；activePath 指向目录时当作"没有当前文件"，不给快照一个假文件。
  const activeFilePath = entryByPath.has(activePath) ? activePath : ''

  const treeRoot = buildTreeRoot(source)
  const treeTotalFiles = countTreeFiles(treeRoot)
  const { lines, truncated: treeTruncated } = truncateTreeLines(flattenTreeLines(treeRoot), limits.TREE_MAX_CHARS)

  const files = selectSnapshotFiles({ entryByPath, activeFilePath, openPaths: openList, limits })

  // omitted 只统计"已打开但没带上"的文件。用全部被挤掉的文件会一下列出一百多条路径，
  // 既超出快照的用意，也和界面那句"还有 N 份已打开文件没带"对不上。
  const openFilePaths = openList.filter((path) => filePaths.has(path))
  const includedPaths = new Set(files.map((file) => file.path))
  const omittedPaths = openFilePaths.filter((path) => !includedPaths.has(path))

  return {
    available: true,
    root_name: String(rootName || ''),
    tree: lines.map((line) => line.text).join('\n'),
    tree_total_files: treeTotalFiles,
    tree_shown_files: lines.filter((line) => line.type === 'file').length,
    tree_truncated: treeTruncated,
    active_path: activeFilePath,
    files,
    open_count: openFilePaths.length,
    omitted_count: Math.max(0, openFilePaths.length - files.length),
    omitted_paths: omittedPaths,
  }
}

// 给界面用的一行摘要 + 展开后的细节。界面只负责摆位置，措辞在这里统一，
// 免得同一件事在两处各写一遍、改了一处忘了另一处。
export function describeWorkspaceSnapshot(snapshot) {
  if (!snapshot?.available) {
    return {
      headline: '教练还看不到你的文件 · 打开文件夹后教练才能读到代码',
      rules: [],
      details: [],
    }
  }

  const activeName = snapshot.active_path ? snapshot.active_path.split('/').pop() : ''
  let headline = '教练能看到：'
  if (activeName) headline += `${activeName}（当前）+ `
  headline += `文件树里 ${snapshot.tree_total_files} 个文件`
  if (snapshot.omitted_count > 0) headline += `，还有 ${snapshot.omitted_count} 份已打开文件没带`

  // 「哪些文件会被送出去」背后是两条**规则**，学生得知道 —— 不知道就只能靠猜，
  // 而这一块存在的全部理由就是让人不必猜：
  //   - 打开着的标签页都在里面。这就是"想让他看哪一份"的那个开关，之前从没被说出来过，
  //     于是学生只会读结果（"这 5 份发出去了"），学不会用它。
  //   - 被当前文件引用的文件也在里面。也就是说**他没打开过的文件也可能被送出去** ——
  //     这件事本身在下面列出来了（没藏），但不知道为什么，学生看到会当成 bug。
  // 规则和"这一轮实际送了哪几份"**分开两个字段**：前者不变，后者每轮都变，混在一个
  // 列表里会让人以为规则也在变。
  const rules = [
    '打开着的标签页教练都读得到 —— 想让他看哪一份，在左边把它打开就行。',
    '被当前文件引用的文件也会一起带上（审核要看依赖关系），所以你没打开过的文件也可能在里面。',
    CODE_SENDING_NOTICE,
  ]

  const details = []
  for (const file of snapshot.files) {
    details.push(`${file.path}（${file.text.length} 字符${file.truncated ? '，已截断' : ''}）`)
  }
  if (snapshot.tree_truncated) {
    details.push(`文件树太长，只列出了 ${snapshot.tree_shown_files} 个文件（共 ${snapshot.tree_total_files} 个），其余整行省略`)
  }
  if (snapshot.omitted_paths.length) {
    details.push(`这些已打开的文件这次没带上：${snapshot.omitted_paths.join('、')}`)
  }

  return { headline, rules, details }
}
