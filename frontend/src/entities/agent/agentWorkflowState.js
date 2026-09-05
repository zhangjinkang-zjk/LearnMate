import { reactive } from 'vue'

export const workflowPhases = [
  { id: 'leader', label: '需求规划', agentName: 'LeaderAgent' },
  { id: 'executor', label: '并行生成', agentName: 'ExecutorAgent' },
  { id: 'reviewer', label: '质量审核', agentName: 'ReviewerAgent' },
  { id: 'saver', label: '保存资源', agentName: 'ResourceService' },
  { id: 'complete', label: '完成', agentName: '流程状态' },
]

export const resourceAgentLabels = {
  document: '文档生成智能体',
  mindmap: '思维导图智能体',
  ppt: 'PPT 生成智能体',
  exercise: '习题生成智能体',
  image: '图片生成智能体',
  video: '视频生成智能体',
  case: '案例资料智能体',
  reading: '阅读材料智能体',
}

export const workflowState = reactive({
  available: false,
  open: false,
  workflowKind: 'resource',
  displayMode: 'graph',
  title: '',
  pathId: null,
  nodeId: null,
  activeAgentId: '',
  plannedResourceTypes: [],
  resourceTypes: [],
  nodes: {},
  events: [],
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
    const definition = workflowPhases.find((item) => item.id === phase)
    workflowState.nodes[phase] = makeNode(
      phase,
      definition?.agentName || phase,
      phase,
    )
  }
  return workflowState.nodes[phase]
}

function markPreviousPhasesDone(phase) {
  const phaseIndex = workflowPhases.findIndex((item) => item.id === phase)
  if (phaseIndex <= 0) return
  workflowPhases.slice(0, phaseIndex).forEach((item) => {
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
  workflowPhases.forEach((phase) => { workflowState.nodes[phase.id] = makeNode(phase.id, phase.agentName, phase.id) })
  workflowState.events = []
  workflowState.currentMessage = '等待资源生成服务开始'
  workflowState.progress = 0
  workflowState.startedAt = Date.now()
  workflowState.finishedAt = 0
  workflowState.updatedAt = Date.now()
}

export function applyWorkflowEvent(event) {
  if (!event || event.type !== 'agent_event') return
  updateNode(event)
}

export function applyWorkflowProgress(event) {
  if (!event || event.type === 'agent_event') return
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

export function finishWorkflow(failed = false) {
  const finalStatus = failed ? 'failed' : 'done'
  if (workflowState.activeAgentId === 'complete' && workflowState.nodes.complete?.status === finalStatus) return
  Object.values(workflowState.nodes).forEach((node) => {
    if (failed) {
      if (node.status === 'pending') node.message = '未执行'
      if (node.status !== 'failed') node.status = node.status === 'pending' ? 'skipped' : 'failed'
    } else if (node.status === 'pending') {
      node.status = 'skipped'
      node.message = '未执行或资源已复用'
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
