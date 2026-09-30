// 工作区草稿的**纯**序列化：entries ↔ 能存进 IndexedDB 的普通数据。
//
// 这一层刻意不碰任何浏览器 API（IndexedDB 的读写全在 workspaceDraftStore.js），
// 于是它可以脱离浏览器单测 —— 前端没有测试框架，能纯函数化的部分就纯函数化，
// 而"什么该存、存回来怎么校验"恰好是最容易写错的部分。
//
// **只存文本，不存 handle 和 File。** 两者都不可跨会话复用：句柄在换个页面打开时
// 就已经失效，File 也只是某一刻的快照。存下去的结果是恢复出一个"看起来还连着磁盘、
// 其实写不回去"的条目 —— 比不恢复更坏，因为学生按了保存才发现。
// 所以恢复出来的一律当内存文件处理：保存走下载副本（见 CodeWorkspace 的 canWriteBack）。
//
// 背景：没打开本机文件夹时新建的东西过去只活在组件内存里（CodeWorkspace 的 ref），
// 而那个组件会被「重新同步」和路由跳转卸载 —— 学生人还在页面上，文件就没了。

import { createBlankDirectory, createBlankEntry, isDirectoryEntry } from './localWorkspace'

// 存盘格式变了就把版本号 +1；旧草稿会被 fromDraft 判为不可用而丢弃，
// 而不是勉强读出一堆形状不对的条目。
export const DRAFT_VERSION = 1

// 与 localWorkspace.MAX_FILES 同口径。草稿是学生手写的，正常远达不到这个数；
// 上限只是防止一份被写坏的草稿把 IndexedDB 撑爆。
const MAX_DRAFT_FILES = 400

export function toDraft({ entries, openPaths, activePath, rootName } = {}) {
  const source = Array.isArray(entries) ? entries : []
  const rows = []
  for (const entry of source.slice(0, MAX_DRAFT_FILES)) {
    const path = String(entry?.path || '')
    if (!path) continue
    rows.push(isDirectoryEntry(entry)
      ? { kind: 'directory', path }
      : { kind: 'file', path, text: String(entry?.text ?? '') })
  }
  return {
    version: DRAFT_VERSION,
    root_name: String(rootName || ''),
    active_path: String(activePath || ''),
    open_paths: (Array.isArray(openPaths) ? openPaths : []).map(String).filter(Boolean),
    entries: rows,
    // 只给人看（"上次是几点存的"），不参与任何判断 —— 别拿它做过期淘汰，
    // 学生会隔一晚上回来接着写。
    saved_at: new Date().toISOString(),
  }
}

// 校验并还原。**不做任何补救**：任何一处形状不对就返回 null（当作没有草稿），
// 因为"读出来一半"的工作区比"空工作区"更难让学生理解 —— 他不会知道少了哪个文件。
export function fromDraft(draft) {
  if (!draft || typeof draft !== 'object') return null
  if (draft.version !== DRAFT_VERSION) return null
  if (!Array.isArray(draft.entries)) return null

  const entries = []
  const seen = new Set()
  for (const row of draft.entries.slice(0, MAX_DRAFT_FILES)) {
    const path = String(row?.path || '')
    if (!path || seen.has(path)) continue
    seen.add(path)
    entries.push(row.kind === 'directory'
      ? createBlankDirectory(path)
      : createBlankEntry(path, { text: String(row?.text ?? '') }))
  }
  if (!entries.length) return null

  const files = new Set(entries.filter((entry) => !isDirectoryEntry(entry)).map((entry) => entry.path))
  // 标签页只能指向真的还原出来的文件：草稿里记着一个后来被删掉的文件时，
  // 直接照搬会让编辑器拿到一个 undefined 的标签。
  const openPaths = (Array.isArray(draft.open_paths) ? draft.open_paths : [])
    .map(String)
    .filter((path) => files.has(path))
  const activePath = files.has(String(draft.active_path || ''))
    ? String(draft.active_path)
    : (openPaths[0] || '')

  return {
    rootName: String(draft.root_name || ''),
    entries,
    openPaths,
    activePath,
    fileCount: files.size,
  }
}
