<template>
  <div class="foundation-quiz-page">
    <PageTitle :eyebrow="''" title="题目测试">
      <template #actions>
        <div v-if="activeNode" class="quiz-page__chapter-meta">
          <span>{{ chapterPosition }}</span>
          <strong>{{ activeNode.title }}</strong>
        </div>
        <RouterLink class="quiz-page__back" :to="backToTest" title="返回学习复盘" aria-label="返回学习复盘"><ArrowLeft :size="18" /></RouterLink>
      </template>
    </PageTitle>

    <section v-if="isLoading" class="quiz-state surface" aria-live="polite">
      <LoaderCircle class="spin" :size="24" />
      <div><strong>正在准备本章题目</strong><p>正在读取学习节点和已有测试会话。</p></div>
    </section>

    <section v-else-if="errorMessage" class="quiz-state quiz-state--error surface">
      <CircleAlert :size="24" />
      <div><strong>题目测试暂时不可用</strong><p>{{ errorMessage }}</p></div>
      <button class="button button--quiet" type="button" @click="loadQuizPage">重试</button>
    </section>

    <section v-else-if="!canStartTest" class="quiz-state surface">
      <BookOpenText :size="24" />
      <div><strong>请先完成本章阅读</strong><p>完成基础讲解后，系统才会开放与当前章节对应的检查题。</p></div>
      <RouterLink class="button button--primary" :to="backToLesson">前往基础讲解</RouterLink>
    </section>

    <template v-else>
      <ChapterCheck
        :key="`quiz-${learningPath.path_id}-${activeNode.id}`"
        :path-id="learningPath.path_id"
        :node-id="activeNode.id"
        :session-id="activeNode.session_id || nodeDetail?.quiz_session_id || ''"
        :chapter-title="activeNode.title"
        :quiz-config="nodeDetail?.quiz_config || {}"
        @close="returnToTest"
        @passed="returnToTest"
      />
    </template>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { ArrowLeft, BookOpenText, CircleAlert, LoaderCircle } from 'lucide-vue-next'
import { useRoute, useRouter } from 'vue-router'
import ChapterCheck from '@/features/fundamentals/ChapterCheck.vue'
import PageTitle from '@/shared/ui/PageTitle.vue'
import { fundamentalsApi } from '@/shared/api/fundamentalsApi'

const route = useRoute()
const router = useRouter()
const isLoading = ref(true)
const errorMessage = ref('')
const learningPath = ref(null)
const activeNodeId = ref(null)
const nodeDetail = ref(null)

const activeNode = computed(() => (learningPath.value?.nodes || []).find((node) => String(node.id) === String(activeNodeId.value)) || null)
const canStartTest = computed(() => Boolean(activeNode.value?.resources_viewed))
const backToTest = computed(() => ({ name: 'foundationTest', query: { pathId: learningPath.value?.path_id || route.query.pathId, node: activeNodeId.value || route.query.node } }))
const backToLesson = computed(() => ({ name: 'fundamentals', query: { pathId: learningPath.value?.path_id || route.query.pathId, node: activeNodeId.value || route.query.node } }))
const chapterPosition = computed(() => {
  const index = (learningPath.value?.nodes || []).findIndex((node) => String(node.id) === String(activeNodeId.value))
  return index >= 0 ? `第 ${index + 1} / ${learningPath.value.nodes.length} 章` : '当前章节'
})

async function loadQuizPage() {
  isLoading.value = true
  errorMessage.value = ''
  nodeDetail.value = null
  try {
    const path = await fundamentalsApi.getCurrentPath(route.query.pathId)
    if (!path) throw new Error('没有可用的学习路径')
    learningPath.value = path
    const requestedNodeId = route.query.node ?? route.query.nodeId
    const fallbackNode = path.nodes.find((node) => node.status === 'in_progress') || path.nodes.find((node) => node.status !== 'locked')
    activeNodeId.value = path.nodes.some((node) => String(node.id) === String(requestedNodeId)) ? requestedNodeId : fallbackNode?.id
    if (!activeNode.value) throw new Error('没有可测试的章节')
    nodeDetail.value = await fundamentalsApi.getNode(path.path_id, activeNode.value.id)
  } catch (error) {
    errorMessage.value = error?.response?.data?.detail || error?.message || '请稍后重试。'
  } finally {
    isLoading.value = false
  }
}

function returnToTest() {
  router.replace(backToTest.value)
}

onMounted(loadQuizPage)
</script>

<style scoped>
.foundation-quiz-page { display: grid; min-width: 0; min-height: 0; height: 100%; grid-template-rows: auto minmax(0, 1fr); gap: 10px; overflow: hidden; }
.foundation-quiz-page :deep(.page-heading) { min-height: 42px; margin-bottom: 0; }.foundation-quiz-page :deep(.page-heading h1) { font-size: 26px; }
.quiz-page__chapter-meta { display: flex; min-width: 0; max-width: min(720px, 56vw); align-items: center; gap: 10px; color: var(--muted); font-size: 12px; }.quiz-page__chapter-meta span { flex: 0 0 auto; color: var(--accent-deep); font-weight: 800; }.quiz-page__chapter-meta strong { overflow: hidden; color: var(--ink); font-size: 13px; text-overflow: ellipsis; white-space: nowrap; }.quiz-page__back { display: grid; width: 36px; height: 36px; flex: 0 0 36px; place-items: center; border: 1px solid var(--line); border-radius: 5px; background: var(--paper); color: var(--ink); }.quiz-page__back:hover { background: var(--soft); color: var(--accent-deep); }.quiz-page__back:focus-visible { outline: 2px solid var(--accent-deep); outline-offset: 2px; }
.quiz-state { display: flex; min-height: 128px; align-items: center; gap: 14px; padding: 22px; color: var(--accent-deep); }.quiz-state > div { min-width: 0; flex: 1; }.quiz-state strong { color: var(--ink); }.quiz-state p { margin: 5px 0 0; color: var(--muted); font-size: 12px; line-height: 1.6; }.quiz-state--error { color: #a66442; }
.foundation-quiz-page :deep(.chapter-check) { width: 100%; min-height: 0; height: 100%; }
.spin { animation: spin .8s linear infinite; } @keyframes spin { to { transform: rotate(360deg); } }
:global(.page-container:has(.foundation-quiz-page)) { width: 100%; max-width: none; height: 100%; box-sizing: border-box; margin: 0; padding: 12px 28px 18px; overflow: hidden; background: #f7f7f7; }
:global(.app-content:has(.foundation-quiz-page)) { background: #f7f7f7; }
:global(.app-content:has(.foundation-quiz-page) .app-header) { border-bottom-color: #e8e8e8; background: #f7f7f7; }
@media (max-width: 680px) { :global(.page-container:has(.foundation-quiz-page)) { padding: 10px 14px 14px; }.foundation-quiz-page :deep(.page-heading h1) { font-size: 23px; }.quiz-page__chapter-meta { max-width: calc(100vw - 148px); gap: 6px; font-size: 10px; }.quiz-page__chapter-meta strong { font-size: 11px; }.quiz-state { align-items: flex-start; flex-wrap: wrap; padding: 18px; }.quiz-state .button { width: 100%; } }
</style>
