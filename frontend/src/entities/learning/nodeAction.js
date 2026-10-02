/**
 * 一个章节（学习路径上的一个节点）**当前能做的所有事**，以及各自落到哪个页面。
 *
 * 为什么是一串而不是一个：同一个章节可能"还有资料没看"、"可以去做题"、"已经过关了该复习"，
 * 这三件事是并列的，不是二选一 —— 学生想先做题还是先看资料，该由他自己定。
 *
 * **现在没有地方把这一串逐条画出来。** 花园那棵树上本来挂着几颗可点的水滴（一颗一件事），
 * 后来撤掉了；目前只有两处消费它：花园顶部那句"接下来：看资料"，和每棵树按钮的
 * 无障碍标签。留着这个模块是因为**判断规则本身和渲染无关** ——
 * 它只依赖 `status` + `garden_progress`，哪天要重新把动作摆回树上（或者让概览页
 * 复用它，见第二阶段计划），接回去就行，规则不用重写。
 *
 * 为什么不在后端算：后端的 `next_action`（`backend/src/service/path/service.py:2351`）
 * **只给当前节点一个动作**，不是逐节点的；而且它的 `action_label`（同一文件 `:2323`）
 * 对 `status='completed'` 的节点照样说"开始学习"，**没有"复习"这一档**。
 * 所以文案只能在前端按节点的 `status` + `garden_progress` 推 —— 这两样前端都已经有了，
 * 不用改后端，也不用加接口。
 *
 * 这是**领域规则**，所以放在 `entities` 层（纯函数、不碰 Vue、不碰 router），
 * 页面拿到 `to` 之后自己 `router.push`。
 *
 * 要"这一章只有一个下一步"的地方（比如头部那句"接下来：…"）取数组第一项即可，
 * 所以不另开一个单数版本 —— 两个函数迟早会对不上。
 */

export const NODE_ACTION = {
  LOCKED: 'locked',
  READ: 'read',
  QUIZ: 'quiz',
  REVIEW: 'review',
}

const num = (value) => (Number.isFinite(Number(value)) ? Number(value) : 0)

/**
 * @param {object} node   学习路径节点（`get_current_path` 返回的那份）
 * @param {object} options
 * @param {string|number} options.pathId  路径 id，拼进 query
 * @returns {Array<{key: string, kind: string, label: string, aria: string, to: object}>}
 *          **按重要性从先到后**排（调用方要"下一步是什么"就取头一个）。
 *          未解锁返回空数组。
 */
export function resolveNodeActions(node, { pathId } = {}) {
  if (!node || node.status === 'locked') return []

  const progress = node.garden_progress || {}
  const resourceTotal = num(progress.resource_total)
  const resourceDone = num(progress.resource_completed)
  const quizAnswered = num(progress.quiz_answered)
  const title = node.title || '这一章'
  const query = { pathId, node: node.id }

  // 已经过关 —— 只剩"复习"这一件事。**这一档是给复习留的**：复习本身还没做，
  // 先落在复盘页上，将来换目标页只改 `to` 一处。
  if (node.status === 'completed') {
    return [{
      key: 'review',
      kind: NODE_ACTION.REVIEW,
      label: '复习',
      aria: `复习：${title}`,
      to: { name: 'foundationTest', query },
    }]
  }

  // **"还没开始"必须先判，不能靠 `resource_completed < resource_total`。**
  // 资源是节点**被打开时**才按需生成并绑定的，所以没进过的节点 `resource_total` 是 0，
  // 而 `0 < 0` 为假 —— 按数量比较会把它判成"资料看完了"，给出错误的下一步。
  const started = resourceDone > 0 || quizAnswered > 0 || node.resources_viewed === true

  const actions = []

  if (!started || resourceDone < resourceTotal) {
    actions.push({
      key: 'read',
      kind: NODE_ACTION.READ,
      label: started ? '继续' : '去学',
      aria: `${started ? '继续学' : '去学'}：${title}`,
      to: { name: 'fundamentals', query },
    })
  }

  // 没开始过的节点不给"做题" —— 题还没出，点进去是空页。
  // 开始过之后**不等资料读完**就给：先做题还是先看资料是学生自己的选择。
  if (started && node.type === 'quiz') {
    actions.push({
      key: 'quiz',
      kind: NODE_ACTION.QUIZ,
      label: '做题',
      aria: `去做题：${title}`,
      to: { name: 'foundationQuiz', query },
    })
  }

  // 资料读完了、这个节点**没配测验**（`type` 由后端按 `quiz_config` 给，
  // 见 `backend/src/service/path/service.py:2297`）：没有题可做，就不该给"做题"，
  // 否则学生点进去是个空测验页。退回复盘页（那里能完成章节、也能费曼复讲）。
  if (started && resourceDone >= resourceTotal && node.type !== 'quiz') {
    actions.push({
      key: 'review',
      kind: NODE_ACTION.REVIEW,
      label: '复盘',
      aria: `复盘：${title}`,
      to: { name: 'foundationTest', query },
    })
  }

  return actions
}
