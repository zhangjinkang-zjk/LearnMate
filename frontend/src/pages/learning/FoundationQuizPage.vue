<template>
  <div class="foundation-quiz-page">
    <PageTitle eyebrow="CHAPTER QUIZ" title="题目测试" description="完成本章检查题，结果会同步到学习概览和基础测试。">
      <template #actions>
        <RouterLink class="button button--quiet" :to="backToTest">返回基础测试</RouterLink>
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
      <section class="quiz-context surface">
        <div><p class="eyebrow">CURRENT CHAPTER</p><h2>{{ activeNode.title }}</h2><p>{{ activeNode.summary || '围绕本章关键概念与应用判断完成检查。' }}</p></div>
        <span>{{ chapterPosition }}</span>
      </section>
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
import { BookOpenText, CircleAlert, LoaderCircle } from 'lucide-vue-next'
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
.foundation-quiz-page { display: grid; min-width: 0; min-height: 0; gap: 14px; }
.foundation-quiz-page :deep(.page-heading) { margin-bottom: 4px; }.foundation-quiz-page :deep(.page-heading h1) { font-size: 28px; }
.quiz-state { display: flex; min-height: 128px; align-items: center; gap: 14px; padding: 22px; color: var(--accent-deep); }.quiz-state > div { min-width: 0; flex: 1; }.quiz-state strong { color: var(--ink); }.quiz-state p { margin: 5px 0 0; color: var(--muted); font-size: 12px; line-height: 1.6; }.quiz-state--error { color: #a66442; }
.quiz-context { display: flex; min-width: 0; align-items: center; justify-content: space-between; gap: 20px; padding: 16px 20px; background: #fbfcfa; }.quiz-context .eyebrow { margin-bottom: 5px; }.quiz-context h2 { margin: 0; font-size: 18px; }.quiz-context p:last-child { max-width: 760px; margin: 5px 0 0; color: var(--muted); font-size: 12px; line-height: 1.55; }.quiz-context > span { flex: 0 0 auto; color: var(--accent-deep); font-size: 11px; font-weight: 800; }
.spin { animation: spin .8s linear infinite; } @keyframes spin { to { transform: rotate(360deg); } }
@media (max-width: 680px) { .quiz-context { align-items: flex-start; flex-direction: column; gap: 8px; }.quiz-state { align-items: flex-start; flex-wrap: wrap; padding: 18px; }.quiz-state .button { width: 100%; } }
</style>
