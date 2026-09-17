import { reactive } from 'vue'

// 角色名用业务方的说法，不用框架内部术语 —— 面板是给学生和培训管理者看的，
// 「协同调度 / 学情诊断 / 领域知识生成 / 内容审核 / 交叉验证」能直接说明这一步在
// 干什么。同一份字面量在后端 backend/src/ai_core/agent_names.py，跨语言没法 import，
// 改一边记得同步另一边。
// 这里的 agentName 只在后端没推 agent_name 时兜底，正常情况下以后端推送的为准。
// 注意 saver：那是一次落库，不是智能体，所以它的名字里不带"智能体"。
export const workflowPhases = [
  { id: 'leader', label: '需求规划', agentName: '协同调度智能体' },
  { id: 'executor', label: '并行生成', agentName: '领域知识生成智能体' },
  { id: 'reviewer', label: '质量审核', agentName: '内容审核智能体' },
  { id: 'saver', label: '保存资源', agentName: '保存资源' },
  { id: 'complete', label: '完成', agentName: '流程状态' },
]

// 诊断是独立的一条工作流：它只产出学情画像，不生成资源。
// 必须和 workflowPhases 分开 —— 如果并进去，每次生成学习资料都会多出一个
// 永远停在"等待中"的学情诊断阶段（那条流程压根不会上报 diagnosis 事件）。
export const diagnosisPhases = [
  { id: 'diagnosis', label: '学情诊断', agentName: '学情诊断智能体' },
  { id: 'complete', label: '完成', agentName: '流程状态' },
]

// 哪些资源类型带章节粒度。前端要拿它区分"章节还没开始生成"和"这个类型根本没有章节"，
// 否则 PPT 在大纲阶段会被误报成"没有章节粒度"。
export const sectionedResourceTypes = ['ppt', 'document']

export function phasesForWorkflow(kind) {
  return kind === 'diagnosis' ? diagnosisPhases : workflowPhases
}

function activePhases() {
  return phasesForWorkflow(workflowState.workflowKind)
}

// 和后端 agent_names.RESOURCE_AGENT_NAMES 逐项一致。
// 以前两边对不上（思维导图/案例资料/阅读材料 少了"生成"，PPT 多了一个空格），
// 于是同一批资源在弹窗里和抽屉里叫两个名字 —— 后端推了 agent_name 的地方用后端的，
// 没推的地方用这里的兜底，同屏就能同时看到两种写法。统一成 `{资源}生成智能体`。
export const resourceAgentLabels = {
  document: '文档生成智能体',
  mindmap: '思维导图生成智能体',
  ppt: 'PPT生成智能体',
  exercise: '习题生成智能体',
  image: '图片生成智能体',
  video: '视频生成智能体',
  case: '案例资料生成智能体',
  reading: '阅读材料生成智能体',
}

export const workflowState = reactive({
  available: false,
  open: false,
  // 宽档：抽屉从 370px 的窄条展开成铺满主内容区的看板，用来显示按章节铺开的过程明细。
  expanded: false,
  workflowKind: 'resource',
  displayMode: 'graph',
  title: '',
  pathId: null,
  nodeId: null,
  activeAgentId: '',
  plannedResourceTypes: [],
  resourceTypes: [],
  nodes: {},
  // 按章节聚合的进度，key 形如 "ppt:3"。
  // 为什么不直接用 nodes：后端生成和审核**共用同一个 section agent_id**
  // （resource_graph.py 里 executor:ppt:section-3 同时承载 executor 和 reviewer 两个阶段），
  // 而 nodes 只存每个 agent 的最新一条事件，于是后到的 reviewer 会把 executor 覆盖掉，
  // 连 node.phase 都会从 executor 变成 reviewer。章节看板要求"生成详情"和"审核详情"
  // 同时留着，所以单独聚一份，不参与 nodes 的覆盖语义。
  sections: {},
  events: [],
  // 本会话里真正上报过 agent_event 的 phase。用来区分"跑过并完成"和"压根没跑"——
  // 后端只推当前阶段的链路要靠它来补全前面的阶段，但没上报过的阶段不能补。
  reportedPhases: [],
  // 后端一开始就说"这一轮不做审核"（现在只有视频那条链还在用 skip_review=True，
  // 它生成的 PPT 是中间产物；学习路径的节点资源已经改成走完整审核了）。
  // 它是个会话语义：之后才冒出来的章节也要跟着落成"未审核"，否则每一节都会一直显示
  // "待审核"，而这一轮根本不会有人来审 —— 学生只看到"资源已生成但一直没审核"。
  reviewSkipped: false,
  // 后端给的那句说明（它会说清是哪种情况跳过的），章节出现得比这条信号晚时靠它。
  reviewSkipMessage: '',
  currentMessage: '',
  progress: 0,
  startedAt: 0,
  finishedAt: 0,
  updatedAt: 0,
})

function normalizeStatus(status) {
  const value = String(status || 'pending').toLowerCase()
  return ['pending', 'running', 'reviewing', 'retrying', 'saving', 'done', 'failed', 'skipped'].includes(value)
    ? value
    : 'pending'
}

function phaseLabel(phase) {
  return workflowPhases.find((item) => item.id === phase)?.label || phase
}

function makeNode(agentId, agentName, phase, status = 'pending', message = '等待中') {
  return {
    agent_id: agentId,
    agent_name: agentName,
    phase,
    status,
    message,
    current: 0,
    total: 0,
    updatedAt: Date.now(),
  }
}

function ensurePhaseNode(phase) {
  if (!workflowState.nodes[phase]) {
    const definition = activePhases().find((item) => item.id === phase)
    workflowState.nodes[phase] = makeNode(
      phase,
      definition?.agentName || phase,
      phase,
    )
  }
  return workflowState.nodes[phase]
}

function markPreviousPhasesDone(phase) {
  const phases = activePhases()
  const phaseIndex = phases.findIndex((item) => item.id === phase)
  if (phaseIndex <= 0) return
  phases.slice(0, phaseIndex).forEach((item) => {
    // 只推进"确实上报过"的阶段。它的本意是补全那些后端只报当前阶段的链路
    // （前面的阶段只报过 running、没报 done，所以要收尾）——但从未上报过的
    // 阶段不能补：那条链路可能压根没跑它。比如视频链的 skip_review=True，
    // 审核从来不执行，补成"已完成"就是假话。
    if (!workflowState.reportedPhases.includes(item.id)) return
    const node = ensurePhaseNode(item.id)
    if (['pending', 'running', 'reviewing', 'retrying', 'saving'].includes(node.status)) {
      node.status = 'done'
      node.message = '已完成'
      node.updatedAt = Date.now()
    }
  })
}

function updateNode(event) {
  const agentId = String(event.agent_id || event.agentId || event.phase || `agent-${Date.now()}`)
  const phase = String(event.phase || agentId.split(':')[0] || 'executor')
  const resourceType = String(event.resource_type || event.resourceType || '').trim().toLowerCase()
  const previous = workflowState.nodes[agentId] || makeNode(
    agentId,
    event.agent_name || event.agentName || phaseLabel(phase),
    phase,
  )
  const status = normalizeStatus(event.status)
  const next = {
    ...previous,
    ...event,
    agent_id: agentId,
    agent_name: event.agent_name || event.agentName || previous.agent_name,
    phase,
    status,
    resource_type: resourceType || previous.resource_type,
    message: event.message || previous.message || '等待中',
    current: event.current ?? previous.current ?? 0,
    total: event.total ?? previous.total ?? 0,
    updatedAt: Date.now(),
  }

  markPreviousPhasesDone(phase)
  if (!workflowState.reportedPhases.includes(phase)) workflowState.reportedPhases.push(phase)
  workflowState.nodes[agentId] = next

  if (phase === 'executor' && resourceType) {
    if (!workflowState.resourceTypes.includes(resourceType)) workflowState.resourceTypes.push(resourceType)
    const branchId = `executor:${resourceType}`
    const branch = workflowState.nodes[branchId] || makeNode(
      branchId,
      resourceAgentLabels[resourceType] || `${resourceType} 智能体`,
      'executor',
    )
    workflowState.nodes[branchId] = {
      ...branch,
      agent_name: event.agent_name || event.agentName || branch.agent_name,
      status: !agentId.includes(':section-') || ['running', 'reviewing', 'retrying', 'saving', 'failed'].includes(status)
        ? status
        : branch.status,
      message: !agentId.includes(':section-') || status !== 'done' ? next.message : branch.message,
      resource_type: resourceType,
      current: next.current,
      total: next.total,
      updatedAt: Date.now(),
    }
  }

  if (['running', 'reviewing', 'retrying', 'saving'].includes(status)) {
    workflowState.activeAgentId = agentId
  } else if (phase === 'complete') {
    workflowState.activeAgentId = 'complete'
  }
  workflowState.events = [
    ...workflowState.events,
    { ...next },
  ].slice(-80)
  workflowState.available = true
  workflowState.updatedAt = Date.now()
}

// ── 章节级聚合 ──────────────────────────────────────────────
// 一个章节的事件来自两条互不相干的通道，两条都要归到同一个 key 上，
// 少一条就只能做出半个看板：
//   1. agent_event —— agent_id 形如 "executor:ppt:section-3"
//   2. 正文流 —— stream_slide_* / stream_text_*，带 file_type + section_idx
const SECTION_AGENT_PATTERN = /^executor:([a-z_]+):section-(\d+)$/
const SECTION_TIMELINE_LIMIT = 40
const SECTION_CONTENT_LIMIT = 2000
// 审核被整轮跳过时给章节盖的那句话。措辞要让人一眼看出是"这次不做"，而不是"还没轮到"。
const REVIEW_SKIPPED_MESSAGE = '本次未做章节审核'

function sectionKeyFromEvent(event) {
  const matched = SECTION_AGENT_PATTERN.exec(String(event.agent_id || event.agentId || ''))
  if (matched) return `${matched[1]}:${matched[2]}`
  const fileType = String(event.file_type || event.fileType || '').trim().toLowerCase()
  const sectionIdx = Number(event.section_idx ?? event.sectionIdx)
  if (!fileType || !Number.isInteger(sectionIdx) || sectionIdx < 0) return ''
  return `${fileType}:${sectionIdx}`
}

function sectionLabel(resourceType, sectionIdx) {
  if (resourceType === 'ppt') return `PPT第 ${sectionIdx + 1} 章`
  if (resourceType === 'document') return `文档第 ${sectionIdx + 1} 节`
  return `${resourceAgentLabels[resourceType] || resourceType} 第 ${sectionIdx + 1} 节`
}

function ensureSection(key) {
  if (!workflowState.sections[key]) {
    const [resourceType, idxText] = key.split(':')
    const sectionIdx = Number(idxText)
    workflowState.sections[key] = {
      key,
      resourceType,
      sectionIdx,
      label: sectionLabel(resourceType, sectionIdx),
      title: '',
      // 后端报的章节总数（ppt 走 section_total、document 走 total、agent_event 走 total）。
      // 章节是边生成边冒出来的，光数 sections 的长度会低估总数。
      total: 0,
      genStatus: 'pending',
      genMessage: '等待生成',
      // 这一轮的审核被跳过时，新冒出来的章节也要直接落"未审核"（见 reviewSkipped）。
      reviewStatus: workflowState.reviewSkipped ? 'skipped' : 'pending',
      reviewMessage: workflowState.reviewSkipped
        ? (workflowState.reviewSkipMessage || REVIEW_SKIPPED_MESSAGE)
        : '等待审核',
      score: null,
      // PPT 才有"页"的概念。slideIdx 是当前正在写的那一页，slidesSeen 是推送过内容的页数，
      // 都来自 stream_slide_* 的 slide_idx（resource_graph.py:692-699）。文档没有这个字段。
      slideIdx: -1,
      slidesSeen: 0,
      timeline: [],
      content: '',
      streaming: false,
      updatedAt: Date.now(),
    }
  }
  return workflowState.sections[key]
}

// 把一条事件落到某一节上。章节级事件和整篇级审核共用这一段，免得两条路的
// 时间线/分数规则各写一遍、慢慢走偏。
function writeSection(section, { phase, status, message, event }) {
  if (phase === 'reviewer') {
    section.reviewStatus = status
    if (message) section.reviewMessage = message
    // score 只挂在"审核通过"那条事件上（resource_graph.py:1119），"使用兜底内容"
    // 那条没有。用 != null 保住已经拿到的分数，别让后面的兜底事件把它擦成空。
    if (event.score !== undefined && event.score !== null) section.score = Number(event.score)
  } else {
    section.genStatus = status
    if (message) section.genMessage = message
  }

  // 时间线只记"说法变了"的条目。同一个章节重试多轮时会反复推同样的文案，
  // 全记下来会把时间线冲成大段重复。
  if (message && section.timeline[section.timeline.length - 1]?.message !== message) {
    section.timeline = [
      ...section.timeline,
      { at: Date.now(), phase, status, message },
    ].slice(-SECTION_TIMELINE_LIMIT)
  }
  section.updatedAt = Date.now()
}

// 返回是否认领了这条事件（整篇级事件认领不了，交给后面那条路）。
function recordSectionEvent(event) {
  const key = sectionKeyFromEvent(event)
  if (!key) return false
  const section = ensureSection(key)
  const agentName = String(event.agent_name || event.agentName || '').trim()
  const sectionTitle = String(event.section_title || event.sectionTitle || '').trim()
  if (agentName) section.label = agentName
  if (sectionTitle) section.title = sectionTitle
  const reportedTotal = Number(event.total)
  if (Number.isInteger(reportedTotal) && reportedTotal > 0) section.total = reportedTotal
  writeSection(section, {
    phase: String(event.phase || '').toLowerCase(),
    status: normalizeStatus(event.status),
    message: String(event.message || '').trim(),
    event,
  })
  return true
}

// 整篇级的审核事件没有 file_type / section_idx，按章节 id 找不到归属。
//
// 目前只有文档走这条路：它的审核是**整篇**的跨章节一致性检查（resource_graph 的
// 文档生成器内部把 cross_validator 事件推给 stream_writer，不带章节信息），PPT 才
// 是逐节审核。以前这类事件被直接丢掉，于是文档每一节都永远停在"待审核" —— 生成早就
// 完成、资源也抛给前端了，抽屉里却写着没审核。
//
// 认的是 agent_id 而不是猜资源类型：交叉验证目前只有文档这一条链路在用。哪天别的
// 类型也接上它，就要让后端在事件里带上 file_type（那一处现在夹着同事未完成的改动，
// 没有顺手改），这里才能按事件归属。
function recordWholeResourceReview(event) {
  if (String(event.agent_id || event.agentId || '').toLowerCase() !== 'cross_validator') return
  if (String(event.phase || '').toLowerCase() !== 'reviewer') return
  const keys = Object.keys(workflowState.sections).filter((key) => key.startsWith('document:'))
  if (!keys.length) return
  const status = normalizeStatus(event.status)
  const message = String(event.message || '').trim()
  keys.forEach((key) => {
    // 已经逐节审过并落了结论的不覆盖：整篇审核晚到的"通过"不该把逐节的失败翻案。
    const section = workflowState.sections[key]
    if (section.reviewStatus === 'failed') return
    writeSection(section, { phase: 'reviewer', status, message, event })
  })
}

// 后端说这一轮不做审核时，把当前所有还没出结论的章节一并落成"未审核"，
// 并记住这个会话语义（之后才冒出来的章节由 ensureSection 直接落这个状态）。
function markReviewSkipped(message) {
  if (workflowState.reviewSkipped) return
  workflowState.reviewSkipped = true
  const text = message || REVIEW_SKIPPED_MESSAGE
  workflowState.reviewSkipMessage = text
  Object.values(workflowState.sections).forEach((section) => {
    if (section.reviewStatus !== 'pending') return
    section.reviewStatus = 'skipped'
    section.reviewMessage = text
    section.updatedAt = Date.now()
  })
}

function isReviewSkipEvent(event) {
  return String(event.phase || '').toLowerCase() === 'reviewer'
    && normalizeStatus(event.status) === 'skipped'
}

function applySectionStream(event) {
  const type = String(event.type || '').toLowerCase()
  const isSlide = type.startsWith('stream_slide')
  const isText = type.startsWith('stream_text')
  // stream_progress 也以 stream_ 开头但只带一句 message，不是正文流，交给下面通用分支处理。
  if (!isSlide && !isText) return false
  const key = sectionKeyFromEvent(event)
  if (!key) return false
  const section = ensureSection(key)
  const sectionTitle = String(event.section_title || event.sectionTitle || '').trim()
  if (sectionTitle) section.title = sectionTitle
  const reportedTotal = Number(event.section_total ?? event.total)
  if (Number.isInteger(reportedTotal) && reportedTotal > 0) section.total = reportedTotal
  const slideIdx = Number(event.slide_idx ?? event.slideIdx)
  if (Number.isInteger(slideIdx) && slideIdx >= 0) {
    section.slideIdx = slideIdx
    section.slidesSeen = Math.max(section.slidesSeen, slideIdx + 1)
  }

  if (type === 'stream_slide_start' || type === 'stream_text_start') {
    // 新一页 / 新一节开始，清掉上一段的正文。
    section.content = ''
    section.streaming = true
  } else if (type === 'stream_slide_delta' || type === 'stream_text_delta') {
    const delta = String(event.delta || '')
    if (delta) section.content = (section.content + delta).slice(0, SECTION_CONTENT_LIMIT)
    section.streaming = true
  } else if (typeof event.content === 'string') {
    // stream_slide / *_done 都带完整内容，以它为准，避免 delta 丢包导致正文缺字。
    section.content = event.content.slice(0, SECTION_CONTENT_LIMIT)
    section.streaming = !type.endsWith('_done')
  }
  section.updatedAt = Date.now()
  return true
}

export function resetWorkflow({ title = '', pathId = null, nodeId = null, resourceTypes = [], workflowKind = 'resource', displayMode = 'graph' } = {}) {
  workflowState.available = true
  workflowState.open = false
  workflowState.workflowKind = workflowKind
  workflowState.displayMode = displayMode
  workflowState.title = title
  workflowState.pathId = pathId
  workflowState.nodeId = nodeId
  workflowState.activeAgentId = 'leader'
  workflowState.plannedResourceTypes = [...new Set(resourceTypes.map((item) => String(item).trim().toLowerCase()).filter(Boolean))]
  // 只有收到真实的 executor/resource 事件后，才把资源类型加入展示分支。
  // plannedResourceTypes 仅用于记录 Leader 的规划，不能代表任务已启动。
  workflowState.resourceTypes = []
  workflowState.nodes = {}
  activePhases().forEach((phase) => { workflowState.nodes[phase.id] = makeNode(phase.id, phase.agentName, phase.id) })
  workflowState.sections = {}
  workflowState.events = []
  workflowState.reportedPhases = []
  workflowState.reviewSkipped = false
  workflowState.reviewSkipMessage = ''
  workflowState.currentMessage = '等待资源生成服务开始'
  workflowState.progress = 0
  workflowState.startedAt = Date.now()
  workflowState.finishedAt = 0
  workflowState.updatedAt = Date.now()
}

export function applyWorkflowEvent(event) {
  if (!event || event.type !== 'agent_event') return
  updateNode(event)
  if (isReviewSkipEvent(event)) markReviewSkipped(String(event.message || '').trim())
  if (!recordSectionEvent(event)) recordWholeResourceReview(event)
}

export function applyWorkflowProgress(event) {
  if (!event || event.type === 'agent_event') return
  // 章节正文流只喂章节看板，不再往下走：这些事件没有 message，落到通用分支里
  // 只会把 currentMessage 冲成一句"正在处理"，反而盖掉真实进度文案。
  if (applySectionStream(event)) return
  const type = String(event.type || '').toLowerCase()
  const message = String(event.progress_msg || event.progressMsg || event.message || event.msg || '')
  const resourceType = String(event.resource_type || event.resourceType || event.file_type || event.fileType || '').trim().toLowerCase()
  if (event.error || type === 'error') {
    updateNode({
      type: 'agent_event',
      agent_id: 'complete',
      agent_name: '流程失败',
      phase: 'complete',
      status: 'failed',
      message: String(event.error || message || '资源生成失败'),
    })
    return
  }
  if (event.done || type === 'done') {
    finishWorkflow(String(event.status || '').toLowerCase() === 'failed')
    return
  }
  if (type === 'resource' || type === 'file') {
    applyWorkflowResource(resourceType, message || '资源已就绪')
    return
  }
  if (!message && !resourceType && type !== 'stream_start') return
  workflowState.currentMessage = message || (type === 'stream_start' ? '正在启动资源生成' : '正在处理')
  workflowState.progress = Math.max(0, Math.min(100, Number(event.progress || event.percent || workflowState.progress || 0)))
  // status 消息同时进"实时动态"。收尾时 finishWorkflow 会把 currentMessage 覆盖成
  // "资源准备完成"，只放在 currentMessage 里的话，等用户打开抽屉时后端那句说明
  // （例如"资源已存在，本次直接复用，未重新生成"）已经被冲掉了。
  if (message) {
    workflowState.events = [...workflowState.events, {
      type: 'status',
      agent_id: 'status',
      agent_name: '流程状态',
      phase: 'status',
      status: 'running',
      message,
      updatedAt: Date.now(),
    }].slice(-80)
  }
  workflowState.updatedAt = Date.now()
}

export function applyWorkflowResource(resourceType, message = '资源已就绪') {
  const type = String(resourceType || '').trim().toLowerCase()
  if (!type) return
  if (!workflowState.resourceTypes.includes(type)) workflowState.resourceTypes.push(type)
  updateNode({
    type: 'agent_event',
    agent_id: `executor:${type}`,
    agent_name: resourceAgentLabels[type] || `${type} 智能体`,
    phase: 'executor',
    status: 'done',
    message,
    resource_type: type,
  })
}

// 章节卡片状态：生成和审核两维的合成。抽屉里的芯片和章节卡片**共用这一处** ——
// 以前两边各写一份，注释写着"必须一致"，而实际上已经不一致了：抽屉把"生成完成"就算
// 完成，卡片还要求审核完成，于是同一节在芯片上是已完成、在卡片上是待审核。
//
// 判定顺序有讲究：失败优先（任意一维失败就是这张卡有问题），然后是谁正在动，
// 最后才轮到完成。
const SECTION_ACTIVE_STATUSES = new Set(['running', 'reviewing', 'retrying', 'saving'])

export function sectionStatus(section) {
  if (!section) return 'pending'
  const genStatus = normalizeStatus(section.genStatus)
  const reviewStatus = normalizeStatus(section.reviewStatus)
  if (genStatus === 'failed' || reviewStatus === 'failed') return 'failed'
  const active = [reviewStatus, genStatus].find((status) => SECTION_ACTIVE_STATUSES.has(status))
  if (active) return active
  // 审核被跳过（这一轮压根不审）：生成完就算这一节做完了，卡上显示"已完成"，
  // 审核那一行会写明"本次未做章节审核"。卡在"待审核"才是假的 —— 不会有人来审。
  if (genStatus === 'done') return 'done'
  if (reviewStatus === 'done' || reviewStatus === 'skipped') return 'done'
  return 'pending'
}

export function finishWorkflow(failed = false) {
  const finalStatus = failed ? 'failed' : 'done'
  // 收尾时把"没等到审核结论"的章节落成未审核：流程已经结束，审核要么跑完了、
  // 要么这一轮就没打算跑（单节文档不走跨章节检查、画像引入页不审、skip_review）。
  // 留一句"待审核"等于告诉学生还有事没做完 —— 那是假的。
  Object.values(workflowState.sections).forEach((section) => {
    if (section.reviewStatus !== 'pending') return
    section.reviewStatus = 'skipped'
    section.reviewMessage = REVIEW_SKIPPED_MESSAGE
    section.updatedAt = Date.now()
  })
  if (workflowState.activeAgentId === 'complete' && workflowState.nodes.complete?.status === finalStatus) {
    // 资源任务收尾时会先发一条 phase='complete' 的 agent_event、紧跟一条 type='done'
    // （backend/src/service/resource/service.py:745/754）。前者已经把 complete 节点置成
    // 终态，所以真正的 done 进来时守卫就命中了。节点不必再扫一遍，但进度和结束时间
    // 还停在上一次 status 事件的值（通常 70%，"AI 审核中"那一档），必须补上，
    // 否则抽屉会永远显示 70%。这里保持幂等，重复调用不会改结果。
    if (!failed) workflowState.progress = 100
    if (!workflowState.finishedAt) workflowState.finishedAt = Date.now()
    return
  }
  Object.values(workflowState.nodes).forEach((node) => {
    if (failed) {
      if (node.status === 'pending') node.message = '未执行'
      if (node.status !== 'failed') node.status = node.status === 'pending' ? 'skipped' : 'failed'
    } else if (node.status === 'pending') {
      // 走到这里说明这个阶段从头到尾没上报过任何事件。措辞要区分于"跑过但失败/跳过"：
      // "本次未涉及"是陈述事实，不像"未执行或资源已复用"那样读起来像出了故障。
      node.status = 'skipped'
      node.message = '本次未涉及'
    } else if (node.status !== 'failed') {
      node.status = finalStatus
    }
    node.updatedAt = Date.now()
    if (!failed && !node.message) node.message = '已完成'
  })
  workflowState.currentMessage = failed ? '资源生成失败' : '资源准备完成'
  workflowState.progress = failed ? workflowState.progress : 100
  workflowState.finishedAt = Date.now()
  updateNode({
    type: 'agent_event',
    agent_id: 'complete',
    agent_name: failed ? '流程失败' : '流程完成',
    phase: 'complete',
    status: finalStatus,
    message: failed ? '资源生成失败' : '本章资源已准备完成',
  })
}

export function setWorkflowOpen(open) {
  workflowState.open = Boolean(open)
}

export function setWorkflowExpanded(expanded) {
  workflowState.expanded = Boolean(expanded)
}
