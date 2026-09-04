<template>
  <div class="foundation-test-page">
    <PageTitle
      eyebrow="知识学习 · 基础测试"
      title="确认你真的掌握了"
      description="先用题目检查关键概念，再用费曼反讲把知识讲成自己的话。两种方式都不会替你跳过基础学习。"
    >
      <template #actions>
        <RouterLink class="button button--quiet" to="/learning/fundamentals">回到基础讲解</RouterLink>
      </template>
    </PageTitle>

    <section v-if="loading" class="surface surface-pad foundation-state" aria-live="polite">
      <LoaderCircle class="spin" :size="22" />
      <div><strong>正在同步可测试章节</strong><p>读取你的学习路径和当前章节材料。</p></div>
    </section>
    <section v-else-if="errorMessage" class="surface surface-pad foundation-state foundation-state--error">
      <CircleAlert :size="22" />
      <div><strong>基础测试暂时不可用</strong><p>{{ errorMessage }}</p></div>
      <button class="button button--quiet" type="button" @click="loadPage">重试</button>
    </section>
    <section v-else-if="!learningPath" class="surface surface-pad foundation-state">
      <Route :size="22" />
      <div><strong>还没有可测试的学习路径</strong><p>先完成学习定向、能力诊断并生成学习路径。</p></div>
      <RouterLink class="button button--primary" to="/onboarding/direction">开始学习定向</RouterLink>
    </section>

    <template v-else>
      <PathPicker
        :paths="pathCatalog"
        :active-path-id="learningPath.path_id"
        :loading="loading"
        :switching="switching"
        @select="selectPath"
      />

      <section class="test-context surface surface-pad">
        <div>
          <p class="eyebrow">当前章节</p>
          <h2>{{ activeNode?.title || '选择一个章节' }}</h2>
          <p>{{ activeNode?.summary || '从上方路径或下方章节选择要检查的知识。' }}</p>
        </div>
        <label class="chapter-picker">
          <span>选择章节</span>
          <select v-model="activeNodeId" @change="selectNode(activeNodeId)">
            <option v-for="node in testableNodes" :key="node.id" :value="node.id">{{ node.title }}</option>
          </select>
        </label>
      </section>

      <div v-if="activeNode" class="test-tabs" role="tablist" aria-label="基础测试方式">
        <button type="button" role="tab" :aria-selected="activeTab === 'quiz'" :class="{ 'is-active': activeTab === 'quiz' }" @click="activeTab = 'quiz'">
          <SquareCheck :size="16" /> 题目测试
          <small>检查关键概念和应用判断</small>
        </button>
        <button type="button" role="tab" :aria-selected="activeTab === 'feynman'" :class="{ 'is-active': activeTab === 'feynman' }" @click="activeTab = 'feynman'">
          <MessageCircle :size="16" /> 费曼反讲
          <small>用自己的话讲清楚知识关系</small>
        </button>
      </div>

      <ChapterCheck
        v-if="activeTab === 'quiz' && activeNode"
        :key="`quiz-${activeNode.id}`"
        :path-id="learningPath.path_id"
        :node-id="activeNode.id"
        :session-id="activeNode.session_id || nodeDetail?.quiz_session_id || ''"
        :chapter-title="activeNode.title"
        :quiz-config="nodeDetail?.quiz_config || {}"
        @close="leaveTest"
        @passed="handlePassed"
      />
      <FeynmanCoach
        v-else-if="activeTab === 'feynman' && activeNode"
        :key="`feynman-${activeNode.id}`"
        :path-id="learningPath.path_id"
        :node-id="activeNode.id"
        :chapter-title="activeNode.title"
        :chapter-content="chapterContent"
        :knowledge-tags="activeNode.knowledge_tags || []"
        :resource-id="documentResource?.resource_id"
        @end="leaveTest"
      />

      <p v-if="notice" class="test-notice" role="status">{{ notice }}</p>
    </template>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { CircleAlert, LoaderCircle, MessageCircle, Route, SquareCheck } from 'lucide-vue-next'
import { useRoute, useRouter } from 'vue-router'
import ChapterCheck from '@/features/fundamentals/ChapterCheck.vue'
import FeynmanCoach from '@/features/fundamentals/FeynmanCoach.vue'
import PathPicker from '@/features/fundamentals/PathPicker.vue'
import PageTitle from '@/shared/ui/PageTitle.vue'
import { fundamentalsApi } from '@/shared/api/fundamentalsApi'

const route = useRoute()
const router = useRouter()
const loading = ref(true)
const switching = ref(false)
const errorMessage = ref('')
const notice = ref('')
const learningPath = ref(null)
const pathCatalog = ref([])
const activeNodeId = ref(null)
const nodeDetail = ref(null)
const documentResource = ref(null)
const chapterContent = ref('')
const activeTab = ref('quiz')

const testableNodes = computed(() => (learningPath.value?.nodes || []).filter((node) => node.status !== 'locked'))
const activeNode = computed(() => testableNodes.value.find((node) => String(node.id) === String(activeNodeId.value)) || testableNodes.value[0] || null)

function chooseNode(path) {
  const requested = route.query.nodeId
  activeNodeId.value = requested && path.nodes.some((node) => String(node.id) === String(requested))
    ? Number(requested)
    : path.current_node_id || path.nodes.find((node) => node.status === 'in_progress')?.id || path.nodes.find((node) => node.status !== 'locked')?.id || null
}

async function loadNode() {
  nodeDetail.value = null
  documentResource.value = null
  chapterContent.value = ''
  if (!learningPath.value || !activeNode.value) return
  try {
    nodeDetail.value = await fundamentalsApi.getNode(learningPath.value.path_id, activeNode.value.id)
    const resources = nodeDetail.value?.progress?.resources || nodeDetail.value?.resources || activeNode.value.resources || []
    documentResource.value = resources.find((resource) => resource.resource_type === 'document') || null
    const resourceId = documentResource.value?.resource_id || documentResource.value?.id
    if (resourceId) {
      const resource = await fundamentalsApi.getResource(resourceId)
      chapterContent.value = normalizeContent(resource?.content || documentResource.value?.content)
    } else chapterContent.value = normalizeContent(documentResource.value?.content)
  } catch {
    chapterContent.value = activeNode.value.summary || ''
  }
}

function normalizeContent(value) {
  if (typeof value === 'string') return value
  if (value && typeof value === 'object') return String(value.markdown || value.content || value.text || '')
  return ''
}

async function loadPage() {
  loading.value = true
  errorMessage.value = ''
  try {
    const [current, paths] = await Promise.all([fundamentalsApi.getCurrentPath(route.query.pathId), fundamentalsApi.listPaths()])
    learningPath.value = current
    pathCatalog.value = Array.isArray(paths) ? paths : (paths?.paths || [])
    if (learningPath.value) {
      chooseNode(learningPath.value)
      await loadNode()
    }
  } catch (error) {
    errorMessage.value = error.response?.data?.detail || error.message || '请检查后端服务后重试。'
  } finally {
    loading.value = false
  }
}

async function selectPath(pathId) {
  if (switching.value || Number(pathId) === Number(learningPath.value?.path_id)) return
  switching.value = true
  try {
    const selected = await fundamentalsApi.getCurrentPath(pathId)
    if (selected) {
      learningPath.value = selected
      chooseNode(selected)
      await loadNode()
      await router.replace({ query: { pathId: selected.path_id } })
    }
  } finally {
    switching.value = false
  }
}

async function selectNode(nodeId) {
  activeNodeId.value = nodeId
  await loadNode()
  await router.replace({ query: { pathId: learningPath.value.path_id, nodeId: nodeId } })
}

function leaveTest() {
  router.push({ path: '/learning/fundamentals', query: { pathId: learningPath.value?.path_id, nodeId: activeNode.value?.id } })
}

function handlePassed() {
  notice.value = '题目测试已通过。你可以继续做一次费曼反讲，确认自己能够独立讲清楚。'
}

onMounted(loadPage)
</script>

<style scoped>
.foundation-state { display: flex; align-items: center; gap: 13px; min-height: 110px; color: var(--accent-deep); }.foundation-state > div { flex: 1; }.foundation-state strong { color: var(--ink); }.foundation-state p { margin: 5px 0 0; color: var(--muted); font-size: 12px; line-height: 1.6; }.foundation-state--error { color: #a66442; }.spin { animation: spin .8s linear infinite; }
.test-context { display: flex; align-items: flex-end; justify-content: space-between; gap: 24px; margin-bottom: 16px; }.test-context h2 { margin: 0; font-size: 21px; }.test-context p:last-child { max-width: 680px; margin: 7px 0 0; color: var(--muted); font-size: 12px; line-height: 1.7; }.chapter-picker { display: grid; flex: 0 0 min(300px, 35%); gap: 7px; color: var(--muted); font-size: 11px; }.chapter-picker select { min-height: 40px; padding: 0 11px; border: 1px solid var(--line); border-radius: 5px; background: var(--paper); color: var(--ink); outline: none; }.chapter-picker select:focus { border-color: var(--accent-deep); }
.test-tabs { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; margin-bottom: 18px; }.test-tabs button { display: grid; grid-template-columns: auto 1fr; align-items: center; gap: 7px 9px; min-height: 62px; padding: 12px 14px; border: 1px solid var(--line); border-radius: 6px; background: var(--paper); color: var(--muted); text-align: left; font-size: 13px; font-weight: 800; }.test-tabs button small { grid-column: 2; color: var(--muted); font-size: 10px; font-weight: 400; }.test-tabs button.is-active { border-color: var(--accent-deep); background: #f4f8ed; color: var(--accent-deep); box-shadow: inset 3px 0 0 var(--accent-deep); }.test-notice { margin: 12px 0 0; padding: 11px 13px; border: 1px solid #d7e3c9; border-radius: 5px; background: #f4f8ed; color: var(--accent-deep); font-size: 12px; }
@keyframes spin { to { transform: rotate(360deg); } }
@media (max-width: 680px) { .test-context { align-items: stretch; flex-direction: column; }.chapter-picker { flex-basis: auto; }.test-tabs { grid-template-columns: 1fr; } }
</style>
