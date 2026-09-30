// 工作区草稿与"上次打开的文件夹句柄"的 IndexedDB 适配层。
//
// **为什么在 shared/ 而不是 features/advanced/workspace/**：登出时必须清掉它
// （见下面 clearWorkspaceStorage），而登出走的是 shared/auth/session.js —— shared
// 不能反向依赖 features。放在同一层是为了让 session.js 能直接调，不用绕注册回调
// （注册那一套还要求"学生这次会话访问过进阶学习页"，而陈旧草稿恰恰可能来自上一次会话）。
// 这和 shared/api/ 里放各域 API 客户端是同一条惯例：多于一层的域模块住 shared。
//
// 为什么是 IndexedDB 而不是 localStorage：草稿里是代码正文，localStorage 只有约 5MB
// 且是同步 API（写的时候会卡住主线程）；更关键的是句柄 —— `FileSystemDirectoryHandle`
// 是**结构化克隆**对象，只有 IndexedDB 存得下，localStorage 会把它 `[object Object]` 掉。
// 这两样东西放同一个库、两个 store，登出时一起清。
//
// **这个模块的任何函数都不抛异常。** IndexedDB 在隐私模式、存储被禁用、库被别处
// 升级卡住（onblocked）等情况下会直接不可用，而"草稿存不下"绝不该让编辑器崩掉 ——
// 最坏的结果是回到今天的行为（这一屏没了就没了），而不是学生连代码都写不了。
// 所以每个入口失败一律 resolve(null)，调用方按"没有草稿"处理。

const DB_NAME = 'learnmate_workspace'
const DB_VERSION = 1
const DRAFT_STORE = 'drafts'
const FOLDER_STORE = 'folders'
const FOLDER_KEY = 'last_directory'

let dbPromise = null

function openDb() {
  if (dbPromise) return dbPromise
  dbPromise = new Promise((resolve) => {
    let request
    try {
      if (!window.indexedDB) { resolve(null); return }
      request = window.indexedDB.open(DB_NAME, DB_VERSION)
    } catch {
      resolve(null)
      return
    }
    request.onupgradeneeded = () => {
      const db = request.result
      if (!db.objectStoreNames.contains(DRAFT_STORE)) db.createObjectStore(DRAFT_STORE)
      if (!db.objectStoreNames.contains(FOLDER_STORE)) db.createObjectStore(FOLDER_STORE)
    }
    request.onsuccess = () => resolve(request.result)
    // 被别的标签页占着升不了级（onblocked）也当不可用：等下去只会让页面一直悬着。
    request.onerror = () => resolve(null)
    request.onblocked = () => resolve(null)
  })
  return dbPromise
}

async function run(storeName, mode, act) {
  const db = await openDb()
  if (!db) return null
  return new Promise((resolve) => {
    let request
    try {
      request = act(db.transaction(storeName, mode).objectStore(storeName))
    } catch {
      resolve(null)
      return
    }
    if (!request) { resolve(null); return }
    request.onsuccess = () => resolve(request.result ?? null)
    request.onerror = () => resolve(null)
  })
}

// 草稿按**学习路径**存，不按任务卡、也不按节点。
//
// 不按 task_id：工作区现在就是跨任务卡共享的（换任务卡不重建组件），按 task 分会
// 把这个行为改掉 —— 而用户抱怨的是"丢"，不是"留得太多"。
//
// 不按 node_id：那会让"换到下一个节点"变成清空工作区，同样是个没人要的行为变更。
// 更要紧的是 **draftKey 是个 prop**，节点一变它就变，而 CodeWorkspace 没有 :key、
// 不会被重建 —— 结果是旧节点的那几份文件被写进新节点的草稿里，那份草稿还是脏的。
// 按路径存就没有这个窗口：path_id 在一个学习路径的生命周期里是稳定的。
export function draftKeyFor(pathId) {
  if (pathId === null || pathId === undefined || pathId === '') return ''
  return `path_${pathId}`
}

export const readDraft = (key) => (key ? run(DRAFT_STORE, 'readonly', (store) => store.get(key)) : Promise.resolve(null))

export const writeDraft = (key, draft) => (
  key ? run(DRAFT_STORE, 'readwrite', (store) => store.put(draft, key)) : Promise.resolve(null)
)

export const deleteDraft = (key) => (key ? run(DRAFT_STORE, 'readwrite', (store) => store.delete(key)) : Promise.resolve(null))

export const readFolderHandle = () => run(FOLDER_STORE, 'readonly', (store) => store.get(FOLDER_KEY))

export const writeFolderHandle = (handle) => run(FOLDER_STORE, 'readwrite', (store) => store.put(handle, FOLDER_KEY))

export const deleteFolderHandle = () => run(FOLDER_STORE, 'readwrite', (store) => store.delete(FOLDER_KEY))

// 登出时调用。**必须清**：这是同一台机器上下一个账号的隔离边界 ——
// 和 shared/auth/session.js 里那些 learnmate_* 草稿是同一条规矩，
// 不清就等于把上一个人的代码留在浏览器里给下一个人看。
export async function clearWorkspaceStorage() {
  await run(DRAFT_STORE, 'readwrite', (store) => store.clear())
  await run(FOLDER_STORE, 'readwrite', (store) => store.clear())
}
