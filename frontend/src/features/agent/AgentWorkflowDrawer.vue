<template>
  <Teleport to="body">
    <Transition name="agent-workflow-slide">
      <aside v-if="state.open && state.available" class="agent-workflow" role="dialog" aria-label="智能体工作流">
        <header class="agent-workflow__header">
          <div>
            <p class="eyebrow">AGENT WORKFLOW</p>
            <h2>智能体工作流</h2>
            <p>{{ state.title || '当前学习资源' }}</p>
          </div>
          <button class="agent-workflow__close" type="button" aria-label="关闭智能体工作流" title="关闭" @click="close">
            <X :size="17" />
          </button>
        </header>

        <section v-if="state.displayMode !== 'single'" class="agent-workflow__stages" aria-label="工作阶段">
          <div v-for="(stage, index) in stages" :key="stage.id" class="workflow-stage-wrap">
            <article class="workflow-stage" :class="[`is-${stage.status}`, { 'is-active': isActive(stage.status) }]">
              <span class="workflow-stage__icon"><Check v-if="stage.status === 'done'" :size="15" /><AlertCircle v-else-if="stage.status === 'failed'" :size="15" /><Minus v-else-if="stage.status === 'skipped'" :size="15" /><LoaderCircle v-else-if="isActive(stage.status)" class="spin" :size="15" /><Circle v-else :size="11" /></span>
              <div>
                <strong>{{ stage.label }}</strong>
                <small>{{ stage.message }}</small>
              </div>
            </article>
            <span v-if="index < stages.length - 1" class="workflow-connector" :class="{ 'is-lit': isConnectorLit(index) }" aria-hidden="true"></span>
          </div>
        </section>

        <section v-else class="workflow-single" aria-live="polite">
          <span class="workflow-single__icon"><LoaderCircle v-if="isBusy" class="spin" :size="18" /><Check v-else-if="isComplete" :size="18" /><AlertCircle v-else-if="isFailed" :size="18" /><Circle v-else :size="13" /></span>
          <div>
            <strong>{{ activeNode?.agent_name || state.title || '智能体' }}</strong>
            <p>{{ state.currentMessage || activeNode?.message || '等待智能体开始工作' }}</p>
          </div>
          <span v-if="state.progress" class="workflow-single__progress">{{ state.progress }}%</span>
        </section>

        <section v-if="state.displayMode !== 'single'" class="workflow-current" aria-live="polite">
          <span class="workflow-current__dot" :class="{ 'is-active': isBusy }"></span>
          <span>{{ state.currentMessage || '等待智能体开始工作' }}</span>
          <strong v-if="state.progress">{{ state.progress }}%</strong>
        </section>

        <section v-if="state.displayMode !== 'single' && branches.length" class="workflow-branches" aria-label="并行任务分支">
          <div class="workflow-section-heading"><span>{{ parallelTitle }}</span><small>{{ branches.length }} / {{ plannedCount }} 项已启动</small></div>
          <div v-if="branches.length > 1" class="workflow-parallel-hub" aria-hidden="true"><span>ExecutorAgent</span><i></i></div>
          <div class="workflow-branch-list">
            <article v-for="branch in branches" :key="branch.id" class="workflow-branch" :class="`is-${branch.status}`">
              <span class="workflow-branch__icon"><Check v-if="branch.status === 'done'" :size="14" /><AlertCircle v-else-if="branch.status === 'failed'" :size="14" /><Minus v-else-if="branch.status === 'skipped'" :size="14" /><LoaderCircle v-else-if="isActive(branch.status)" class="spin" :size="14" /><Circle v-else :size="10" /></span>
              <div class="workflow-branch__copy">
                <strong>{{ branch.label }}</strong>
                <small>{{ branch.message }}</small>
                <div v-if="branch.children.length" class="workflow-branch__children">
                  <span v-for="child in branch.children" :key="child.id" :class="`is-${child.status}`" :title="child.message">{{ child.label }}</span>
                  <em v-if="branch.hiddenChildren">+{{ branch.hiddenChildren }}</em>
                </div>
              </div>
              <span v-if="branch.progress" class="workflow-branch__progress">{{ branch.progress }}</span>
            </article>
          </div>
        </section>

        <section class="workflow-log" aria-label="实时动态">
          <div class="workflow-section-heading"><span>实时动态</span><small>{{ recentEvents.length }} 条</small></div>
          <div v-if="recentEvents.length" class="workflow-log__list">
            <p v-for="event in recentEvents" :key="event.key">
              <span :class="`is-${event.status}`"></span>
              <strong>{{ event.agent_name || event.agent_id }}</strong>
              <em>{{ event.message || statusLabel(event.status) }}</em>
            </p>
          </div>
          <p v-else class="workflow-log__empty">等待智能体开始工作…</p>
        </section>
      </aside>
    </Transition>
  </Teleport>
</template>

<script setup>
import { computed } from 'vue'
import { AlertCircle, Check, Circle, LoaderCircle, Minus, X } from 'lucide-vue-next'
import { resourceAgentLabels, workflowPhases, setWorkflowOpen } from '@/entities/agent/agentWorkflowState'

const props = defineProps({
  state: { type: Object, required: true },
})

const activeStatuses = new Set(['running', 'reviewing', 'retrying', 'saving'])
const isBusy = computed(() => activeStatuses.has(String(props.state.nodes?.[props.state.activeAgentId]?.status || '').toLowerCase()))
const activeNode = computed(() => props.state.nodes?.[props.state.activeAgentId] || null)
const isComplete = computed(() => String(activeNode.value?.status || '').toLowerCase() === 'done')
const isFailed = computed(() => String(activeNode.value?.status || '').toLowerCase() === 'failed')
const normalizeStatus = (status) => {
  const value = String(status || 'pending').toLowerCase()
  return ['pending', 'running', 'reviewing', 'retrying', 'saving', 'done', 'failed', 'skipped'].includes(value) ? value : 'pending'
}
const statusLabel = (status) => ({ pending: '等待中', running: '工作中', reviewing: '审核中', retrying: '修订中', saving: '保存中', done: '已完成', failed: '失败', skipped: '未执行' })[normalizeStatus(status)] || '等待中'
const isActive = (status) => activeStatuses.has(normalizeStatus(status))

const phaseCandidates = (phase) => Object.values(props.state.nodes || {})
  .filter((node) => node.phase === phase)
  .sort((left, right) => Number(right.updatedAt || 0) - Number(left.updatedAt || 0))

const aggregateStatus = (phase) => {
  const candidates = phaseCandidates(phase)
  if (!candidates.length) return 'pending'
  if (candidates.some((node) => normalizeStatus(node.status) === 'failed')) return 'failed'
  const active = candidates.find((node) => isActive(node.status))
  if (active) return normalizeStatus(active.status)
  if (candidates.some((node) => normalizeStatus(node.status) === 'done')) return 'done'
  return normalizeStatus(candidates[0].status)
}

const phaseMessage = (phase, status) => {
  const candidates = phaseCandidates(phase)
  const preferred = status === 'done'
    ? candidates.find((node) => normalizeStatus(node.status) === 'done')
    : candidates.find((node) => isActive(node.status)) || candidates.find((node) => normalizeStatus(node.status) === status)
  return preferred?.message || candidates[0]?.message || statusLabel(status)
}

const stages = computed(() => workflowPhases.map((phase) => ({
  ...phase,
  status: aggregateStatus(phase.id),
  message: phaseMessage(phase.id, aggregateStatus(phase.id)),
})))

const parallelTitle = computed(() => (props.state.resourceTypes || []).length > 1 ? '并行任务' : '任务分支')
const plannedCount = computed(() => Math.max(
  (props.state.plannedResourceTypes || []).length,
  (props.state.resourceTypes || []).length,
))

const childNodesForType = (type) => Object.values(props.state.nodes || {})
  .filter((node) => node.phase === 'executor' && String(node.resource_type || node.resourceType || '').toLowerCase() === type && String(node.agent_id || node.agentId || '').includes(':section-'))
  .sort((left, right) => Number(left.updatedAt || 0) - Number(right.updatedAt || 0))
  .map((node, index) => ({
    id: node.agent_id || node.agentId || `${type}-section-${index}`,
    label: `S${index + 1}`,
    status: normalizeStatus(node.status),
    message: node.message || statusLabel(node.status),
  }))

const branches = computed(() => [...new Set((props.state.resourceTypes || []).map((item) => String(item).toLowerCase()).filter(Boolean))]
  .map((type) => {
    const node = props.state.nodes?.[`executor:${type}`]
    const children = childNodesForType(type)
    return {
      id: `branch-${type}`,
      label: node?.agent_name || resourceAgentLabels[type] || `${type} 智能体`,
      status: normalizeStatus(node?.status),
      message: node?.message || statusLabel(node?.status),
      progress: node?.total ? `${node.current || 0}/${node.total}` : '',
      children: children.slice(0, 8),
      hiddenChildren: Math.max(children.length - 8, 0),
    }
  }))

const recentEvents = computed(() => (Array.isArray(props.state.events) ? props.state.events : [])
  .slice(-8)
  .reverse()
  .map((event, index) => ({
    ...event,
    key: `${event.agent_id || index}-${event.updatedAt || index}`,
    status: normalizeStatus(event.status),
  })))

const isConnectorLit = (index) => stages.value[index]?.status === 'done' || isActive(stages.value[index + 1]?.status)
const close = () => setWorkflowOpen(false)
</script>

<style scoped>
.agent-workflow { position: fixed; top: 78px; left: 128px; z-index: 90; display: grid; width: min(370px, calc(100vw - 150px)); max-height: calc(100vh - 98px); gap: 16px; overflow-y: auto; padding: 20px; border: 1px solid var(--line); border-radius: 8px; background: rgba(255,255,255,.98); box-shadow: 0 20px 50px rgba(3,20,13,.2); }
.agent-workflow__header { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; padding-bottom: 2px; }
.agent-workflow__header .eyebrow { margin-bottom: 6px; color: var(--muted); }
.agent-workflow__header h2 { margin: 0; color: var(--ink); font-size: 19px; }
.agent-workflow__header p:last-child { max-width: 260px; margin: 6px 0 0; overflow: hidden; color: var(--muted); font-size: 11px; line-height: 1.5; text-overflow: ellipsis; white-space: nowrap; }
.agent-workflow__close { display: grid; width: 30px; height: 30px; flex: 0 0 auto; place-items: center; border: 1px solid var(--line); border-radius: 5px; background: var(--paper); color: var(--muted); }
.agent-workflow__close:hover { color: var(--ink); background: var(--soft); }
.agent-workflow__stages { display: grid; gap: 0; }
.workflow-stage-wrap { display: grid; justify-items: start; }
.workflow-stage { display: grid; width: 100%; min-height: 58px; grid-template-columns: 32px minmax(0, 1fr); align-items: center; gap: 11px; padding: 10px 11px; border: 1px solid var(--line); border-radius: 6px; background: #fbfcfa; transition: border-color .18s ease, background .18s ease, box-shadow .18s ease; }
.workflow-stage.is-active { border-color: #a9bf91; background: #f5f9ef; box-shadow: 0 6px 16px rgba(63,91,49,.1); }
.workflow-stage.is-done { background: #f8fbf6; }
.workflow-stage.is-failed { border-color: #e1bba9; background: #fff9f4; }
.workflow-stage.is-skipped { background: #f6f7f4; }
.workflow-stage__icon, .workflow-branch__icon { display: grid; width: 28px; height: 28px; place-items: center; border-radius: 50%; background: #edf2ed; color: var(--muted); }
.workflow-stage.is-active .workflow-stage__icon { background: var(--accent); color: var(--accent-deep); }
.workflow-stage.is-done .workflow-stage__icon { background: var(--accent-deep); color: #fff; }
.workflow-stage.is-failed .workflow-stage__icon { background: #b96e4d; color: #fff; }
.workflow-stage.is-skipped .workflow-stage__icon { background: #dfe4dc; color: #7d897d; }
.workflow-stage strong, .workflow-branch strong { display: block; color: var(--ink); font-size: 12px; }
.workflow-stage small, .workflow-branch small { display: block; margin-top: 4px; overflow: hidden; color: var(--muted); font-size: 10px; line-height: 1.45; text-overflow: ellipsis; white-space: nowrap; }
.workflow-connector { width: 2px; height: 17px; margin-left: 24px; background: var(--line); }
.workflow-connector.is-lit { background: var(--accent-deep); }
.workflow-single { display: grid; grid-template-columns: 34px minmax(0, 1fr) auto; align-items: center; gap: 11px; min-height: 72px; padding: 13px; border: 1px solid #a9bf91; border-radius: 6px; background: #f5f9ef; }
.workflow-single__icon { display: grid; width: 32px; height: 32px; place-items: center; border-radius: 50%; background: var(--accent); color: var(--accent-deep); }
.workflow-single strong { display: block; color: var(--ink); font-size: 13px; }
.workflow-single p { margin: 5px 0 0; color: var(--muted); font-size: 11px; line-height: 1.5; }
.workflow-single__progress { color: var(--accent-deep); font-size: 11px; font-variant-numeric: tabular-nums; }
.workflow-current { display: grid; grid-template-columns: 8px minmax(0, 1fr) auto; align-items: center; gap: 8px; min-height: 34px; padding: 8px 10px; border: 1px solid var(--line); border-radius: 5px; background: #f5f8f3; color: var(--muted); font-size: 10px; line-height: 1.4; }
.workflow-current__dot { width: 7px; height: 7px; border-radius: 50%; background: #aeb9ae; }
.workflow-current__dot.is-active { background: var(--accent); box-shadow: 0 0 0 4px rgba(226,244,82,.24); animation: workflowCurrentPulse 1.2s ease-out infinite; }
.workflow-current strong { color: var(--accent-deep); font-size: 10px; font-variant-numeric: tabular-nums; }
.workflow-section-heading { display: flex; align-items: center; justify-content: space-between; gap: 12px; color: var(--ink); font-size: 12px; font-weight: 800; }
.workflow-section-heading small { color: var(--muted); font-size: 10px; font-weight: 500; }
.workflow-parallel-hub { display: grid; justify-items: center; margin: 10px 0 2px; color: var(--muted); font-size: 10px; }
.workflow-parallel-hub i { width: 1px; height: 10px; margin-top: 4px; background: var(--line); }
.workflow-branch-list { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 7px; margin-top: 10px; }
.workflow-log__list { display: grid; gap: 7px; margin-top: 10px; }
.workflow-branch { display: grid; grid-template-columns: 28px minmax(0, 1fr) auto; align-items: center; gap: 9px; min-height: 48px; padding: 8px 10px; border: 1px solid var(--line); border-radius: 5px; background: var(--paper); }
.workflow-branch.is-active { border-color: #a9bf91; background: #f5f9ef; }
.workflow-branch.is-done .workflow-branch__icon { background: var(--accent-deep); color: #fff; }
.workflow-branch.is-failed .workflow-branch__icon { background: #b96e4d; color: #fff; }
.workflow-branch.is-skipped { background: #f6f7f4; }
.workflow-branch.is-skipped .workflow-branch__icon { background: #dfe4dc; color: #7d897d; }
.workflow-branch__progress { color: var(--accent-deep); font-size: 10px; font-variant-numeric: tabular-nums; }
.workflow-branch__children { display: flex; flex-wrap: wrap; gap: 4px; margin-top: 7px; }
.workflow-branch__children span, .workflow-branch__children em { display: inline-grid; min-width: 22px; height: 18px; place-items: center; padding: 0 4px; border: 1px solid var(--line); border-radius: 3px; color: var(--muted); font-size: 9px; font-style: normal; line-height: 1; }
.workflow-branch__children span.is-running, .workflow-branch__children span.is-reviewing, .workflow-branch__children span.is-retrying, .workflow-branch__children span.is-saving { border-color: #a9bf91; background: #f5f9ef; color: var(--accent-deep); }
.workflow-branch__children span.is-done { border-color: #b7d2ad; background: #f3f8f0; color: #4e8650; }
.workflow-branch__children span.is-failed { border-color: #e1bba9; background: #fff9f4; color: #a65d43; }
.workflow-log { padding-top: 2px; border-top: 1px solid var(--line); }
.workflow-log__list p, .workflow-log__empty { display: grid; grid-template-columns: 7px auto minmax(0, 1fr); align-items: baseline; gap: 6px; margin: 7px 0 0; padding: 8px 9px; border-radius: 4px; background: var(--soft); color: var(--muted); font-size: 10px; line-height: 1.45; }
.workflow-log__list p > span { width: 6px; height: 6px; border-radius: 50%; background: #bbc5bc; }
.workflow-log__list p > span.is-running, .workflow-log__list p > span.is-reviewing, .workflow-log__list p > span.is-retrying, .workflow-log__list p > span.is-saving { background: var(--accent); }
.workflow-log__list p > span.is-done { background: #70aa63; }
.workflow-log__list p > span.is-failed { background: #b96e4d; }
.workflow-log__list strong { color: var(--ink); font-size: 10px; }
.workflow-log__list em { overflow: hidden; font-style: normal; text-overflow: ellipsis; white-space: nowrap; }
.spin { animation: spin .8s linear infinite; }
.agent-workflow-slide-enter-active, .agent-workflow-slide-leave-active { transition: opacity .2s ease, transform .2s ease; }
.agent-workflow-slide-enter-from, .agent-workflow-slide-leave-to { opacity: 0; transform: translateX(-12px); }
@keyframes spin { to { transform: rotate(360deg); } }
@keyframes workflowCurrentPulse { 0%, 100% { opacity: .65; } 50% { opacity: 1; } }
@media (max-width: 860px) { .agent-workflow { top: 74px; left: 14px; width: min(370px, calc(100vw - 28px)); max-height: calc(100vh - 90px); } }
@media (max-width: 430px) { .workflow-branch-list { grid-template-columns: 1fr; } }
@media (prefers-reduced-motion: reduce) { .spin, .workflow-current__dot.is-active { animation: none; } }
</style>
