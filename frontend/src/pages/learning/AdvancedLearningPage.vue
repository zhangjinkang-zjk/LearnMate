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
          <div class="recommendation-card__heading"><div><p class="eyebrow">系统推荐</p><h2>{{ task.kind_label || '案例诊断' }}</h2></div><span class="recommendation-badge">{{ task.difficulty_label || '当前推荐' }}</span></div>
          <h3>{{ task.title }}</h3>
          <p>{{ task.why || task.recommendation || task.brief }}</p>
          <div class="recommendation-facts"><span><strong>{{ task.focus || '当前薄弱点' }}</strong>重点能力</span><span><strong>{{ task.deliverables?.length || 0 }}</strong>项预期成果</span><span><strong>{{ task.resources?.length || 0 }}</strong>份关联材料</span></div>
          <RouterLink class="button button--primary" :to="workspaceLink">开始学习巩固 <ArrowRight :size="15" /></RouterLink>
        </article>
        <aside class="surface surface-pad decision-reason"><p class="eyebrow">为什么现在做</p><h2>这不是继续阅读</h2><p>进阶学习用来选择实践方向。你将在下一个页面亲自判断、提出假设并验证结果，系统只负责追问和提供必要提示。</p><div class="decision-reason__line"><span>当前阶段</span><strong>{{ path.stage || '基础到应用' }}</strong></div><div class="decision-reason__line"><span>任务顺序</span><strong>先看任务，再进入对话</strong></div></aside>
      </section>

      <section class="task-catalog"><div class="catalog-heading"><div><p class="eyebrow">实践任务目录</p><h2>也可以从这里换一个入口</h2></div><span>{{ tasks.length }} 个可选任务</span></div><div class="catalog-grid" role="list">
        <button v-for="item in tasks" :key="item.id" type="button" class="catalog-card" :class="{ 'is-selected': item.id === task.id }" @click="selectTask(item)"><span class="catalog-card__top"><strong>{{ item.kind_label || '实践任务' }}</strong><small>{{ item.difficulty_label || '当前阶段' }}</small></span><h3>{{ item.title }}</h3><p>{{ item.why || item.brief }}</p><span class="catalog-card__footer"><span>{{ item.status === 'active' ? '系统推荐' : item.status === 'completed' ? '已完成' : '待开始' }}</span><ArrowUpRight :size="14" /></span></button>
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
const workspaceLink = computed(() => ({ path: '/learning/consolidation', query: { taskId: task.value?.id, pathId: task.value?.workspace?.path_id, nodeId: task.value?.workspace?.node_id } }))

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

function selectTask(item) { task.value = item }
onMounted(loadTask)
</script>

<style scoped>
.button { gap: 8px; }.button:disabled { cursor: wait; opacity: .55; }.state-panel { display: flex; align-items: center; gap: 14px; min-height: 96px; color: var(--accent-deep); }.state-panel div { flex: 1; }.state-panel p, .empty-panel p { margin: 5px 0 0; color: var(--muted); font-size: 13px; line-height: 1.7; }.state-panel--error { color: #954e38; }.spin { animation: spin 1s linear infinite; }.empty-panel { max-width: 720px; }.empty-panel h2 { margin: 0; font-size: 22px; }.empty-panel > p:not(.eyebrow) { margin-bottom: 20px; }
.learning-snapshot { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 1px; margin-bottom: 18px; border: 1px solid var(--line); border-radius: 7px; background: var(--line); overflow: hidden; }.snapshot-item { display: grid; min-width: 0; gap: 7px; padding: 15px 16px; background: var(--paper); }.snapshot-item span { color: var(--muted); font-size: 10px; }.snapshot-item strong { overflow: hidden; color: var(--ink); font-size: 13px; text-overflow: ellipsis; white-space: nowrap; }.snapshot-item--progress strong { color: var(--accent-deep); font-size: 18px; }.snapshot-item--progress .progress-track { height: 5px; margin-top: 2px; }
.decision-layout { display: grid; grid-template-columns: minmax(0, 1.35fr) minmax(0, .65fr); gap: 18px; margin-bottom: 30px; }.recommendation-card { border-color: #d3e0c7; background: #f8fbf3; }.recommendation-card__heading { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; }.recommendation-card__heading h2 { margin: 0; font-size: 18px; }.recommendation-badge { padding: 5px 8px; border: 1px solid #d5e2c8; border-radius: 4px; color: var(--accent-deep); font-size: 10px; font-weight: 800; }.recommendation-card h3 { margin: 23px 0 8px; font-size: 22px; line-height: 1.45; }.recommendation-card > p { max-width: 720px; margin: 0; color: #536057; font-size: 13px; line-height: 1.75; }.recommendation-facts { display: flex; flex-wrap: wrap; gap: 24px; margin: 23px 0 20px; padding-top: 16px; border-top: 1px solid #dbe7d2; }.recommendation-facts span { display: grid; gap: 4px; color: var(--muted); font-size: 10px; }.recommendation-facts strong { color: var(--ink); font-size: 12px; }.decision-reason h2 { margin: 0; font-size: 19px; }.decision-reason > p:not(.eyebrow) { margin: 10px 0 21px; color: var(--muted); font-size: 12px; line-height: 1.75; }.decision-reason__line { display: flex; justify-content: space-between; gap: 12px; padding-top: 12px; border-top: 1px solid var(--line); color: var(--muted); font-size: 10px; }.decision-reason__line + .decision-reason__line { margin-top: 11px; }.decision-reason__line strong { color: var(--ink); font-size: 11px; text-align: right; }
.task-catalog { padding-top: 2px; }.catalog-heading { display: flex; align-items: flex-end; justify-content: space-between; gap: 18px; margin-bottom: 13px; }.catalog-heading h2 { margin: 0; font-size: 20px; }.catalog-heading > span { color: var(--muted); font-size: 11px; }.catalog-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 10px; }.catalog-card { display: grid; min-height: 172px; align-content: start; gap: 9px; padding: 15px; border: 1px solid var(--line); border-radius: 7px; background: var(--paper); color: var(--ink); text-align: left; transition: border-color .16s ease, background .16s ease, transform .16s ease; }.catalog-card:hover { border-color: #b9c9b2; transform: translateY(-1px); }.catalog-card.is-selected { border-color: var(--accent-deep); background: #f4f8ed; box-shadow: inset 3px 0 0 var(--accent-deep); }.catalog-card__top, .catalog-card__footer { display: flex; align-items: center; justify-content: space-between; gap: 8px; }.catalog-card__top strong { color: var(--accent-deep); font-size: 10px; }.catalog-card__top small { color: var(--muted); font-size: 10px; }.catalog-card h3 { margin: 4px 0 0; font-size: 14px; line-height: 1.5; }.catalog-card p { min-height: 51px; margin: 0; color: var(--muted); font-size: 11px; line-height: 1.6; }.catalog-card__footer { margin-top: auto; color: var(--muted); font-size: 10px; }
@keyframes spin { to { transform: rotate(360deg); } }
@media (max-width: 900px) { .learning-snapshot { grid-template-columns: repeat(2, minmax(0, 1fr)); }.decision-layout { grid-template-columns: 1fr; }.catalog-grid { grid-template-columns: 1fr; } }
@media (max-width: 560px) { .learning-snapshot { grid-template-columns: 1fr; }.catalog-heading { align-items: flex-start; flex-direction: column; gap: 6px; }.recommendation-card h3 { font-size: 19px; }.recommendation-facts { gap: 14px; }.recommendation-card .button { width: 100%; } }
</style>
