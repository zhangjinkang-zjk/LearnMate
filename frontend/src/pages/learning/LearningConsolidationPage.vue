<template>
  <div class="consolidation-page">
    <PageTitle
      eyebrow="应用实践 · 学习巩固"
      title="把知识用到任务里"
      description="从进阶任务中选择一个情境，和 LearnMate 一步步讨论证据、假设与方案。你可以随时结束，不会被强制提交。"
    >
      <template #actions><RouterLink class="button button--quiet" to="/learning/advanced">返回进阶学习</RouterLink></template>
    </PageTitle>

    <section v-if="loading" class="surface surface-pad consolidation-state" aria-live="polite"><LoaderCircle class="spin" :size="22" /><div><strong>正在同步进阶任务</strong><p>读取你的学习目标、掌握情况和当前章节。</p></div></section>
    <section v-else-if="errorMessage" class="surface surface-pad consolidation-state consolidation-state--error"><CircleAlert :size="22" /><div><strong>学习巩固暂时不可用</strong><p>{{ errorMessage }}</p></div><button class="button button--quiet" type="button" @click="loadPage">重试</button></section>
    <section v-else-if="!tasks.length" class="surface surface-pad consolidation-state"><Route :size="22" /><div><strong>还没有可开始的进阶任务</strong><p>完成一部分基础讲解和基础测试后，系统会生成适合你的实践任务。</p></div><RouterLink class="button button--primary" to="/learning/fundamentals">回到基础讲解</RouterLink></section>

    <template v-else>
      <section class="practice-task-strip">
        <div class="strip-heading"><div><p class="eyebrow">选择实践入口</p><h2>从当前掌握程度开始</h2></div><span>{{ tasks.length }} 个任务</span></div>
        <div class="practice-task-list" role="list">
          <button v-for="item in tasks" :key="item.id" type="button" class="practice-task-card" :class="{ 'is-active': item.id === selectedTask?.id }" @click="selectTask(item)">
            <span class="practice-task-card__meta"><span>{{ item.kind_label || '实践任务' }}</span><span>{{ item.difficulty_label || item.mode }}</span></span>
            <strong>{{ item.title }}</strong>
            <small>{{ item.why || item.brief }}</small>
            <span class="practice-task-card__status">{{ item.status === 'active' ? '推荐现在开始' : item.status === 'completed' ? '已完成' : '待开始' }}</span>
          </button>
        </div>
      </section>

      <section v-if="selectedTask" class="selected-task-summary surface surface-pad">
        <div><p class="eyebrow">当前实践任务</p><h2>{{ selectedTask.title }}</h2><p>{{ selectedTask.brief }}</p></div>
        <div class="summary-metrics"><span><strong>{{ selectedTask.focus || '当前薄弱点' }}</strong>重点能力</span><span><strong>{{ selectedTask.deliverables?.length || 0 }}</strong>项交付</span><span><strong>{{ selectedTask.criteria?.length || 0 }}</strong>条验收标准</span></div>
      </section>

      <PracticeDialogue v-if="selectedTask && !sessionEnded" :key="selectedTask.id" :path-id="selectedTask.workspace?.path_id" :node-id="selectedTask.workspace?.node_id" :task="selectedTask" :chapter-content="chapterContent" :resource-id="resourceId" @end="endSession" />
      <section v-else-if="selectedTask" class="surface surface-pad session-ended">
        <span class="session-ended__mark">✓</span><p class="eyebrow">本次巩固已结束</p><h2>你的对话已经保存</h2><p>结束本次巩固不会直接改变路径完成状态。你可以稍后继续，或回到进阶学习选择另一个实践入口。</p><div><button class="button button--quiet" type="button" @click="sessionEnded = false">继续这个任务</button><RouterLink class="button button--primary" to="/learning/advanced">回到进阶学习</RouterLink></div>
      </section>
    </template>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { CircleAlert, LoaderCircle, Route } from 'lucide-vue-next'
import { useRoute } from 'vue-router'
import PracticeDialogue from '@/features/advanced/PracticeDialogue.vue'
import PageTitle from '@/shared/ui/PageTitle.vue'
import { advancedLearningApi } from '@/shared/api/advancedLearningApi'
import { fundamentalsApi } from '@/shared/api/fundamentalsApi'

const route = useRoute()
const loading = ref(true)
const errorMessage = ref('')
const tasks = ref([])
const selectedTask = ref(null)
const chapterContent = ref('')
const resourceId = ref(null)
const sessionEnded = ref(false)

const unwrap = (response) => response?.data?.data ?? response?.data ?? null

function normalizeContent(value) {
  if (typeof value === 'string') return value
  if (value && typeof value === 'object') return String(value.markdown || value.content || value.text || '')
  return ''
}

async function loadNodeContext(task) {
  chapterContent.value = ''
  resourceId.value = null
  const pathId = task?.workspace?.path_id
  const nodeId = task?.workspace?.node_id
  if (!pathId || !nodeId) return
  try {
    const detail = await fundamentalsApi.getNode(pathId, nodeId)
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

async function selectTask(task) {
  selectedTask.value = task
  sessionEnded.value = false
  await loadNodeContext(task)
}

async function loadPage() {
  loading.value = true
  errorMessage.value = ''
  try {
    const result = unwrap(await advancedLearningApi.getCurrentTask())
    const source = Array.isArray(result?.tasks) && result.tasks.length ? result.tasks : (result?.task ? [result.task] : [])
    tasks.value = source
    const requestedId = route.query.taskId
    selectedTask.value = source.find((task) => String(task.id) === String(requestedId)) || source.find((task) => task.status === 'active') || source[0] || null
    await loadNodeContext(selectedTask.value)
  } catch (error) {
    errorMessage.value = error.response?.data?.detail || error.message || '请检查后端服务后重试。'
  } finally {
    loading.value = false
  }
}

function endSession() {
  sessionEnded.value = true
}

onMounted(loadPage)
</script>

<style scoped>
.consolidation-state { display: flex; align-items: center; gap: 13px; min-height: 110px; color: var(--accent-deep); }.consolidation-state > div { flex: 1; }.consolidation-state strong { color: var(--ink); }.consolidation-state p { margin: 5px 0 0; color: var(--muted); font-size: 12px; line-height: 1.6; }.consolidation-state--error { color: #a66442; }.spin { animation: spin .8s linear infinite; }.practice-task-strip { margin-bottom: 18px; }.strip-heading { display: flex; align-items: flex-end; justify-content: space-between; gap: 18px; margin-bottom: 13px; }.strip-heading h2 { margin: 0; font-size: 20px; }.strip-heading > span { color: var(--muted); font-size: 11px; }.practice-task-list { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 10px; }.practice-task-card { display: grid; min-height: 154px; align-content: start; gap: 8px; padding: 15px; border: 1px solid var(--line); border-radius: 7px; background: var(--paper); color: var(--ink); text-align: left; transition: border-color .16s ease, background .16s ease, transform .16s ease; }.practice-task-card:hover { border-color: #b9c9b2; transform: translateY(-1px); }.practice-task-card.is-active { border-color: var(--accent-deep); background: #f4f8ed; box-shadow: inset 3px 0 0 var(--accent-deep); }.practice-task-card__meta, .practice-task-card__status { display: flex; justify-content: space-between; gap: 7px; color: var(--accent-deep); font-size: 10px; font-weight: 800; }.practice-task-card strong { font-size: 13px; line-height: 1.5; }.practice-task-card small { min-height: 34px; color: var(--muted); font-size: 11px; line-height: 1.55; }.practice-task-card__status { justify-content: flex-start; margin-top: auto; color: var(--muted); font-weight: 400; }.selected-task-summary { display: flex; align-items: flex-end; justify-content: space-between; gap: 24px; margin-bottom: 18px; }.selected-task-summary h2 { margin: 0; font-size: 21px; }.selected-task-summary p:last-child { max-width: 720px; margin: 7px 0 0; color: var(--muted); font-size: 12px; line-height: 1.7; }.summary-metrics { display: flex; flex: 0 0 auto; gap: 20px; }.summary-metrics span { display: grid; gap: 4px; color: var(--muted); font-size: 10px; }.summary-metrics strong { color: var(--ink); font-size: 13px; }.session-ended { display: grid; min-height: 420px; place-items: center; align-content: center; gap: 10px; text-align: center; }.session-ended__mark { display: grid; width: 54px; height: 54px; place-items: center; border-radius: 50%; background: #e8f2de; color: var(--accent-deep); font-size: 24px; }.session-ended h2 { margin: 0; font-size: 23px; }.session-ended > p:not(.eyebrow) { max-width: 500px; margin: 0; color: var(--muted); font-size: 12px; line-height: 1.7; }.session-ended > div { display: flex; gap: 9px; margin-top: 12px; }
@keyframes spin { to { transform: rotate(360deg); } }
@media (max-width: 900px) { .practice-task-list { grid-template-columns: 1fr; }.practice-task-card { min-height: 0; }.selected-task-summary { align-items: flex-start; flex-direction: column; }.summary-metrics { width: 100%; justify-content: space-between; } }
@media (max-width: 560px) { .strip-heading { align-items: flex-start; flex-direction: column; gap: 6px; }.summary-metrics { align-items: flex-start; flex-direction: column; gap: 9px; }.session-ended > div { align-items: stretch; flex-direction: column; width: 100%; }.session-ended .button { width: 100%; } }
</style>
