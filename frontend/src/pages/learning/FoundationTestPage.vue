<template>
  <div class="foundation-test-page">
    <PageTitle
      eyebrow="FOUNDATION TEST"
      title="学习复盘"
      description="用题目测试和费曼反讲确认本章掌握情况，结果会同步到学习概览。"
    >
      <!-- **这一页必须给往前走的门。** 它是整条主线的中转站：基础学习每章的主按钮
           （「完成阅读，进入检查」）就跳到这里。而这里原来唯一的按钮是「回到基础学习」——
           一个指向**后面**的动作，两个阶段共用。于是整条路径都学完的学生站在这里，
           找不到去做实战任务的路，只能自己回到侧边栏猜第三个图标是干什么的。
           现在按路径的实际状态分岔：学完 → 进阶学习；没学完 → 回去继续下一章。 -->
      <template #actions>
        <RouterLink v-if="pathCompleted" class="button button--primary" to="/learning/advanced">
          去做实战任务
          <ArrowRight :size="15" />
        </RouterLink>
        <RouterLink v-else class="button button--quiet" to="/learning/fundamentals">继续基础学习</RouterLink>
      </template>
    </PageTitle>

    <section v-if="loading" class="surface surface-pad foundation-state" aria-live="polite">
      <LoaderCircle class="spin" :size="22" />
      <div><strong>正在同步可测试章节</strong><p>读取你的学习路径和当前章节材料。</p></div>
    </section>
    <section v-else-if="errorMessage" class="surface surface-pad foundation-state foundation-state--error">
      <CircleAlert :size="22" />
      <div><strong>学习复盘暂时不可用</strong><p>{{ errorMessage }}</p></div>
      <button class="button button--quiet" type="button" @click="loadPage">重试</button>
    </section>
    <section v-else-if="!learningPath" class="surface surface-pad foundation-state">
      <Route :size="22" />
      <div><strong>还没有可测试的学习路径</strong><p>先完成学习定向、能力诊断并生成学习路径。</p></div>
      <RouterLink class="button button--primary" to="/onboarding/direction">开始学习定向</RouterLink>
    </section>

    <template v-else>
      <StudyGarden
        v-if="!isReviewOpen"
        :nodes="learningPath.nodes || []"
        :active-node-id="null"
        @select="selectNode"
      />

      <TreeReviewScene
        v-else-if="activeNode"
        :node="activeNode"
        :latest-score-label="latestScoreLabel"
        :answer-summary="answerSummary"
        :mastery-label="masteryLabel"
        :mastery-value="masteryValue"
        :weak-points="testInsights.weakPoints"
        :next-suggestion-title="nextSuggestionTitle"
        :next-suggestion-reason="nextSuggestionReason"
        :can-start-test="canStartTest"
        @back="closeReview"
        @quiz="openQuiz"
        @feynman="activeTab = 'feynman'"
        @learn="leaveTest"
      />

      <section v-if="isReviewOpen && nodeError" class="surface surface-pad foundation-state foundation-state--error">
        <CircleAlert :size="22" />
        <div><strong>当前章节无法读取</strong><p>{{ nodeError }}</p></div>
        <button class="button button--quiet" type="button" @click="loadNode">重试</button>
      </section>

      <template v-if="isReviewOpen && activeNode">
        <FeynmanCoach
          v-if="canStartTest && activeTab === 'feynman'"
          :key="`feynman-${activeNode.id}`"
          :path-id="learningPath.path_id"
          :node-id="activeNode.id"
          :chapter-title="activeNode.title"
          :chapter-content="chapterContent"
          :knowledge-tags="activeNode.knowledge_tags || []"
          :resource-id="documentResource?.resource_id || documentResource?.id"
          @end="leaveTest"
          @recorded="loadNode"
        />
      </template>

      <p v-if="notice" class="test-notice" role="status">{{ notice }}</p>
    </template>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { ArrowRight, CircleAlert, LoaderCircle, Route } from 'lucide-vue-next'
import { useRoute, useRouter } from 'vue-router'
import FeynmanCoach from '@/features/fundamentals/FeynmanCoach.vue'
import StudyGarden from '@/features/fundamentals/StudyGarden.vue'
import TreeReviewScene from '@/features/fundamentals/TreeReviewScene.vue'
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
const isReviewOpen = ref(false)
const nodeDetail = ref(null)
const documentResource = ref(null)
const chapterContent = ref('')
const activeTab = ref('')
const testInsights = ref(createEmptyInsights())

const testableNodes = computed(() => (learningPath.value?.nodes || []).filter((node) => node.status !== 'locked'))

// 整条路径学完没有 —— 决定头部那个按钮指向"继续基础学习"还是"去做实战任务"。
// 判据就是节点状态本身：`get_current_path` 的载荷里**没有** completed 字段（见
// path/service.py 的返回），而"每个节点都 completed"就是它的定义，不需要再问一次服务端。
// 节点为空时算没学完：那说明路径还没生成出来，谈不上"学完了"。
const pathCompleted = computed(() => {
  const nodes = learningPath.value?.nodes || []
  return nodes.length > 0 && nodes.every((node) => node.status === 'completed')
})

// 复盘要复的是「用户最近所在的那一章」，不是「第一个没锁的章节」。
//
// 以前两处兜底取的都是"第一个 unlocked/in_progress 的节点"（服务端 current_node_id 也是这个口径，
// 见 path/service.py:2115）。实测这个口径会猜错：真实数据里 90 个 用户×路径 组合有 24 个
// 同时存在 ≥2 个 unlocked，主模式是「1..10 completed，11..14 unlocked」——
// 这时"第一个未锁"给出的是 11，而用户真正学完的最后一章是 10。复盘一章没碰过的内容没有意义。
// 后端 advanced/service.py:178 被同一个坑坑过，那边改成了"最近完成的节点"。
//
// 规则：**从后往前，取第一个"用户真正碰过的"节点**。
// 碰过 = completed（学完）或 in_progress（正在学）。路径是顺序解锁的
// （PathNode.order_index + prerequisites 门禁），所以最靠后的那个就是最近所在的章节。
//
// 不做 in_progress 优先：实测存在「15 正在学、16 已学完」这种回头补课的情况，
// 这时该取 16 而不是 15。
const ENGAGED_NODE_STATUSES = ['completed', 'in_progress']

function resolveFallbackNode(nodes) {
  const list = Array.isArray(nodes) ? nodes : []
  for (let i = list.length - 1; i >= 0; i -= 1) {
    if (ENGAGED_NODE_STATUSES.includes(list[i].status)) return list[i]
  }
  // 一章都还没碰过（刚加入路径）：最靠前的未锁节点才是"当前"。
  return list.find((node) => node.status === 'unlocked') || null
}

const activeNode = computed(() => testableNodes.value.find((node) => String(node.id) === String(activeNodeId.value)) || resolveFallbackNode(testableNodes.value) || null)
const canStartTest = computed(() => Boolean(activeNode.value?.resources_viewed))
const latestScore = computed(() => testInsights.value.masteryScore)
const latestScoreLabel = computed(() => latestScore.value === null || latestScore.value === undefined ? '--' : `${Math.round(Number(latestScore.value))}%`)
const answerSummary = computed(() => {
  const { totalAnswered, totalCorrect, totalQuestions } = testInsights.value
  if (totalAnswered) return `${totalCorrect} / ${totalAnswered} 题正确`
  return totalQuestions ? `本章已有 ${totalQuestions} 道待完成题目` : '本章尚未生成题目'
})
const masteryValue = computed(() => Math.max(0, Math.min(100, Number(latestScore.value || 0))))
const masteryLabel = computed(() => latestScore.value === null || latestScore.value === undefined ? '--' : `${Math.round(Number(latestScore.value))}%`)
const nextSuggestionTitle = computed(() => testInsights.value.recommendation?.action || '完成本章题目测试')
const nextSuggestionReason = computed(() => testInsights.value.recommendation?.reason || '本章还没有已提交的答题记录。')

function createEmptyInsights() {
  return { totalQuestions: 0, totalAnswered: 0, totalCorrect: 0, masteryScore: null, weakPoints: [], recommendation: null }
}

function collectWeakPoints(records) {
  const counts = new Map()
  records.filter((record) => record.is_correct === false).forEach((record) => {
    const tags = Array.isArray(record.question?.knowledge_tags) ? record.question.knowledge_tags : []
    tags.forEach((tag) => counts.set(tag, (counts.get(tag) || 0) + 1))
  })
  return [...counts.entries()]
    .sort(([, left], [, right]) => right - left)
    .map(([tag, count]) => ({ tag, count }))
}

function applyNodeSession(session) {
  const records = Array.isArray(session?.records) ? session.records : []
  const judged = records.filter((record) => typeof record.is_correct === 'boolean')
  const totalCorrect = judged.filter((record) => record.is_correct).length
  const masteryScore = judged.length ? Number(session.percentage ?? (totalCorrect / judged.length * 100)) : null
  const weakPoints = collectWeakPoints(records)
  const recommendation = !judged.length
    ? { action: '完成本章题目测试', reason: '本章还没有已提交的答题记录。' }
    : masteryScore < 60
      ? { action: '先回看错误知识点', reason: '本章答题正确率低于 60%，建议先针对错题复习。' }
      : masteryScore < 80
        ? { action: '再做一次巩固练习', reason: '本章已有基础掌握，可以通过补题巩固薄弱点。' }
        : { action: '进入下一学习节点', reason: '本章答题表现良好，可以继续下一节点。' }
  testInsights.value = {
    totalQuestions: Number(session?.total_questions || records.length),
    totalAnswered: judged.length,
    totalCorrect,
    masteryScore: Number.isFinite(masteryScore) ? masteryScore : null,
    weakPoints,
    recommendation,
  }
}

async function loadNodeInsights(sessionId) {
  testInsights.value = createEmptyInsights()
  if (!sessionId) return
  try {
    applyNodeSession(await fundamentalsApi.getQuizSession(sessionId))
  } catch (error) {
    if (error.response?.status !== 404) throw error
  }
}

function chooseNode(path) {
  // `node` is the canonical FundamentalsPage query key; accept the older
  // `nodeId` key so existing bookmarks continue to open the same chapter.
  const requested = route.query.node ?? route.query.nodeId
  activeNodeId.value = requested && path.nodes.some((node) => String(node.id) === String(requested))
    ? Number(requested)
    : resolveFallbackNode(path.nodes)?.id ?? null
  isReviewOpen.value = Boolean(requested)
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
    await loadNodeInsights(nodeDetail.value?.quiz_session_id)
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

  // 当前节点是学习复盘的必要数据，路径目录只是切换科目的辅助数据。
  // 不让目录接口的慢响应阻塞当前节点和题目组件的加载。
  try {
    const current = await fundamentalsApi.getCurrentPath(route.query.pathId)
    learningPath.value = current
    pathCatalog.value = current ? [{
      path_id: current.path_id,
      subject: current.goal || current.subject || '当前科目',
      node_count: current.nodes?.length || 0,
      progress: current.progress || 0,
    }] : []
    if (learningPath.value) {
      chooseNode(learningPath.value)
      await loadNode()
      if (route.query.autoStart === '1' && canStartTest.value && activeNode.value) {
        await router.replace({
          name: 'foundationQuiz',
          query: { pathId: learningPath.value.path_id, node: activeNode.value.id },
        })
        return
      }
    }

    // 目录加载失败不影响当前节点测试；成功后再补齐科目切换列表。
    void fundamentalsApi.listPaths()
      .then((paths) => {
        const catalog = Array.isArray(paths) ? paths : (paths?.paths || [])
        if (catalog.length) pathCatalog.value = catalog
      })
      .catch(() => {})
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
      activeTab.value = ''
      isReviewOpen.value = false
      await router.replace({ query: { pathId: selected.path_id } })
    } else nodeError.value = '这条学习路径尚未加入，暂时不能进行学习复盘。'
  } catch (error) {
    nodeError.value = error.response?.data?.detail || error.message || '切换学习路径失败，请重试。'
  } finally {
    switching.value = false
  }
}

async function selectNode(nodeId) {
  activeNodeId.value = nodeId
  isReviewOpen.value = true
  nodeError.value = ''
  await loadNode()
  activeTab.value = ''
  await router.replace({ query: { pathId: learningPath.value.path_id, node: nodeId } })
}

async function closeReview() {
  isReviewOpen.value = false
  activeTab.value = ''
  await router.replace({ query: { pathId: learningPath.value?.path_id } })
}

function leaveTest() {
  router.push({ path: '/learning/fundamentals', query: { pathId: learningPath.value?.path_id, node: activeNode.value?.id } })
}

function openQuiz() {
  if (!learningPath.value || !activeNode.value || !canStartTest.value) return
  router.push({ name: 'foundationQuiz', query: { pathId: learningPath.value.path_id, node: activeNode.value.id } })
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
.test-insights { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; margin: 0 0 18px; }
.insight-card { display: grid; min-width: 0; min-height: 118px; align-content: start; gap: 7px; padding: 16px; border: 1px solid #dfe6df; border-radius: 14px; background: #fff; box-shadow: 0 6px 16px rgba(31, 49, 40, .035); }
.insight-label { color: #728078; font-size: 11px; font-weight: 800; }
.insight-card strong { overflow: hidden; color: #203a33; font-size: 24px; line-height: 1.2; text-overflow: ellipsis; white-space: nowrap; }
.insight-card > span:last-child { overflow: hidden; color: #78857d; font-size: 11px; line-height: 1.5; text-overflow: ellipsis; white-space: nowrap; }
.insight-card--score strong { color: #3f5b31; }
.insight-card--next strong { font-size: 15px; }
.insight-tags { display: flex; flex-wrap: wrap; gap: 5px; min-width: 0; }
.insight-tags span { max-width: 100%; overflow: hidden; padding: 4px 7px; border-radius: 999px; background: #f1f6eb; color: #53713e; font-size: 10px; text-overflow: ellipsis; white-space: nowrap; }
.insight-progress { width: 100%; height: 5px; margin-top: 3px; background: #e7eee3; }
.insight-progress span { display: block; height: 100%; border-radius: inherit; background: #8cae5a; transition: width .25s ease; }
.test-entries { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; margin-bottom: 12px; }
.entry-card { display: grid; grid-template-columns: 42px minmax(0, 1fr) 18px; align-items: center; gap: 12px; min-width: 0; min-height: 84px; padding: 14px 16px; border: 1px solid #dfe6df; border-radius: 14px; background: #fff; color: #203a33; text-align: left; box-shadow: 0 7px 18px rgba(31, 49, 40, .04); transition: border-color .2s ease, box-shadow .2s ease, transform .2s ease; }
.entry-card:hover:not(:disabled), .entry-card.is-active { border-color: #a9c27f; box-shadow: 0 9px 22px rgba(63, 91, 49, .1); transform: translateY(-1px); }
.entry-card:focus-visible { outline: 2px solid #8cae5a; outline-offset: 2px; }
.entry-card:disabled { cursor: not-allowed; opacity: .52; }
.entry-icon { display: grid; width: 42px; height: 42px; place-items: center; border-radius: 12px; background: #edf4e6; color: #3f5b31; }
.entry-card:nth-child(2) .entry-icon { background: #f0eef9; color: #514c8c; }
.entry-copy { display: grid; min-width: 0; gap: 5px; }
.entry-copy strong { color: #203a33; font-size: 15px; }
.entry-copy small { overflow: hidden; color: #78857d; font-size: 11px; line-height: 1.45; text-overflow: ellipsis; white-space: nowrap; }
.entry-card > svg { color: #8cae5a; }
.test-tabs { display: none; }
@media (max-width: 900px) { .test-controls { grid-template-columns: 1fr 1fr; }.test-path-summary { grid-column: 1 / -1; }.test-context { align-items: flex-start; flex-direction: column; gap: 10px; }.test-chapter-status { align-self: flex-start; } }
@media (max-width: 900px) { .test-insights { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
@media (max-width: 680px) { :global(.page-container:has(.foundation-test-page)) { padding: 22px 18px 42px; }.test-controls { grid-template-columns: 1fr; gap: 13px; padding: 15px; }.test-path-summary { grid-column: auto; }.test-context h2 { font-size: 20px; }.test-gate { align-items: flex-start; padding: 15px; }.test-gate .button { width: 100%; }.test-insights, .test-entries { grid-template-columns: 1fr; }.insight-card { min-height: 100px; }.entry-copy small { white-space: normal; } }
</style>
