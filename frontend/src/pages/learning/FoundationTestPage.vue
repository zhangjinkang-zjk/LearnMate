<template>
  <div class="foundation-test-page">
    <PageTitle
      eyebrow="FOUNDATION TEST"
      title="基础测试"
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
      <section class="test-controls surface">
        <div class="test-path-summary">
          <p class="eyebrow">当前学习路径</p>
          <strong>{{ learningPath.subject || learningPath.goal || '当前科目' }}</strong>
          <div class="test-path-progress"><span>{{ learningPath.progress || 0 }}%</span><div class="progress-track"><div class="progress-value" :style="{ width: `${learningPath.progress || 0}%` }"></div></div></div>
        </div>
        <label class="test-select">
          <span>切换科目</span>
          <select :value="learningPath.path_id" :disabled="switching" @change="selectPath($event.target.value)">
            <option v-for="path in pathCatalog" :key="path.path_id" :value="path.path_id">{{ path.subject || '未命名科目' }}</option>
          </select>
        </label>
        <label class="test-select">
          <span>选择章节</span>
          <select v-model="activeNodeId" @change="selectNode(activeNodeId)">
            <option v-for="node in testableNodes" :key="node.id" :value="node.id">第 {{ node.order_index || 1 }} 章 · {{ node.title }}</option>
          </select>
        </label>
      </section>

      <section class="test-context">
        <div>
          <p class="eyebrow">CHAPTER CHECK</p>
          <h2>{{ activeNode?.title || '选择一个章节' }}</h2>
          <p>{{ activeNode?.summary || '从上方路径或下方章节选择要检查的知识。' }}</p>
        </div>
        <span class="test-chapter-status">{{ canStartTest ? '可以开始测试' : '等待完成阅读' }}</span>
      </section>

      <section v-if="nodeError" class="surface surface-pad foundation-state foundation-state--error">
        <CircleAlert :size="22" />
        <div><strong>当前章节无法读取</strong><p>{{ nodeError }}</p></div>
        <button class="button button--quiet" type="button" @click="loadNode">重试</button>
      </section>

      <section v-else-if="activeNode && !canStartTest" class="surface surface-pad test-gate">
        <BookOpenText :size="23" />
        <div>
          <p class="eyebrow">开始测试前</p>
          <h2>先完成本章主讲文档</h2>
          <p>题目和费曼反讲会根据你实际阅读的内容生成。打开当前章节的基础讲解，读完文档后再回来，系统才能判断你的掌握程度。</p>
        </div>
        <RouterLink
          class="button button--primary"
          :to="{ path: '/learning/fundamentals', query: { pathId: learningPath.path_id, node: activeNode.id } }"
        >
          去基础讲解
        </RouterLink>
      </section>

      <template v-else-if="activeNode">
        <div class="test-tabs" role="tablist" aria-label="基础测试方式">
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
          v-if="activeTab === 'quiz'"
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
          v-else
          :key="`feynman-${activeNode.id}`"
          :path-id="learningPath.path_id"
          :node-id="activeNode.id"
          :chapter-title="activeNode.title"
          :chapter-content="chapterContent"
          :knowledge-tags="activeNode.knowledge_tags || []"
          :resource-id="documentResource?.resource_id || documentResource?.id"
          @end="leaveTest"
        />
      </template>

      <p v-if="notice" class="test-notice" role="status">{{ notice }}</p>
    </template>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { BookOpenText, CircleAlert, LoaderCircle, MessageCircle, Route, SquareCheck } from 'lucide-vue-next'
import { useRoute, useRouter } from 'vue-router'
import ChapterCheck from '@/features/fundamentals/ChapterCheck.vue'
import FeynmanCoach from '@/features/fundamentals/FeynmanCoach.vue'
import PageTitle from '@/shared/ui/PageTitle.vue'
import { fundamentalsApi } from '@/shared/api/fundamentalsApi'

const route = useRoute()
const router = useRouter()
const loading = ref(true)
const switching = ref(false)
const errorMessage = ref('')
const nodeError = ref('')
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
const canStartTest = computed(() => Boolean(activeNode.value?.resources_viewed))

function chooseNode(path) {
  // `node` is the canonical FundamentalsPage query key; accept the older
  // `nodeId` key so existing bookmarks continue to open the same chapter.
  const requested = route.query.node ?? route.query.nodeId
  activeNodeId.value = requested && path.nodes.some((node) => String(node.id) === String(requested))
    ? Number(requested)
    : path.current_node_id || path.nodes.find((node) => node.status === 'in_progress')?.id || path.nodes.find((node) => node.status !== 'locked')?.id || null
}

async function loadNode() {
  nodeError.value = ''
  nodeDetail.value = null
  documentResource.value = null
  chapterContent.value = ''
  if (!learningPath.value || !activeNode.value) return
  try {
    nodeDetail.value = await fundamentalsApi.getNode(learningPath.value.path_id, activeNode.value.id)
    const resources = nodeDetail.value?.progress?.resources || nodeDetail.value?.resources || activeNode.value.resources || []
    documentResource.value = resources.find((resource) => resource.resource_type === 'document') || null
    const resourceId = documentResource.value?.resource_id || documentResource.value?.id
    // 只有基础讲解页已经记录过阅读，测试页才读取完整正文；否则读取接口
    // 会把未学习章节误计为已查看，绕过后端的资源阅读门禁。
    if (resourceId && canStartTest.value) {
      const resource = await fundamentalsApi.getResource(resourceId)
      chapterContent.value = normalizeContent(resource?.content || documentResource.value?.content)
    } else chapterContent.value = normalizeContent(documentResource.value?.content)
  } catch (error) {
    nodeError.value = error.response?.data?.detail || error.message || '请检查后端服务后重试。'
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
  nodeError.value = ''
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
  nodeError.value = ''
  try {
    const selected = await fundamentalsApi.getCurrentPath(pathId)
    if (selected) {
      learningPath.value = selected
      chooseNode(selected)
      await loadNode()
      await router.replace({ query: { pathId: selected.path_id } })
    } else nodeError.value = '这条学习路径尚未加入，暂时不能进行基础测试。'
  } catch (error) {
    nodeError.value = error.response?.data?.detail || error.message || '切换学习路径失败，请重试。'
  } finally {
    switching.value = false
  }
}

async function selectNode(nodeId) {
  activeNodeId.value = nodeId
  nodeError.value = ''
  await loadNode()
  await router.replace({ query: { pathId: learningPath.value.path_id, node: nodeId } })
}

function leaveTest() {
  router.push({ path: '/learning/fundamentals', query: { pathId: learningPath.value?.path_id, node: activeNode.value?.id } })
}

function handlePassed() {
  notice.value = '题目测试已通过。你可以继续做一次费曼反讲，确认自己能够独立讲清楚。'
}

onMounted(loadPage)
</script>

<style scoped>
.foundation-test-page { min-width: 0; }.foundation-test-page :deep(.page-heading) { margin-bottom: 22px; }.foundation-test-page :deep(.page-heading h1) { max-width: 620px; }.foundation-test-page :deep(.page-heading p) { max-width: 620px; font-size: 13px; }.foundation-test-page :deep(.path-picker) { margin-bottom: 16px; padding-bottom: 16px; }.foundation-test-page :deep(.path-picker__heading) { align-items: center; margin-bottom: 10px; }.foundation-test-page :deep(.path-picker__heading h2) { font-size: 16px; }.foundation-test-page :deep(.path-picker__heading p:last-child) { max-width: 560px; }.foundation-test-page :deep(.path-picker__list) { padding-bottom: 3px; }
.foundation-state { display: flex; align-items: center; gap: 13px; min-height: 104px; color: var(--accent-deep); }.foundation-state > div { flex: 1; min-width: 0; }.foundation-state strong { color: var(--ink); }.foundation-state p { margin: 5px 0 0; color: var(--muted); font-size: 12px; line-height: 1.6; }.foundation-state--error { color: #a66442; }.spin { animation: spin .8s linear infinite; }
.test-context { display: grid; grid-template-columns: minmax(0, 1fr) minmax(220px, 30%); align-items: center; gap: 22px; margin-bottom: 12px; padding: 17px 20px; background: #fbfcfa; }.test-context h2 { margin: 0; font-size: 20px; line-height: 1.3; }.test-context p:last-child { max-width: 680px; margin: 6px 0 0; color: var(--muted); font-size: 12px; line-height: 1.65; }.chapter-picker { display: grid; gap: 6px; color: var(--muted); font-size: 11px; }.chapter-picker select { width: 100%; min-height: 39px; padding: 0 11px; border: 1px solid var(--line); border-radius: 5px; background: var(--paper); color: var(--ink); outline: none; }.chapter-picker select:focus { border-color: var(--accent-deep); }
.test-gate { display: flex; align-items: flex-start; gap: 14px; margin-bottom: 12px; color: var(--accent-deep); background: #f7faf3; }.test-gate > svg { flex: 0 0 auto; margin-top: 2px; }.test-gate > div { flex: 1; min-width: 0; }.test-gate .eyebrow { margin: 0 0 6px; }.test-gate h2 { margin: 0; font-size: 18px; color: var(--ink); }.test-gate p:last-child { max-width: 760px; margin: 7px 0 0; color: var(--muted); font-size: 12px; line-height: 1.7; }.test-gate .button { flex: 0 0 auto; margin-top: 1px; }
.test-tabs { display: inline-flex; gap: 4px; margin-bottom: 12px; padding: 4px; border: 1px solid var(--line); border-radius: 7px; background: #f4f7f3; }.test-tabs button { display: inline-flex; align-items: center; gap: 7px; min-height: 38px; padding: 0 13px; border: 0; border-radius: 4px; background: transparent; color: var(--muted); text-align: left; font-size: 12px; font-weight: 800; }.test-tabs button small { display: none; }.test-tabs button.is-active { background: var(--paper); color: var(--accent-deep); box-shadow: 0 1px 3px rgba(32,40,36,.1); }.test-notice { margin: 12px 0 0; padding: 11px 13px; border: 1px solid #d7e3c9; border-radius: 5px; background: #f4f8ed; color: var(--accent-deep); font-size: 12px; }
@keyframes spin { to { transform: rotate(360deg); } }
@media (max-width: 680px) { .foundation-test-page :deep(.page-heading) { margin-bottom: 18px; }.foundation-test-page :deep(.path-picker) { margin-bottom: 12px; }.test-context { grid-template-columns: 1fr; gap: 13px; padding: 15px; }.test-gate { flex-direction: column; gap: 10px; }.test-gate .button { width: 100%; margin-top: 0; }.test-tabs { display: flex; width: 100%; }.test-tabs button { flex: 1; justify-content: center; padding: 0 9px; } }
:global(.app-content:has(.foundation-test-page)) { background: #f7f7f7; }
:global(.page-container:has(.foundation-test-page)) { width: 100%; max-width: none; box-sizing: border-box; min-height: calc(100vh - 64px); margin: 0; background: #f7f7f7; }
:global(.app-content:has(.foundation-test-page) .app-header) { border-bottom-color: #e8e8e8; background: #f7f7f7; }
.foundation-test-page :deep(.page-heading) { margin-bottom: 18px; }
.foundation-test-page :deep(.page-heading .eyebrow) { color: #738078; font-size: 12px; letter-spacing: .14em; }
.foundation-test-page :deep(.page-heading h1) { color: #1e3c34; font-size: clamp(28px, 2.5vw, 36px); }
.foundation-test-page .surface { border-color: #dfe6df; border-radius: 16px; box-shadow: 0 8px 22px rgba(31, 49, 40, .045); }
.foundation-test-page .button { border-radius: 12px; }
.foundation-test-page .button--primary { border-color: #c4df3d; background: #b6d837; color: #1e3c34; box-shadow: 0 6px 14px rgba(63, 91, 49, .14); }
.foundation-test-page .button--primary:hover { border-color: #a9ca27; background: #a9ca27; color: #1e3c34; }
.foundation-test-page .button--quiet { border-color: #dce3dc; background: #fff; color: #3f5b31; }
.foundation-test-page .button--quiet:hover { border-color: #b9c9b2; background: #f1f6eb; }
.test-controls { display: grid; grid-template-columns: minmax(230px, 1.15fr) minmax(190px, .82fr) minmax(260px, 1fr); align-items: end; gap: 16px; margin-bottom: 22px; padding: 16px 18px; background: #fff; }
.test-path-summary { display: grid; min-width: 0; gap: 5px; }
.test-path-summary .eyebrow { margin: 0; color: #728078; font-size: 10px; }
.test-path-summary strong { overflow: hidden; color: #203a33; font-size: 16px; text-overflow: ellipsis; white-space: nowrap; }
.test-path-progress { display: grid; grid-template-columns: auto minmax(70px, 1fr); align-items: center; gap: 9px; max-width: 250px; color: #547042; font-size: 11px; font-weight: 800; }
.test-path-progress .progress-track { height: 5px; overflow: hidden; border-radius: 999px; background: #e7eee3; }
.test-path-progress .progress-value { height: 100%; border-radius: inherit; background: #8cae5a; }
.test-select { display: grid; min-width: 0; gap: 6px; color: #728078; font-size: 11px; }
.test-select select { width: 100%; min-height: 40px; padding: 0 34px 0 11px; border: 1px solid #dce4dc; border-radius: 10px; outline: none; background: #fbfcfa; color: #263c35; font: inherit; font-size: 12px; }
.test-select select:focus { border-color: #8cae5a; box-shadow: 0 0 0 3px rgba(140, 174, 90, .14); }
.test-select select:disabled { cursor: wait; color: #9ba69f; }
.test-context { display: flex; align-items: flex-end; justify-content: space-between; gap: 20px; margin: 0 0 13px; padding: 0; background: transparent; }
.test-context .eyebrow { margin: 0 0 5px; color: #71807a; font-size: 10px; }
.test-context h2 { color: #203a33; font-size: 23px; }
.test-context p:last-child { max-width: 720px; margin-top: 5px; font-size: 12px; }
.test-chapter-status { flex: 0 0 auto; padding: 8px 11px; border: 1px solid #dce7d4; border-radius: 999px; background: #f3f8ee; color: #53713e; font-size: 11px; font-weight: 800; }
.test-gate { align-items: center; gap: 13px; min-height: 0; margin-bottom: 12px; padding: 16px 18px; border: 1px solid #d8e4cd; border-radius: 16px; background: #f4f8ef; }
.test-gate h2 { font-size: 16px; }
.test-gate p:last-child { max-width: 850px; margin-top: 4px; }
.test-gate .button { min-height: 40px; padding: 0 14px; border-radius: 10px; }
.test-tabs { border: 0; border-radius: 14px; background: #eaf1e5; }
.test-tabs button { border-radius: 10px; }
.test-tabs button.is-active { background: #fff; color: var(--accent-deep); }
.foundation-test-page :deep(.chapter-check), .foundation-test-page :deep(.feynman-coach) { border-radius: 16px; }
.foundation-test-page :deep(.option-item) { border-radius: 12px; }
.test-notice { border-radius: 12px; background: #f4f8ed; }
@media (max-width: 900px) { .test-controls { grid-template-columns: 1fr 1fr; }.test-path-summary { grid-column: 1 / -1; }.test-context { align-items: flex-start; flex-direction: column; gap: 10px; }.test-chapter-status { align-self: flex-start; } }
@media (max-width: 680px) { :global(.page-container:has(.foundation-test-page)) { padding: 22px 18px 42px; }.test-controls { grid-template-columns: 1fr; gap: 13px; padding: 15px; }.test-path-summary { grid-column: auto; }.test-context h2 { font-size: 20px; }.test-gate { align-items: flex-start; padding: 15px; }.test-gate .button { width: 100%; } }
</style>
