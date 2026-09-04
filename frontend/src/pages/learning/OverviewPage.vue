<template>
  <div>
    <PageTitle eyebrow="学习概览" title="把下一步学习说清楚" :description="`围绕“${profile.goal || '正在生成'}”，这里汇总你正在学习的内容、当前掌握情况和最值得先做的行动。`">
      <template #actions><RouterLink class="button button--quiet" to="/learning/navigation">查看学习导航</RouterLink></template>
    </PageTitle>

    <div v-if="loading" class="surface surface-pad loading-state">正在同步你的学习状态…</div>
    <div v-else class="overview-layout">
      <main class="overview-main">
        <section class="surface surface-pad status-panel">
          <div class="section-heading section-heading--compact"><div><p class="eyebrow">学习状态与科目进度</p><h2>当前学习状态</h2></div><span class="status-progress">{{ path.hasPath ? `${path.progress}%` : '正在生成' }}</span></div>
          <div class="status-grid">
            <div class="status-item"><span class="block-label">当前目标</span><strong>{{ profile.goal || '正在生成' }}</strong></div>
            <div class="status-item"><span class="block-label">学习方向</span><strong>{{ profile.direction || '正在生成' }}</strong></div>
          </div>
          <div class="progress-track" aria-label="学习路径完成度"><div class="progress-value" :style="{ width: `${path.progress}%` }"></div></div>
          <p class="status-meta">{{ path.hasPath ? `已完成 ${path.completedNodes} / ${path.totalNodes} 个学习节点` : '正在生成学习路径' }}</p>
        </section>

        <section class="surface surface-pad">
          <div class="section-heading section-heading--compact"><div><p class="eyebrow">相关科目</p><h2>相关科目</h2></div><span class="muted">{{ subjects.length ? `${subjects.length} 个科目` : '正在生成' }}</span></div>
          <div v-if="subjects.length" class="subject-list">
            <div class="subject-header" aria-hidden="true"><span>科目</span><span>完成度</span><span>完成用时</span></div>
            <article v-for="subject in subjects" :key="subject.id" class="subject-row">
              <div class="subject-copy"><strong>{{ subject.name }}</strong><span class="muted">{{ subject.statusLabel }}</span></div>
              <div class="subject-progress"><div class="progress-track"><div class="progress-value" :style="{ width: `${subject.progress}%` }"></div></div><span>{{ subject.progress }}%</span></div>
              <time class="subject-time">{{ subject.time }}</time>
            </article>
          </div>
          <div v-else class="empty-state">正在生成相关科目…</div>
        </section>

        <section class="surface surface-pad diagnosis-panel">
          <div class="section-heading section-heading--compact"><div><p class="eyebrow">当前诊断</p><h2>当前能力起点</h2></div><RouterLink class="text-link" to="/onboarding/diagnosis">重新诊断 →</RouterLink></div>
          <div class="diagnosis-summary"><div class="diagnosis-score"><strong>{{ diagnosis.hasData ? `${diagnosis.score}%` : '正在生成' }}</strong><span class="muted">综合掌握度</span></div><div class="diagnosis-stats"><span><strong>{{ diagnosis.stage }}</strong> 当前阶段</span><span><strong>{{ stats.examAnswered || '正在生成' }}</strong> 道题已作答</span></div></div>
          <div v-if="diagnosis.weakPoints.length" class="weak-points"><span class="muted">优先补强</span><span v-for="point in diagnosis.weakPoints" :key="point.tag" class="weak-point">{{ point.tag }} {{ point.accuracy }}%</span></div>
          <p v-else class="muted diagnosis-note">正在生成当前诊断…</p>
        </section>
      </main>

      <aside class="overview-aside">
        <section class="surface surface-pad recommendation-panel">
          <div class="section-heading"><div><p class="eyebrow">当前建议</p><h2>学习决策</h2></div><span class="recommendation-mark">→</span></div>
          <div class="recommendation-block recommendation-block--first"><span class="block-label">系统判断</span><p>{{ recommendation.judgement }}</p></div>
          <div class="recommendation-block"><span class="block-label">推荐行动</span><p>{{ recommendation.guidance }}</p></div>
          <div class="recommendation-block"><span class="block-label">推荐理由</span><p>{{ recommendation.reason }}</p></div>
          <div class="recommendation-block"><span class="block-label">完成标准</span><p>{{ recommendation.criteria }}</p></div>
          <RouterLink v-if="recommendation.to" class="button button--primary recommendation-action" :to="recommendation.to">{{ recommendation.actionLabel }} <span>→</span></RouterLink>
        </section>
      </aside>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import PageTitle from '@/shared/ui/PageTitle.vue'
import { learningApi } from '@/shared/api/learningApi'
import { learningState } from '@/entities/learning/learningState'

const loading = ref(true)
const profile = reactive({ direction: learningState.direction, goal: learningState.goal })
const path = reactive({ hasPath: false, progress: 0, stage: '', currentNode: '', completedNodes: 0, totalNodes: 0, nodes: [], diagnosis: null, nextAction: null })
const stats = reactive({ studySeconds: 0, examAnswered: 0, weakPoints: [] })
const pathStats = ref([])
const mastery = ref([])
const guidance = ref('')
const unwrap = (response) => response?.data?.data ?? response?.data ?? null

function parseGuidanceSections(value) {
  const sections = {}
  let current = ''
  String(value || '').split(/\r?\n/).forEach((rawLine) => {
    const line = rawLine.trim()
    if (!line) return
    const heading = line.match(/^##\s+(.+)$/)
    if (heading) {
      current = heading[1].trim()
      sections[current] = []
      return
    }
    if (current && line.startsWith('-')) sections[current].push(line.replace(/^-\s*/, '').trim())
  })
  return sections
}

const guidanceSections = computed(() => parseGuidanceSections(guidance.value))
const abilityScores = computed(() => (guidanceSections.value['学习者能力分析'] || []).flatMap((line) => {
  const match = line.match(/^(.+?):\s*(\d+(?:\.\d+)?)\s*分/)
  return match ? [{ tag: match[1].trim(), score: Number(match[2]) }] : []
}))

const nodeSubjects = computed(() => path.nodes.map((node, index) => {
  const status = node.status || 'locked'
  const progress = status === 'completed' ? 100 : status === 'in_progress' ? 55 : status === 'unlocked' ? 15 : 0
  return { id: node.id || index, name: node.title || node.topic || '正在生成', progress, statusLabel: ({ completed: '已完成', in_progress: '进行中', unlocked: '待开始', locked: '待解锁' })[status] || '正在生成', time: node.time_spent ? formatDuration(node.time_spent) : '正在生成' }
}))

const subjects = computed(() => {
  if (pathStats.value.length) return pathStats.value.map((item) => ({
    id: item.path_id,
    name: item.subject || '正在生成',
    progress: Number(item.progress?.percentage ?? 0),
    statusLabel: item.progress?.completed_nodes ? `${item.progress.completed_nodes}/${item.progress.total_nodes} 个节点已完成` : '尚未开始',
    time: formatDuration(item.study_time?.total_seconds || 0),
  }))
  return nodeSubjects.value
})

const diagnosis = computed(() => {
  const radarWeakPoints = abilityScores.value.filter((item) => item.score < 50).map((item) => ({ tag: item.tag, accuracy: item.score / 100 }))
  const points = [...(stats.weakPoints || []), ...mastery.value.filter((item) => item.accuracy < 0.6).map((item) => ({ tag: item.knowledge_tag, accuracy: item.accuracy })), ...radarWeakPoints]
  const unique = points.filter((item, index, all) => item.tag && all.findIndex((other) => other.tag === item.tag) === index).slice(0, 3)
  const scores = mastery.value.map((item) => Number(item.accuracy || 0)).filter(Boolean)
  const masteryScore = scores.length ? Math.round(scores.reduce((sum, value) => sum + value, 0) / scores.length * 100) : null
  const radarScore = abilityScores.value.length ? Math.round(abilityScores.value.reduce((sum, item) => sum + item.score, 0) / abilityScores.value.length) : null
  const storedScore = Number(path.diagnosis?.latest_score)
  const score = Number.isFinite(storedScore) && storedScore > 0 ? storedScore : (masteryScore ?? radarScore ?? (Number.isFinite(storedScore) ? storedScore : null))
  const hasData = score !== null || unique.length > 0 || stats.examAnswered > 0
  const stage = score === null ? '正在生成' : score >= 85 ? '应用进阶期' : score >= 60 ? '基础巩固期' : '基础建立期'
  return { score, stage, hasData, weakPoints: unique.map((item) => ({ ...item, accuracy: Math.round(Number(item.accuracy || 0) * 100) })) }
})

const recommendation = computed(() => {
  const strategyLines = guidanceSections.value['学习策略建议'] || []
  const materialLines = guidanceSections.value['学习资料指导'] || []
  const actionableLine = strategyLines.find((line) => !line.startsWith('建议难度配比')) || materialLines[0] || ''
  const weak = diagnosis.value.weakPoints[0]?.tag
  const title = weak ? `优先补强：${weak}` : (path.currentNode || '当前学习节点')
  const hasRecommendation = Boolean(path.currentNode || weak || actionableLine)
  const action = path.currentNode ? `完成“${path.currentNode}”练习` : actionableLine
  const weakSubject = weak && subjects.value.find((item) => item.name.includes(weak) || weak.includes(item.name))
  const resolvedAction = path.currentNode ? action : (weak ? `完成“${weak}”基础练习` : action)
  return {
    title: hasRecommendation ? title : '正在生成',
    judgement: weak ? `当前主要短板是 ${weak} 能力` : '正在生成系统判断…',
    guidance: hasRecommendation ? resolvedAction : '正在生成推荐行动…',
    reason: weakSubject ? `${weakSubject.name}完成度 ${weakSubject.progress}%，掌握度偏低，先补强可以减少后续练习中的反复。` : (weak ? `诊断显示“${weak}”是当前薄弱点，先处理它可以减少后续练习中的反复。` : '正在生成依据。'),
    criteria: path.currentNode ? `能够解释“${path.currentNode}”的关键方法，并通过节点测验。` : (weak ? `能够解释“${weak}”的关键方法，并完成一次针对性练习。` : '正在生成完成标准。'),
    to: hasRecommendation && path.nextAction?.type ? (path.nextAction.type === 'quiz' ? '/learning/advanced' : '/learning/fundamentals') : '',
    actionLabel: path.nextAction?.label || '开始当前节点',
  }
})

function formatDuration(seconds) { const value = Number(seconds || 0); if (value < 60) return `${value}秒`; const minutes = Math.round(value / 60); if (minutes < 60) return `${minutes}分钟`; return `${(minutes / 60).toFixed(1)}小时` }

async function loadOverview() {
  const results = await Promise.allSettled([learningApi.getCurrentPath(), learningApi.getStudyStats(), learningApi.getPathStats(), learningApi.getMastery(), learningApi.getLearningGuidance()])
  let currentPathPayload = results[0].status === 'fulfilled' ? unwrap(results[0].value) : null
  // 首次诊断只保存学习画像，若尚无路径则按学习方向创建用户专属路径。
  // 复用现有路径生成接口，避免在前端复制路径或节点入库逻辑。
  if (!currentPathPayload) {
    try {
      await learningApi.generatePathsFromDirection(profile.direction, profile.goal)
      currentPathPayload = unwrap(await learningApi.getCurrentPath())
    } catch {
      // 页面仍可展示画像和诊断状态，用户可稍后刷新重试路径生成。
    }
  }
  const currentPath = currentPathPayload && Array.isArray(currentPathPayload.nodes) ? currentPathPayload : null
  const studyStats = results[1].status === 'fulfilled' ? unwrap(results[1].value) : null
  const pathStatsResult = results[2].status === 'fulfilled' ? unwrap(results[2].value) : null
  const masteryResult = results[3].status === 'fulfilled' ? unwrap(results[3].value) : null
  const guidanceResult = results[4].status === 'fulfilled' ? unwrap(results[4].value) : null
  if (currentPath) {
    const nodes = currentPath.nodes || []
    const nextActionNode = nodes.find((node) => node.id === currentPath.next_action?.target_id)
    Object.assign(path, { hasPath: true, progress: Number(currentPath.progress || 0), stage: currentPath.stage || '正在生成', currentNode: nodes.find((node) => node.id === currentPath.current_node_id)?.title || nextActionNode?.title || '', completedNodes: nodes.filter((node) => node.status === 'completed').length, totalNodes: nodes.length, nodes, diagnosis: currentPath.diagnosis || null, nextAction: currentPath.next_action || null })
    profile.goal = currentPath.goal || profile.goal
  }
  if (studyStats) { stats.studySeconds = studyStats.study_time?.total_seconds || 0; stats.examAnswered = studyStats.exam_summary?.completed_questions || 0; stats.weakPoints = studyStats.weak_points || [] }
  if (Array.isArray(pathStatsResult?.paths)) pathStats.value = pathStatsResult.paths
  if (Array.isArray(masteryResult)) mastery.value = masteryResult
  guidance.value = guidanceResult?.guidance || ''
  loading.value = false
}

onMounted(loadOverview)
</script>

<style scoped>
.overview-layout { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); gap: 18px; align-items: start; }.overview-main, .overview-aside { display: grid; gap: 18px; min-width: 0; }.loading-state, .empty-state { color: var(--muted); font-size: 13px; }.empty-state { display: grid; gap: 8px; padding: 8px 0 2px; line-height: 1.65; }.empty-state strong { color: var(--ink); font-size: 14px; }.section-heading { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; margin-bottom: 18px; }.section-heading--compact { align-items: center; margin-bottom: 16px; }.section-heading h2 { margin: 0; font-size: 19px; letter-spacing: -.01em; }.section-heading .eyebrow { margin-bottom: 6px; }.goal-progress { color: var(--accent-deep); font-size: 24px; font-weight: 800; }.goal-copy { margin: 0 0 16px; font-size: 13px; }.goal-meta { display: flex; justify-content: space-between; gap: 12px; margin-top: 10px; color: var(--muted); font-size: 11px; }.subject-list { display: grid; gap: 2px; }.subject-row { display: grid; grid-template-columns: minmax(130px, 1fr) minmax(150px, 1.2fr) 74px; align-items: center; gap: 18px; min-height: 62px; padding: 11px 0; border-top: 1px solid var(--line); }.subject-row:first-child { border-top: 0; }.subject-copy { display: grid; gap: 5px; min-width: 0; }.subject-copy strong { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 13px; }.subject-copy span { font-size: 11px; }.subject-progress { display: flex; align-items: center; gap: 9px; min-width: 0; }.subject-progress .progress-track { flex: 1; }.subject-progress > span { width: 34px; color: var(--muted); font-size: 11px; text-align: right; }.subject-time { color: var(--muted); font-size: 11px; text-align: right; }.diagnosis-summary { display: flex; align-items: center; gap: 28px; }.diagnosis-score { display: grid; gap: 4px; min-width: 112px; }.diagnosis-score strong { color: var(--accent-deep); font-size: 32px; letter-spacing: -.04em; }.diagnosis-score span, .diagnosis-stats span { font-size: 11px; }.diagnosis-stats { display: grid; gap: 8px; }.diagnosis-stats strong { color: var(--ink); font-size: 15px; }.weak-points { display: flex; flex-wrap: wrap; align-items: center; gap: 7px; margin-top: 20px; font-size: 11px; }.weak-point { padding: 5px 8px; border: 1px solid #e2e9d5; border-radius: 4px; background: #f8fbf2; color: var(--accent-deep); }.diagnosis-note { margin: 20px 0 0; font-size: 12px; }.text-link { color: var(--accent-deep); font-size: 12px; font-weight: 800; text-decoration: none; white-space: nowrap; }.recommendation-panel { border-color: #ccd9b8; background: #f8fbf2; }.recommendation-mark { display: grid; width: 32px; height: 32px; place-items: center; border-radius: 50%; background: var(--accent); color: var(--accent-deep); font-size: 18px; font-weight: 800; }.recommendation-copy { margin: 8px 0 22px; color: var(--ink); font-size: 14px; line-height: 1.75; }.recommendation-block { padding: 14px 0; border-top: 1px solid #dce7cc; }.block-label { color: var(--accent-deep); font-size: 11px; font-weight: 800; }.recommendation-block p { margin: 6px 0 0; color: var(--muted); font-size: 12px; line-height: 1.7; }.recommendation-action { margin-top: 20px; width: 100%; }.recommendation-action span { margin-left: 8px; }
.status-progress { color: var(--accent-deep); font-size: 24px; font-weight: 800; }.status-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 18px; margin-bottom: 18px; }.status-item { display: grid; gap: 6px; }.status-item strong { color: var(--ink); font-size: 17px; }.status-meta { margin: 10px 0 0; color: var(--muted); font-size: 11px; }.subject-header { display: grid; grid-template-columns: minmax(130px, 1fr) minmax(150px, 1.2fr) 74px; gap: 18px; padding: 0 0 8px; color: var(--muted); font-size: 10px; }.recommendation-block--first { padding-top: 0; border-top: 0; }.recommendation-block--first p { color: var(--ink); font-size: 14px; }.recommendation-panel { min-height: 100%; } @media (max-width: 960px) { .overview-layout { grid-template-columns: 1fr; } } @media (max-width: 620px) { .status-grid { grid-template-columns: 1fr; gap: 12px; }.subject-header { grid-template-columns: 1fr 1fr 74px; gap: 8px; }.subject-row { grid-template-columns: 1fr 1fr 74px; gap: 8px; padding: 14px 0; }.subject-time { text-align: right; }.goal-meta { display: grid; }.diagnosis-summary { align-items: flex-start; gap: 18px; } }
</style>
