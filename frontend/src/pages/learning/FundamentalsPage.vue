<template>
  <div class="fundamentals-page">
    <div v-if="isPageLoading" class="page-state surface" aria-live="polite">
      <LoaderCircle class="spin" :size="28" />
      <strong>正在打开你的学习章节</strong>
      <p>同步学习路径、章节状态和主讲文档。</p>
    </div>

    <div v-else-if="pageError" class="page-state page-state--error surface">
      <CircleAlert :size="28" />
      <strong>基础讲解暂时没有加载成功</strong>
      <p>{{ pageError }}</p>
      <button class="button button--quiet" type="button" @click="loadPage">重新加载</button>
    </div>

    <div v-else-if="!learningPath" class="page-state surface">
      <Route :size="28" />
      <strong>还没有可以学习的路径</strong>
      <p>先完成学习定向与能力诊断，系统才会按你的目标生成科目和章节。</p>
      <RouterLink class="button button--primary" to="/onboarding/direction">开始学习定向</RouterLink>
    </div>

    <template v-else>
      <header class="lesson-context">
        <div class="lesson-context__copy">
          <p class="eyebrow">基础讲解 · {{ learningPath.goal }}</p>
          <h1>{{ activeNode?.title || '选择一个章节' }}</h1>
          <p>{{ activeNode?.summary || '按学习路径逐章补齐知识基础。' }}</p>
        </div>
        <div class="path-progress" aria-label="当前科目学习进度">
          <div><span>科目进度</span><strong>{{ learningPath.progress }}%</strong></div>
          <div class="progress-track"><div class="progress-value" :style="{ width: `${learningPath.progress}%` }"></div></div>
          <small>已完成 {{ completedNodeCount }} / {{ learningPath.nodes.length }} 章</small>
        </div>
      </header>

      <div class="learning-layout">
        <ChapterRail :nodes="learningPath.nodes" :active-node-id="activeNodeId" @select="selectNode" />

        <main class="lesson-main">
          <div class="resource-toolbar" aria-label="章节材料视图">
            <div class="resource-tabs">
              <button type="button" :class="{ 'is-active': resourceView === 'document' }" @click="resourceView = 'document'">
                <BookOpenText :size="15" />
                <span>主讲文档</span>
              </button>
              <button
                v-if="mindmapResource"
                type="button"
                :class="{ 'is-active': resourceView === 'mindmap' }"
                :disabled="isMindmapLoading"
                @click="showMindmap"
              >
                <Network :size="15" />
                <span>{{ isMindmapLoading ? '读取中' : '知识结构' }}</span>
              </button>
            </div>
            <span class="resource-status"><span class="status-dot"></span>{{ resourceStatusLabel }}</span>
          </div>

          <ChapterCheck
            v-if="isChecking && activeNode"
            :key="`check-${activeNode.id}`"
            :path-id="learningPath.path_id"
            :node-id="activeNode.id"
            :session-id="activeNode.session_id || nodeDetail?.quiz_session_id || ''"
            :chapter-title="activeNode.title"
            :quiz-config="nodeDetail?.quiz_config || {}"
            @close="isChecking = false"
            @passed="handleChapterPassed"
          />

          <template v-else>
            <div v-if="isResourceLoading" class="document-loading surface" aria-live="polite">
              <LoaderCircle class="spin" :size="25" />
              <strong>{{ resourceLoadingMessage }}</strong>
              <p>页面会在文档准备好后自动显示，不需要重复刷新。</p>
            </div>

            <div v-else-if="resourceError" class="document-loading document-loading--error surface">
              <CircleAlert :size="25" />
              <strong>本章文档暂时不可用</strong>
              <p>{{ resourceError }}</p>
              <button class="button button--quiet" type="button" @click="loadActiveNode">重试本章</button>
            </div>

            <MarkdownDocument
              v-else
              :title="resourceView === 'mindmap' ? `${activeNode.title} · 知识结构` : activeNode.title"
              :content="visibleResourceContent"
              :tags="activeNode.knowledge_tags || []"
              :chapter-number="activeNodeIndex + 1"
              :empty-message="resourceView === 'mindmap' ? '本章暂时没有知识结构材料。' : '本章文档尚未生成。'"
            />

            <footer class="chapter-footer surface">
              <button class="button button--quiet" type="button" :disabled="!previousNode" @click="previousNode && selectNode(previousNode.id)">
                <ArrowLeft :size="15" />
                上一章
              </button>
              <div class="chapter-footer__copy">
                <strong>{{ activeNode.status === 'completed' ? '本章已完成' : '读完正文，再用检查确认真正掌握' }}</strong>
                <span>{{ documentContent ? `${estimatedReadMinutes} 分钟阅读 · ${activeNode.knowledge_tags?.length || 0} 个知识点` : '正在准备学习材料' }}</span>
              </div>
              <button class="button button--primary" type="button" :disabled="!documentContent || isResourceLoading" @click="openChapterCheck">
                {{ activeNode.status === 'completed' ? '复习本章检查' : '完成阅读，进入检查' }}
                <ArrowRight :size="15" />
              </button>
            </footer>
          </template>
        </main>

        <LearningAssistant
          v-if="activeNode"
          :key="activeNode.id"
          :path-id="learningPath.path_id"
          :node-id="activeNode.id"
          :chapter-title="activeNode.title"
          :chapter-content="documentContent"
          :knowledge-tags="activeNode.knowledge_tags || []"
        />
      </div>
    </template>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ArrowLeft, ArrowRight, BookOpenText, CircleAlert, LoaderCircle, Network, Route } from 'lucide-vue-next'
import ChapterCheck from '@/features/fundamentals/ChapterCheck.vue'
import ChapterRail from '@/features/fundamentals/ChapterRail.vue'
import LearningAssistant from '@/features/fundamentals/LearningAssistant.vue'
import MarkdownDocument from '@/features/fundamentals/MarkdownDocument.vue'
import { fundamentalsApi } from '@/shared/api/fundamentalsApi'

const route = useRoute()
const router = useRouter()
const isPageLoading = ref(true)
const pageError = ref('')
const learningPath = ref(null)
const activeNodeId = ref(null)
const nodeDetail = ref(null)
const documentResource = ref(null)
const documentContent = ref('')
const mindmapResource = ref(null)
const mindmapContent = ref('')
const resourceView = ref('document')
const isResourceLoading = ref(false)
const isMindmapLoading = ref(false)
const resourceLoadingMessage = ref('正在读取本章文档')
const resourceError = ref('')
const isChecking = ref(false)
let resourceController = null
let nodeLoadVersion = 0
let openedAt = 0
let hasReportedCurrentRead = false

const activeNodeIndex = computed(() => learningPath.value?.nodes.findIndex((node) => node.id === activeNodeId.value) ?? -1)
const activeNode = computed(() => learningPath.value?.nodes[activeNodeIndex.value] || null)
const completedNodeCount = computed(() => learningPath.value?.nodes.filter((node) => node.status === 'completed').length || 0)
const previousNode = computed(() => {
  if (!learningPath.value || activeNodeIndex.value <= 0) return null
  return learningPath.value.nodes[activeNodeIndex.value - 1]
})
const visibleResourceContent = computed(() => resourceView.value === 'mindmap' ? mindmapContent.value : documentContent.value)
const estimatedReadMinutes = computed(() => Math.max(3, Math.ceil(documentContent.value.replace(/\s/g, '').length / 420)))
const resourceStatusLabel = computed(() => {
  if (isResourceLoading.value) return '正在准备本章'
  if (resourceError.value) return '同步异常'
  if (documentContent.value) return '内容已同步'
  return '等待内容'
})

function errorDetail(error, fallback) {
  return error.response?.data?.detail || error.message || fallback
}

function normalizeResourceId(resource) {
  return resource?.resource_id || resource?.id || null
}

function normalizeDocumentContent(content) {
  if (typeof content !== 'string') return content ? String(content) : ''
  const trimmed = content.trim()
  if (!trimmed.startsWith('{')) return trimmed
  try {
    const parsed = JSON.parse(trimmed)
    return parsed.markdown || parsed.content || parsed.document || parsed.body || trimmed
  } catch {
    return trimmed
  }
}

function findResource(resources, type) {
  return (resources || []).find((resource) => resource.resource_type === type) || null
}

async function loadPage() {
  isPageLoading.value = true
  pageError.value = ''
  try {
    const path = await fundamentalsApi.getCurrentPath()
    if (!path || !Array.isArray(path.nodes) || !path.nodes.length) {
      learningPath.value = null
      activeNodeId.value = null
      return
    }
    learningPath.value = path
    const requestedId = Number(route.query.node)
    const requestedNode = path.nodes.find((node) => node.id === requestedId && node.status !== 'locked')
    const currentNode = path.nodes.find((node) => node.id === path.current_node_id)
      || path.nodes.find((node) => node.status === 'in_progress' || node.status === 'unlocked')
      || path.nodes.find((node) => node.status === 'completed')
    const initialNode = requestedNode || currentNode
    if (initialNode) await selectNode(initialNode.id, false)
  } catch (error) {
    pageError.value = errorDetail(error, '无法读取当前学习路径，请稍后重试。')
  } finally {
    isPageLoading.value = false
  }
}

async function selectNode(nodeId, updateUrl = true) {
  const node = learningPath.value?.nodes.find((item) => item.id === nodeId)
  if (!node || node.status === 'locked') return
  if (activeNodeId.value && activeNodeId.value !== nodeId) reportReadDuration()
  activeNodeId.value = nodeId
  resourceView.value = 'document'
  isChecking.value = false
  if (updateUrl) router.replace({ query: { ...route.query, node: nodeId } })
  await loadActiveNode()
}

async function loadActiveNode() {
  if (!learningPath.value || !activeNode.value) return
  const loadVersion = ++nodeLoadVersion
  resourceController?.abort()
  resourceController = new AbortController()
  isResourceLoading.value = true
  resourceLoadingMessage.value = '正在读取本章文档'
  resourceError.value = ''
  nodeDetail.value = null
  documentResource.value = null
  documentContent.value = ''
  mindmapResource.value = null
  mindmapContent.value = ''
  openedAt = Date.now()
  hasReportedCurrentRead = false

  try {
    let detail = await fundamentalsApi.getNode(learningPath.value.path_id, activeNode.value.id)
    if (loadVersion !== nodeLoadVersion) return
    nodeDetail.value = detail
    let resources = detail?.progress?.resources || activeNode.value.resources || []
    let document = findResource(resources, 'document')

    if (!document) {
      resourceLoadingMessage.value = '正在为本章生成完整讲解'
      await fundamentalsApi.generateResources(learningPath.value.path_id, activeNode.value.id, (event) => {
        if (event?.type === 'status') resourceLoadingMessage.value = event.msg || event.message || resourceLoadingMessage.value
        if (event?.type === 'error') resourceError.value = event.detail || event.message || '本章资源生成失败'
      }, resourceController.signal)
      if (resourceError.value) throw new Error(resourceError.value)
      detail = await fundamentalsApi.getNode(learningPath.value.path_id, activeNode.value.id)
      if (loadVersion !== nodeLoadVersion) return
      nodeDetail.value = detail
      resources = detail?.progress?.resources || []
      document = findResource(resources, 'document')
    }

    if (!document) throw new Error('资源生成完成，但没有找到本章主讲文档')
    const fullDocument = await fundamentalsApi.getResource(normalizeResourceId(document))
    if (loadVersion !== nodeLoadVersion) return
    documentResource.value = fullDocument
    documentContent.value = normalizeDocumentContent(fullDocument?.content)
    mindmapResource.value = findResource(resources, 'mindmap')
    if (!documentContent.value) throw new Error('本章文档内容为空，请重新生成后再试')
  } catch (error) {
    if (error.name !== 'AbortError' && loadVersion === nodeLoadVersion) {
      resourceError.value = errorDetail(error, '本章学习材料加载失败。')
    }
  } finally {
    if (loadVersion === nodeLoadVersion) isResourceLoading.value = false
  }
}

async function showMindmap() {
  if (!mindmapResource.value || isMindmapLoading.value) return
  resourceView.value = 'mindmap'
  if (mindmapContent.value) return
  isMindmapLoading.value = true
  try {
    const resource = await fundamentalsApi.getResource(normalizeResourceId(mindmapResource.value))
    mindmapContent.value = normalizeDocumentContent(resource?.content)
  } catch (error) {
    resourceError.value = errorDetail(error, '知识结构加载失败。')
    resourceView.value = 'document'
  } finally {
    isMindmapLoading.value = false
  }
}

async function reportReadDuration() {
  const resourceId = documentResource.value?.resource_id
  if (!resourceId || !openedAt || hasReportedCurrentRead) return
  hasReportedCurrentRead = true
  const seconds = Math.max(1, Math.round((Date.now() - openedAt) / 1000))
  try {
    await fundamentalsApi.markResourceRead(resourceId, seconds)
  } catch {
    hasReportedCurrentRead = false
  }
}

async function openChapterCheck() {
  await reportReadDuration()
  resourceView.value = 'document'
  isChecking.value = true
}

async function handleChapterPassed() {
  const finishedIndex = activeNodeIndex.value
  isChecking.value = false
  try {
    const refreshed = await fundamentalsApi.getCurrentPath()
    if (refreshed?.nodes) learningPath.value = refreshed
    const nextNode = learningPath.value?.nodes[finishedIndex + 1]
    if (nextNode && nextNode.status !== 'locked') await selectNode(nextNode.id)
  } catch (error) {
    pageError.value = errorDetail(error, '章节已完成，但刷新下一章时失败。')
  }
}

onMounted(loadPage)
onBeforeUnmount(() => {
  resourceController?.abort()
  reportReadDuration()
})
</script>

<style scoped>
.fundamentals-page { min-width: 0; }
.lesson-context { display: flex; align-items: flex-end; justify-content: space-between; gap: 28px; margin-bottom: 24px; }
.lesson-context__copy { min-width: 0; }
.lesson-context__copy .eyebrow { margin-bottom: 8px; }
.lesson-context h1 { max-width: 760px; margin: 0; color: var(--ink); font-size: clamp(27px, 3vw, 38px); line-height: 1.22; }
.lesson-context__copy > p:last-child { max-width: 680px; margin: 9px 0 0; color: var(--muted); font-size: 13px; line-height: 1.65; }
.path-progress { display: grid; flex: 0 0 190px; gap: 8px; }
.path-progress > div:first-child { display: flex; align-items: baseline; justify-content: space-between; color: var(--muted); font-size: 10px; }
.path-progress strong { color: var(--accent-deep); font-size: 20px; }
.path-progress small { color: var(--muted); font-size: 10px; text-align: right; }
.learning-layout { display: grid; grid-template-columns: 168px minmax(440px, 1fr) 286px; align-items: start; gap: 14px; }
.lesson-main { display: grid; min-width: 0; gap: 12px; }
.resource-toolbar { display: flex; min-height: 38px; align-items: center; justify-content: space-between; gap: 12px; }
.resource-tabs { display: flex; align-items: center; gap: 4px; }
.resource-tabs button { display: inline-flex; min-height: 34px; align-items: center; gap: 7px; padding: 0 10px; border: 0; border-radius: 4px; background: transparent; color: var(--muted); font-size: 11px; }
.resource-tabs button:hover:not(:disabled) { background: #e9eeea; color: var(--ink); }
.resource-tabs button.is-active { background: #e4ecdd; color: var(--accent-deep); font-weight: 800; }
.resource-tabs button:disabled { cursor: wait; opacity: .55; }
.resource-status { display: inline-flex; align-items: center; gap: 6px; color: var(--muted); font-size: 10px; }
.resource-status .status-dot { width: 6px; height: 6px; }
.chapter-footer { display: grid; grid-template-columns: auto minmax(0, 1fr) auto; align-items: center; gap: 18px; padding: 15px 17px; }
.chapter-footer__copy { display: grid; min-width: 0; gap: 4px; text-align: center; }
.chapter-footer__copy strong { font-size: 11px; }
.chapter-footer__copy span { color: var(--muted); font-size: 9px; }
.chapter-footer .button { gap: 7px; white-space: nowrap; }
.chapter-footer .button:disabled { cursor: not-allowed; opacity: .45; }
.page-state, .document-loading { display: grid; place-items: center; align-content: center; gap: 10px; color: var(--accent-deep); text-align: center; }
.page-state { min-height: 520px; padding: 50px; }
.document-loading { min-height: 680px; padding: 40px; }
.page-state strong, .document-loading strong { color: var(--ink); font-size: 16px; }
.page-state p, .document-loading p { max-width: 440px; margin: 0; color: var(--muted); font-size: 12px; line-height: 1.7; }
.page-state .button, .document-loading .button { margin-top: 8px; }
.page-state--error, .document-loading--error { color: #a66442; }
.spin { animation: spin .8s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
@media (max-width: 1100px) {
  .learning-layout { grid-template-columns: minmax(0, 1fr) 286px; }
  .learning-layout > :first-child { grid-column: 1 / -1; }
}
@media (max-width: 840px) {
  .lesson-context { align-items: stretch; flex-direction: column; gap: 16px; }
  .path-progress { flex-basis: auto; width: min(360px, 100%); }
  .path-progress small { text-align: left; }
  .learning-layout { grid-template-columns: 1fr; }
  .learning-layout > :first-child { grid-column: auto; }
}
@media (max-width: 620px) {
  .resource-toolbar { align-items: flex-start; flex-direction: column; }
  .chapter-footer { grid-template-columns: 1fr 1fr; }
  .chapter-footer__copy { grid-column: 1 / -1; grid-row: 1; }
  .chapter-footer .button { width: 100%; }
}
</style>
