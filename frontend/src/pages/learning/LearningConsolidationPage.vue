<template>
  <div class="consolidation-page">
    <PageTitle eyebrow="应用实践 · 学习巩固" title="和 LearnMate 一起推演" description="这里不再选择任务，而是围绕一个已经选定的实践情境展开对话。你可以随时暂停或结束，不会被强制提交。">
      <template #actions><RouterLink class="button button--quiet" to="/learning/advanced">返回进阶学习</RouterLink></template>
    </PageTitle>

    <section v-if="loading" class="surface surface-pad consolidation-state" aria-live="polite"><LoaderCircle class="spin" :size="22" /><div><strong>正在打开实践会话</strong><p>读取已选任务和它所依赖的学习材料。</p></div></section>
    <section v-else-if="errorMessage" class="surface surface-pad consolidation-state consolidation-state--error"><CircleAlert :size="22" /><div><strong>学习巩固暂时不可用</strong><p>{{ errorMessage }}</p></div><button class="button button--quiet" type="button" @click="loadPage">重试</button></section>
    <section v-else-if="!selectedTask" class="surface surface-pad consolidation-state"><Route :size="22" /><div><strong>还没有选定实践任务</strong><p>先在进阶学习中查看任务并选择一个实践入口。</p></div><RouterLink class="button button--primary" to="/learning/advanced">选择实践任务</RouterLink></section>

    <template v-else>
      <section class="session-context surface">
        <div class="session-context__identity"><span class="session-context__kind">{{ selectedTask.kind_label || '实践任务' }}</span><div><strong>{{ selectedTask.title }}</strong><p>{{ selectedTask.brief }}</p></div></div>
        <div class="session-context__facts"><span><b>{{ selectedTask.focus || '当前薄弱点' }}</b>重点能力</span><span><b>{{ selectedTask.workspace?.node_id || '当前节点' }}</b>关联节点</span><span><b>{{ selectedTask.deliverables?.length || 0 }}</b>项成果</span></div>
      </section>

      <PracticeDialogue v-if="!sessionEnded" :key="selectedTask.id" :path-id="selectedTask.workspace?.path_id" :node-id="selectedTask.workspace?.node_id" :task="selectedTask" :chapter-content="chapterContent" :resource-id="resourceId" @end="endSession" />
      <section v-else class="surface surface-pad session-ended"><span class="session-ended__mark">✓</span><p class="eyebrow">本次巩固已结束</p><h2>对话过程已经保存</h2><p>结束本次巩固不会改变路径完成状态。你可以稍后从进阶学习重新进入这个任务。</p><div><button class="button button--quiet" type="button" @click="sessionEnded = false">继续这个任务</button><RouterLink class="button button--primary" to="/learning/advanced">返回进阶学习</RouterLink></div></section>
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

async function loadPage() {
  loading.value = true
  errorMessage.value = ''
  try {
    const result = unwrap(await advancedLearningApi.getCurrentTask())
    const source = Array.isArray(result?.tasks) && result.tasks.length ? result.tasks : (result?.task ? [result.task] : [])
    const requestedId = route.query.taskId
    selectedTask.value = source.find((task) => String(task.id) === String(requestedId)) || null
    await loadNodeContext(selectedTask.value)
  } catch (error) {
    errorMessage.value = error.response?.data?.detail || error.message || '请检查后端服务后重试。'
  } finally { loading.value = false }
}

function endSession() { sessionEnded.value = true }
onMounted(loadPage)
</script>

<style scoped>
.consolidation-state { display: flex; align-items: center; gap: 13px; min-height: 110px; color: var(--accent-deep); }.consolidation-state > div { flex: 1; }.consolidation-state strong { color: var(--ink); }.consolidation-state p { margin: 5px 0 0; color: var(--muted); font-size: 12px; line-height: 1.6; }.consolidation-state--error { color: #a66442; }.spin { animation: spin .8s linear infinite; }
.session-context { display: flex; align-items: center; justify-content: space-between; gap: 24px; margin-bottom: 18px; padding: 17px 20px; }.session-context__identity { display: flex; min-width: 0; align-items: flex-start; gap: 13px; }.session-context__kind { flex: 0 0 auto; padding: 6px 8px; border: 1px solid #d7e3c9; border-radius: 4px; background: #f3f8ea; color: var(--accent-deep); font-size: 10px; font-weight: 800; }.session-context strong { display: block; overflow: hidden; font-size: 14px; line-height: 1.45; text-overflow: ellipsis; white-space: nowrap; }.session-context p { max-width: 650px; margin: 5px 0 0; color: var(--muted); font-size: 11px; line-height: 1.6; }.session-context__facts { display: flex; flex: 0 0 auto; gap: 20px; }.session-context__facts span { display: grid; gap: 3px; color: var(--muted); font-size: 10px; text-align: right; }.session-context__facts b { color: var(--ink); font-size: 11px; }.session-ended { display: grid; min-height: 480px; place-items: center; align-content: center; gap: 10px; text-align: center; }.session-ended__mark { display: grid; width: 54px; height: 54px; place-items: center; border-radius: 50%; background: #e8f2de; color: var(--accent-deep); font-size: 24px; }.session-ended h2 { margin: 0; font-size: 23px; }.session-ended > p:not(.eyebrow) { max-width: 500px; margin: 0; color: var(--muted); font-size: 12px; line-height: 1.7; }.session-ended > div { display: flex; gap: 9px; margin-top: 12px; }
@keyframes spin { to { transform: rotate(360deg); } }
@media (max-width: 760px) { .session-context { align-items: flex-start; flex-direction: column; padding: 15px 17px; }.session-context__identity { width: 100%; }.session-context strong { white-space: normal; }.session-context__facts { width: 100%; justify-content: space-between; }.session-context__facts span { text-align: left; } }
@media (max-width: 560px) { .session-ended > div { align-items: stretch; flex-direction: column; width: 100%; }.session-ended .button { width: 100%; } }
</style>
