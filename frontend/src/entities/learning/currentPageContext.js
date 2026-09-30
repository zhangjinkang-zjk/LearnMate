import { reactive } from 'vue'

// 当前页面的**标识** —— 页面写，跨界面助手（罗伯特）读。
//
// 为什么要一个共享单例：悬浮助手挂在 App.vue 上，它拿不到任何页面的数据（任务卡、
// 当前节点都在页面组件自己的 ref 里）。所以要页面主动把"我在哪"报上来。
//
// **这里只放标识，不放正文。** 任务说明、教材、节点内容在后端都有权威副本，一律由
// 后端按 id 重查（见 schemas/chat.py 的 PageContext）。多塞内容没有意义：后端不会信，
// 只会拿 id 去查 —— 这也是为什么它不该被改造成"页面快照"。
//
// `page` 必须命中的后端的白名单（service/chat/service._PAGE_LABELS），否则后端整块
// 不渲染。传中文名没用，那边只认这几个标识。
export const currentPageContext = reactive({
  page: '',
  node_id: null,
  task_id: '',
})

// 页面挂载 / 切换节点时调用。
export function setCurrentPage(page, { nodeId = null, taskId = '' } = {}) {
  const id = Number(nodeId)
  currentPageContext.page = String(page || '')
  currentPageContext.node_id = Number.isFinite(id) && id > 0 ? id : null
  currentPageContext.task_id = String(taskId || '')
}

// 页面卸载时调用。**必须带上自己是谁**：路由切换时"新页面挂载"和"旧页面卸载"没有
// 可靠的先后顺序，不带判断地清空会把新页面刚报上来的上下文抹掉。
export function clearCurrentPage(page) {
  if (page && currentPageContext.page !== page) return
  currentPageContext.page = ''
  currentPageContext.node_id = null
  currentPageContext.task_id = ''
}

// 组装成请求体里的那一段。没有页面时返回 null —— 让"没带"保持显式，
// 而不是发一个 {} 让后端去猜这是"空的"还是"忘了带"。
export function pageContextPayload() {
  if (!currentPageContext.page) return null
  return {
    page: currentPageContext.page,
    node_id: currentPageContext.node_id,
    task_id: currentPageContext.task_id,
  }
}
