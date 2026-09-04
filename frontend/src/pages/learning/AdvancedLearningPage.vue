<template>
  <div class="advanced-page">
    <PageTitle eyebrow="应用实践 · 进阶学习" title="先选择要解决的问题" description="这里是实践任务目录。先看清任务和推荐依据，再进入学习巩固与 LearnMate 一起推演方案。">
      <template #actions><button class="button button--quiet" type="button" :disabled="loading" @click="loadTask"><RefreshCw :size="15" />重新同步</button></template>
    </PageTitle>

    <section v-if="loading" class="surface surface-pad state-panel" aria-live="polite"><LoaderCircle class="spin" :size="20" /><div><strong>正在整理实践任务</strong><p>系统正在读取你的学习目标、路径进度和能力诊断。</p></div></section>
    <section v-else-if="errorMessage" class="surface surface-pad state-panel state-panel--error"><CircleAlert :size="20" /><div><strong>暂时无法读取实践任务</strong><p>{{ errorMessage }}</p></div><button class="button button--quiet" type="button" @click="loadTask">重试</button></section>
    <section v-else-if="!task" class="surface surface-pad empty-panel"><p class="eyebrow">进阶学习</p><h2>还没有可开始的实践任务</h2><p>完成一部分基础讲解和基础测试后，系统会根据你的目标生成实践入口。</p><RouterLink class="button button--primary" to="/learning/fundamentals">回到基础讲解</RouterLink></section>

    <template v-else>
      <section class="learning-snapshot">
        <div class="snapshot-item"><span>当前身份</span><strong>{{ profile.identity || '学习者' }}</strong></div>
        <div class="snapshot-item"><span>当前目标</span><strong>{{ profile.goal || '建立系统化知识基础' }}</strong></div>
        <div class="snapshot-item"><span>学习方向</span><strong>{{ profile.direction || '当前学习方向' }}</strong></div>
        <div class="snapshot-item snapshot-item--progress"><span>路径进度</span><strong>{{ path.progress }}%</strong><div class="progress-track"><div class="progress-value" :style="{ width: `${path.progress}%` }"></div></div></div>
      </section>

      <section class="decision-layout">
        <article class="surface surface-pad recommendation-card">
          <div class="recommendation-card__heading"><div><p class="eyebrow">{{ task.is_recommended ? '系统推荐任务' : '当前选择任务' }}</p><h2>{{ task.kind_label || '案例诊断' }}</h2></div><span class="recommendation-badge">{{ task.difficulty_label || '建议先做' }}</span></div>
          <h3>{{ task.title }}</h3>
          <p>{{ task.brief }}</p>
          <div class="task-scenario"><span class="block-label">任务情境</span><p>{{ task.scenario || task.problem }}</p></div>
          <div class="recommendation-facts"><span><strong>{{ task.context?.focus || task.focus || '当前薄弱点' }}</strong>重点能力</span><span><strong>{{ task.context?.mastery_label || '暂无测验证据' }}</strong>基础证据</span><span><strong>{{ task.deliverables?.length || 0 }}</strong>项交付</span></div>
          <RouterLink class="button button--primary" :to="workspaceLink">进入学习巩固 <ArrowRight :size="15" /></RouterLink>
        </article>
        <aside class="surface surface-pad decision-reason"><p class="eyebrow">推荐依据</p><h2>根据你的基础学习</h2><p>{{ task.context?.reason || task.recommendation || '系统会根据当前学习节点生成实践入口。' }}</p><div class="decision-reason__line"><span>学习节点</span><strong>{{ task.context?.node_title || '当前节点' }}</strong></div><div class="decision-reason__line"><span>节点状态</span><strong>{{ task.context?.node_status_label || path.stage || '学习中' }}</strong></div><div class="decision-reason__line"><span>学习材料</span><strong>{{ task.context?.resource_label || `${task.resources?.length || 0} 份关联材料` }}</strong></div><div class="decision-reason__line"><span>路径进度</span><strong>{{ path.stage || '基础到应用' }}</strong></div></aside>
      </section>

      <section v-if="optionalTasks.length" class="task-catalog"><div class="catalog-heading"><div><p class="eyebrow">可选实践任务</p><h2>换一个情境练习迁移</h2></div><span>{{ optionalTasks.length }} 个可选任务</span></div><div class="catalog-grid" role="list">
        <button v-for="item in optionalTasks" :key="item.id" type="button" class="catalog-card" :class="{ 'is-selected': item.id === task.id }" :aria-pressed="item.id === task.id" :aria-label="`选择${item.kind_label || '实践任务'}：${item.title}`" @click="selectTask(item)"><span class="catalog-card__top"><strong>{{ item.kind_label || '实践任务' }}</strong><small>{{ item.difficulty_label || '当前阶段' }}</small></span><h3>{{ item.title }}</h3><p>{{ item.why || item.brief }}</p><span class="catalog-card__footer"><span>{{ item.id === task.id ? '当前已选' : item.status === 'completed' ? '已完成' : '选择任务' }}</span><ArrowUpRight :size="14" /></span></button>
      </div></section>
    </template>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { ArrowRight, ArrowUpRight, CircleAlert, LoaderCircle, RefreshCw } from 'lucide-vue-next'
import { useRoute } from 'vue-router'
import PageTitle from '@/shared/ui/PageTitle.vue'
import { advancedLearningApi } from '@/shared/api/advancedLearningApi'

const route = useRoute()
const loading = ref(true)
const errorMessage = ref('')
const task = ref(null)
const tasks = ref([])
const profile = reactive({ identity: '', direction: '', goal: '' })
const path = reactive({ stage: '', progress: 0 })
const unwrap = (response) => response?.data?.data ?? response?.data ?? null
function getTaskWorkspace(value) {
  const workspace = value?.workspace || {}
  return {
    pathId: workspace.path_id ?? workspace.pathId ?? value?.path_id ?? value?.pathId ?? null,
    nodeId: workspace.node_id ?? workspace.nodeId ?? value?.node_id ?? value?.nodeId ?? null,
  }
}

function buildWorkspaceLocation(value) {
  const workspace = getTaskWorkspace(value)
  const query = { taskId: value?.id }
  if (workspace.pathId !== null && workspace.pathId !== undefined) query.pathId = workspace.pathId
  if (workspace.nodeId !== null && workspace.nodeId !== undefined) query.nodeId = workspace.nodeId
  return { path: '/learning/consolidation', query }
}

const workspaceLink = computed(() => buildWorkspaceLocation(task.value))
const optionalTasks = computed(() => tasks.value.filter((item) => !item.is_recommended).slice(0, 2))

async function loadTask() {
  loading.value = true
  errorMessage.value = ''
  try {
    const result = unwrap(await advancedLearningApi.getCurrentTask())
    Object.assign(profile, result?.profile || {})
    Object.assign(path, result?.path || { stage: '', progress: 0 })
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
onMounted(loadTask)
</script>

<style scoped>
.advanced-page { min-width: 0; }
.advanced-page :deep(.page-heading) { margin-bottom: 20px; }
.advanced-page :deep(.page-heading p) { max-width: 640px; font-size: 13px; }
.button { gap: 8px; }.button:disabled { cursor: wait; opacity: .55; }
.state-panel { display: flex; align-items: center; gap: 14px; min-height: 96px; color: var(--accent-deep); }.state-panel > div { min-width: 0; flex: 1; }.state-panel p, .empty-panel p { margin: 5px 0 0; color: var(--muted); font-size: 13px; line-height: 1.7; }.state-panel--error { color: #954e38; }.spin { animation: spin 1s linear infinite; }.empty-panel { max-width: 720px; }.empty-panel h2 { margin: 0; font-size: 22px; }.empty-panel > p:not(.eyebrow) { margin-bottom: 20px; }
.learning-snapshot { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 1px; margin-bottom: 14px; border: 1px solid var(--line); border-radius: 7px; background: var(--line); overflow: hidden; }.snapshot-item { display: grid; min-width: 0; gap: 6px; padding: 12px 14px; background: var(--paper); }.snapshot-item span { color: var(--muted); font-size: 10px; }.snapshot-item strong { min-width: 0; overflow: hidden; color: var(--ink); font-size: 13px; text-overflow: ellipsis; white-space: nowrap; }.snapshot-item--progress strong { color: var(--accent-deep); font-size: 17px; }.snapshot-item--progress .progress-track { height: 5px; margin-top: 1px; }
.decision-layout { display: grid; grid-template-columns: minmax(0, 1.35fr) minmax(245px, .65fr); gap: 14px; margin-bottom: 20px; }.recommendation-card, .decision-reason { min-width: 0; padding: 18px; }.recommendation-card { border-color: #d3e0c7; background: #f8fbf3; }.recommendation-card__heading { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; }.recommendation-card__heading > div { min-width: 0; }.recommendation-card__heading h2 { margin: 0; font-size: 17px; }.recommendation-badge { max-width: 42%; padding: 5px 8px; border: 1px solid #d5e2c8; border-radius: 4px; color: var(--accent-deep); font-size: 10px; font-weight: 800; line-height: 1.3; text-align: right; }.recommendation-card h3 { margin: 17px 0 7px; overflow-wrap: anywhere; font-size: clamp(18px, 2vw, 22px); line-height: 1.4; }.recommendation-card > p { max-width: 720px; margin: 0; color: #536057; font-size: 12px; line-height: 1.7; }.recommendation-facts { display: flex; flex-wrap: wrap; gap: 18px; margin: 17px 0 15px; padding-top: 13px; border-top: 1px solid #dbe7d2; }.recommendation-facts span { display: grid; gap: 3px; color: var(--muted); font-size: 10px; }.recommendation-facts strong { color: var(--ink); font-size: 12px; overflow-wrap: anywhere; }.decision-reason h2 { margin: 0; font-size: 18px; }.decision-reason > p:not(.eyebrow) { margin: 9px 0 17px; color: var(--muted); font-size: 12px; line-height: 1.7; }.decision-reason__line { display: flex; justify-content: space-between; gap: 12px; padding-top: 10px; border-top: 1px solid var(--line); color: var(--muted); font-size: 10px; }.decision-reason__line + .decision-reason__line { margin-top: 9px; }.decision-reason__line strong { min-width: 0; color: var(--ink); font-size: 11px; overflow-wrap: anywhere; text-align: right; }
.task-catalog { padding-top: 1px; }.catalog-heading { display: flex; align-items: flex-end; justify-content: space-between; gap: 18px; margin-bottom: 11px; }.catalog-heading h2 { margin: 0; font-size: 18px; }.catalog-heading > span { color: var(--muted); font-size: 11px; }.catalog-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 10px; }.catalog-card { display: grid; min-width: 0; min-height: 142px; align-content: start; gap: 7px; padding: 13px; border: 1px solid var(--line); border-radius: 7px; background: var(--paper); color: var(--ink); text-align: left; transition: border-color .16s ease, background .16s ease, transform .16s ease; }.catalog-card:hover { border-color: #b9c9b2; transform: translateY(-1px); }.catalog-card.is-selected { border-color: var(--accent-deep); background: #f4f8ed; box-shadow: inset 3px 0 0 var(--accent-deep); }.catalog-card__top, .catalog-card__footer { display: flex; align-items: center; justify-content: space-between; gap: 8px; }.catalog-card__top strong { color: var(--accent-deep); font-size: 10px; }.catalog-card__top small { color: var(--muted); font-size: 10px; }.catalog-card h3 { margin: 4px 0 0; overflow-wrap: anywhere; font-size: 13px; line-height: 1.45; }.catalog-card p { display: -webkit-box; min-height: 36px; margin: 0; overflow: hidden; color: var(--muted); font-size: 11px; line-height: 1.6; -webkit-box-orient: vertical; -webkit-line-clamp: 2; }.catalog-card__footer { margin-top: auto; color: var(--muted); font-size: 10px; }
.task-scenario { margin-top: 15px; padding: 11px 12px; border-left: 3px solid #c8d9b7; background: #f1f6eb; }.task-scenario p { margin: 5px 0 0; color: #536057; font-size: 12px; line-height: 1.65; overflow-wrap: anywhere; }
@keyframes spin { to { transform: rotate(360deg); } }
@media (max-width: 900px) { .learning-snapshot { grid-template-columns: repeat(2, minmax(0, 1fr)); }.decision-layout { grid-template-columns: 1fr; }.catalog-grid { grid-template-columns: repeat(3, minmax(0, 1fr)); } }
@media (max-width: 700px) { .catalog-grid { grid-template-columns: 1fr; } }
@media (max-width: 560px) { .learning-snapshot { grid-template-columns: 1fr; }.catalog-heading { align-items: flex-start; flex-direction: column; gap: 6px; }.recommendation-card h3 { font-size: 19px; }.recommendation-facts { gap: 14px; }.recommendation-card .button { width: 100%; } }
:global(.page-container:has(.advanced-page)) { background: #f7f7f7; }
:global(.app-content:has(.advanced-page) .app-header) { border-bottom-color: #e8e8e8; background: #f7f7f7; }
.advanced-page h2 { color: #1e3c34; }
.advanced-page .surface { border-color: rgba(63, 91, 49, .28); box-shadow: 0 8px 24px rgba(45, 40, 92, .07); }
</style>
