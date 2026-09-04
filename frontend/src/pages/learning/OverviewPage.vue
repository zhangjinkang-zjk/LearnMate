<template>
  <div>
    <PageTitle eyebrow="学习概览" title="把下一步学习说清楚" :description="`围绕“${profile.goal || '正在生成'}”，这里汇总你正在学习的内容、当前掌握情况和最值得先做的行动。`">
      <template #actions><RouterLink class="button button--quiet" to="/learning/navigation">查看学习导航</RouterLink></template>
    </PageTitle>

    <div v-if="loading" class="surface surface-pad loading-state">正在同步你的学习状态…</div>
    <div v-else class="overview-layout">
      <main class="overview-main">
        <section class="surface surface-pad goal-panel">
          <div class="section-heading"><div><p class="eyebrow">当前目标</p><h2>{{ profile.goal || '正在生成' }}</h2></div><span class="goal-progress">{{ path.hasPath ? `${path.progress}%` : '正在生成' }}</span></div>
          <p class="muted goal-copy">学习方向：{{ profile.direction || '正在生成' }}</p>
          <div class="progress-track" aria-label="学习路径完成度"><div class="progress-value" :style="{ width: `${path.progress}%` }"></div></div>
          <div class="goal-meta"><span v-if="path.hasPath">已完成 {{ path.completedNodes }} / {{ path.totalNodes }} 个学习节点</span><span v-else>正在生成学习路径</span><span v-if="path.currentNode">当前节点：{{ path.currentNode }}</span></div>
        </section>

        <section class="surface surface-pad">
          <div class="section-heading section-heading--compact"><div><p class="eyebrow">相关科目</p><h2>按路径拆开的学习内容</h2></div><span class="muted">{{ subjects.length }} 个科目</span></div>
          <div v-if="subjects.length" class="subject-list">
            <article v-for="subject in subjects" :key="subject.id" class="subject-row">
              <div class="subject-copy"><strong>{{ subject.name }}</strong><span class="muted">{{ subject.statusLabel }}</span></div>
              <div class="subject-progress"><div class="progress-track"><div class="progress-value" :style="{ width: `${subject.progress}%` }"></div></div><span>{{ subject.progress }}%</span></div>
              <time class="subject-time">{{ subject.time }}</time>
            </article>
          </div>
          <div v-else class="empty-state">正在生成相关科目…</div>
        </section>

        <section class="surface surface-pad diagnosis-panel">
          <div class="section-heading section-heading--compact"><div><p class="eyebrow">当前诊断</p><h2>知道哪里需要补强</h2></div><RouterLink class="text-link" to="/onboarding/diagnosis">重新诊断 →</RouterLink></div>
          <div class="diagnosis-summary"><div class="diagnosis-score"><strong>{{ diagnosis.hasData ? `${diagnosis.score}%` : '正在生成' }}</strong><span class="muted">{{ diagnosis.hasData ? '综合掌握度' : '正在生成诊断' }}</span></div><div class="diagnosis-stats"><span><strong>{{ stats.examAnswered || '正在生成' }}</strong> 道题已作答</span><span><strong>{{ stats.studySeconds ? formatDuration(stats.studySeconds) : '正在生成' }}</strong> 累计学习</span></div></div>
          <div v-if="diagnosis.weakPoints.length" class="weak-points"><span class="muted">优先补强</span><span v-for="point in diagnosis.weakPoints" :key="point.tag" class="weak-point">{{ point.tag }} {{ point.accuracy }}%</span></div>
          <p v-else class="muted diagnosis-note">正在生成当前诊断…</p>
        </section>
      </main>

      <aside class="overview-aside">
        <section class="surface surface-pad recommendation-panel">
          <div class="section-heading"><div><p class="eyebrow">当前建议</p><h2>{{ recommendation.title }}</h2></div><span class="recommendation-mark">→</span></div>
          <p class="recommendation-copy">{{ recommendation.guidance }}</p>
          <div class="recommendation-block"><span class="block-label">为什么现在做</span><p>{{ recommendation.reason }}</p></div>
          <div class="recommendation-block"><span class="block-label">完成标志</span><p>{{ recommendation.criteria }}</p></div>
          <RouterLink v-if="recommendation.to" class="button button--primary recommendation-action" :to="recommendation.to">{{ recommendation.actionLabel }} <span>→</span></RouterLink>
        </section>
        <section class="surface surface-pad next-node-panel"><p class="eyebrow">路径进度</p><div class="next-node-heading"><h2>{{ path.hasPath ? '接下来会学' : '正在生成' }}</h2><span class="muted">{{ path.hasPath ? path.stage : '正在生成' }}</span></div><p class="muted">{{ path.currentNode || '正在生成下一步学习内容…' }}</p><RouterLink v-if="path.hasPath" class="text-link" to="/learning/navigation">查看完整路径 →</RouterLink></section>
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
const mastery = ref([])
const guidance = ref('')
const unwrap = (response) => response?.data?.data ?? response?.data ?? null

const subjects = computed(() => path.nodes.map((node, index) => {
  const status = node.status || 'locked'
  const progress = status === 'completed' ? 100 : status === 'in_progress' ? 55 : status === 'unlocked' ? 15 : 0
  return { id: node.id || index, name: node.title || node.topic || '正在生成', progress, statusLabel: ({ completed: '已完成', in_progress: '进行中', unlocked: '待开始', locked: '待解锁' })[status] || '正在生成', time: node.time_spent ? formatDuration(node.time_spent) : '正在生成' }
}))

const diagnosis = computed(() => {
  const points = [...(stats.weakPoints || []), ...mastery.value.filter((item) => item.accuracy < 0.6).map((item) => ({ tag: item.knowledge_tag, accuracy: item.accuracy }))]
  const unique = points.filter((item, index, all) => item.tag && all.findIndex((other) => other.tag === item.tag) === index).slice(0, 3)
  const scores = mastery.value.map((item) => Number(item.accuracy || 0)).filter(Boolean)
  const score = path.diagnosis?.latest_score || (scores.length ? Math.round(scores.reduce((sum, value) => sum + value, 0) / scores.length * 100) : 0)
  return { score, hasData: Boolean(path.diagnosis?.latest_score || scores.length || stats.examAnswered), weakPoints: unique.map((item) => ({ ...item, accuracy: Math.round(Number(item.accuracy || 0) * 100) })) }
})

const recommendation = computed(() => {
  const needsDiagnosis = !path.hasPath && !diagnosis.value.hasData
  const current = needsDiagnosis ? '正在生成' : (path.currentNode || (path.progress >= 100 ? '复盘已完成内容' : '当前学习节点'))
  const weak = diagnosis.value.weakPoints[0]?.tag
  const text = typeof guidance.value === 'string' ? guidance.value.trim() : ''
  if (needsDiagnosis) return { title: current, guidance: '正在生成当前建议…', reason: '正在生成依据。', criteria: '正在生成完成标志。', to: '', actionLabel: '' }
  if (!text) return { title: '正在生成', guidance: '正在生成当前建议…', reason: '正在生成依据。', criteria: '正在生成完成标志。', to: '', actionLabel: '' }
  return { title: current, guidance: text, reason: weak ? `诊断显示“${weak}”仍是当前薄弱点，先处理它能减少后续迁移练习中的反复。` : '正在生成依据。', criteria: '正在生成完成标志。', to: path.nextAction?.type === 'quiz' ? '/learning/advanced' : '/learning/fundamentals', actionLabel: path.nextAction?.label || '开始当前节点' }
})

function formatDuration(seconds) { const value = Number(seconds || 0); if (value < 60) return `${value}秒`; const minutes = Math.round(value / 60); if (minutes < 60) return `${minutes}分钟`; return `${(minutes / 60).toFixed(1)}小时` }

async function loadOverview() {
  const results = await Promise.allSettled([learningApi.getCurrentPath(), learningApi.getStudyStats(), learningApi.getMastery(), learningApi.getLearningGuidance()])
  const currentPathPayload = results[0].status === 'fulfilled' ? unwrap(results[0].value) : null
  const currentPath = currentPathPayload && Array.isArray(currentPathPayload.nodes) ? currentPathPayload : null
  const studyStats = results[1].status === 'fulfilled' ? unwrap(results[1].value) : null
  const masteryResult = results[2].status === 'fulfilled' ? unwrap(results[2].value) : null
  const guidanceResult = results[3].status === 'fulfilled' ? unwrap(results[3].value) : null
  if (currentPath) {
    const nodes = currentPath.nodes || []
    const nextActionNode = nodes.find((node) => node.id === currentPath.next_action?.target_id)
    Object.assign(path, { hasPath: true, progress: Number(currentPath.progress || 0), stage: currentPath.stage || '正在生成', currentNode: nodes.find((node) => node.id === currentPath.current_node_id)?.title || nextActionNode?.title || '', completedNodes: nodes.filter((node) => node.status === 'completed').length, totalNodes: nodes.length, nodes, diagnosis: currentPath.diagnosis || null, nextAction: currentPath.next_action || null })
    profile.goal = currentPath.goal || profile.goal
  }
  if (studyStats) { stats.studySeconds = studyStats.study_time?.total_seconds || 0; stats.examAnswered = studyStats.exam_summary?.completed_questions || 0; stats.weakPoints = studyStats.weak_points || [] }
  if (Array.isArray(masteryResult)) mastery.value = masteryResult
  guidance.value = guidanceResult?.guidance || ''
  loading.value = false
}

onMounted(loadOverview)
</script>

<style scoped>
.overview-layout { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); gap: 18px; align-items: start; }.overview-main, .overview-aside { display: grid; gap: 18px; min-width: 0; }.loading-state, .empty-state { color: var(--muted); font-size: 13px; }.empty-state { display: grid; gap: 8px; padding: 8px 0 2px; line-height: 1.65; }.empty-state strong { color: var(--ink); font-size: 14px; }.section-heading { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; margin-bottom: 18px; }.section-heading--compact { align-items: center; margin-bottom: 16px; }.section-heading h2, .next-node-heading h2 { margin: 0; font-size: 19px; letter-spacing: -.01em; }.section-heading .eyebrow { margin-bottom: 6px; }.goal-progress { color: var(--accent-deep); font-size: 24px; font-weight: 800; }.goal-copy { margin: 0 0 16px; font-size: 13px; }.goal-meta { display: flex; justify-content: space-between; gap: 12px; margin-top: 10px; color: var(--muted); font-size: 11px; }.subject-list { display: grid; gap: 2px; }.subject-row { display: grid; grid-template-columns: minmax(130px, 1fr) minmax(150px, 1.2fr) 74px; align-items: center; gap: 18px; min-height: 62px; padding: 11px 0; border-top: 1px solid var(--line); }.subject-row:first-child { border-top: 0; }.subject-copy { display: grid; gap: 5px; min-width: 0; }.subject-copy strong { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 13px; }.subject-copy span { font-size: 11px; }.subject-progress { display: flex; align-items: center; gap: 9px; min-width: 0; }.subject-progress .progress-track { flex: 1; }.subject-progress > span { width: 34px; color: var(--muted); font-size: 11px; text-align: right; }.subject-time { color: var(--muted); font-size: 11px; text-align: right; }.diagnosis-summary { display: flex; align-items: center; gap: 28px; }.diagnosis-score { display: grid; gap: 4px; min-width: 112px; }.diagnosis-score strong { color: var(--accent-deep); font-size: 32px; letter-spacing: -.04em; }.diagnosis-score span, .diagnosis-stats span { font-size: 11px; }.diagnosis-stats { display: grid; gap: 8px; }.diagnosis-stats strong { color: var(--ink); font-size: 15px; }.weak-points { display: flex; flex-wrap: wrap; align-items: center; gap: 7px; margin-top: 20px; font-size: 11px; }.weak-point { padding: 5px 8px; border: 1px solid #e2e9d5; border-radius: 4px; background: #f8fbf2; color: var(--accent-deep); }.diagnosis-note { margin: 20px 0 0; font-size: 12px; }.text-link { color: var(--accent-deep); font-size: 12px; font-weight: 800; text-decoration: none; white-space: nowrap; }.recommendation-panel { border-color: #ccd9b8; background: #f8fbf2; }.recommendation-mark { display: grid; width: 32px; height: 32px; place-items: center; border-radius: 50%; background: var(--accent); color: var(--accent-deep); font-size: 18px; font-weight: 800; }.recommendation-copy { margin: 8px 0 22px; color: var(--ink); font-size: 14px; line-height: 1.75; }.recommendation-block { padding: 14px 0; border-top: 1px solid #dce7cc; }.block-label { color: var(--accent-deep); font-size: 11px; font-weight: 800; }.recommendation-block p { margin: 6px 0 0; color: var(--muted); font-size: 12px; line-height: 1.7; }.recommendation-action { margin-top: 20px; width: 100%; }.recommendation-action span { margin-left: 8px; }.next-node-heading { display: flex; align-items: baseline; justify-content: space-between; gap: 12px; }.next-node-panel > p:not(.eyebrow) { margin: 13px 0 15px; font-size: 13px; line-height: 1.7; }
@media (max-width: 960px) { .overview-layout { grid-template-columns: 1fr; } } @media (max-width: 620px) { .subject-row { grid-template-columns: 1fr; gap: 8px; padding: 14px 0; }.subject-time { text-align: left; }.goal-meta { display: grid; }.diagnosis-summary { align-items: flex-start; gap: 18px; } }
</style>
