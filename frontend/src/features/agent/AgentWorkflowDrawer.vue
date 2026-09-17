<template>
  <Teleport to="body">
    <Transition name="agent-workflow-slide">
      <aside v-if="state.open" class="agent-workflow" :class="{ 'is-expanded': state.expanded }" role="dialog" aria-label="智能体工作流">
        <header class="agent-workflow__header">
          <div>
            <p class="eyebrow">AGENT WORKFLOW</p>
            <h2>智能体工作流</h2>
            <p>{{ state.title || '暂无进行中的任务' }}</p>
          </div>
          <div class="agent-workflow__actions">
            <button
              class="agent-workflow__icon-btn"
              type="button"
              :aria-pressed="state.expanded"
              :aria-label="state.expanded ? '收起章节明细' : '展开章节明细'"
              :title="state.expanded ? '收起' : '展开章节明细'"
              @click="setWorkflowExpanded(!state.expanded)"
            >
              <Minimize2 v-if="state.expanded" :size="16" />
              <Maximize2 v-else :size="16" />
            </button>
            <button class="agent-workflow__icon-btn" type="button" aria-label="关闭智能体工作流" title="关闭" @click="close">
              <X :size="17" />
            </button>
          </div>
        </header>

        <!-- available 表示"本会话已经有流程可展示"。侧边栏入口现在常驻，所以用户可能
             在什么都没跑过时就打开这里 —— 那种情况下给一句说明，而不是五行假的"等待中"。 -->
        <!-- 两栏：左边流程与章节，右边实时动态。实时动态原本堆在最底下，
             面板就变成又窄又长的一条，横向空间全浪费了。 -->
        <template v-if="state.available">
        <div class="workflow-main">
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
            <div v-if="branches.length > 1" class="workflow-parallel-hub" aria-hidden="true"><span>领域知识生成智能体</span><i></i></div>
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

          <section class="workflow-global" aria-label="全局动态">
            <div class="workflow-section-heading"><span>全局动态</span><small>{{ globalEvents.length }} 条</small></div>
            <div v-if="globalEvents.length" class="workflow-global__list">
              <p v-for="event in globalEvents" :key="event.key">
                <span :class="`is-${event.status}`"></span>
                <strong>{{ event.agent_name || event.agent_id }}</strong>
                <em>{{ event.message || statusLabel(event.status) }}</em>
              </p>
            </div>
            <p v-else class="workflow-global__empty">等待智能体开始工作…</p>
          </section>
        </div>

        <section class="workflow-board" aria-label="实时动态">
          <div class="workflow-section-heading">
            <span>实时动态</span>
            <small>{{ boardSummary }}</small>
          </div>
          <div v-if="hasSections" class="workflow-board__tabs" role="tablist">
            <button
              v-for="tab in boardTabs"
              :key="tab.id"
              type="button"
              role="tab"
              :aria-selected="boardFilter === tab.id"
              :class="{ 'is-on': boardFilter === tab.id }"
              @click="boardFilter = tab.id"
            >
              {{ tab.label }}<em v-if="tab.count">{{ tab.count }}</em>
            </button>
          </div>
          <div v-if="boardSections.length" ref="boardListEl" class="workflow-board__grid">
            <WorkflowSectionCard v-for="section in boardSections" :key="section.key" :section="section" />
          </div>
          <p v-else class="workflow-board__empty">{{ boardEmptyMessage }}</p>
        </section>
        </template>

        <section v-else class="workflow-empty">
          <Circle :size="18" />
          <div>
            <strong>还没有智能体任务</strong>
            <p>当你生成学习资料、准备章节资源，或点开视频讲解时，这里会实时显示智能体的工作流程。</p>
          </div>
        </section>
      </aside>
    </Transition>
  </Teleport>
</template>

<script setup>
import { computed, nextTick, ref, watch } from 'vue'
import { AlertCircle, Check, Circle, LoaderCircle, Maximize2, Minimize2, Minus, X } from 'lucide-vue-next'
import { phasesForWorkflow, resourceAgentLabels, sectionedResourceTypes, sectionStatus, setWorkflowExpanded, setWorkflowOpen } from '@/entities/agent/agentWorkflowState'
import WorkflowSectionCard from './WorkflowSectionCard.vue'

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

// 阶段表按工作流种类取：资源流程是 leader/executor/reviewer/saver/complete，
// 诊断流程只有"学情诊断"。
const phases = computed(() => phasesForWorkflow(props.state.workflowKind))

const stages = computed(() => phases.value.map((phase) => ({
  ...phase,
  status: aggregateStatus(phase.id),
  message: phaseMessage(phase.id, aggregateStatus(phase.id)),
})))

const parallelTitle = computed(() => (props.state.resourceTypes || []).length > 1 ? '并行任务' : '任务分支')
const plannedCount = computed(() => Math.max(
  (props.state.plannedResourceTypes || []).length,
  (props.state.resourceTypes || []).length,
))

// 章节状态由"生成"和"审核"两维合成。这条规则和章节卡片共用同一个实现
// （agentWorkflowState.sectionStatus）—— 以前两边各写一份，注释写着"必须一致"，
// 实际已经不一致了：这里把"生成完成"就算完成，卡片还要求审核完成。
const sectionStatusOf = (section) => sectionStatus(section)

const sectionsOfType = (type) => Object.values(props.state.sections || {})
  .filter((section) => section.resourceType === type)
  .sort((left, right) => left.sectionIdx - right.sectionIdx)

// 章节芯片的数据源是 sections，不是 nodes。后端生成和审核共用同一个 section
// agent_id，而 nodes 只存每个 agent 的最新一条事件 —— reviewer 事件一到，那个节点的
// phase 就从 executor 变成 reviewer，被这里的 phase 过滤踢出去，章节一进审核就从
// 这排消失。sections 把两维分开存，不受这个覆盖影响。
const childNodesForType = (type) => sectionsOfType(type).map((section) => ({
  id: section.key,
  label: `S${section.sectionIdx + 1}`,
  status: sectionStatusOf(section),
  message: section.genMessage,
}))

// 进度按"已完成章节数/章节总数"算，不用后端那个 current —— 它只在整份 PPT 收尾时
// 才被补成 total（resource_graph.py:1157），中途一直是 0，会显示成 0/15。
const branchProgress = (type, node) => {
  const list = sectionsOfType(type)
  const totalCount = Math.max(list.length, Number(node?.total || 0))
  if (!totalCount) return ''
  const done = list.filter((section) => sectionStatusOf(section) === 'done').length
  return `${done}/${totalCount}`
}

const branches = computed(() => [...new Set((props.state.resourceTypes || []).map((item) => String(item).toLowerCase()).filter(Boolean))]
  .map((type) => {
    const node = props.state.nodes?.[`executor:${type}`]
    const children = childNodesForType(type)
    return {
      id: `branch-${type}`,
      label: node?.agent_name || resourceAgentLabels[type] || `${type} 智能体`,
      status: normalizeStatus(node?.status),
      message: node?.message || statusLabel(node?.status),
      progress: branchProgress(type, node),
      children: children.slice(0, 8),
      hiddenChildren: Math.max(children.length - 8, 0),
    }
  }))

// 左栏这条扁平流水只放"非章节"事件：章节的生成/审核明细已经在右栏按章节归好了，
// 再在这里重复一遍就是同一件事说两遍。留下的是全局叙述 —— Leader 规划、
// 资源类型级进度（"已生成 3/15 章节"）、保存与收尾。
const SECTION_AGENT_ID = /^executor:[a-z_]+:section-\d+$/
const globalEvents = computed(() => (Array.isArray(props.state.events) ? props.state.events : [])
  .filter((event) => !SECTION_AGENT_ID.test(String(event.agent_id || event.agentId || '')))
  .slice(props.state.expanded ? -14 : -8)
  .reverse()
  .map((event, index) => ({
    ...event,
    key: `${event.agent_id || index}-${event.updatedAt || index}`,
    status: normalizeStatus(event.status),
  })))

// ── 章节看板（宽档）──────────────────────────────────────────
const boardFilter = ref('all')
const allSections = computed(() => Object.values(props.state.sections || {}))
const hasSections = computed(() => allSections.value.length > 0)

const boardBuckets = computed(() => {
  const all = allSections.value
  return {
    all,
    failed: all.filter((section) => sectionStatusOf(section) === 'failed'),
    done: all.filter((section) => sectionStatusOf(section) === 'done'),
    open: all.filter((section) => {
      const status = sectionStatusOf(section)
      return status !== 'failed' && status !== 'done'
    }),
  }
})

const boardTabs = computed(() => [
  { id: 'all', label: '全部', count: boardBuckets.value.all.length },
  { id: 'open', label: '未完成', count: boardBuckets.value.open.length },
  { id: 'done', label: '已完成', count: boardBuckets.value.done.length },
  { id: 'failed', label: '异常', count: boardBuckets.value.failed.length },
])

// 严格按章节顺序，不按状态重排。
// 之前试过"异常顶到最前"，结果第 1 章一跑完就被归到"已完成"那一档、沉到最后，
// 看着像是乱序。要突出有问题的章节靠上面的筛选标签，不该动顺序 ——
// 位置稳定比"聪明"更重要，用户是拿这个列表当进度条读的。
// 同一章号可能同时有 ppt 和 document，先按资源类型分组，免得两份文档的章节交错在一起。
const boardSections = computed(() => [...(boardBuckets.value[boardFilter.value] || boardBuckets.value.all)]
  .sort((left, right) => (
    left.resourceType === right.resourceType
      ? left.sectionIdx - right.sectionIdx
      : String(left.resourceType).localeCompare(String(right.resourceType))
  )))

// "一张章节卡都没有"有三种完全不同的原因，不能共用一句话 —— 之前把第 3 种
// （PPT 还在规划大纲）说成了第 2 种，等于在自己的界面上谎报 PPT 没有章节粒度。
const boardEmptyMessage = computed(() => {
  if (hasSections.value) return '这个筛选下没有章节。'
  if (props.state.workflowKind === 'diagnosis') return '诊断流程没有章节明细，进度看左边。'
  const types = (props.state.resourceTypes || []).map((type) => String(type).toLowerCase())
  if (types.length && !types.some((type) => sectionedResourceTypes.includes(type))) {
    return '本次生成的资源没有章节粒度（思维导图、习题这类是整份生成的），进度看左边的「任务分支」「全局动态」。'
  }
  return '章节还没开始生成，进度看左边的「任务分支」「全局动态」。'
})

const boardSummary = computed(() => {
  if (!hasSections.value) return ''
  const { all, open, done, failed } = boardBuckets.value
  const totalCount = all.reduce((max, section) => Math.max(max, Number(section.total || 0)), all.length)
  const parts = [`共 ${totalCount} 章`, `已完成 ${done.length}`]
  if (open.length) parts.push(`未完成 ${open.length}`)
  if (failed.length) parts.push(`异常 ${failed.length}`)
  return parts.join(' · ')
})

// 新一轮任务开始时把筛选复位。否则上一轮筛在"异常"、这一轮没问题，打开就是一片空白。
watch(() => props.state.startedAt, () => { boardFilter.value = 'all' })

// ── 自动跟随 ────────────────────────────────────────────────
// 章节一多，"正在动"的那张卡经常在视口外。让列表跟着它走；用户一旦自己滚动就停 5 秒，
// 否则就是和用户抢滚动条（和视频讲解里正文自动跟随是同一个取舍）。
const FOLLOW_PAUSE_MS = 5000
let followPausedUntil = 0
const boardListEl = ref(null)
const noteUserScroll = () => { followPausedUntil = Date.now() + FOLLOW_PAUSE_MS }

watch(boardListEl, (el, previous) => {
  previous?.removeEventListener('wheel', noteUserScroll)
  previous?.removeEventListener('touchstart', noteUserScroll)
  el?.addEventListener('wheel', noteUserScroll, { passive: true })
  el?.addEventListener('touchstart', noteUserScroll, { passive: true })
})

// 可能同时有多个章节在跑（后端是并行的），取最近有动静的那个。
const activeSectionKey = computed(() => allSections.value
  .filter((section) => activeStatuses.has(sectionStatusOf(section)))
  .sort((left, right) => Number(right.updatedAt || 0) - Number(left.updatedAt || 0))[0]?.key || '')

watch(activeSectionKey, async (key) => {
  if (!key || Date.now() < followPausedUntil) return
  await nextTick()
  boardListEl.value?.querySelector(`[data-section-key="${key}"]`)?.scrollIntoView({ block: 'nearest', behavior: 'smooth' })
})

const isConnectorLit = (index) => stages.value[index]?.status === 'done' || isActive(stages.value[index + 1]?.status)
const close = () => setWorkflowOpen(false)
</script>

<style scoped>
/* 左栏固定一个"够读就行"的宽度放整体状态，右栏吃掉剩余空间放按章节铺开的实时动态 ——
   主角在右边。左栏刻意压窄：里面的五阶段/任务分支/全局动态都是概况，宽度超过 ~320px 后
   多出来的空间只是把文字拉稀，不如全部让给右边的章节卡。 */
.agent-workflow { position: fixed; top: 78px; left: 128px; z-index: 90; display: grid; grid-template-columns: minmax(0, 320px) minmax(0, 1fr); align-items: start; width: min(1000px, calc(100vw - 160px)); max-height: calc(100vh - 98px); gap: 16px; overflow-y: auto; padding: 20px; border: 1px solid var(--line); border-radius: 8px; background: rgba(255,255,255,.98); box-shadow: 0 20px 50px rgba(3,20,13,.2); }
.agent-workflow.is-expanded { width: min(1640px, calc(100vw - 168px)); }
.workflow-main { display: grid; align-content: start; gap: 16px; min-width: 0; }
.agent-workflow__header { grid-column: 1 / -1; display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; padding-bottom: 2px; }
.agent-workflow__header .eyebrow { margin-bottom: 6px; color: var(--muted); }
.agent-workflow__header h2 { margin: 0; color: var(--ink); font-size: 19px; }
.agent-workflow__header p:last-child { max-width: 260px; margin: 6px 0 0; overflow: hidden; color: var(--muted); font-size: 11px; line-height: 1.5; text-overflow: ellipsis; white-space: nowrap; }
.agent-workflow__actions { display: flex; flex: 0 0 auto; gap: 6px; }
.agent-workflow__icon-btn { display: grid; width: 30px; height: 30px; flex: 0 0 auto; place-items: center; border: 1px solid var(--line); border-radius: 5px; background: var(--paper); color: var(--muted); }
.agent-workflow__icon-btn:hover { color: var(--ink); background: var(--soft); }
.agent-workflow__icon-btn[aria-pressed="true"] { border-color: #a9bf91; background: #f5f9ef; color: var(--accent-deep); }
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
/* 自适应列数：左栏现在只有 320px，写死两列会把每张分支卡压到 ~150px，
   里面的 S1/S2 章节芯片会摊成好几行。minmax(240px) 在这个宽度下自然退成一列。 */
.workflow-branch-list { display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: 7px; margin-top: 10px; }
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
.workflow-board { position: sticky; top: 0; display: flex; flex-direction: column; gap: 10px; align-self: start; min-width: 0; max-height: calc(100vh - 220px); padding-left: 16px; border-left: 1px solid var(--line); }
.workflow-board__tabs { display: flex; flex-wrap: wrap; gap: 6px; }
.workflow-board__tabs button { display: inline-flex; align-items: center; gap: 5px; padding: 4px 10px; border: 1px solid var(--line); border-radius: 999px; background: var(--paper); color: var(--muted); font-size: 11px; }
.workflow-board__tabs button:hover { color: var(--ink); background: var(--soft); }
.workflow-board__tabs button.is-on { border-color: #a9bf91; background: var(--accent); color: var(--accent-deep); font-weight: 700; }
.workflow-board__tabs em { font-style: normal; font-size: 10px; font-variant-numeric: tabular-nums; opacity: .75; }
/* 章节必须从上到下一张接一张读，所以是单列。 */
.workflow-board__grid { display: grid; grid-template-columns: minmax(0, 1fr); gap: 9px; overflow-y: auto; min-height: 0; padding-right: 2px; }
.workflow-board__empty { margin: 0; padding: 12px; border: 1px dashed var(--line); border-radius: 5px; background: var(--soft); color: var(--muted); font-size: 11px; line-height: 1.6; }
.workflow-global { padding-top: 2px; border-top: 1px solid var(--line); }
.workflow-global__list p, .workflow-global__empty { display: grid; grid-template-columns: 7px auto minmax(0, 1fr); align-items: baseline; gap: 6px; margin: 7px 0 0; padding: 8px 9px; border-radius: 4px; background: var(--soft); color: var(--muted); font-size: 10px; line-height: 1.45; }
.workflow-empty { grid-column: 1 / -1; display: grid; grid-template-columns: 18px minmax(0, 1fr); align-items: start; gap: 10px; padding: 14px; border: 1px dashed var(--line); border-radius: 5px; background: var(--soft); color: var(--muted); }
.workflow-empty > div { display: grid; gap: 4px; }
.workflow-empty strong { color: var(--ink); font-size: 12px; }
.workflow-empty p { margin: 0; font-size: 11px; line-height: 1.6; }
.workflow-global__list p > span { width: 6px; height: 6px; border-radius: 50%; background: #bbc5bc; }
.workflow-global__list p > span.is-running, .workflow-global__list p > span.is-reviewing, .workflow-global__list p > span.is-retrying, .workflow-global__list p > span.is-saving { background: var(--accent); }
.workflow-global__list p > span.is-done { background: #70aa63; }
.workflow-global__list p > span.is-failed { background: #b96e4d; }
.workflow-global__list strong { color: var(--ink); font-size: 10px; }
.workflow-global__list em { overflow: hidden; font-style: normal; text-overflow: ellipsis; white-space: nowrap; }
.spin { animation: spin .8s linear infinite; }
.agent-workflow-slide-enter-active, .agent-workflow-slide-leave-active { transition: opacity .2s ease, transform .2s ease; }
.agent-workflow-slide-enter-from, .agent-workflow-slide-leave-to { opacity: 0; transform: translateX(-12px); }
@keyframes spin { to { transform: rotate(360deg); } }
@keyframes workflowCurrentPulse { 0%, 100% { opacity: .65; } 50% { opacity: 1; } }
/* 窄屏放不下两栏，退回单栏：实时动态回到最底部，边框也跟着换边。 */
@media (max-width: 860px) {
  .agent-workflow, .agent-workflow.is-expanded { top: 74px; left: 14px; width: min(370px, calc(100vw - 28px)); max-height: calc(100vh - 90px); grid-template-columns: minmax(0, 1fr); }
  .workflow-board { position: static; max-height: none; padding-left: 0; border-left: none; }
  .workflow-board__grid { overflow-y: visible; }
}
@media (max-width: 430px) { .workflow-branch-list { grid-template-columns: 1fr; } }
@media (prefers-reduced-motion: reduce) { .spin, .workflow-current__dot.is-active { animation: none; } }
</style>
