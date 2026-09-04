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

    <div v-else-if="!learningPath && !pathCatalog.length" class="page-state surface">
      <Route :size="28" />
      <strong>还没有可以学习的路径</strong>
      <p>先完成学习定向与能力诊断，系统才会按你的目标生成科目和章节。</p>
      <RouterLink class="button button--primary" to="/onboarding/direction">开始学习定向</RouterLink>
    </div>

    <template v-else>
      <div v-if="pathSwitchError" class="path-switch-error" role="status">
        <CircleAlert :size="16" />
        <span>{{ pathSwitchError }}</span>
        <button class="button button--quiet" type="button" @click="pathSwitchError = ''">关闭</button>
      </div>

      <div v-if="!learningPath" class="page-state surface">
        <Route :size="25" />
        <strong>请选择一条学习路径</strong>
        <p>打开科目抽屉，从当前学习方向下的相关科目中选择一条路径。</p>
        <button class="button button--primary" type="button" @click="openNavigationDrawer('paths')">选择学习科目</button>
      </div>

      <template v-else>
        <header class="lesson-context">
          <div class="lesson-context__copy">
            <p class="eyebrow">基础讲解 · {{ learningPath.goal }}</p>
            <h1>{{ activeNode?.title || '选择一个章节' }}</h1>
            <p>第 {{ activeNodeIndex + 1 }} / {{ learningPath.nodes.length }} 章<span>{{ activeNode?.summary || '按学习路径逐章补齐知识基础。' }}</span></p>
          </div>
          <div class="path-progress" aria-label="当前科目学习进度">
            <div><span>科目进度</span><strong>{{ learningPath.progress }}%</strong></div>
            <div class="progress-track"><div class="progress-value" :style="{ width: `${learningPath.progress}%` }"></div></div>
            <small>已完成 {{ completedNodeCount }} / {{ learningPath.nodes.length }} 章</small>
          </div>
        </header>

        <div class="learning-layout">
          <nav class="workspace-rail" aria-label="学习内容切换">
            <button
              type="button"
              title="切换学习科目"
              aria-label="切换学习科目"
              aria-controls="fundamentals-navigation-drawer"
              :aria-expanded="navigationDrawer === 'paths'"
              :class="{ 'is-active': navigationDrawer === 'paths' }"
              @click="toggleNavigationDrawer('paths')"
            >
              <Route :size="18" />
              <span>科目</span>
              <small>{{ pathCatalog.length }}</small>
            </button>
            <button
              type="button"
              title="展开章节节点"
              aria-label="展开章节节点"
              aria-controls="fundamentals-navigation-drawer"
              :aria-expanded="navigationDrawer === 'chapters'"
              :class="{ 'is-active': navigationDrawer === 'chapters' }"
              @click="toggleNavigationDrawer('chapters')"
            >
              <ListTree :size="18" />
              <span>章节</span>
              <small>{{ activeNodeIndex + 1 }}</small>
            </button>
          </nav>

          <main class="lesson-main">
            <div class="resource-toolbar" aria-label="章节材料视图">
              <div class="resource-tabs">
                <button type="button" :class="{ 'is-active': resourceView === 'document' }" @click="showDocument">
                  <BookOpenText :size="15" />
                  <span>主讲文档</span>
                </button>
                <button
                  v-if="mindmapResource"
                  type="button"
                  :class="{ 'is-active': resourceView === 'mindmap' }"
                  :disabled="isMindmapLoading"
                  :title="mindmapError || '查看本章知识结构'"
                  @click="showMindmap"
                >
                  <Network :size="15" />
                  <span>{{ isMindmapLoading ? '读取中' : mindmapError ? '知识结构重试' : '知识结构' }}</span>
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
              @close="closeChapterCheck"
              @passed="handleChapterPassed"
            />

            <template v-else>
              <div v-if="isResourceLoading" class="document-loading surface" aria-live="polite">
                <LoaderCircle class="spin" :size="25" />
                <strong>{{ resourceLoadingMessage }}</strong>
                <p>页面会在文档准备好后自动显示，不需要重复刷新。</p>
              </div>

              <div v-else-if="documentError" class="document-loading document-loading--error surface">
                <CircleAlert :size="25" />
                <strong>本章文档暂时不可用</strong>
                <p>{{ documentError }}</p>
                <button class="button button--quiet" type="button" @click="loadActiveNode">重试本章</button>
              </div>

              <MarkdownDocument
                v-else
                wide
                :paginate="resourceView === 'document'"
                :show-title="false"
                :title="resourceView === 'mindmap' ? `${activeNode.title} · 知识结构` : activeNode.title"
                :content="visibleResourceContent"
                :tags="activeNode.knowledge_tags || []"
                :chapter-number="activeNodeIndex + 1"
                :empty-message="resourceView === 'mindmap' ? '本章暂时没有知识结构材料。' : '本章文档尚未生成。'"
              >
                <template #pagination-action="{ isLastPage }">
                  <button
                    v-if="isLastPage"
                    class="button button--primary document-pagination__action"
                    type="button"
                    :disabled="!documentContent || isResourceLoading"
                    @click="handlePrimaryAction"
                  >
                    {{ primaryActionLabel }}
                    <ArrowRight :size="15" />
                  </button>
                </template>
              </MarkdownDocument>

              <footer v-if="resourceView !== 'document'" class="chapter-footer surface">
                <button class="button button--quiet" type="button" :disabled="!previousNode" @click="previousNode && selectNode(previousNode.id)">
                  <ArrowLeft :size="15" />
                  上一章
                </button>
                <div class="chapter-footer__copy">
                  <strong>{{ chapterFooterTitle }}</strong>
                  <span>{{ documentContent ? `${estimatedReadMinutes} 分钟阅读 · ${activeNode.knowledge_tags?.length || 0} 个知识点` : '正在准备学习材料' }}</span>
                </div>
                <button class="button button--primary" type="button" :disabled="!documentContent || isResourceLoading" @click="handlePrimaryAction">
                  {{ primaryActionLabel }}
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
            :resource-id="documentResource?.resource_id"
          />
        </div>
      </template>
    </template>

    <Teleport to="body">
      <Transition name="drawer-fade">
        <button
          v-if="navigationDrawer"
          class="navigation-drawer-backdrop"
          type="button"
          aria-label="关闭学习导航"
          @click="closeNavigationDrawer"
        ></button>
      </Transition>
      <Transition name="drawer-slide">
        <aside
          v-if="navigationDrawer"
          id="fundamentals-navigation-drawer"
          class="navigation-drawer"
          role="dialog"
          aria-modal="true"
          :aria-labelledby="`${navigationDrawer}-drawer-title`"
        >
          <header class="navigation-drawer__header">
            <div>
              <p class="eyebrow">{{ navigationDrawer === 'paths' ? '学习方向拆解' : learningPath?.goal }}</p>
              <h2 :id="`${navigationDrawer}-drawer-title`">{{ navigationDrawer === 'paths' ? '切换学习科目' : '选择章节' }}</h2>
              <p>{{ navigationDrawer === 'paths' ? `${pathCatalog.length} 个相关科目，选择后正文和助教会同步切换。` : `第 ${activeNodeIndex + 1} / ${learningPath?.nodes?.length || 0} 章` }}</p>
            </div>
            <button type="button" title="关闭" aria-label="关闭学习导航" @click="closeNavigationDrawer">
              <X :size="18" />
            </button>
          </header>
          <div class="navigation-drawer__body">
            <PathPicker
              v-if="navigationDrawer === 'paths'"
              compact
              :paths="pathCatalog"
              :active-path-id="learningPath?.path_id"
              :loading="isPathsLoading"
              :switching="isPathSwitching"
              @select="selectPathFromDrawer"
            />
            <ChapterRail
              v-else-if="learningPath"
              drawer
              :nodes="learningPath.nodes"
              :active-node-id="activeNodeId"
              @select="selectNodeFromDrawer"
            />
          </div>
        </aside>
      </Transition>
    </Teleport>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ArrowLeft, ArrowRight, BookOpenText, CircleAlert, ListTree, LoaderCircle, Network, Route, X } from 'lucide-vue-next'
import ChapterCheck from '@/features/fundamentals/ChapterCheck.vue'
import ChapterRail from '@/features/fundamentals/ChapterRail.vue'
import LearningAssistant from '@/features/fundamentals/LearningAssistant.vue'
import MarkdownDocument from '@/features/fundamentals/MarkdownDocument.vue'
import PathPicker from '@/features/fundamentals/PathPicker.vue'
import { fundamentalsApi } from '@/shared/api/fundamentalsApi'
import { readPortrait } from '@/shared/api/portraitApi'

const route = useRoute()
const router = useRouter()
const isPageLoading = ref(true)
const pageError = ref('')
const learningPath = ref(null)
const pathCatalog = ref([])
const isPathsLoading = ref(true)
const isPathSwitching = ref(false)
const pathSwitchError = ref('')
const activeNodeId = ref(null)
const nodeDetail = ref(null)
const documentResource = ref(null)
const documentContent = ref('')
const mindmapResource = ref(null)
const mindmapContent = ref('')
const resourceView = ref('document')
const isResourceLoading = ref(false)
const isMindmapLoading = ref(false)
const navigationDrawer = ref(null)
const resourceLoadingMessage = ref('正在读取本章文档')
const documentError = ref('')
const mindmapError = ref('')
const isChecking = ref(false)
let resourceController = null
let nodeLoadVersion = 0
let openedAt = 0
let readReportPromise = null
let readingIntervalId = null

const activeNodeIndex = computed(() => learningPath.value?.nodes.findIndex((node) => node.id === activeNodeId.value) ?? -1)
const activeNode = computed(() => learningPath.value?.nodes[activeNodeIndex.value] || null)
const completedNodeCount = computed(() => learningPath.value?.nodes.filter((node) => node.status === 'completed').length || 0)
const previousNode = computed(() => {
  if (!learningPath.value || activeNodeIndex.value <= 0) return null
  return learningPath.value.nodes[activeNodeIndex.value - 1]
})
const nextNode = computed(() => {
  if (!learningPath.value || activeNodeIndex.value < 0) return null
  const candidate = learningPath.value.nodes[activeNodeIndex.value + 1]
  return candidate && candidate.status !== 'locked' ? candidate : null
})
const visibleResourceContent = computed(() => resourceView.value === 'mindmap' ? mindmapContent.value : documentContent.value)
const estimatedReadMinutes = computed(() => Math.max(3, Math.ceil(documentContent.value.replace(/\s/g, '').length / 420)))
const resourceStatusLabel = computed(() => {
  if (isResourceLoading.value) return '正在准备本章'
  if (documentError.value) return '同步异常'
  if (documentContent.value) return '内容已同步'
  return '等待内容'
})
const primaryActionLabel = computed(() => {
  if (activeNode.value?.status === 'completed' && nextNode.value) return '进入下一章'
  if (activeNode.value?.status === 'completed') return '复习本章检查'
  return '完成阅读，进入检查'
})
const chapterFooterTitle = computed(() => {
  if (activeNode.value?.status !== 'completed') return '读完正文，再用检查确认真正掌握'
  return nextNode.value ? '本章已完成，下一章已经解锁' : '本章已完成'
})

function openNavigationDrawer(drawer) {
  if (!['paths', 'chapters'].includes(drawer)) return
  navigationDrawer.value = drawer
}

function closeNavigationDrawer() {
  navigationDrawer.value = null
}

function toggleNavigationDrawer(drawer) {
  navigationDrawer.value = navigationDrawer.value === drawer ? null : drawer
}

function handleGlobalKeydown(event) {
  if (event.key === 'Escape') closeNavigationDrawer()
}

function errorDetail(error, fallback) {
  return error.response?.data?.detail || error.message || fallback
}

function normalizeResourceId(resource) {
  return resource?.resource_id || resource?.id || null
}

function mindmapTreeToMarkdown(tree) {
  if (!tree || typeof tree !== 'object') return ''
  const lines = []
  const walk = (node, depth) => {
    const topic = String(node?.topic || node?.title || node?.name || '').trim()
    if (!topic) return
    lines.push(depth === 0 ? `# ${topic}` : `${'  '.repeat(depth - 1)}- ${topic}`)
    const children = Array.isArray(node.children) ? node.children : []
    children.forEach((child) => walk(child, depth + 1))
  }
  walk(tree, 0)
  return lines.join('\n')
}

function normalizeResourceContent(content, resourceType = 'document') {
  if (content && typeof content === 'object') {
    if (resourceType === 'mindmap' || Array.isArray(content.children)) return mindmapTreeToMarkdown(content)
    const nestedContent = content.markdown ?? content.content ?? content.document ?? content.body
    return nestedContent === undefined ? '' : normalizeResourceContent(nestedContent, resourceType)
  }
  if (typeof content !== 'string') return ''
  const trimmed = content.trim()
  if (!trimmed.startsWith('{')) return trimmed
  try {
    const parsed = JSON.parse(trimmed)
    return normalizeResourceContent(parsed, resourceType) || trimmed
  } catch {
    return trimmed
  }
}

function findResource(resources, type) {
  return (resources || []).find((resource) => resource.resource_type === type) || null
}

function progressSummary(path, progress = null) {
  const nodes = Array.isArray(path?.nodes) ? path.nodes : []
  const rows = Array.isArray(progress?.nodes) ? progress.nodes : []
  const completedNodes = Number(progress?.completed_nodes ?? progress?.completed ?? nodes.filter((node) => node.status === 'completed').length)
  const totalNodes = Number(progress?.total_nodes ?? nodes.length)
  const currentRow = rows.find((row) => ['in_progress', 'unlocked'].includes(row.status))
  const currentNodeId = progress?.current_node_id ?? currentRow?.node_id ?? nodes.find((node) => ['in_progress', 'unlocked'].includes(node.status))?.id ?? null
  const currentNode = nodes.find((node) => Number(node.id) === Number(currentNodeId))
  const rawPercentage = progress?.percentage ?? path?.progress
  const fallbackPercentage = totalNodes ? completedNodes / totalNodes : 0
  const numericPercentage = Number(rawPercentage)
  const percentage = Number.isFinite(numericPercentage)
    ? (numericPercentage <= 1 ? numericPercentage * 100 : numericPercentage)
    : fallbackPercentage * 100
  return {
    percentage: Math.min(100, Math.max(0, Math.round(percentage))),
    completed_nodes: completedNodes,
    total_nodes: totalNodes,
    current_node: progress?.current_node || currentNode?.title || currentNode?.topic || '',
    current_node_id: currentNodeId,
  }
}

const SUBJECT_TERM_GROUPS = [
  { terms: ['python'], weight: 8 },
  { terms: ['rag'], weight: 8 },
  { terms: ['大模型', '语言模型'], weight: 5 },
  { terms: ['提示词', '提示工程', 'prompt'], weight: 5 },
  { terms: ['文档'], weight: 3 },
  { terms: ['向量', '嵌入', '语义'], weight: 4 },
  { terms: ['检索'], weight: 4 },
  { terms: ['知识库'], weight: 4 },
  { terms: ['架构'], weight: 3 },
  { terms: ['性能', '优化', '评估', '部署'], weight: 2 },
  { terms: ['编程', '数据处理'], weight: 3 },
  { terms: ['应用', '开发'], weight: 2 },
]

function normalizeSubject(value) {
  return String(value || '')
    .toLowerCase()
    .replace(/[\s·:：、，,。！？!?/\\_\-]+/g, '')
}

function subjectMatchScore(source, target) {
  const sourceText = normalizeSubject(source)
  const targetText = normalizeSubject(target)
  if (!sourceText || !targetText) return 0
  if (sourceText === targetText) return 1000
  let score = sourceText.includes(targetText) || targetText.includes(sourceText) ? 30 : 0
  SUBJECT_TERM_GROUPS.forEach(({ terms, weight }) => {
    const sourceHasTerm = terms.some((term) => sourceText.includes(normalizeSubject(term)))
    const targetHasTerm = terms.some((term) => targetText.includes(normalizeSubject(term)))
    if (sourceHasTerm && targetHasTerm) score += weight
  })
  const sourceBigrams = new Set(Array.from(sourceText).map((_, index) => sourceText.slice(index, index + 2)).filter((item) => item.length === 2))
  const sharedBigrams = Array.from(new Set(Array.from(targetText).map((_, index) => targetText.slice(index, index + 2)).filter((item) => item.length === 2)))
    .filter((item) => sourceBigrams.has(item)).length
  return score + Math.min(sharedBigrams, 8)
}

function selectRelatedPaths(values, relatedSubjects) {
  const selected = []
  const remaining = [...values]
  relatedSubjects.forEach((subject) => {
    let bestIndex = -1
    let bestScore = 0
    remaining.forEach((path, index) => {
      const score = subjectMatchScore(subject, path.subject)
      if (score > bestScore) {
        bestScore = score
        bestIndex = index
      }
    })
    // Do not present an unrelated historical path as a current-direction course.
    if (bestIndex >= 0 && bestScore >= 4) {
      selected.push({ ...remaining[bestIndex], related_subject: subject })
      remaining.splice(bestIndex, 1)
    }
  })
  return selected
}

function mergePathCatalog(pathList, statsPaths, currentPath = null, relatedSubjects = []) {
  const byId = new Map()
  ;(pathList || []).forEach((path) => {
    if (!path?.path_id) return
    byId.set(Number(path.path_id), { ...path, path_id: Number(path.path_id) })
  })
  ;(statsPaths || []).forEach((stat) => {
    if (!stat?.path_id) return
    const pathId = Number(stat.path_id)
    const existing = byId.get(pathId) || { path_id: pathId, subject: stat.subject || stat.goal || '' }
    byId.set(pathId, {
      ...existing,
      subject: existing.subject || stat.subject || stat.goal || '',
      difficulty: existing.difficulty || stat.difficulty,
      node_count: existing.node_count || stat.progress?.total_nodes || stat.total_nodes || 0,
      progress: stat.progress || existing.progress,
    })
  })
  if (currentPath?.path_id) {
    const pathId = Number(currentPath.path_id)
    const existing = byId.get(pathId) || { path_id: pathId }
    byId.set(pathId, {
      ...existing,
      subject: existing.subject || currentPath.goal || '',
      node_count: existing.node_count || currentPath.nodes?.length || 0,
      progress: {
        ...existing.progress,
        ...progressSummary(currentPath),
      },
    })
  }
  const values = [...byId.values()]
  if (relatedSubjects.length) {
    const subjects = relatedSubjects.map((subject) => String(subject || '').trim()).filter(Boolean)
    const relatedPaths = selectRelatedPaths(values, subjects)
    if (relatedPaths.length) return relatedPaths
  }
  return values.sort((left, right) => Number(right.path_id) - Number(left.path_id))
}

function chooseInitialNode(path, requestedNodeId = null) {
  if (!path || !Array.isArray(path.nodes)) return null
  const requestedNode = Number(requestedNodeId)
  if (requestedNode > 0) {
    const requested = path.nodes.find((node) => Number(node.id) === requestedNode && node.status !== 'locked')
    if (requested) return requested
  }
  return path.nodes.find((node) => Number(node.id) === Number(path.current_node_id))
    || path.nodes.find((node) => node.status === 'in_progress' || node.status === 'unlocked')
    || [...path.nodes].reverse().find((node) => node.status === 'completed')
    || path.nodes[0]
    || null
}

async function loadPathWorkspace(pathId) {
  const selected = await fundamentalsApi.getCurrentPath(pathId)
  if (selected && Number(selected.path_id) === Number(pathId) && Array.isArray(selected.nodes)) return selected

  // Older deployments may not support the path_id query parameter yet. Build
  // the same workspace shape from the protected path and progress endpoints.
  const [detail, progress] = await Promise.all([
    fundamentalsApi.getPath(pathId),
    fundamentalsApi.getPathProgress(pathId).catch(() => null),
  ])
  if (!detail) return null
  const progressRows = Array.isArray(progress?.nodes) ? progress.nodes : []
  const nodes = (detail.nodes || []).map((node, index) => {
    const id = node.node_id ?? node.id
    const row = progressRows.find((item) => Number(item.node_id) === Number(id))
    return {
      id,
      title: node.topic || node.title || `第 ${index + 1} 节`,
      summary: node.description || '',
      knowledge_tags: node.knowledge_tags || [],
      resource_types: node.resource_types || [],
      teaching_spec: node.teaching_spec || null,
      status: row?.status || (index === 0 ? 'unlocked' : 'locked'),
      session_id: row?.session_id || null,
      resources: [],
    }
  })
  const currentNodeId = progress?.current_node_id
    || nodes.find((node) => node.status === 'in_progress' || node.status === 'unlocked')?.id
    || null
  const completedNodes = nodes.filter((node) => node.status === 'completed').length
  return {
    path_id: detail.path_id,
    goal: detail.subject,
    stage: `${completedNodes}/${nodes.length}`,
    progress: progress?.percentage ?? Math.round(completedNodes / Math.max(nodes.length, 1) * 100),
    current_node_id: currentNodeId,
    nodes,
    next_action: currentNodeId ? { target_id: currentNodeId, type: 'read', label: '开始学习' } : null,
    diagnosis: null,
  }
}

function syncPathCatalog(path) {
  if (!path?.path_id) return
  const pathId = Number(path.path_id)
  const summary = {
    path_id: pathId,
    subject: path.goal || '',
    node_count: path.nodes?.length || 0,
    progress: progressSummary(path),
  }
  const index = pathCatalog.value.findIndex((item) => Number(item.path_id) === pathId)
  if (index < 0) pathCatalog.value = [...pathCatalog.value, summary]
  else pathCatalog.value[index] = { ...pathCatalog.value[index], ...summary }
}

async function loadPage() {
  isPageLoading.value = true
  pageError.value = ''
  pathSwitchError.value = ''
  isPathsLoading.value = true
  try {
    const [pathListResult, pathStatsResult, currentResult, portraitResult] = await Promise.allSettled([
      fundamentalsApi.listPaths(),
      fundamentalsApi.getPathStats(),
      fundamentalsApi.getCurrentPath(),
      readPortrait(),
    ])
    const pathList = pathListResult.status === 'fulfilled' && Array.isArray(pathListResult.value) ? pathListResult.value : []
    const pathStats = pathStatsResult.status === 'fulfilled' ? pathStatsResult.value : null
    let current = currentResult.status === 'fulfilled' ? currentResult.value : null
    const portrait = portraitResult.status === 'fulfilled' ? portraitResult.value : null
    const relatedSubjects = Array.isArray(portrait?.traits?.learning_direction_subjects)
      ? portrait.traits.learning_direction_subjects
      : []
    pathCatalog.value = mergePathCatalog(pathList, pathStats?.paths, current, relatedSubjects)

    const requestedPathId = Number(route.query.pathId)
    const listedPathIds = new Set(pathCatalog.value.map((path) => Number(path.path_id)))
    const selectedPathId = requestedPathId > 0 && listedPathIds.has(requestedPathId)
      ? requestedPathId
      : (current?.path_id && listedPathIds.has(Number(current.path_id))
          ? current.path_id
          : pathCatalog.value[0]?.path_id)
    if (selectedPathId && (!current || Number(current.path_id) !== Number(selectedPathId))) {
      current = await loadPathWorkspace(selectedPathId)
    }
    if (!current || !Array.isArray(current.nodes) || !current.nodes.length) {
      learningPath.value = null
      activeNodeId.value = null
      return
    }
    learningPath.value = current
    syncPathCatalog(current)
    const initialNode = chooseInitialNode(current, route.query.node)
    if (selectedPathId && (Number(route.query.pathId) !== Number(selectedPathId)
      || (initialNode && Number(route.query.node) !== Number(initialNode.id)))) {
      await router.replace({
        query: {
          ...route.query,
          pathId: selectedPathId,
          ...(initialNode ? { node: initialNode.id } : {}),
        },
      })
    }
    if (initialNode) {
      isPageLoading.value = false
      await selectNode(initialNode.id, false)
    }
  } catch (error) {
    pageError.value = errorDetail(error, '无法读取当前学习路径，请稍后重试。')
  } finally {
    isPathsLoading.value = false
    isPageLoading.value = false
  }
}

async function selectPath(pathId) {
  const nextPathId = Number(pathId)
  if (!nextPathId || isPathSwitching.value || Number(learningPath.value?.path_id) === nextPathId) return
  isPathSwitching.value = true
  pathSwitchError.value = ''
  await reportReadDuration(true)
  resourceController?.abort()
  try {
    const selected = await loadPathWorkspace(nextPathId)
    if (!selected || !Array.isArray(selected.nodes) || !selected.nodes.length) throw new Error('这条路径暂时没有可学习的章节')
    learningPath.value = selected
    activeNodeId.value = null
    syncPathCatalog(selected)
    const initialNode = chooseInitialNode(selected)
    await router.replace({ query: { ...route.query, pathId: nextPathId, node: initialNode?.id } })
    if (initialNode) {
      isPageLoading.value = false
      // Path selection should finish before the potentially slow document
      // generation begins, so the user can switch to another subject anytime.
      void selectNode(initialNode.id, false).catch((error) => {
        if (error?.name !== 'AbortError') pathSwitchError.value = errorDetail(error, '本章材料加载失败，请稍后重试。')
      })
    }
  } catch (error) {
    pathSwitchError.value = errorDetail(error, '无法打开这条学习路径，请稍后重试。')
  } finally {
    isPathSwitching.value = false
  }
}

async function selectPathFromDrawer(pathId) {
  closeNavigationDrawer()
  await selectPath(pathId)
}

async function selectNodeFromDrawer(nodeId) {
  closeNavigationDrawer()
  await selectNode(nodeId)
}

async function selectNode(nodeId, updateUrl = true) {
  const node = learningPath.value?.nodes.find((item) => item.id === nodeId)
  if (!node || node.status === 'locked') return
  if (activeNodeId.value && activeNodeId.value !== nodeId) await reportReadDuration(true)
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
  documentError.value = ''
  mindmapError.value = ''
  nodeDetail.value = null
  documentResource.value = null
  documentContent.value = ''
  mindmapResource.value = null
  mindmapContent.value = ''
  openedAt = 0

  try {
    let detail = await fundamentalsApi.getNode(learningPath.value.path_id, activeNode.value.id)
    if (loadVersion !== nodeLoadVersion) return
    nodeDetail.value = detail
    let resources = detail?.progress?.resources || activeNode.value.resources || []
    let documentSummary = findResource(resources, 'document')

    // Always pass through the idempotent path-node resource endpoint.  The
    // backend decides whether to reuse a validated binding or generate a
    // missing/stale chapter; the page must not infer that from a summary row.
    resourceLoadingMessage.value = documentSummary
      ? '正在校验本章资源'
      : '正在调用资源生成服务'
    await fundamentalsApi.generateResources(
      learningPath.value.path_id,
      activeNode.value.id,
      (event) => {
        if (event?.type === 'status') {
          resourceLoadingMessage.value = event.msg || event.message || resourceLoadingMessage.value
        }
        if (event?.type === 'resource') {
          resourceLoadingMessage.value = event.resource_type === 'document'
            ? '主讲文档已准备，正在读取正文'
            : '章节资源已准备'
        }
        if (event?.type === 'error') {
          documentError.value = event.detail || event.message || '本章资源生成失败'
        }
      },
      resourceController.signal,
      detail?.resource_types || activeNode.value.resource_types,
    )
    if (documentError.value) throw new Error(documentError.value)
    detail = await fundamentalsApi.getNode(learningPath.value.path_id, activeNode.value.id)
    if (loadVersion !== nodeLoadVersion) return
    nodeDetail.value = detail
    resources = detail?.progress?.resources || []
    documentSummary = findResource(resources, 'document')

    if (!documentSummary) throw new Error('资源生成完成，但没有找到本章主讲文档')
    const fullDocument = await fundamentalsApi.getResource(normalizeResourceId(documentSummary))
    if (loadVersion !== nodeLoadVersion) return
    documentResource.value = fullDocument
    documentContent.value = normalizeResourceContent(fullDocument?.content, 'document')
    mindmapResource.value = findResource(resources, 'mindmap')
    if (!documentContent.value) throw new Error('本章文档内容为空，请重新生成后再试')
    if (document.visibilityState === 'visible') openedAt = Date.now()
  } catch (error) {
    if (error.name !== 'AbortError' && loadVersion === nodeLoadVersion) {
      documentError.value = errorDetail(error, '本章学习材料加载失败。')
    }
  } finally {
    if (loadVersion === nodeLoadVersion) isResourceLoading.value = false
  }
}

async function showMindmap() {
  if (!mindmapResource.value || isMindmapLoading.value) return
  await reportReadDuration(true)
  resourceView.value = 'mindmap'
  openedAt = 0
  if (mindmapContent.value) return
  isMindmapLoading.value = true
  mindmapError.value = ''
  try {
    const resource = await fundamentalsApi.getResource(normalizeResourceId(mindmapResource.value))
    mindmapContent.value = normalizeResourceContent(resource?.content, 'mindmap')
    if (!mindmapContent.value) throw new Error('知识结构内容为空')
  } catch (error) {
    mindmapError.value = errorDetail(error, '知识结构加载失败。')
    resourceView.value = 'document'
    if (document.visibilityState === 'visible') openedAt = Date.now()
  } finally {
    isMindmapLoading.value = false
  }
}

function showDocument() {
  if (resourceView.value === 'document') return
  resourceView.value = 'document'
  if (documentContent.value && document.visibilityState === 'visible' && !isChecking.value) openedAt = Date.now()
}

async function reportReadDuration(force = false) {
  const resourceId = documentResource.value?.resource_id
  if (readReportPromise) return readReportPromise
  if (!resourceId || !openedAt) return
  if (!force && (document.visibilityState !== 'visible' || resourceView.value !== 'document' || isChecking.value)) return
  const seconds = Math.max(1, Math.round((Date.now() - openedAt) / 1000))
  openedAt = 0
  readReportPromise = fundamentalsApi.markResourceRead(resourceId, seconds).catch(() => null)
  await readReportPromise
  readReportPromise = null
  if (documentResource.value?.resource_id === resourceId && resourceView.value === 'document' && !isChecking.value && document.visibilityState === 'visible') openedAt = Date.now()
}

async function openChapterCheck() {
  await reportReadDuration(true)
  resourceView.value = 'document'
  isChecking.value = true
  openedAt = 0
}

function closeChapterCheck() {
  isChecking.value = false
  if (documentContent.value && document.visibilityState === 'visible') openedAt = Date.now()
}

async function handlePrimaryAction() {
  if (activeNode.value?.status === 'completed' && nextNode.value) {
    await selectNode(nextNode.value.id)
    return
  }
  await openChapterCheck()
}

async function handleChapterPassed() {
  const finishedIndex = activeNodeIndex.value
  isChecking.value = false
  try {
    const currentPathId = learningPath.value?.path_id
    const refreshed = currentPathId ? await fundamentalsApi.getCurrentPath(currentPathId) : null
    if (refreshed?.nodes) {
      learningPath.value = refreshed
      syncPathCatalog(refreshed)
    }
    const nextNode = learningPath.value?.nodes[finishedIndex + 1]
    if (nextNode && nextNode.status !== 'locked') await selectNode(nextNode.id)
  } catch (error) {
    pageError.value = errorDetail(error, '章节已完成，但刷新下一章时失败。')
  }
}

function handleVisibilityChange() {
  if (document.visibilityState === 'hidden') {
    void reportReadDuration(true)
  } else if (documentContent.value && resourceView.value === 'document' && !isChecking.value) {
    openedAt = Date.now()
  }
}

onMounted(() => {
  document.addEventListener('visibilitychange', handleVisibilityChange)
  document.addEventListener('keydown', handleGlobalKeydown)
  readingIntervalId = window.setInterval(() => void reportReadDuration(), 30000)
  loadPage()
})
onBeforeUnmount(() => {
  resourceController?.abort()
  document.removeEventListener('visibilitychange', handleVisibilityChange)
  document.removeEventListener('keydown', handleGlobalKeydown)
  if (readingIntervalId) window.clearInterval(readingIntervalId)
  void reportReadDuration(true)
})
</script>

<style scoped>
.fundamentals-page { min-width: 0; }
.lesson-context { display: flex; align-items: center; justify-content: space-between; gap: 28px; margin-bottom: 12px; padding: 0 0 16px; border-bottom: 1px solid var(--line); }
.lesson-context__copy { min-width: 0; }
.lesson-context__copy .eyebrow { margin-bottom: 6px; }
.lesson-context h1 { max-width: 920px; margin: 0; color: var(--ink); font-size: clamp(22px, 2.1vw, 30px); line-height: 1.25; }
.lesson-context__copy > p:last-child { max-width: 880px; margin: 7px 0 0; color: var(--muted); font-size: 12px; line-height: 1.6; }
.lesson-context__copy > p:last-child span { margin-left: 9px; }
.lesson-context__copy > p:last-child span::before { content: "·"; margin-right: 10px; color: #a5aea7; }
.path-progress { display: grid; flex: 0 0 180px; gap: 7px; }
.path-progress > div:first-child { display: flex; align-items: baseline; justify-content: space-between; color: var(--muted); font-size: 10px; }
.path-progress strong { color: var(--accent-deep); font-size: 18px; }
.path-progress small { color: var(--muted); font-size: 10px; text-align: right; }
.learning-layout { display: grid; grid-template-columns: 52px minmax(0, 1fr) minmax(280px, 310px); align-items: start; gap: 14px; }
.path-switch-error { display: flex; min-height: 42px; align-items: center; gap: 9px; margin: 0 0 12px; padding: 9px 12px; border: 1px solid #ead6c8; border-radius: 6px; background: #fff9f4; color: #965536; font-size: 11px; }
.path-switch-error > span { min-width: 0; flex: 1; }
.path-switch-error .button { min-height: 28px; padding: 0 9px; font-size: 10px; }
.workspace-rail { position: sticky; top: 82px; display: grid; gap: 7px; min-width: 0; padding: 5px; border: 1px solid var(--line); border-radius: 7px; background: var(--paper); }
.workspace-rail button { position: relative; display: grid; width: 40px; min-height: 57px; place-items: center; align-content: center; gap: 4px; padding: 5px 2px; border: 0; border-radius: 5px; background: transparent; color: var(--muted); transition: background .16s ease, color .16s ease; }
.workspace-rail button:hover,
.workspace-rail button.is-active { background: #e8efdf; color: var(--accent-deep); }
.workspace-rail button:focus-visible { outline: 2px solid var(--accent-deep); outline-offset: 2px; }
.workspace-rail button > span { font-size: 9px; font-weight: 800; }
.workspace-rail button > small { position: absolute; top: 4px; right: 4px; display: grid; min-width: 14px; height: 14px; place-items: center; padding: 0 3px; border-radius: 7px; background: var(--soft); color: var(--accent-deep); font-size: 8px; font-weight: 800; }
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
.navigation-drawer-backdrop { position: fixed; inset: 64px 0 0 112px; z-index: 29; border: 0; background: rgba(12, 28, 22, .28); cursor: default; }
.navigation-drawer { position: fixed; top: 64px; bottom: 0; left: 112px; z-index: 30; display: flex; width: min(420px, calc(100vw - 112px)); flex-direction: column; border-right: 1px solid var(--line); background: var(--paper); color: var(--ink); box-shadow: 18px 0 44px rgba(8, 28, 20, .18); }
.navigation-drawer__header { display: flex; flex: 0 0 auto; align-items: flex-start; justify-content: space-between; gap: 16px; padding: 24px 22px 20px; border-bottom: 1px solid var(--line); }
.navigation-drawer__header .eyebrow { max-width: 310px; margin-bottom: 7px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.navigation-drawer__header h2 { margin: 0; font-size: 21px; line-height: 1.3; }
.navigation-drawer__header p:last-child { margin: 8px 0 0; color: var(--muted); font-size: 11px; line-height: 1.6; }
.navigation-drawer__header > button { display: grid; width: 34px; height: 34px; flex: 0 0 34px; place-items: center; border: 1px solid var(--line); border-radius: 5px; background: var(--paper); color: var(--muted); }
.navigation-drawer__header > button:hover { background: #edf2ed; color: var(--ink); }
.navigation-drawer__header > button:focus-visible { outline: 2px solid var(--accent-deep); outline-offset: 2px; }
.navigation-drawer__body { min-height: 0; flex: 1 1 auto; overflow-y: auto; padding: 20px 18px 32px; scrollbar-width: thin; }
.drawer-fade-enter-active,
.drawer-fade-leave-active { transition: opacity .18s ease; }
.drawer-fade-enter-from,
.drawer-fade-leave-to { opacity: 0; }
.drawer-slide-enter-active,
.drawer-slide-leave-active { transition: transform .25s cubic-bezier(.16, 1, .3, 1), opacity .18s ease; }
.drawer-slide-enter-from,
.drawer-slide-leave-to { opacity: 0; transform: translateX(-24px); }
.page-state, .document-loading { display: grid; place-items: center; align-content: center; gap: 10px; color: var(--accent-deep); text-align: center; }
.page-state { min-height: clamp(420px, calc(100vh - 260px), 520px); padding: 42px; }
.document-loading { min-height: clamp(420px, calc(100vh - 380px), 680px); padding: 36px; }
.page-state strong, .document-loading strong { color: var(--ink); font-size: 16px; }
.page-state p, .document-loading p { max-width: 440px; margin: 0; color: var(--muted); font-size: 12px; line-height: 1.7; }
.page-state .button, .document-loading .button { margin-top: 8px; }
.page-state--error, .document-loading--error { color: #a66442; }
.spin { animation: spin .8s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
@media (max-width: 1120px) {
  .learning-layout { grid-template-columns: 52px minmax(0, 1fr); }
  .learning-layout > :last-child { grid-column: 2; }
  .learning-layout :deep(.learning-assistant) { position: relative; top: auto; height: 520px; min-height: 420px; max-height: none; }
}
@media (max-width: 860px) {
  .navigation-drawer-backdrop { left: 0; }
  .navigation-drawer { left: 0; width: min(420px, 100vw); }
}
@media (max-width: 680px) {
  .lesson-context { align-items: stretch; flex-direction: column; gap: 16px; }
  .path-progress { flex-basis: auto; width: min(360px, 100%); }
  .path-progress small { text-align: left; }
  .learning-layout { grid-template-columns: 1fr; }
  .learning-layout > :last-child { grid-column: auto; }
  .workspace-rail { position: static; display: flex; gap: 7px; padding: 0 0 10px; border: 0; border-bottom: 1px solid var(--line); border-radius: 0; background: transparent; }
  .workspace-rail button { display: flex; width: auto; min-width: 72px; min-height: 38px; gap: 6px; padding: 0 10px; }
  .workspace-rail button > small { position: static; min-width: 16px; }
  .lesson-context__copy > p:last-child { display: grid; gap: 5px; }
  .lesson-context__copy > p:last-child span { margin-left: 0; }
  .lesson-context__copy > p:last-child span::before { display: none; }
  .resource-toolbar { align-items: flex-start; flex-direction: column; }
  .chapter-footer { grid-template-columns: 1fr 1fr; }
  .chapter-footer__copy { grid-column: 1 / -1; grid-row: 1; }
  .chapter-footer .button { width: 100%; }
  .navigation-drawer__header { padding: 20px 18px 17px; }
  .navigation-drawer__body { padding: 17px 14px 28px; }
}
</style>
