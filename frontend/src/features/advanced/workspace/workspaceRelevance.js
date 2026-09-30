// 对话教练看不见学生工作区，所以每次对话前要把工作区压成一段文本推给后端。
// 压之前先要回答一个问题：**哪些文件值得占那点配额**。
//
// 这个文件只做"选谁"这一件事，输出一份带分数的排序；真正切成文本在
// workspaceSnapshot.js。两边都是纯函数、不碰 Vue —— 项目没有测试基建，而"引用识别"
// 和"排序稳定性"恰好是最容易悄悄坏掉、又最值得补测的两块，纯函数至少让将来能补测。
//
// 引用匹配的容错（后缀省略、__init__.py / index.js）也放在这里：扫描出来的候选串
// 本身就是"可能指向谁"，只有和真实路径对上才算数，所以匹配天然属于这一层。

import { isDirectoryEntry } from './localWorkspace'

// 只扫文件开头。import / require 集中在文件头部，扫全文既费时间，又会把正文里
// 散落的普通字符串（日志、错误信息）误认成引用 —— 那些噪音比多扫出来的引用更碍事。
export const REFERENCE_SCAN_CHARS = 4000

// 打分权重是设计定好的口径，不要随手调：它直接决定"教练先看到谁"。
export const WEIGHT_ACTIVE = 100
export const WEIGHT_OPEN_TAB = 40
export const WEIGHT_DIRTY = 15
export const WEIGHT_REFERENCED_BY_ACTIVE = 30
export const WEIGHT_REFERENCED_BY_PEER = 10

// 引用图只传播一跳，种子数固定。跳数再多，收益就只剩"给所有文件都加一点分"，
// 反而把真正相关的文件淹掉；固定种子数也让结果不受文件总数影响。
export const PEER_PROPAGATION_SEEDS = 8

// 写 import 时后缀常被省略（import 'search' 可能对应 search.py）。这些是工作区里
// 认得的源码后缀，按最可能到最不可能排，匹配时逐个试。
const REFERENCE_FILE_EXTENSIONS = ['.py', '.js', '.ts', '.tsx', '.jsx', '.vue']

// 目录导入的两种入口写法：Python 的 __init__.py、JS 的 index.js。
// 候选串 tools 要能同时对上 tools/__init__.py、tools/index.js 和 tools.py。
const DIRECTORY_INDEX_NAMES = ['__init__', 'index']

// ── 引用识别 ─────────────────────────────────────────────────────

// JS / TS：`import x from './a'`、`export { x } from './a'`
const JS_IMPORT_FROM = /\b(?:import|export)\b[^'"\n]*?\bfrom\s*['"]([^'"\n]+)['"]/g
// JS：副作用导入 `import './a'`（没有 from，上面那条抓不到）
const JS_SIDE_EFFECT_IMPORT = /\bimport\s*['"]([^'"\n]+)['"]/g
// JS：`require('./a')` 与动态 `import('./a')`
const JS_REQUIRE_OR_DYNAMIC = /\b(?:require|import)\s*\(\s*['"]([^'"\n]+)['"]\s*\)/g
// Python：`from a.b import c`、`from . import x`、`from .mod import y`。
// 行首用 [ \t]* 而不是 \s*：允许缩进，但不吃掉上一行的换行，免得跨行误配。
// 排除引号是为了不和上面的 JS 写法互相串台（JS 行里没有引号就不该被 Python 规则认领）。
const PY_FROM_IMPORT = /^[ \t]*from[ \t]+([.\w]+)[ \t]+import[ \t]+([^\n#;'"]+)/gm
// Python：`import a.b`、`import a, b`、`import a.b as c`
const PY_IMPORT = /^[ \t]*import[ \t]+([^\n#;'"]+)/gm

// 把一段代码正文里引用的**其它文件**扫出来。
//
// 输出的是"候选串"，不是已经对上的路径：同一个引用会给出归一化形式和原样两份
// （`./tools/search` 与 `tools/search`、`a.b` 与 `a/b`），因为不同工程习惯两种写法
// 混着来，谁对上算谁的。归一化只做无歧义的部分：`./` 前缀、Python 的点号。`../`
// 需要知道引用方在哪个目录才能解析，这个函数拿不到位置，所以原样留着、由匹配阶段落空。
export function scanLocalReferences(text) {
  const body = String(text || '').slice(0, REFERENCE_SCAN_CHARS)
  if (!body) return []

  const candidates = []
  const seen = new Set()
  const addCandidate = (value) => {
    if (value && !seen.has(value)) {
      seen.add(value)
      candidates.push(value)
    }
  }
  const addReference = (raw) => {
    for (const candidate of toPathCandidates(raw)) addCandidate(candidate)
  }

  for (const match of body.matchAll(JS_IMPORT_FROM)) addReference(match[1])
  for (const match of body.matchAll(JS_SIDE_EFFECT_IMPORT)) addReference(match[1])
  for (const match of body.matchAll(JS_REQUIRE_OR_DYNAMIC)) addReference(match[1])

  for (const match of body.matchAll(PY_FROM_IMPORT)) {
    const moduleSpec = match[1]
    addReference(moduleSpec)
    // `from . import x` 里模块本身只有一个点，没有可匹配的信息；真正可能指向文件的是
    // 被导入的名字（x 可能是 x.py 或 x/ 包）。只有纯点号的相对导入才需要补这一手。
    if (/^\.+$/.test(moduleSpec)) {
      for (const name of splitPythonImportNames(match[2])) addReference(name)
    }
  }
  for (const match of body.matchAll(PY_IMPORT)) {
    for (const name of splitPythonImportNames(match[1])) addReference(name)
  }

  return candidates
}

// `a, b as c, d` -> ['a', 'b', 'd']。`as` 只是本地别名，与被引用的模块名无关。
function splitPythonImportNames(list) {
  return String(list || '')
    .split(',')
    .map((part) => part.trim().split(/\s+as\s+/)[0].trim())
    .filter(Boolean)
}

// 一个引用串变成它可能对应的工作区相对路径候选。保持输入顺序，首个永远是原样。
function toPathCandidates(raw) {
  const original = String(raw || '').trim()
  if (!original) return []
  const candidates = [original]

  // `./tools/search` 和 `tools/search` 指的是同一份，去掉 `./` 才能和 entries 的路径对上。
  if (original.startsWith('./')) {
    const withoutPrefix = original.slice(2)
    if (withoutPrefix) candidates.push(withoutPrefix)
    return candidates
  }
  // `../` 要引用方所在目录才能解析；`/` 开头是绝对路径，工作区路径都是相对的。
  // 两者都原样留着 —— 匹配不上就落空，好过猜一个错误的目录。
  if (original.startsWith('../') || original.startsWith('/')) return candidates

  // Python 点号模块名：`a.b` -> `a/b`，`.mod` -> `mod`。只对"纯点号 + 词字符"下手，
  // 免得把 `@scope/pkg`、`./x` 这类带符号的 JS 说明符改坏。
  if (/^[.\w]+$/.test(original)) {
    const normalized = original.replace(/^\.+/, '').replace(/\./g, '/')
    if (normalized) candidates.push(normalized)
  }
  return candidates
}

// ── 排序 ─────────────────────────────────────────────────────────

// 候选串 -> 真实存在的文件路径集合。形式枚举而非正则：候选 `tools` 要能对上
// tools.py、tools/__init__.py、tools/index.js 三种；候选 `search` 要能对上 search.py。
// 枚举出来再查 Set，比写一堆分支更容易看清"到底容忍了哪些写法"。
function buildCandidatePathForms(candidate) {
  const forms = new Set()
  const stems = [candidate]
  for (const indexName of DIRECTORY_INDEX_NAMES) stems.push(`${candidate}/${indexName}`)
  for (const stem of stems) {
    forms.add(stem)
    for (const extension of REFERENCE_FILE_EXTENSIONS) forms.add(`${stem}${extension}`)
  }
  return forms
}

// 一组候选串里，哪些能对上真实文件。对不上就忽略，不猜。
function matchReferencedPaths(candidates, knownPaths) {
  const matched = new Set()
  for (const candidate of candidates) {
    for (const form of buildCandidatePathForms(candidate)) {
      if (knownPaths.has(form)) matched.add(form)
    }
  }
  return matched
}

function compareRankedFiles(a, b) {
  if (b.score !== a.score) return b.score - a.score
  // 同分按路径升序：没有这条，同分文件的先后就取决于 entries 的遍历顺序，
  // 同一个工作区两次请求可能给出不同快照，缓存和调试都会变得莫名其妙。
  return a.path.localeCompare(b.path, 'zh-CN')
}

// 按重要性给工作区里的**文件**排序（目录跳过）。返回 [{ path, text, score }]。
//
// 前四条信号是基础分，第四条（被当前文件引用）让"顺着 import 走一层"的文件浮上来。
// 再做一个简化版 PageRank：拿基础分最高的几个文件当种子，扫它们引用了谁，给被引用者
// 加一点分。**只传播一跳**，不迭代 —— 迭代会把分量摊到整张图上，最后每个文件都差不多，
// 也就失去了排序的意义。
export function rankWorkspaceFiles({ entries, openPaths, activePath }) {
  const fileEntries = (entries || []).filter((entry) => entry && !isDirectoryEntry(entry))
  if (!fileEntries.length) return []

  const knownPaths = new Set(fileEntries.map((entry) => entry.path))
  const openTabs = new Set(openPaths || [])
  const activeEntry = fileEntries.find((entry) => entry.path === activePath) || null

  const referencedByActive = activeEntry
    ? matchReferencedPaths(scanLocalReferences(activeEntry.text), knownPaths)
    : new Set()

  const baseScores = new Map()
  for (const entry of fileEntries) {
    let score = 0
    if (entry.path === activePath) score += WEIGHT_ACTIVE
    if (openTabs.has(entry.path)) score += WEIGHT_OPEN_TAB
    if (entry.dirty) score += WEIGHT_DIRTY
    if (referencedByActive.has(entry.path)) score += WEIGHT_REFERENCED_BY_ACTIVE
    baseScores.set(entry.path, score)
  }

  const seeds = fileEntries
    .slice()
    .sort((a, b) => {
      const diff = baseScores.get(b.path) - baseScores.get(a.path)
      return diff !== 0 ? diff : a.path.localeCompare(b.path, 'zh-CN')
    })
    .slice(0, PEER_PROPAGATION_SEEDS)

  const referencedByPeer = new Set()
  for (const seed of seeds) {
    // 当前文件引用谁已经算进 WEIGHT_REFERENCED_BY_ACTIVE 了，这里只认"其它高分文件"，
    // 否则同一个引用会被记两次，权重口径就偏了。
    if (seed.path === activePath) continue
    for (const path of matchReferencedPaths(scanLocalReferences(seed.text), knownPaths)) {
      if (path !== seed.path) referencedByPeer.add(path)
    }
  }

  return fileEntries
    .map((entry) => ({
      path: entry.path,
      text: entry.text,
      score: baseScores.get(entry.path)
        + (referencedByPeer.has(entry.path) ? WEIGHT_REFERENCED_BY_PEER : 0),
    }))
    .sort(compareRankedFiles)
}
