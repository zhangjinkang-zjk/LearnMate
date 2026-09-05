<template>
  <div class="overview-page">
    <div v-if="loading" class="surface surface-pad loading-state">正在同步你的学习状态…</div>
    <div v-else class="overview-dashboard">
      <section class="path-trend-panel">
        <div class="section-heading section-heading--compact"><div><p class="eyebrow path-eyebrow">LEARNING PATH</p><h2>{{ trendMode === 'path' ? '学习路径' : '资源难度匹配' }}</h2><small v-if="path.subject || profile.direction" class="path-subject">{{ path.subject || profile.direction }}</small></div><div class="trend-heading-side"><div class="trend-switch" :class="{ 'is-resource': trendMode === 'resource' }" role="tablist" aria-label="难度曲线类型"><span class="trend-switch-indicator" aria-hidden="true"></span><button type="button" :class="{ 'is-active': trendMode === 'path' }" role="tab" :aria-selected="trendMode === 'path'" @click="trendMode = 'path'">学习路径</button><button type="button" :class="{ 'is-active': trendMode === 'resource' }" role="tab" :aria-selected="trendMode === 'resource'" @click="trendMode = 'resource'">资源匹配</button></div><div class="trend-caption"><span v-if="trendMode === 'path'">当前路径进度 {{ path.progress }}%</span><span v-else>资源难度与当前能力的匹配</span><small>{{ trendMode === 'path' ? '首节点难度 = 1.0' : '实线为资源难度，虚线为当前能力' }}</small></div></div></div>
        <div v-if="activeTrend.length > 1" class="trend-chart" :aria-label="trendMode === 'path' ? '当前学习路径相对难度折线图' : '资源难度与当前能力匹配曲线'">
          <svg viewBox="0 0 920 180" role="img" :aria-label="trendMode === 'path' ? '学习路径节点相对难度折线图' : '资源难度与当前能力匹配曲线'" preserveAspectRatio="none">
            <line v-for="level in [25, 50, 75]" :key="level" x1="0" :y1="180 - level * 1.55" x2="920" :y2="180 - level * 1.55" class="chart-grid" />
            <polyline :points="trendPoints" class="trend-line" :class="{ 'resource-difficulty-line': trendMode === 'resource' }" />
            <polyline v-if="trendMode === 'resource' && resourceTrendHasUserLevel" :points="userLevelPoints" class="user-level-line" />
            <circle v-for="(point, index) in activeTrend" :key="point.id" :cx="trendX(index)" :cy="trendY(point.value)" r="4" class="trend-point"><title>{{ point.label }}：{{ point.tooltip }}</title></circle>
          </svg>
          <div class="trend-labels"><span v-for="point in activeTrend" :key="`${point.id}-label`">{{ point.label }}</span></div>
        </div>
        <div v-else class="empty-state trend-empty">{{ trendMode === 'path' ? '路径节点生成后，这里会显示每个节点的相对难度变化。' : '打开学习章节并生成资源后，这里会显示资源难度与当前能力的匹配情况。' }}</div>
      </section>

      <div class="overview-columns">
        <div class="overview-left">
          <div class="overview-top-cards">
            <section class="surface surface-pad compact-panel goal-panel"><div class="goal-heading"><div><p class="eyebrow">CURRENT FOCUS</p><h2>当前学习目标</h2></div><span class="goal-count">{{ goalItems.length }}</span></div><ul class="goal-list"><li v-for="(item, index) in goalItems" :key="item"><span class="goal-index">{{ String(index + 1).padStart(2, '0') }}</span><span class="goal-copy">{{ item }}</span><span class="goal-status" aria-hidden="true"></span></li></ul></section>
            <section class="surface surface-pad compact-panel next-panel"><div class="next-heading"><div><p class="eyebrow">NEXT STEP</p><h2>下一步学习内容</h2></div><span class="next-mark"><ArrowUpRight :size="19" /></span></div><div class="next-content"><span class="next-label">推荐学习节点</span><p class="next-topic">{{ nextTopic }}</p></div><RouterLink class="button button--primary overview-start-button" :to="nextAction.to">开始学习 <ArrowRight :size="14" /></RouterLink></section>
          </div>
          <section class="surface surface-pad blindspot-panel"><div class="section-heading section-heading--compact"><div><p class="eyebrow module-eyebrow">KNOWLEDGE GAPS</p><h2>知识盲区</h2></div><span class="muted">{{ weakPoints.length }} 个待巩固</span></div><div v-if="weakPoints.length" class="blindspot-list"><article v-for="(point, index) in weakPoints" :key="point.tag" class="blindspot-item"><div class="blindspot-copy"><span class="blindspot-index">{{ String(index + 1).padStart(2, '0') }}</span><div><strong>{{ point.tag }}</strong><small>正确率 {{ point.accuracy }}%</small></div></div><div class="mini-progress"><span :style="{ width: `${point.accuracy}%` }"></span></div><RouterLink class="icon-link" to="/learning/advanced" :aria-label="`练习${point.tag}`" title="开始练习"><ArrowRight :size="15" /></RouterLink></article></div><div v-else class="empty-state">完成几道练习后，这里会显示需要关注的知识点。</div></section>
        </div>

        <section class="surface surface-pad mastery-panel"><div class="mastery-card-header"><div><p class="eyebrow module-eyebrow">OVERALL MASTERY</p><h2>总体掌握度</h2><p class="muted">按知识点对比当前掌握度与达标线</p></div><div class="mastery-headline"><span>当前总计</span><strong>{{ masteryScore }}%</strong><em :class="{ 'is-positive': masteryDelta >= 0 }">{{ masteryDeltaLabel }} 达标线</em></div></div><div class="mastery-legend" aria-label="柱状图图例"><span><i class="legend-swatch legend-swatch--current"></i>当前掌握度</span><span><i class="legend-swatch legend-swatch--target"></i>达标线 60%</span></div><div class="mastery-chart" aria-label="知识点掌握度与达标线柱状图"><div class="mastery-axis"><span>100%</span><span>50%</span><span>0%</span></div><div class="bars"><div v-for="item in masteryItems" :key="item.tag" class="bar-column"><div class="bar-track"><span class="bar-value bar-value--current" :style="{ height: `${item.score}%` }" :title="`${item.tag}：当前掌握度 ${item.score}%`"><strong>{{ item.score }}%</strong></span><span class="bar-value bar-value--target" :style="{ height: `${item.target}%` }" :title="`${item.tag}：达标线 ${item.target}%`"></span></div><span class="bar-label" :title="item.tag">{{ item.shortTag }}</span></div></div></div><div class="mastery-footer"><span>已答 {{ stats.examAnswered }} 题</span><span>学习 {{ formatDuration(stats.studySeconds) }}</span></div></section>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { ArrowRight, ArrowUpRight } from 'lucide-vue-next'
import { learningApi } from '@/shared/api/learningApi'
import { learningState } from '@/entities/learning/learningState'

const loading = ref(true)
const profile = reactive({ direction: learningState.direction, goal: learningState.goal })
const path = reactive({ subject: '', currentNode: '', nextAction: null, nodes: [], difficultyTrend: [], resourceDifficultyMatch: [], progress: 0 })
const stats = reactive({ studySeconds: 0, examAnswered: 0, weakPoints: [] })
const goals = ref([])
const nextContent = ref([])
const mastery = ref([])
const overviewSummary = reactive({ masteryScore: null, text: '' })
const unwrap = (response) => response?.data?.data ?? response?.data ?? null
const toPercent = (value) => { const numeric = Number(value); return Number.isFinite(numeric) ? Math.max(0, Math.min(100, Math.round(numeric <= 1 ? numeric * 100 : numeric))) : 0 }
const goalItems = computed(() => { const items = goals.value.map((item) => item.title).filter(Boolean).slice(0, 4); return items.length ? items : [profile.goal || '建立稳定的学习节奏', path.subject ? `完成「${path.subject}」学习路径` : '完成当前学习路径', `${stats.examAnswered || 0} 道练习题已记录`] })
const nextTopic = computed(() => nextContent.value[0]?.title || path.currentNode || '从学习路径中选择一个节点开始')
const nextAction = computed(() => ({ to: path.nextAction?.type === 'quiz' ? '/learning/advanced' : '/learning/fundamentals' }))
const weakPoints = computed(() => { const values = stats.weakPoints || []; const unique = values.filter((item, index, all) => item.tag && all.findIndex((other) => other.tag === item.tag) === index); return unique.slice(0, 3).map((item) => { const raw = Number(item.accuracy || 0); return { tag: item.tag || item.knowledge_tag, accuracy: Math.round(raw <= 1 ? raw * 100 : raw) } }) })
const pathTrend = computed(() => path.difficultyTrend.slice(0, 12).map((node, index) => ({ id: node.id || index, label: String(node.title || `节点 ${index + 1}`).slice(0, 8), relative_difficulty: Number(node.relative_difficulty || 50), difficulty_score: Number(node.difficulty_score || 1).toFixed(2), status: node.status })))
const resourceTrend = computed(() => path.resourceDifficultyMatch.slice(0, 12).map((item, index) => ({ id: item.resource_id || index, label: String(item.title || `资源 ${index + 1}`).slice(0, 8), value: Number(item.difficulty_score || 0), user_level: item.user_level === null || item.user_level === undefined ? null : Number(item.user_level), status: item.status, tooltip: item.status === 'well_matched' ? `难度 ${item.difficulty_score}，匹配度 ${item.match_score}%` : item.status === 'too_hard' ? `难度 ${item.difficulty_score}，当前偏难` : item.status === 'too_easy' ? `难度 ${item.difficulty_score}，当前偏简单` : `难度 ${item.difficulty_score}，等待能力数据` })))
const trendMode = ref('path')
const activeTrend = computed(() => trendMode.value === 'path' ? pathTrend.value.map((point) => ({ ...point, value: point.relative_difficulty, tooltip: `相对难度 ${point.difficulty_score}` })) : resourceTrend.value)
const resourceTrendHasUserLevel = computed(() => resourceTrend.value.some((point) => point.user_level !== null))
const userLevelPoints = computed(() => resourceTrend.value.map((point, index) => `${trendX(index)},${trendY(point.user_level)}`).join(' '))
const masteryItems = computed(() => { const source = (mastery.value.length ? mastery.value : weakPoints.value).slice(0, 6); return source.map((item) => { const tag = item.knowledge_tag || item.tag || item.label || '知识点'; const score = toPercent(item.accuracy ?? item.score ?? 0); return { tag, shortTag: tag.length > 6 ? `${tag.slice(0, 6)}…` : tag, score, target: 60 } }) })
const masteryScore = computed(() => { const rawSummaryScore = overviewSummary.masteryScore; const summaryScore = Number(rawSummaryScore); if (rawSummaryScore !== null && rawSummaryScore !== undefined && rawSummaryScore !== '' && Number.isFinite(summaryScore)) return Math.round(summaryScore); const values = masteryItems.value.map((item) => item.score); return values.length ? Math.round(values.reduce((sum, value) => sum + value, 0) / values.length) : 0 })
const masteryDelta = computed(() => masteryScore.value - 60)
const masteryDeltaLabel = computed(() => `${masteryDelta.value >= 0 ? '+' : ''}${masteryDelta.value}%`)
const learningSummary = computed(() => overviewSummary.text || '完成练习后，这里会显示你的学习总结。')
const trendPoints = computed(() => activeTrend.value.map((point, index) => `${trendX(index)},${trendY(point.value)}`).join(' '))
const trendX = (index) => activeTrend.value.length < 2 ? 460 : Math.round(index * (920 / (activeTrend.value.length - 1)))
const trendY = (rate) => 170 - Math.max(0, Math.min(100, Number(rate || 0))) * 1.45
function formatDuration(seconds) { const value = Number(seconds || 0); if (value < 60) return `${value}秒`; const minutes = Math.round(value / 60); if (minutes < 60) return `${minutes}分钟`; return `${(minutes / 60).toFixed(1)}小时` }

async function loadOverview() {
  const result = await learningApi.getOverview()
  const overview = unwrap(result) || {}
  Object.assign(profile, overview.profile || {})
  const subjects = Array.isArray(overview.subjects) ? overview.subjects : []
  const pathData = overview.path || {}
  const content = Array.isArray(overview.next_content) ? overview.next_content : []
  Object.assign(path, { subject: subjects[0]?.name || '', currentNode: content[0]?.title || '', nextAction: { type: overview.recommendation?.action_type || '' }, nodes: content, difficultyTrend: Array.isArray(pathData.difficulty_trend) ? pathData.difficulty_trend : [], resourceDifficultyMatch: Array.isArray(pathData.resource_difficulty_match) ? pathData.resource_difficulty_match : [], progress: Number(pathData.progress || 0) })
  goals.value = Array.isArray(overview.goals) ? overview.goals : []
  nextContent.value = content
  const summary = overview.summary || {}
  const diagnosis = overview.diagnosis || {}
  Object.assign(stats, { studySeconds: summary.total_study_seconds || 0, examAnswered: diagnosis.answered || 0, weakPoints: overview.blind_spots || [] })
  overviewSummary.masteryScore = summary.mastery_score
  overviewSummary.text = summary.text || summary.description || overview.recommendation?.reason || overview.recommendation?.judgement || ''
  mastery.value = Array.isArray(overview.mastery_bars) ? overview.mastery_bars : []
  loading.value = false
}
onMounted(loadOverview)
</script>

<style scoped>
.overview-page { display: flex; height: calc(100vh - 64px); min-height: 0; flex-direction: column; overflow: hidden; }.overview-page :deep(.page-heading) { flex: 0 0 auto; margin-bottom: 18px; }.overview-dashboard { display: grid; min-height: 0; flex: 1; grid-template-rows: minmax(150px, .5fr) minmax(0, 1fr); gap: 18px; }.overview-columns { display: grid; min-height: 0; grid-template-columns: minmax(0, 1.08fr) minmax(320px, .92fr); gap: 18px; align-items: stretch; }.overview-left { display: grid; min-height: 0; grid-template-rows: minmax(0, .78fr) minmax(0, 1fr); gap: 18px; }.overview-top-cards { display: grid; min-height: 0; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 18px; }.surface-pad { padding: 22px; }.path-trend-panel { min-height: 0; padding-bottom: 15px; }.section-heading { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; margin-bottom: 18px; }.section-heading--compact { align-items: center; margin-bottom: 16px; }.section-heading h2 { margin: 0; font-size: 18px; }.section-heading .eyebrow { margin-bottom: 6px; }.trend-caption,.muted { color: var(--muted); font-size: 11px; }.trend-chart { position: relative; min-height: 0; height: calc(100% - 47px); }.trend-chart svg { display: block; width: 100%; height: calc(100% - 20px); overflow: visible; }.chart-grid { stroke: var(--line); stroke-width: 1; stroke-dasharray: 4 6; }.trend-line { fill: none; stroke: var(--accent-deep); stroke-width: 3; stroke-linecap: round; stroke-linejoin: round; }.trend-point { fill: var(--paper); stroke: var(--accent-deep); stroke-width: 2; }.trend-labels { display: flex; justify-content: space-between; color: var(--muted); font-size: 10px; }.compact-panel { min-height: 0; }.compact-panel .section-heading svg { color: var(--accent-deep); }.goal-list { display: grid; gap: 14px; margin: 28px 0 0; padding: 0; list-style: none; }.goal-list li { display: flex; align-items: center; gap: 11px; color: var(--ink); font-size: 12px; line-height: 1.4; }.check-circle { flex: 0 0 14px; width: 14px; height: 14px; border: 1px solid var(--accent-deep); border-radius: 50%; }.next-topic { min-height: 0; margin: 29px 0 15px; color: var(--ink); font-size: 14px; line-height: 1.65; }.text-link { display: inline-flex; align-items: center; gap: 5px; color: var(--accent-deep); font-size: 11px; font-weight: 800; text-decoration: none; }.blindspot-panel { min-height: 0; overflow: hidden; }.blindspot-list { display: grid; gap: 0; }.blindspot-item { display: grid; grid-template-columns: minmax(120px, 1fr) minmax(100px, 1.2fr) 26px; align-items: center; gap: 14px; min-height: 50px; border-top: 1px solid var(--line); }.blindspot-item:first-child { border-top: 0; }.blindspot-item strong,.blindspot-item small { display: block; }.blindspot-item strong { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 12px; }.blindspot-item small { margin-top: 4px; color: var(--muted); font-size: 10px; }.mini-progress { height: 5px; overflow: hidden; border-radius: 99px; background: #e9eee8; }.mini-progress span { display: block; height: 100%; border-radius: inherit; background: var(--accent-deep); }.icon-link { display: grid; width: 26px; height: 26px; place-items: center; border-radius: 50%; color: var(--accent-deep); }.icon-link:hover { background: var(--soft); }.mastery-panel { display: flex; min-height: 0; flex-direction: column; }.mastery-score { color: var(--accent-deep); font-size: 28px; }.mastery-chart { position: relative; display: flex; min-height: 0; flex: 1; padding: 10px 0 0 38px; border-bottom: 1px solid var(--ink); border-left: 1px solid var(--ink); }.mastery-axis { position: absolute; top: 8px; bottom: -4px; left: -36px; display: flex; flex-direction: column; justify-content: space-between; color: var(--muted); font-size: 10px; }.bars { display: flex; flex: 1; align-items: stretch; justify-content: space-around; gap: 14px; }.bar-column { display: grid; flex: 1; grid-template-rows: 1fr auto; gap: 9px; min-width: 0; }.bar-track { position: relative; display: flex; align-items: flex-end; justify-content: center; height: 100%; }.bar-value { display: block; width: min(42px, 70%); min-height: 4px; border: 1px solid var(--accent-deep); border-radius: 5px 5px 0 0; background: var(--accent); }.bar-label { overflow: hidden; color: var(--muted); font-size: 10px; text-align: center; text-overflow: ellipsis; white-space: nowrap; }.mastery-footer { display: flex; justify-content: space-between; gap: 10px; margin-top: 15px; color: var(--muted); font-size: 11px; }.empty-state,.loading-state { color: var(--muted); font-size: 12px; line-height: 1.6; }.empty-state { padding: 20px 0; }
@media (max-width: 900px) { .overview-page { height: auto; min-height: 0; overflow: visible; }.overview-columns { grid-template-columns: 1fr; }.overview-left { grid-template-rows: auto auto; }.mastery-panel { min-height: 460px; } } @media (max-width: 620px) { .overview-top-cards { grid-template-columns: 1fr; }.compact-panel { min-height: auto; }.mastery-chart { height: 280px; flex: none; }.trend-chart { height: 155px; }.trend-chart svg { height: 135px; }.surface-pad { padding: 17px; }.trend-heading-side { justify-items: start; }.trend-caption { text-align: left; } }
</style>

<style scoped>
.overview-page :deep(.page-heading) { margin-bottom: 8px; }
.overview-page :deep(.page-heading h1) { font-size: 20px; line-height: 1.4; }
.overview-page :deep(.page-heading .eyebrow) { font-size: 12px; line-height: 1.3; letter-spacing: .08em; }
.overview-page :deep(.page-heading .eyebrow) { color: var(--muted); }
.overview-page { height: 100%; --ink: #3f4146; }
.overview-dashboard { grid-template-rows: minmax(210px, .42fr) minmax(0, 1fr); gap: 16px; }
.overview-columns, .overview-left, .overview-top-cards { gap: 16px; }
.overview-left { grid-template-rows: minmax(220px, .9fr) minmax(0, 1fr); }
.path-trend-panel { padding: 0 20px 4px; background: transparent; border: 0; }
.path-trend-panel { overflow: hidden; }
.path-trend-panel .trend-chart, .path-trend-panel .trend-chart svg { overflow: hidden; }
.path-trend-panel { min-height: 210px; }
.path-trend-panel .trend-chart { min-height: 110px; height: 110px; }
.path-trend-panel .trend-chart svg { height: 94px; }
.path-trend-panel .trend-line { stroke: var(--accent-deep); stroke-width: 4; }
.path-trend-panel .trend-point { stroke: var(--accent-deep); stroke-width: 2.5; }
.path-trend-panel .trend-caption { display: grid; gap: 3px; text-align: right; }
.trend-heading-side { display: grid; justify-items: end; gap: 8px; }
.trend-switch { position: relative; display: inline-flex; gap: 3px; min-width: 148px; padding: 3px; border: 1px solid var(--line); border-radius: 6px; background: var(--paper); }
.trend-switch-indicator { position: absolute; top: 3px; bottom: 3px; left: 3px; width: calc(50% - 3px); border-radius: 4px; background: var(--ink); transition: transform .22s cubic-bezier(.2,.8,.2,1); }
.trend-switch.is-resource .trend-switch-indicator { transform: translateX(100%); }
.trend-switch button { position: relative; z-index: 1; flex: 1; min-height: 25px; padding: 0 8px; border: 0; border-radius: 4px; background: transparent; color: var(--muted); font-size: 10px; }
.trend-switch button.is-active { color: #fff; }
.resource-difficulty-line { stroke: var(--accent-deep); }
.user-level-line { fill: none; stroke: #8a4c43; stroke-width: 2; stroke-dasharray: 6 5; stroke-linecap: round; }
.path-trend-panel .trend-caption small { color: var(--muted); font-size: 10px; }
.path-eyebrow { margin-bottom: 6px; color: var(--muted); }
.module-eyebrow { margin-bottom: 6px; color: var(--muted); font-size: 11px; line-height: 1.3; }
.path-subject { display: block; margin-top: 5px; color: var(--muted); font-size: 12px; }
.goal-panel { border: 0; background: rgba(250, 255, 196, .18); }
.goal-heading { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; margin-bottom: 10px; }
.goal-heading .eyebrow { margin: 0 0 6px; color: var(--muted); font-size: 11px; }
.goal-heading h2 { margin: 0; font-size: 20px; line-height: 1.4; }
.goal-count { display: grid; min-width: 28px; height: 28px; place-items: center; border-radius: 50%; background: rgba(255, 255, 255, .72); color: var(--ink); font-size: 12px; font-weight: 800; }
.next-panel { border: 0; background: #f7f6fb; }
.next-panel { display: flex; flex-direction: column; }
.next-heading { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; }
.next-heading .eyebrow { margin: 0 0 6px; color: var(--muted); font-size: 11px; }
.next-heading h2 { margin: 0; font-size: 20px; line-height: 1.4; }
.next-mark { display: grid; width: 40px; height: 40px; flex: 0 0 40px; place-items: center; border-radius: 50%; background: rgba(255, 255, 255, .76); color: #403D88; }
.compact-panel, .blindspot-panel, .mastery-panel { border-radius: 12px; }
.compact-panel, .blindspot-panel, .mastery-panel { box-sizing: border-box; padding: 20px; }
.section-heading--compact { margin-bottom: 16px; }
.section-heading h2 { font-size: 20px; line-height: 1.4; }
.trend-caption, .muted { font-size: 12px; line-height: 1.4; }
.goal-list { margin: 0; }
.goal-list { gap: 12px; }
.goal-list li { font-size: 14px; line-height: 1.5; }
.goal-list { gap: 0; }
.goal-list li { display: grid; grid-template-columns: 28px minmax(0, 1fr) 8px; align-items: center; gap: 10px; min-height: 36px; padding: 6px 0; border-top: 1px solid rgba(63, 65, 70, .12); }
.goal-list li:first-child { border-top: 0; }
.goal-index { color: var(--muted); font-size: 11px; font-variant-numeric: tabular-nums; }
.goal-copy { min-width: 0; overflow: hidden; color: var(--ink); font-size: 13px; line-height: 1.5; text-overflow: ellipsis; white-space: nowrap; }
.goal-status { width: 8px; height: 8px; border-radius: 50%; background: #403D88; }
.next-topic { margin: 0 0 22px; }
.next-topic { margin-bottom: 16px; font-size: 14px; line-height: 1.5; }
.next-content { flex: 1; margin: 16px 0 20px; padding-top: 16px; border-top: 1px solid rgba(63, 65, 70, .12); }
.next-label { display: block; margin-bottom: 8px; color: var(--muted); font-size: 12px; line-height: 1.4; }
.next-content .next-topic { margin: 0; color: var(--ink); font-size: 16px; line-height: 1.5; }
.mastery-footer { margin-top: 22px; }
.mastery-footer { margin-top: 16px; font-size: 12px; line-height: 1.4; }
.blindspot-item { min-height: 48px; gap: 12px; }
.blindspot-panel { background: rgba(250, 255, 196, .18); padding: 16px; }
.blindspot-panel .section-heading { margin-bottom: 8px; }
.blindspot-copy { display: grid; grid-template-columns: 28px minmax(0, 1fr); align-items: center; gap: 10px; min-width: 0; }
.blindspot-index { color: var(--muted); font-size: 11px; font-variant-numeric: tabular-nums; }
.blindspot-item { grid-template-columns: minmax(0, 1fr) minmax(110px, 1.2fr) 28px; min-height: 48px; padding: 4px 0; }
.blindspot-item strong { font-size: 14px; line-height: 1.4; }
.blindspot-item small { font-size: 12px; line-height: 1.4; }
.blindspot-item .mini-progress span { background: #403D88; }
.blindspot-item .icon-link { background: rgba(255, 255, 255, .68); }
.mastery-chart { border-color: var(--line); }
.mastery-chart { padding-left: 0; }
.mastery-axis { display: none; }
.mastery-card-header { display: flex; align-items: flex-start; justify-content: space-between; gap: 18px; }
.mastery-headline { display: grid; justify-items: end; gap: 3px; min-width: 94px; }
.mastery-headline span { color: var(--muted); font-size: 11px; }
.mastery-headline strong { color: var(--ink); font-size: 28px; line-height: 1; }
.mastery-headline em { padding: 3px 7px; border-radius: 999px; background: #f8e8e5; color: #8a4c43; font-size: 10px; font-style: normal; font-weight: 800; white-space: nowrap; }
.mastery-headline em.is-positive { background: #e9f0e3; color: var(--accent-deep); }
.mastery-legend { display: flex; gap: 15px; margin: 16px 0 8px; color: var(--muted); font-size: 10px; }
.mastery-legend span { display: inline-flex; align-items: center; gap: 6px; }
.legend-swatch { width: 8px; height: 8px; border-radius: 2px; background: #1e3c34; }
.legend-swatch--target { background: #dce3dc; }
.overview-start-button { border: 0; border-radius: 12px; background: #1e3c34; color: #fff; }
.overview-start-button:hover { border: 0; border-radius: 12px; background: #142a24; color: #fff; }
.bar-track { gap: 4px; }
.bar-value { display: flex; align-items: flex-start; justify-content: center; width: min(26px, 42%); border-color: #1e3c34; background: #1e3c34; transition: height .62s cubic-bezier(.22,1,.36,1), background-color .25s ease; }
.bar-value--target { border-color: #dce3dc; background: #dce3dc; }
.bar-value strong { padding-top: 6px; color: #fff; font-size: 10px; font-weight: 800; opacity: 0; transform: translateY(4px); transition: opacity .3s ease .12s, transform .42s cubic-bezier(.22,1,.36,1) .12s; white-space: nowrap; }
.bar-column:hover .bar-value strong, .bar-value:focus-within strong { opacity: 1; transform: translateY(0); }
:global(.page-container:has(.overview-page)) { background: #f7f7f7; }
:global(.app-content:has(.overview-page) .app-header) { border-bottom-color: #e8e8e8; background: #f7f7f7; }
.overview-page .surface { border: 1px solid rgba(63, 91, 49, .28); box-shadow: 0 8px 24px rgba(45, 40, 92, .07); }
.overview-page h2 { color: #1e3c34; }
.overview-page .goal-panel, .overview-page .next-panel { box-shadow: 0 8px 22px rgba(45, 40, 92, .06); }
.compact-panel .section-heading > svg { width: 32px; height: 32px; padding: 8px; border-radius: 50%; background: rgba(255, 255, 255, .72); }
.overview-start-button { box-shadow: 0 6px 14px rgba(30, 60, 52, .2); }
.overview-start-button:hover { box-shadow: 0 8px 18px rgba(30, 60, 52, .26); }
:global(.page-container:has(.overview-page)) { width: 100%; height: calc(100vh - 64px); box-sizing: border-box; margin: 0; padding: 20px 20px 20px 28px; overflow: hidden; }
@media (max-width: 900px) {
  .overview-page { height: auto; }
  .overview-dashboard { grid-template-rows: auto auto; }
  .path-trend-panel { min-height: 180px; }
  .path-trend-panel .trend-chart { height: 100px; }
  .overview-left { grid-template-rows: auto auto; }
  :global(.page-container:has(.overview-page)) { height: auto; min-height: 0; padding: 24px 20px 58px 24px; overflow: visible; }
}
@media (max-width: 620px) {
  .mastery-card-header { gap: 12px; }
  .mastery-headline { min-width: 76px; }
  .mastery-headline strong { font-size: 24px; }
  .mastery-legend { margin-top: 13px; }
}
</style>
