<template>
  <div class="advanced-page">
    <PageTitle eyebrow="ADVANCED PRACTICE" title="应用实践 · 进阶学习">
      <template #actions><button v-if="practiceOpen" class="button button--quiet" type="button" @click="closePractice"><ArrowLeft :size="15" />返回任务选择</button><button v-else class="button button--quiet" type="button" :disabled="loading" @click="loadTask"><RefreshCw :size="15" />重新同步</button></template>
    </PageTitle>

    <section v-if="loading" class="surface surface-pad state-panel" aria-live="polite"><LoaderCircle class="spin" :size="20" /><div><strong>正在整理实践任务</strong><p>系统正在读取你的学习目标、路径进度和能力诊断。</p></div></section>
    <section v-else-if="errorMessage" class="surface surface-pad state-panel state-panel--error"><CircleAlert :size="20" /><div><strong>暂时无法读取实践任务</strong><p>{{ errorMessage }}</p></div><button class="button button--quiet" type="button" @click="loadTask">重试</button></section>
    <section v-else-if="!task" class="surface surface-pad empty-panel"><p class="eyebrow">进阶学习</p><h2>{{ learningStatus === 'locked' ? '先完成基础学习，再进入实践' : '还没有可开始的实践任务' }}</h2><p v-if="learningStatus === 'locked'">已完成 {{ milestone.completed_nodes }} / {{ milestone.unlock_nodes }} 个基础学习节点，还需 {{ milestone.remaining }} 个节点解锁第一组进阶任务。</p><p v-else>完成基础讲解和基础测试后，系统会在下一个学习里程碑生成实践入口。</p><RouterLink class="button button--primary" to="/learning/fundamentals">继续基础学习</RouterLink></section>

    <template v-else>
      <template v-if="!practiceOpen">
      <section class="learning-snapshot">
        <div class="snapshot-item"><span>当前身份</span><strong>{{ profile.identity || '学习者' }}</strong></div>
        <div class="snapshot-item"><span>当前目标</span><strong>{{ profile.goal || '建立系统化知识基础' }}</strong></div>
        <div class="snapshot-item"><span>学习方向</span><strong>{{ profile.direction || '当前学习方向' }}</strong></div>
        <div class="snapshot-item snapshot-item--progress"><span>基础节点</span><strong>{{ path.completed_nodes ?? 0 }} / {{ path.total_nodes ?? 0 }}</strong><div class="progress-track"><div class="progress-value" :style="{ width: `${path.progress}%` }"></div></div></div>
      </section>

      <section class="decision-layout">
        <article class="surface surface-pad recommendation-card">
          <div class="recommendation-card__heading"><div><p class="eyebrow">{{ task.is_recommended ? '系统推荐任务' : '当前选择任务' }}</p><h2>{{ task.kind_label || '案例诊断' }}</h2></div><span class="recommendation-badge">{{ task.difficulty_label || '建议先做' }}</span></div>
          <h3>{{ task.title }}</h3>
          <p>{{ task.brief }}</p>
          <p v-if="taskSummary" class="task-summary">{{ taskSummary }}</p>
          <div class="task-scenario"><span class="block-label">任务情境</span><p>{{ task.scenario || task.problem }}</p></div>
          <div class="recommendation-facts"><span><strong>{{ task.context?.focus || task.focus || '当前薄弱点' }}</strong>重点能力</span><span><strong>{{ task.context?.mastery_label || '暂无测验证据' }}</strong>基础证据</span><span><strong>{{ task.deliverables?.length || 0 }}</strong>项交付</span></div>
          <button class="button button--primary" type="button" :disabled="practiceLoading" @click="startPractice"><LoaderCircle v-if="practiceLoading" class="spin" :size="15" /><ArrowRight v-else :size="15" />开始实践巩固</button>
        </article>
        <aside class="surface surface-pad decision-reason"><p class="eyebrow">推荐依据</p><h2>根据你的基础学习</h2><p>{{ task.context?.reason || task.recommendation || '系统会根据当前学习节点生成实践入口。' }}</p><div class="decision-reason__line"><span>学习节点</span><strong>{{ task.context?.node_title || '当前节点' }}</strong></div><div class="decision-reason__line"><span>节点状态</span><strong>{{ task.context?.node_status_label || path.stage || '学习中' }}</strong></div><div class="decision-reason__line"><span>学习材料</span><strong>{{ task.context?.resource_label || `${task.resources?.length || 0} 份关联材料` }}</strong></div><div class="decision-reason__line"><span>路径进度</span><strong>{{ path.stage || '基础到应用' }}</strong></div></aside>
      </section>

      <section v-if="optionalTasks.length" class="task-catalog"><div class="catalog-heading"><div><p class="eyebrow">可选实践任务</p><h2>换一个情境练习迁移</h2></div><span>第 {{ milestone.current }} 个里程碑 · {{ optionalTasks.length }} 个可选任务</span></div><div class="catalog-grid" role="list">
        <button v-for="item in optionalTasks" :key="item.id" type="button" class="catalog-card" :class="{ 'is-selected': item.id === task.id }" :aria-pressed="item.id === task.id" :aria-label="`选择${item.kind_label || '实践任务'}：${item.title}`" @click="selectTask(item)"><span class="catalog-card__top"><strong>{{ item.kind_label || '实践任务' }}</strong><small>{{ item.difficulty_label || '当前阶段' }}</small></span><h3>{{ item.title }}</h3><p>{{ item.why || item.brief }}</p><span class="catalog-card__footer"><span>{{ item.id === task.id ? '当前已选' : item.status === 'completed' ? '已完成' : '选择任务' }}</span><ArrowUpRight :size="14" /></span></button>
      </div></section>
      </template>

      <template v-else>
        <section class="session-context surface">
          <div class="session-context__identity"><span class="session-context__kind">{{ task.kind_label || '实践任务' }}</span><div><strong>{{ task.title }}</strong><p>{{ task.brief }}</p></div></div>
          <div class="session-context__facts"><span><b>{{ task.focus || '当前薄弱点' }}</b>重点能力</span><span><b>{{ selectedWorkspace.nodeId || '当前节点' }}</b>关联节点</span><span><b>{{ task.deliverables?.length || 0 }}</b>项成果</span></div>
        </section>
        <PracticeDialogue v-if="!sessionEnded && hasWorkspace" :key="task.id" :path-id="selectedWorkspace.pathId" :node-id="selectedWorkspace.nodeId" :task="task" :chapter-content="chapterContent" :resource-id="resourceId" @end="endPractice" />
        <section v-else-if="!sessionEnded" class="surface surface-pad state-panel state-panel--error"><CircleAlert :size="20" /><div><strong>实践任务缺少关联节点</strong><p>请重新同步任务后再开始巩固。</p></div><button class="button button--quiet" type="button" @click="loadTask">重新同步</button></section>
        <section v-else class="surface surface-pad session-ended"><span class="session-ended__mark">✓</span><p class="eyebrow">本次巩固已结束</p><h2>对话过程已经保存</h2><p>你可以返回任务选择，或继续当前实践。</p><div><button class="button button--quiet" type="button" @click="sessionEnded = false">继续这个任务</button><button class="button button--primary" type="button" @click="closePractice">返回任务选择</button></div></section>
      </template>
    </template>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { ArrowLeft, ArrowRight, ArrowUpRight, CircleAlert, LoaderCircle, RefreshCw } from 'lucide-vue-next'
import { useRoute } from 'vue-router'
import PracticeDialogue from '@/features/advanced/PracticeDialogue.vue'
import PageTitle from '@/shared/ui/PageTitle.vue'
import { advancedLearningApi } from '@/shared/api/advancedLearningApi'
import { fundamentalsApi } from '@/shared/api/fundamentalsApi'

const route = useRoute()
const loading = ref(true)
const errorMessage = ref('')
const learningStatus = ref('')
const taskSummary = ref('')
const task = ref(null)
const tasks = ref([])
const practiceOpen = ref(false)
const practiceLoading = ref(false)
const sessionEnded = ref(false)
const chapterContent = ref('')
const resourceId = ref(null)
const profile = reactive({ identity: '', direction: '', goal: '' })
const path = reactive({ stage: '', progress: 0, completed_nodes: 0, total_nodes: 0 })
const milestone = reactive({ size: 10, unlock_nodes: 10, completed_nodes: 0, current: 0, next: 10, remaining: 10 })
const unwrap = (response) => response?.data?.data ?? response?.data ?? null
function getTaskWorkspace(value) {
  const workspace = value?.workspace || {}
  return {
    pathId: workspace.path_id ?? workspace.pathId ?? value?.path_id ?? value?.pathId ?? null,
    nodeId: workspace.node_id ?? workspace.nodeId ?? value?.node_id ?? value?.nodeId ?? null,
  }
}

const optionalTasks = computed(() => tasks.value.filter((item) => !item.is_recommended).slice(0, 2))
const selectedWorkspace = computed(() => getTaskWorkspace(task.value))
const hasWorkspace = computed(() => selectedWorkspace.value.pathId !== null && selectedWorkspace.value.nodeId !== null)

async function loadTask() {
  loading.value = true
  errorMessage.value = ''
  try {
    const result = unwrap(await advancedLearningApi.getCurrentTask())
    learningStatus.value = result?.status || ''
    taskSummary.value = result?.task_summary || ''
    Object.assign(profile, result?.profile || {})
    Object.assign(path, result?.path || { stage: '', progress: 0, completed_nodes: 0, total_nodes: 0 })
    Object.assign(milestone, result?.milestone || {})
    const source = Array.isArray(result?.tasks) && result.tasks.length ? result.tasks : (result?.task ? [result.task] : [])
    tasks.value = result?.status === 'ready' ? source : []
    task.value = tasks.value.find((item) => String(item.id) === String(route.query.taskId)) || tasks.value.find((item) => item.status === 'active') || tasks.value[0] || null
  } catch (error) {
    errorMessage.value = error.response?.data?.detail || error.message || '请检查后端服务后重新同步。'
  } finally { loading.value = false }
}

function selectTask(item) {
  task.value = item
}

function normalizeContent(value) {
  if (typeof value === 'string') return value
  if (value && typeof value === 'object') return String(value.markdown || value.content || value.text || '')
  return ''
}

async function loadNodeContext() {
  chapterContent.value = ''
  resourceId.value = null
  if (!hasWorkspace.value) return
  try {
    const detail = await fundamentalsApi.getNode(selectedWorkspace.value.pathId, selectedWorkspace.value.nodeId)
    const resources = detail?.progress?.resources || detail?.resources || []
    const documentResource = resources.find((resource) => resource.resource_type === 'document')
    resourceId.value = documentResource?.resource_id || documentResource?.id || null
    if (resourceId.value) {
      const resource = await fundamentalsApi.getResource(resourceId.value)
      chapterContent.value = normalizeContent(resource?.content || documentResource?.content)
    } else chapterContent.value = normalizeContent(documentResource?.content)
  } catch {
    chapterContent.value = ''
  }
}

async function startPractice() {
  if (!task.value || practiceLoading.value) return
  practiceLoading.value = true
  sessionEnded.value = false
  await loadNodeContext()
  practiceOpen.value = true
  practiceLoading.value = false
}

function closePractice() {
  practiceOpen.value = false
  sessionEnded.value = false
}

function endPractice() {
  sessionEnded.value = true
}

onMounted(async () => {
  await loadTask()
  if (route.query.taskId && task.value) await startPractice()
})
</script>

<style scoped>
.advanced-page { min-width: 0; }
.advanced-page :deep(.page-heading) { margin-bottom: 20px; }
.advanced-page :deep(.page-heading p) { max-width: 640px; font-size: 13px; }
.advanced-page :deep(.page-heading .eyebrow) { margin-bottom: 10px; color: var(--muted); font-size: 13px; letter-spacing: .14em; }
.advanced-page :deep(.page-heading h1) { font-size: clamp(28px, 3vw, 38px); line-height: 1.2; }
.button { gap: 8px; }.button:disabled { cursor: wait; opacity: .55; }
.state-panel { display: flex; align-items: center; gap: 14px; min-height: 96px; color: var(--accent-deep); }.state-panel > div { min-width: 0; flex: 1; }.state-panel p, .empty-panel p { margin: 5px 0 0; color: var(--muted); font-size: 13px; line-height: 1.7; }.state-panel--error { color: #954e38; }.spin { animation: spin 1s linear infinite; }.empty-panel { max-width: 720px; }.empty-panel h2 { margin: 0; font-size: 22px; }.empty-panel > p:not(.eyebrow) { margin-bottom: 20px; }
.learning-snapshot { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 1px; margin-bottom: 14px; border: 1px solid var(--line); border-radius: 7px; background: var(--line); overflow: hidden; }.snapshot-item { display: grid; min-width: 0; gap: 6px; padding: 12px 14px; background: var(--paper); }.snapshot-item span { color: var(--muted); font-size: 10px; }.snapshot-item strong { min-width: 0; overflow: hidden; color: var(--ink); font-size: 13px; text-overflow: ellipsis; white-space: nowrap; }.snapshot-item--progress strong { color: var(--accent-deep); font-size: 17px; }.snapshot-item--progress .progress-track { height: 5px; margin-top: 1px; }
.decision-layout { display: grid; grid-template-columns: minmax(0, 1.35fr) minmax(245px, .65fr); gap: 14px; margin-bottom: 20px; }.recommendation-card, .decision-reason { min-width: 0; padding: 18px; }.recommendation-card { border-color: #d3e0c7; background: #f8fbf3; }.recommendation-card__heading { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; }.recommendation-card__heading > div { min-width: 0; }.recommendation-card__heading h2 { margin: 0; font-size: 17px; }.recommendation-badge { max-width: 42%; padding: 5px 8px; border: 1px solid #d5e2c8; border-radius: 4px; color: var(--accent-deep); font-size: 10px; font-weight: 800; line-height: 1.3; text-align: right; }.recommendation-card h3 { margin: 17px 0 7px; overflow-wrap: anywhere; font-size: clamp(18px, 2vw, 22px); line-height: 1.4; }.recommendation-card > p { max-width: 720px; margin: 0; color: #536057; font-size: 12px; line-height: 1.7; }.recommendation-facts { display: flex; flex-wrap: wrap; gap: 18px; margin: 17px 0 15px; padding-top: 13px; border-top: 1px solid #dbe7d2; }.recommendation-facts span { display: grid; gap: 3px; color: var(--muted); font-size: 10px; }.recommendation-facts strong { color: var(--ink); font-size: 12px; overflow-wrap: anywhere; }.decision-reason h2 { margin: 0; font-size: 18px; }.decision-reason > p:not(.eyebrow) { margin: 9px 0 17px; color: var(--muted); font-size: 12px; line-height: 1.7; }.decision-reason__line { display: flex; justify-content: space-between; gap: 12px; padding-top: 10px; border-top: 1px solid var(--line); color: var(--muted); font-size: 10px; }.decision-reason__line + .decision-reason__line { margin-top: 9px; }.decision-reason__line strong { min-width: 0; color: var(--ink); font-size: 11px; overflow-wrap: anywhere; text-align: right; }
.task-catalog { padding-top: 1px; }.catalog-heading { display: flex; align-items: flex-end; justify-content: space-between; gap: 18px; margin-bottom: 11px; }.catalog-heading h2 { margin: 0; font-size: 18px; }.catalog-heading > span { color: var(--muted); font-size: 11px; }.catalog-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 10px; }.catalog-card { display: grid; min-width: 0; min-height: 142px; align-content: start; gap: 7px; padding: 13px; border: 1px solid var(--line); border-radius: 7px; background: var(--paper); color: var(--ink); text-align: left; transition: border-color .16s ease, background .16s ease, transform .16s ease; }.catalog-card:hover { border-color: #b9c9b2; transform: translateY(-1px); }.catalog-card.is-selected { border-color: var(--accent-deep); background: #f4f8ed; box-shadow: inset 3px 0 0 var(--accent-deep); }.catalog-card__top, .catalog-card__footer { display: flex; align-items: center; justify-content: space-between; gap: 8px; }.catalog-card__top strong { color: var(--accent-deep); font-size: 10px; }.catalog-card__top small { color: var(--muted); font-size: 10px; }.catalog-card h3 { margin: 4px 0 0; overflow-wrap: anywhere; font-size: 13px; line-height: 1.45; }.catalog-card p { display: -webkit-box; min-height: 36px; margin: 0; overflow: hidden; color: var(--muted); font-size: 11px; line-height: 1.6; -webkit-box-orient: vertical; -webkit-line-clamp: 2; }.catalog-card__footer { margin-top: auto; color: var(--muted); font-size: 10px; }
.task-scenario { margin-top: 15px; padding: 11px 12px; border-left: 3px solid #c8d9b7; background: #f1f6eb; }.task-scenario p { margin: 5px 0 0; color: #536057; font-size: 12px; line-height: 1.65; overflow-wrap: anywhere; }
.task-summary { margin-top: 8px !important; color: var(--accent-deep) !important; font-size: 11px !important; }
.session-context { display: grid; grid-template-columns: minmax(0, 1fr) auto; align-items: center; gap: 18px; margin-bottom: 12px; padding: 14px 17px; }
.session-context__identity { display: flex; min-width: 0; align-items: flex-start; gap: 12px; }
.session-context__identity > div { min-width: 0; }
.session-context__kind { flex: 0 0 auto; padding: 5px 8px; border: 1px solid #d7e3c9; border-radius: 4px; background: #f3f8ea; color: var(--accent-deep); font-size: 10px; font-weight: 800; }
.session-context strong { display: -webkit-box; overflow: hidden; color: var(--ink); font-size: 14px; line-height: 1.4; -webkit-box-orient: vertical; -webkit-line-clamp: 2; }
.session-context p { max-width: 650px; margin: 4px 0 0; color: var(--muted); font-size: 11px; line-height: 1.55; }
.session-context__facts { display: grid; grid-auto-flow: column; grid-auto-columns: minmax(66px, auto); gap: 18px; flex: 0 0 auto; }
.session-context__facts span { display: grid; gap: 3px; color: var(--muted); font-size: 10px; text-align: right; }
.session-context__facts b { color: var(--ink); font-size: 11px; overflow-wrap: anywhere; }
.session-ended { display: grid; min-height: min(480px, calc(100vh - 300px)); place-items: center; align-content: center; gap: 10px; text-align: center; }
.session-ended__mark { display: grid; width: 54px; height: 54px; place-items: center; border-radius: 50%; background: #e8f2de; color: var(--accent-deep); font-size: 24px; }
.session-ended h2 { margin: 0; font-size: 23px; }
.session-ended > p:not(.eyebrow) { max-width: 500px; margin: 0; color: var(--muted); font-size: 12px; line-height: 1.7; }
.session-ended > div { display: flex; gap: 9px; margin-top: 12px; }
@keyframes spin { to { transform: rotate(360deg); } }
@media (max-width: 900px) { .learning-snapshot { grid-template-columns: repeat(2, minmax(0, 1fr)); }.decision-layout { grid-template-columns: 1fr; }.catalog-grid { grid-template-columns: repeat(3, minmax(0, 1fr)); } }
@media (max-width: 700px) { .catalog-grid { grid-template-columns: 1fr; } }
@media (max-width: 560px) { .learning-snapshot { grid-template-columns: 1fr; }.catalog-heading { align-items: flex-start; flex-direction: column; gap: 6px; }.recommendation-card h3 { font-size: 19px; }.recommendation-facts { gap: 14px; }.recommendation-card .button { width: 100%; } }
@media (max-width: 760px) { .session-context { grid-template-columns: 1fr; align-items: flex-start; padding: 14px 15px; }.session-context__identity { width: 100%; }.session-context__facts { width: 100%; grid-auto-columns: minmax(0, 1fr); justify-content: space-between; }.session-context__facts span { text-align: left; } }
@media (max-width: 560px) { .session-ended > div { align-items: stretch; flex-direction: column; width: 100%; }.session-ended .button { width: 100%; } }
:global(.app-content:has(.advanced-page)) { background: #f7f7f7; }
:global(.page-container:has(.advanced-page)) { background: #f7f7f7; }
:global(.app-content:has(.advanced-page) .app-header) { border-bottom-color: #e8e8e8; background: #f7f7f7; }
:global(.page-container:has(.advanced-page)) { width: 100%; height: calc(100vh - 64px); box-sizing: border-box; margin: 0; padding: 28px 42px 58px; overflow-x: hidden; overflow-y: auto; }
.advanced-page h2 { color: #1e3c34; }
.advanced-page .surface { border-radius: 14px; border-color: rgba(63, 91, 49, .28); box-shadow: 0 8px 24px rgba(45, 40, 92, .07); }
.advanced-page .button { border-radius: 12px; }
.advanced-page .button--primary { border-color: #c4df3d; background: #b6d837; color: #1e3c34; box-shadow: 0 6px 14px rgba(63, 91, 49, .14); }
.advanced-page .button--primary:hover { border-color: #a9ca27; background: #a9ca27; color: #1e3c34; }
.advanced-page .button--quiet { border-color: #dce3dc; background: #fff; color: #3f5b31; }
.advanced-page .button--quiet:hover { border-color: #b9c9b2; background: #f1f6eb; }
.advanced-page .learning-snapshot { border-radius: 14px; }
.advanced-page .recommendation-card { border-radius: 16px; background: #f4f8ed; }
.advanced-page .decision-reason { border-radius: 16px; background: #f7f6fb; }
.advanced-page .task-scenario { border-radius: 0 12px 12px 0; background: #edf4e5; }
.advanced-page .catalog-card { border-radius: 12px; }
@media (max-width: 900px) { :global(.page-container:has(.advanced-page)) { height: auto; min-height: 0; padding: 28px 20px 58px; overflow: visible; } }
</style>
