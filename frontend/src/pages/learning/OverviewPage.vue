<template>
  <div class="overview-page">
    <div v-if="loading" class="surface surface-pad loading-state">正在同步你的学习状态…</div>

    <div v-else-if="errorMessage" class="surface surface-pad error-state">
      <strong>学习概览暂时无法读取</strong>
      <p>{{ errorMessage }}</p>
      <!-- 这里原来是 button--secondary：main.css 里没有这个类（只有 primary / quiet / accent），
           所以重试一直渲染成一个没有样式的文字链接。 -->
      <button class="button button--quiet" type="button" @click="loadOverview">重试 <ArrowRight :size="14" /></button>
    </div>

    <template v-else>
      <PageTitle eyebrow="学习概览" :title="headingTitle" :description="profile.direction" />

      <!-- ① 现在做什么。整页的主位 —— 以前唯一能行动的那张卡片被夹在中间，和另外三张一样大。 -->
      <RecommendationPanel
        :title="nextActionTitle"
        :reason="recommendation.reason"
        :criteria="recommendation.criteria"
        :to="nextActionTarget"
        :action-label="nextActionLabel"
      />

      <!-- ② 为什么是它。知识盲区和总体掌握度本来就是同一批掌握度记录的两种切法，
           以前分成两个面板，正是"四张卡片没有优先级"的来源，这里合成一张表。 -->
      <section class="surface surface-pad">
        <div class="panel-heading">
          <div class="panel-heading__copy">
            <p class="eyebrow">WHY THIS</p>
            <h2>薄弱知识点</h2>
            <small v-if="recommendation.judgement">{{ recommendation.judgement }}</small>
          </div>
          <span v-if="weakRows.length" class="panel-count">{{ weakRows.length }} 个待巩固</span>
        </div>
        <ul v-if="weakRows.length" class="weak-list">
          <li v-for="row in weakRows" :key="row.tag" class="weak-item">
            <div class="weak-item__copy">
              <strong>{{ row.tag }}</strong>
              <small>{{ row.detail }}</small>
            </div>
            <div class="mini-progress"><span :style="{ width: `${row.accuracy}%` }"></span></div>
            <RouterLink
              v-if="row.reviewTo"
              class="icon-link"
              :to="row.reviewTo"
              :aria-label="`查看「${row.nodeTitle}」的学习复盘`"
              title="查看对应学习复盘"
            >
              <ArrowRight :size="15" />
            </RouterLink>
            <span v-else class="icon-link icon-link--none" aria-hidden="true"></span>
          </li>
        </ul>
        <p v-else class="empty-state">{{ weakEmptyCopy }}</p>
      </section>

      <!-- ③ 我在哪。收成一张紧凑面板，不再排四张等权卡片把同样的毛病搬到页面底部。 -->
      <section class="surface surface-pad">
        <div class="panel-heading">
          <div class="panel-heading__copy">
            <p class="eyebrow">WHERE I AM</p>
            <h2>我在哪</h2>
          </div>
        </div>
        <template v-if="pathSegments.length">
          <!-- 这条带子取代了原来的折线图：同样的 difficulty_trend 数据，以前画的是
               relative_difficulty（路径内归一化，没有外部刻度，加纵轴等于伪造精度），
               现在画的是每个节点的完成状态 —— 读的成本几乎为零。 -->
          <div class="path-strip" role="img" :aria-label="pathStripLabel">
            <span
              v-for="segment in pathSegments"
              :key="segment.id"
              class="path-seg"
              :class="`path-seg--${segment.kind}`"
              :title="`${segment.title}（${segment.kindLabel}）`"
            ></span>
          </div>
          <p class="path-caption">{{ pathStripLabel }}</p>
        </template>
        <p v-else class="empty-state">学习路径还在生成中。生成之后，这里会显示每个节点学到哪了。</p>
        <dl class="where-facts">
          <div class="where-fact"><dt>当前阶段</dt><dd>{{ stageLabel }}</dd></div>
          <div class="where-fact"><dt>近期活跃</dt><dd>{{ activityLabel }}</dd></div>
        </dl>
      </section>
    </template>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { ArrowRight } from 'lucide-vue-next'
import { learningApi } from '@/shared/api/learningApi'
import PageTitle from '@/shared/ui/PageTitle.vue'
import RecommendationPanel from '@/widgets/learning/RecommendationPanel.vue'

const loading = ref(true)
const errorMessage = ref('')
const profile = reactive({ direction: '', goal: '' })
const path = reactive({ id: null, completed: false, trend: [] })
const diagnosis = reactive({ stage: '', answered: 0 })
const recommendation = reactive({ judgement: '', reason: '', criteria: '', action: '', targetId: null })
const activity = reactive({ activeDays7d: 0, lastActiveDate: null, windowDays: 0 })
const blindSpots = ref([])
const masteryBars = ref([])

const unwrap = (response) => response?.data?.data ?? response?.data ?? null

// 后端这两处给的都是 0–100 的整数（盲区在 _build_reviewable_weak_points 里已经把小数换算过了，
// 掌握度是 round(答对/总数*100)），所以这里只需要夹一下范围。**不要**沿用原来那个
// `value <= 1 ? value * 100 : value` 的换算：正确率真是 1% 的时候它会把 1 读成 100%。
const clampPercent = (value) => {
  const numeric = Number(value)
  return Number.isFinite(numeric) ? Math.max(0, Math.min(100, Math.round(numeric))) : null
}

const headingTitle = computed(() => profile.goal || '继续你的学习')

// ── ① 现在做什么 ─────────────────────────────────────────────
// 后端 recommendation.action 就是当前节点的标题；没有当前节点时（路径学完或还没解锁）
// 退回路径条上的"可学习"节点，再退回一句实话。
const nextActionTitle = computed(() => {
  if (path.completed) return '这条路径已学完，去做实战任务'
  return recommendation.action || currentSegment.value?.title || '继续基础学习'
})
const nextActionLabel = computed(() => (path.completed ? '进入进阶学习' : '开始学习'))

// 目的地的规则只有两条，写在这里而不是抽成模块 —— 没有第二个消费者，前端也没有测试框架：
//   · 路径学完 → 进阶学习（做实战任务）
//   · 否则   → 基础讲解，并把当前节点带过去（基础学习页按 route.query.pathId / .node 落位）
// **主按钮永远不指向学习复盘**：一是系统设计 §1.4 的边表里概览的出口只有基础讲解和基础测试；
// 二是这份载荷支撑不了那个判断 —— recommendation.action_type 是节点的类型（quiz/read），
// 不是"你已经读完了该去测"，拿它分支会跳过没读过的节点的阅读。
const nextActionTarget = computed(() => {
  if (path.completed) return { name: 'advancedLearning' }
  const query = {}
  if (path.id) query.pathId = path.id
  if (recommendation.targetId) query.node = recommendation.targetId
  return Object.keys(query).length ? { name: 'fundamentals', query } : { name: 'fundamentals' }
})

// ── ② 为什么是它 ─────────────────────────────────────────────
const weakRows = computed(() => {
  const rows = new Map()
  for (const point of blindSpots.value) {
    const tag = point?.tag || point?.knowledge_tag
    if (!tag) continue
    rows.set(tag, {
      tag,
      accuracy: clampPercent(point.accuracy),
      attempts: Math.max(0, Math.round(Number(point.attempts) || 0)),
      nodeTitle: point.node_title || '',
      pathId: point.path_id,
      nodeId: point.node_id,
    })
  }
  for (const bar of masteryBars.value) {
    const tag = bar?.label || bar?.knowledge_tag
    if (!tag || rows.has(tag)) continue
    rows.set(tag, {
      tag,
      accuracy: clampPercent(bar.score ?? bar.accuracy),
      attempts: Math.max(0, Math.round(Number(bar.attempts) || 0)),
      nodeTitle: '',
      pathId: null,
      nodeId: null,
    })
  }
  return [...rows.values()]
    .filter((row) => row.accuracy !== null)
    .map((row) => ({
      ...row,
      // 「已答 0 题」是没话找话 —— 雷达维度转过来的条目没有作答次数，那半句就不出现。
      detail: [`正确率 ${row.accuracy}%`, row.attempts > 0 && `已答 ${row.attempts} 题`, row.nodeTitle && `来自「${row.nodeTitle}」`].filter(Boolean).join(' · '),
      reviewTo: row.pathId && row.nodeId ? { name: 'foundationTest', query: { pathId: row.pathId, node: row.nodeId } } : null,
    }))
    // 有复习链接的排前面（那几条才是能立刻动手的），组内按正确率升序 —— 最弱的先看到。
    .sort((a, b) => (b.reviewTo ? 1 : 0) - (a.reviewTo ? 1 : 0) || a.accuracy - b.accuracy)
})

// 空不是"正在生成"。答过题的账号是**终态**（没有弱项是好事），没答过的是"等你去做"。
const weakEmptyCopy = computed(() => (diagnosis.answered > 0
  ? '你已经答过的题里还没有需要补强的知识点。'
  : '还没有答题记录。完成一次章节测验后，这里会列出掌握得还不牢的知识点。'))

// ── ③ 我在哪 ─────────────────────────────────────────────────
const pathSegments = computed(() => path.trend.map((node, index) => {
  const status = String(node?.status || '')
  const kind = status === 'completed' ? 'done' : (status === 'in_progress' || status === 'unlocked') ? 'current' : 'locked'
  return {
    id: node?.id ?? index,
    title: String(node?.title || '').trim() || `第 ${index + 1} 个节点`,
    kind,
    kindLabel: { done: '已完成', current: '可学习', locked: '未解锁' }[kind],
  }
}))
const currentSegment = computed(() => pathSegments.value.find((segment) => segment.kind === 'current'))
const pathStripLabel = computed(() => {
  const total = pathSegments.value.length
  if (!total) return ''
  const done = pathSegments.value.filter((segment) => segment.kind === 'done').length
  const base = `已完成 ${done} / 共 ${total} 个节点`
  return currentSegment.value ? `${base}，当前可学「${currentSegment.value.title}」` : base
})

// 后端还没有掌握度数据时给的 stage 是「正在生成」，那其实是"还没开始答题"，不是"在生成"。
const stageLabel = computed(() => {
  const stage = String(diagnosis.stage || '')
  if (stage && stage !== '正在生成') return stage
  return diagnosis.answered > 0 ? '评估中' : '完成一次测验后给出'
})

// 活跃度取代了原来的「学习 N 秒」—— 那个数结构性恒为 0：StudySession 的唯一写入方是
// /study/heartbeat，而前端从来没调用过它。这里数的是 LearningEvent 与答题记录的并集。
const activityLabel = computed(() => {
  if (!activity.lastActiveDate) {
    return activity.windowDays ? `最近 ${activity.windowDays} 天没有学习记录` : '还没有学习记录'
  }
  const week = activity.activeDays7d > 0 ? `近 7 天活跃 ${activity.activeDays7d} 天` : '近 7 天没有学习'
  return `${week} · 最近学习${relativeDay(activity.lastActiveDate)}`
})

// 后端回的是**日期**不是时间戳，这是刻意的（库里存的是 naive 时间，当时间戳解析会整体偏
// 一个时区）。所以这里也只按日期相减，不做时刻运算。
function relativeDay(value) {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(String(value || ''))
  if (!match) return ''
  const then = Date.UTC(Number(match[1]), Number(match[2]) - 1, Number(match[3]))
  const now = new Date()
  const today = Date.UTC(now.getFullYear(), now.getMonth(), now.getDate())
  // 服务端按 UTC 归日、浏览器按本地日：UTC+8 的凌晨本地已经是新的一天而 UTC 还是前一天，
  // 相减会出现 0 甚至 -1，两种都当"今天"。
  const days = Math.round((today - then) / 86400000)
  if (days <= 0) return '今天'
  if (days === 1) return '昨天'
  return `${days} 天前`
}

function resetOverviewState() {
  Object.assign(profile, { direction: '', goal: '' })
  Object.assign(path, { id: null, completed: false, trend: [] })
  Object.assign(diagnosis, { stage: '', answered: 0 })
  Object.assign(recommendation, { judgement: '', reason: '', criteria: '', action: '', targetId: null })
  Object.assign(activity, { activeDays7d: 0, lastActiveDate: null, windowDays: 0 })
  blindSpots.value = []
  masteryBars.value = []
}

async function loadOverview() {
  loading.value = true
  errorMessage.value = ''
  resetOverviewState()
  try {
    const overview = unwrap(await learningApi.getOverview()) || {}
    const profileData = overview.profile || {}
    const diagnosisData = overview.diagnosis || {}
    const pathData = overview.path || {}
    const advice = overview.recommendation || {}
    const activityData = overview.activity || {}
    Object.assign(profile, { direction: profileData.direction || '', goal: profileData.goal || '' })
    Object.assign(path, {
      id: pathData.id || null,
      completed: pathData.completed === true,
      trend: Array.isArray(pathData.difficulty_trend) ? pathData.difficulty_trend : [],
    })
    Object.assign(diagnosis, { stage: diagnosisData.stage || '', answered: Number(diagnosisData.answered) || 0 })
    Object.assign(recommendation, {
      judgement: advice.judgement || '',
      reason: advice.reason || '',
      criteria: advice.criteria || '',
      action: advice.action || '',
      targetId: advice.target_id ?? null,
    })
    Object.assign(activity, {
      activeDays7d: Number(activityData.active_days_7d) || 0,
      lastActiveDate: activityData.last_active_date || null,
      windowDays: Number(activityData.window_days) || 0,
    })
    blindSpots.value = Array.isArray(overview.blind_spots) ? overview.blind_spots : []
    masteryBars.value = Array.isArray(overview.mastery_bars) ? overview.mastery_bars : []
  } catch (error) {
    errorMessage.value = error?.response?.data?.detail || error?.message || '请稍后重试'
  } finally {
    loading.value = false
  }
}
onMounted(loadOverview)
</script>

<style scoped>
/* 内容驱动的高度：原来用 fr 拉伸面板，于是知识盲区空着也要撑满半屏。整页改成随内容长，
   由 .page-container 滚动。 */
.overview-page { display: grid; gap: 16px; align-content: start; }
.overview-page :deep(.page-heading) { margin-bottom: 2px; }
.overview-page :deep(.page-heading h1) { color: #1e3c34; font-size: 22px; line-height: 1.4; }
.overview-page :deep(.page-heading .eyebrow) { color: var(--muted); font-size: 12px; letter-spacing: .08em; }
.overview-page :deep(.page-heading h1 + p) { margin: 6px 0 0; color: var(--muted); font-size: 12px; }

.overview-page .surface { border: 1px solid rgba(63, 91, 49, .28); border-radius: 12px; box-shadow: 0 8px 24px rgba(45, 40, 92, .07); }
.surface-pad { padding: 20px; }

.panel-heading { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; margin-bottom: 14px; }
.panel-heading__copy { min-width: 0; }
.panel-heading .eyebrow { margin: 0 0 6px; color: var(--muted); font-size: 11px; letter-spacing: .1em; }
.panel-heading h2 { margin: 0; color: #1e3c34; font-size: 20px; line-height: 1.4; }
.panel-heading small { display: block; margin-top: 5px; color: var(--muted); font-size: 12px; line-height: 1.5; }
.panel-count { flex: 0 0 auto; color: var(--muted); font-size: 12px; }

.weak-list { display: grid; margin: 0; padding: 0; list-style: none; }
.weak-item { display: grid; grid-template-columns: minmax(0, 1fr) minmax(120px, 1.1fr) 28px; align-items: center; gap: 14px; min-height: 52px; padding: 6px 0; border-top: 1px solid var(--line); }
.weak-item:first-child { border-top: 0; }
.weak-item__copy { min-width: 0; }
.weak-item strong { display: block; overflow: hidden; color: var(--ink); font-size: 14px; line-height: 1.4; text-overflow: ellipsis; white-space: nowrap; }
.weak-item small { display: block; margin-top: 4px; overflow: hidden; color: var(--muted); font-size: 12px; line-height: 1.4; text-overflow: ellipsis; white-space: nowrap; }
.mini-progress { height: 6px; overflow: hidden; border-radius: 99px; background: #e9eee8; }
.mini-progress span { display: block; height: 100%; border-radius: inherit; background: #1e3c34; }
.icon-link { display: grid; width: 28px; height: 28px; place-items: center; border-radius: 50%; color: #1e3c34; }
.icon-link:hover { background: var(--soft); }
/* 没有复习入口的行也占住这一格，否则右侧的链接会参差不齐 */
.icon-link--none { visibility: hidden; }

.path-strip { display: flex; gap: 3px; height: 14px; }
.path-seg { flex: 1 1 0; min-width: 3px; border-radius: 3px; }
.path-seg--done { background: #1e3c34; }
.path-seg--current { background: var(--accent); box-shadow: inset 0 0 0 1px var(--accent-deep); }
.path-seg--locked { background: #dce3dc; }
.path-caption { margin: 10px 0 18px; color: var(--muted); font-size: 12px; line-height: 1.5; }

.where-facts { display: grid; gap: 12px 28px; margin: 0; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); }
.where-fact { display: grid; grid-template-columns: 72px minmax(0, 1fr); align-items: baseline; gap: 12px; }
.where-fact dt { color: var(--muted); font-size: 12px; }
.where-fact dd { margin: 0; color: var(--ink); font-size: 13px; line-height: 1.6; }

.empty-state, .loading-state { color: var(--muted); font-size: 12px; line-height: 1.6; }
.empty-state { margin: 0; padding: 12px 0 2px; }
.error-state strong { display: block; color: #1e3c34; font-size: 15px; }
.error-state p { margin: 8px 0 14px; color: var(--muted); font-size: 13px; }

:global(.page-container:has(.overview-page)) { background: #f7f7f7; }
:global(.app-content:has(.overview-page) .app-header) { border-bottom-color: #e8e8e8; background: #f7f7f7; }
/* 固定视口高度 + 内部滚动。原来是 overflow: hidden，配上被 fr 拉伸的面板，内容一旦变多
   就被裁掉且滚不动。 */
:global(.page-container:has(.overview-page)) { width: 100%; height: calc(100vh - 64px); box-sizing: border-box; margin: 0; padding: 20px 20px 28px 28px; overflow-y: auto; }

@media (max-width: 900px) {
  .overview-page :deep(.page-heading h1) { font-size: 20px; }
  :global(.page-container:has(.overview-page)) { height: auto; min-height: 0; padding: 24px 20px 58px 24px; overflow: visible; }
}

@media (max-width: 620px) {
  .surface-pad { padding: 16px; }
  /* 窄屏把进度条挪到标题下面独占一行，链接跨两行居中 */
  .weak-item { grid-template-columns: minmax(0, 1fr) 28px; row-gap: 8px; }
  .weak-item .mini-progress { grid-column: 1; grid-row: 2; }
  .weak-item .icon-link { grid-row: 1 / span 2; align-self: center; }
  .weak-item small { white-space: normal; }
}
</style>
