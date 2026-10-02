<template>
  <div class="profile-page">
    <PageTitle eyebrow="学习档案" title="个人画像" />

    <div v-if="loading" class="profile-state surface" aria-live="polite"><LoaderCircle class="spin" :size="20" /> 正在读取你的用户画像</div>
    <div v-else class="profile-layout">
      <section class="profile-summary surface">
        <div class="profile-hero">
          <div class="profile-avatar-wrap"><div class="profile-large-avatar">{{ initial }}</div><span class="profile-status-dot" title="画像已同步"></span></div>
          <div class="profile-hero-copy"><span class="profile-label">学习者画像</span><h2>{{ username }}</h2><p>{{ portrait.profile_summary || '完成画像访谈后，这里会显示你的学习特点和提升方向。' }}</p></div>
        </div>
        <div class="portrait-facts">
          <div class="portrait-fact"><span>学习方向</span><strong>{{ direction || '尚未设置' }}</strong></div>
          <div class="portrait-fact"><span>学习目标</span><strong>{{ portrait.learning_goal || '尚未识别' }}</strong></div>
          <div class="portrait-fact"><span>认知偏好</span><strong>{{ portrait.cognition || '尚未识别' }}</strong></div>
          <div class="portrait-fact"><span>身份</span><strong>{{ identity }}</strong></div>
        </div>
        <div class="profile-summary-footer">
          <div class="profile-completion"><div class="profile-completion-heading"><span>画像完整度</span><strong>{{ profileCompletion }}%</strong></div><div class="profile-completion-track"><span :style="{ width: `${profileCompletion}%` }"></span></div></div>
          <div class="profile-sync"><span>最近同步</span><strong>{{ portraitUpdatedLabel }}</strong></div>
        </div>
      </section>

      <section class="profile-pulse-grid" aria-label="学习概览">
        <article class="pulse-card pulse-card--score">
          <div class="pulse-card-heading"><span>综合能力</span><BarChart3 :size="17" /></div>
          <strong class="pulse-value">{{ averageRadarScore }}<small>/100</small></strong>
          <div class="pulse-track"><span :style="{ width: `${averageRadarScore}%` }"></span></div>
          <p>{{ hasRadarData ? '基于六项能力维度的当前表现' : '完成一次练习后开始生成' }}</p>
        </article>
        <article class="pulse-card pulse-card--strength">
          <div class="pulse-card-heading"><span>当前优势</span><Sparkles :size="17" /></div>
          <strong class="pulse-value pulse-value--text">{{ strongestDimension.label }}</strong>
          <p>{{ hasRadarData ? `${strongestDimension.score}分 · ${strongestDimension.desc}` : '还没有足够数据' }}</p>
          <span class="pulse-accent">保持你的学习节奏</span>
        </article>
        <article class="pulse-card pulse-card--focus">
          <div class="pulse-card-heading"><span>优先提升</span><TrendingUp :size="17" /></div>
          <strong class="pulse-value pulse-value--text">{{ weakestDimension.label }}</strong>
          <p>{{ hasRadarData ? `${weakestDimension.score}分 · 建议安排针对性练习` : '完成一次练习后生成建议' }}</p>
          <span class="pulse-accent">从一个小目标开始</span>
        </article>
        <article class="pulse-card pulse-card--updated">
          <div class="pulse-card-heading"><span>学习记录</span><Clock3 :size="17" /></div>
          <strong class="pulse-value">{{ learningEventCount }}</strong>
          <p>条行为记录</p>
          <span class="pulse-accent">{{ lastLearningLabel }}</span>
        </article>
      </section>

      <section class="portrait-radar surface" aria-labelledby="radar-title">
        <div class="section-heading"><div><p class="eyebrow">学习能力</p><h2 id="radar-title">能力画像</h2><p class="radar-method">综合参考练习表现、知识覆盖与学习投入</p></div><div v-if="hasPreviousRadar" class="radar-legend" aria-label="当前与上一次对比状态"><span><i class="radar-legend__swatch radar-legend__swatch--current"></i>当前</span><span><i class="radar-legend__swatch radar-legend__swatch--previous"></i>上次更新</span></div></div>
        <div v-if="hasRadarData" class="radar-layout">
          <svg class="radar-chart" viewBox="0 0 300 280" role="img" aria-label="六维能力雷达图">
            <polygon v-for="level in radarLevels" :key="level" :points="radarRingPoints(level)" class="radar-ring" />
            <line v-for="(point, index) in radarVertices" :key="`axis-${index}`" :x1="radarCenter.x" :y1="radarCenter.y" :x2="point.x" :y2="point.y" class="radar-axis" />
            <polygon v-if="hasPreviousRadar" :points="radarPreviousDataPoints" class="radar-previous-area" />
            <polygon :points="radarDataPoints" class="radar-area" />
            <circle v-for="(point, index) in radarVertices" :key="`point-${index}`" :cx="point.x" :cy="point.y" r="4" class="radar-point" />
            <text v-for="(point, index) in radarVertices" :key="`label-${index}`" :x="point.labelX" :y="point.labelY" class="radar-label" :text-anchor="point.anchor">{{ point.label }}</text>
          </svg>
          <div class="radar-list"><div v-for="item in radarDimensions" :key="item.key" class="radar-item"><div class="radar-item-heading"><span>{{ item.label }}</span><strong>{{ item.score }}% <em v-if="item.delta !== null" :class="{ 'is-up': item.delta > 0, 'is-down': item.delta < 0 }">{{ item.delta > 0 ? '+' : '' }}{{ item.delta }}</em></strong></div><div class="radar-track"><span :style="{ width: `${item.score}%` }"></span><i v-if="item.previous !== null" :style="{ width: `${item.previous}%` }"></i></div><small>{{ item.desc }}<template v-if="item.previous !== null"> · 上次 {{ item.previous }}%</template></small></div></div>
        </div>
        <div v-else class="profile-empty"><BarChart3 :size="20" /> 完成一些诊断或练习后，这里会生成你的能力雷达图。</div>
      </section>

      <section class="portrait-traits surface" aria-labelledby="traits-title">
        <div class="puzzle-heading"><div><p class="eyebrow">学习特征</p><h2 id="traits-title">把你的学习画像拼起来</h2><p class="puzzle-intro">每块拼图是一条学习线索。它们会先落位，点击任意碎片，查看这条判断和它的依据。</p></div><span class="puzzle-count">{{ displayTraitItems.length }} 块线索</span></div>
        <div v-if="displayTraitItems.length" class="puzzle-layout">
          <div class="puzzle-board" aria-label="学习画像拼图">
            <div class="puzzle-board-heading"><span>画像拼图</span><small>可信度越高，拼片颜色越饱和</small></div>
            <div class="puzzle-pieces" role="list">
              <button v-for="(item, index) in displayTraitItems" :key="item.key" type="button" class="puzzle-piece" :class="[`puzzle-piece--tone-${index % 4}`, { 'is-selected': selectedTrait?.key === item.key }]" :style="{ '--piece-delay': `${Math.min(index, 12) * 65}ms`, '--piece-tilt': `${index % 2 ? 1 : -1}deg`, '--confidence': `${item.confidence}%` }" role="listitem" :aria-pressed="selectedTrait?.key === item.key" :aria-label="`${item.label}：${item.value}`" @click="selectedTraitKey = item.key">
                <span class="puzzle-piece__label">{{ item.label }}</span>
                <strong class="puzzle-piece__value">{{ item.value }}</strong>
                <span class="puzzle-piece__meta">{{ item.confidence ? `可信度 ${item.confidence}%` : '等待更多依据' }}</span>
                <span class="puzzle-piece__bar" aria-hidden="true"><i></i></span>
              </button>
            </div>
          </div>
          <aside v-if="selectedTrait" class="puzzle-detail" aria-live="polite">
            <span class="puzzle-detail__eyebrow">当前拼片</span>
            <h3>{{ selectedTrait.label }}</h3>
            <p>{{ selectedTrait.value }}</p>
            <div class="puzzle-detail__confidence"><span>判断可信度</span><strong>{{ selectedTrait.confidence }}%</strong></div>
            <div class="puzzle-detail__track" role="progressbar" :aria-label="`${selectedTrait.label}判断可信度`" :aria-valuenow="selectedTrait.confidence" aria-valuemin="0" aria-valuemax="100"><span :style="{ width: `${selectedTrait.confidence}%` }"></span></div>
            <small>这代表系统目前有多少依据支持这条画像判断，会随着诊断、练习和对话记录更新。</small>
          </aside>
        </div>
        <div v-else class="profile-empty"><UserRound :size="20" /> 完成画像访谈后，这里会显示你的学习特征。</div>
      </section>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { BarChart3, Clock3, LoaderCircle, Sparkles, TrendingUp, UserRound } from 'lucide-vue-next'
import PageTitle from '@/shared/ui/PageTitle.vue'
import { readPortrait, readPortraitRadar } from '@/shared/api/portraitApi'

const loading = ref(true)
const username = ref(localStorage.getItem('learnmate_username') || '我的学习者')
const identity = ref(localStorage.getItem('learnmate_identity') || '尚未选择')
const direction = ref(localStorage.getItem('learnmate_direction') || '')
const portrait = reactive({ cognition: '', learning_goal: '', profile_summary: '', traits: {} })
const radar = ref(null)
const hasPreviousRadar = computed(() => Array.isArray(radar.value?.previous?.dimensions) && radar.value.previous.dimensions.length > 0)

const initial = computed(() => username.value.trim().slice(0, 1).toUpperCase() || '学')
const traitLabels = { knowbase: '知识掌握', knowledge_mastery: '知识掌握情况', commonmis: '易错点', learning_pace: '学习节奏', interest: '兴趣方向', strengths: '学习强项', weaknesses: '学习弱项', updated_at: '更新时间', created_at: '创建时间', learning_direction: '学习方向', learning_direction_goal: '学习目标', learning_direction_subjects: '学习主题', personality_tags: '个性标签', cognition: '认知偏好', learning_goal: '学习目标', profile_summary: '画像总结', source: '信息来源', confidence: '可信度', tag: '知识点', knowledge_tag: '知识点', level: '掌握程度', mastery_level: '掌握程度', accuracy: '准确率', total_attempts: '练习次数', attempts: '练习次数', total_correct: '答对题数', total_questions: '题目数', last_accuracy: '最近准确率', last_practiced_at: '最近练习', status: '状态' }
const formatTraitValue = (key, raw, depth = 0) => {
  if (raw === null || raw === undefined || raw === '') return ''
  if (key.endsWith('_at') || key === 'updated_at') {
    const date = new Date(raw)
    if (!Number.isNaN(date.getTime())) return date.toLocaleString('zh-CN', { dateStyle: 'medium', timeStyle: 'short' })
  }
  if (Array.isArray(raw)) return raw.map((item) => formatTraitValue(key, item, depth + 1)).filter(Boolean).join('、')
  if (typeof raw !== 'object') return String(raw)
  if (depth > 2) return ''
  if (raw.value !== undefined || raw.text !== undefined) return formatTraitValue(key, raw.value ?? raw.text, depth + 1)
  return Object.entries(raw).filter(([childKey]) => !['source', 'confidence'].includes(childKey)).map(([childKey, childValue]) => {
    const value = formatTraitValue(childKey, childValue, depth + 1)
    return value ? `${traitLabels[childKey] || childKey}：${value}` : ''
  }).filter(Boolean).join('；')
}
const traitItems = computed(() => Object.entries(portrait.traits || {}).map(([key, raw]) => { const value = formatTraitValue(key, raw); if (!value) return null; const confidence = typeof raw === 'object' && Number.isFinite(Number(raw.confidence)) ? Math.round(Number(raw.confidence) * 100) : 0; return { key, label: traitLabels[key] || key, value, confidence } }).filter(Boolean))
const displayTraitLabels = {
  onboarding: '学习定向',
  learning_signals: '学习动态',
  learning_direction: '学习方向',
  learning_direction_goal: '学习目标',
  learning_direction_subjects: '学习主题',
  identity: '身份',
  direction: '学习方向',
  goal: '学习目标',
  total_events: '学习记录',
  activity_counts: '学习活动',
  last_event: '最近学习',
  created_at: '创建时间',
  updated_at: '更新时间',
  cognition: '认知偏好',
  learning_goal: '学习目标',
  profile_summary: '画像总结',
  knowledge_mastery: '知识掌握情况',
  learning_pace: '学习节奏',
  interest: '兴趣方向',
  strengths: '学习强项',
  weaknesses: '待提升方向',
}

const learningEventLabels = {
  resource_read: '阅读学习资料',
  resource_download: '下载学习资料',
  resource_saved: '保存学习资料',
  node_completed: '完成章节学习',
  lesson_completed: '完成课程学习',
  quiz_completed: '完成测试',
  quiz_submitted: '提交测试',
  practice_completed: '完成练习',
}

function formatPortraitDate(value) {
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? '' : date.toLocaleString('zh-CN', { dateStyle: 'medium', timeStyle: 'short' })
}

function formatLearningEvent(type) {
  return learningEventLabels[type] || '学习活动'
}

function formatOnboardingTrait(raw) {
  if (!raw) return ''
  if (typeof raw !== 'object') return '已完成学习定向'
  return [
    ['direction', '学习方向'],
    ['goal', '学习目标'],
    ['identity', '身份'],
  ].map(([key, label]) => raw[key] ? `${label}：${raw[key]}` : '').filter(Boolean).join('；')
}

function formatLearningSignalsTrait(raw) {
  if (!raw) return ''
  if (typeof raw !== 'object') return '暂未积累学习记录'
  const parts = []
  const totalEvents = Number(raw.total_events)
  if (Number.isFinite(totalEvents)) parts.push(`累计学习 ${totalEvents} 次`)

  if (raw.activity_counts && typeof raw.activity_counts === 'object') {
    const activities = Object.entries(raw.activity_counts)
      .map(([type, count]) => Number.isFinite(Number(count)) ? `${formatLearningEvent(type)} ${Number(count)} 次` : '')
      .filter(Boolean)
    if (activities.length) parts.push(activities.join('、'))
  }

  if (raw.last_event && typeof raw.last_event === 'object') {
    if (raw.last_event.type) parts.push(`最近学习：${formatLearningEvent(raw.last_event.type)}`)
    const lastTime = formatPortraitDate(raw.last_event.created_at || raw.last_event.updated_at)
    if (lastTime) parts.push(`最近时间：${lastTime}`)
  }
  return parts.join('；')
}

function formatDisplayTraitValue(key, raw, depth = 0) {
  if (raw === null || raw === undefined || raw === '' || depth > 2) return ''
  if (key === 'onboarding') return formatOnboardingTrait(raw)
  if (key === 'learning_signals') return formatLearningSignalsTrait(raw)
  if (key.endsWith('_at') || key === 'updated_at') return formatPortraitDate(raw)
  if (Array.isArray(raw)) return raw.map((item) => formatDisplayTraitValue(key, item, depth + 1)).filter(Boolean).join('、')
  if (typeof raw !== 'object') return typeof raw === 'boolean' ? (raw ? '是' : '否') : String(raw)
  if (raw.value !== undefined || raw.text !== undefined) return formatDisplayTraitValue(key, raw.value ?? raw.text, depth + 1)

  return Object.entries(raw)
    .map(([childKey, childValue]) => {
      const label = displayTraitLabels[childKey]
      const value = formatDisplayTraitValue(childKey, childValue, depth + 1)
      return label && value ? `${label}：${value}` : ''
    })
    .filter(Boolean)
    .join('；')
}

const hiddenTraitKeys = new Set(['updated_at', 'created_at'])
const displayTraitItems = computed(() => Object.entries(portrait.traits || {}).filter(([key]) => !hiddenTraitKeys.has(key)).map(([key, raw]) => {
  const value = formatDisplayTraitValue(key, raw)
  if (!value) return null
  const rawConfidence = typeof raw === 'object' && raw !== null ? Number(raw.confidence) : NaN
  const confidence = Number.isFinite(rawConfidence) ? Math.round(rawConfidence <= 1 ? rawConfidence * 100 : rawConfidence) : 0
  return { key, label: displayTraitLabels[key] || '学习情况', value, confidence }
}).filter(Boolean))
const selectedTraitKey = ref('')
const selectedTrait = computed(() => {
  const items = displayTraitItems.value
  return items.find((item) => item.key === selectedTraitKey.value) || items[0] || null
})

const profileCompletion = computed(() => {
  const checks = [
    Boolean(portrait.profile_summary),
    Boolean(direction.value),
    Boolean(portrait.learning_goal),
    Boolean(portrait.cognition),
    identity.value !== '尚未选择',
    displayTraitItems.value.length > 0,
    hasRadarData.value,
  ]
  return Math.round(checks.filter(Boolean).length / checks.length * 100)
})
const portraitUpdatedLabel = computed(() => formatPortraitDate(radar.value?.updated_at || portrait.updated_at) || '尚未同步')
const averageRadarScore = computed(() => {
  if (!hasRadarData.value) return 0
  const scores = radarDimensions.value.map((item) => item.score)
  return Math.round(scores.reduce((sum, score) => sum + score, 0) / scores.length)
})
const strongestDimension = computed(() => {
  if (!hasRadarData.value) return { label: '待发现', score: 0, desc: '继续积累学习数据' }
  return [...radarDimensions.value].sort((a, b) => b.score - a.score)[0]
})
const weakestDimension = computed(() => {
  if (!hasRadarData.value) return { label: '待发现', score: 0, desc: '继续积累学习数据' }
  return [...radarDimensions.value].sort((a, b) => a.score - b.score)[0]
})
const learningSignals = computed(() => portrait.traits?.learning_signals || {})
const learningEventCount = computed(() => {
  const count = Number(learningSignals.value.total_events)
  return Number.isFinite(count) ? count : 0
})
const lastLearningLabel = computed(() => {
  const event = learningSignals.value.last_event
  if (!event) return '等待新的学习记录'
  const date = formatPortraitDate(event.created_at || event.updated_at)
  return date ? `${formatLearningEvent(event.type)} · ${date}` : formatLearningEvent(event.type)
})

const fallbackDimensions = [{ key: 'memory', label: '记忆', score: 0, desc: '基础回忆与知识提取表现' }, { key: 'understanding', label: '理解', score: 0, desc: '概念理解与知识关联表现' }, { key: 'application', label: '应用', score: 0, desc: '场景迁移与实际应用表现' }, { key: 'analysis', label: '分析', score: 0, desc: '问题拆解与综合判断表现' }, { key: 'breadth', label: '广度', score: 0, desc: '知识覆盖与探索范围' }, { key: 'persistence', label: '坚持', score: 0, desc: '学习投入与持续参与' }]
const previousRadarByKey = computed(() => new Map((radar.value?.previous?.dimensions || []).map((item) => [item.key, Number(item.score)])))
const radarDimensions = computed(() => { const dimensions = Array.isArray(radar.value?.dimensions) ? radar.value.dimensions : []; return fallbackDimensions.map((fallback) => { const current = dimensions.find((item) => item.key === fallback.key) || {}; const score = Math.max(0, Math.min(100, Math.round(Number(current.score ?? fallback.score) || 0))); const previousValue = previousRadarByKey.value.get(fallback.key); const previous = Number.isFinite(previousValue) ? Math.max(0, Math.min(100, Math.round(previousValue))) : null; return { ...fallback, ...current, desc: fallback.desc, score, previous, delta: previous === null ? null : score - previous } }) })
const hasRadarData = computed(() => {
  const dimensions = radar.value?.dimensions
  if (!Array.isArray(dimensions) || !dimensions.length) return false

  // 已作答但全错时，六个维度可能都是 0；这仍然是一份真实测试结果，必须展示雷达图。
  const answeredCount = Number(radar.value?.answered_count)
  if (Number.isFinite(answeredCount)) return answeredCount > 0

  // 兼容尚未升级 answered_count 字段的历史接口，避免已有雷达记录被误判为空。
  return dimensions.some((item) => Number(item.score) > 0) || Boolean(radar.value?.updated_at)
})
const radarCenter = { x: 150, y: 132 }; const radarRadius = 88; const radarLevels = [25, 50, 75, 100]
const radarVertices = computed(() => radarDimensions.value.map((item, index) => { const angle = -Math.PI / 2 + index * (Math.PI * 2 / 6); const x = radarCenter.x + Math.cos(angle) * radarRadius; const y = radarCenter.y + Math.sin(angle) * radarRadius; const labelRadius = radarRadius + 21; return { ...item, x, y, labelX: radarCenter.x + Math.cos(angle) * labelRadius, labelY: radarCenter.y + Math.sin(angle) * labelRadius + (index === 0 ? -2 : 4), anchor: Math.abs(Math.cos(angle)) < 0.2 ? 'middle' : Math.cos(angle) > 0 ? 'start' : 'end' } }))
const radarRingPoints = (level) => radarVertices.value.map((point) => `${radarCenter.x + (point.x - radarCenter.x) * level / 100},${radarCenter.y + (point.y - radarCenter.y) * level / 100}`).join(' ')
const radarDataPoints = computed(() => radarVertices.value.map((point) => `${radarCenter.x + (point.x - radarCenter.x) * point.score / 100},${radarCenter.y + (point.y - radarCenter.y) * point.score / 100}`).join(' '))
const radarPreviousDataPoints = computed(() => radarVertices.value.map((point) => `${radarCenter.x + (point.x - radarCenter.x) * (point.previous ?? 0) / 100},${radarCenter.y + (point.y - radarCenter.y) * (point.previous ?? 0) / 100}`).join(' '))

async function loadProfile() { try { const [portraitResult, radarResult] = await Promise.allSettled([readPortrait(), readPortraitRadar()]); if (portraitResult.status === 'fulfilled' && portraitResult.value) { Object.assign(portrait, portraitResult.value, { traits: portraitResult.value.traits || {} }); const onboarding = portraitResult.value.traits?.onboarding; if (onboarding && typeof onboarding === 'object') { identity.value = onboarding.identity || identity.value; direction.value = onboarding.direction || direction.value; portrait.learning_goal = portrait.learning_goal || onboarding.goal || '' } } if (radarResult.status === 'fulfilled') radar.value = radarResult.value } finally { loading.value = false } }
onMounted(loadProfile)
</script>

<style scoped>
.profile-page { min-width: 0; }.profile-page :deep(.page-heading) { margin-bottom: 24px; }.profile-layout { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 18px; align-items: stretch; }.surface { border-radius: 10px; }.profile-summary, .portrait-radar, .portrait-traits { grid-column: 1 / -1; padding: 26px; border-color: transparent; }.profile-summary { background: #f7f8ed; }.portrait-radar { background: #f7f6fb; }.portrait-traits { background: #f2f7ed; }.profile-snapshot, .profile-next-step { min-width: 0; padding: 22px; }.profile-snapshot { background: #f5f8ef; }.profile-next-step { display: flex; flex-direction: column; background: #f8f7fc; }.profile-hero { display: flex; align-items: center; gap: 17px; padding-bottom: 23px; border-bottom: 1px solid rgba(63, 65, 70, .14); }.profile-large-avatar { display: grid; width: 68px; height: 68px; flex: 0 0 68px; place-items: center; border-radius: 50%; background: var(--accent); color: #1e3c34; font-size: 24px; font-weight: 900; }.profile-hero-copy { min-width: 0; }.profile-label, .portrait-fact span, .trait-label { color: var(--muted); font-size: 11px; }.profile-hero h2 { margin: 4px 0 5px; font-size: 23px; }.profile-hero p { max-width: 760px; margin: 0; color: var(--muted); font-size: 13px; line-height: 1.7; }.portrait-facts { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 0; margin-top: 22px; }.portrait-fact { display: grid; gap: 7px; min-width: 0; padding: 0 18px; border-left: 1px solid rgba(63, 65, 70, .14); }.portrait-fact:first-child { padding-left: 0; border-left: 0; }.portrait-fact strong { overflow: hidden; color: var(--ink); font-size: 14px; text-overflow: ellipsis; white-space: nowrap; }.section-heading { display: flex; align-items: flex-start; justify-content: space-between; gap: 14px; margin-bottom: 18px; }.section-heading h2 { margin: 0; font-size: 19px; }.section-heading .eyebrow { margin: 0 0 6px; }.section-heading > svg { color: var(--accent-deep); }.snapshot-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 0; border-top: 1px solid rgba(63, 65, 70, .12); }.snapshot-item { display: grid; min-width: 0; gap: 7px; padding: 16px 15px; border-left: 1px solid rgba(63, 65, 70, .12); }.snapshot-item:first-child { padding-left: 0; border-left: 0; }.snapshot-item span, .snapshot-item small, .next-step-copy > span { color: var(--muted); font-size: 10px; }.snapshot-item strong { overflow: hidden; color: var(--ink); font-size: 18px; text-overflow: ellipsis; white-space: nowrap; }.snapshot-item i { display: block; height: 5px; overflow: hidden; border-radius: 99px; background: #e0e8d9; }.snapshot-item i b { display: block; height: 100%; border-radius: inherit; background: var(--accent-deep); }.next-step-copy { display: grid; gap: 7px; }.next-step-copy strong { overflow-wrap: anywhere; color: var(--ink); font-size: 17px; line-height: 1.45; }.next-step-copy p { margin: 1px 0 0; color: var(--muted); font-size: 12px; line-height: 1.65; }.priority-gaps { display: flex; flex-wrap: wrap; gap: 6px; margin: 15px 0; }.priority-gaps span { padding: 4px 7px; border-radius: 4px; background: #eeeef9; color: #514c8c; font-size: 10px; }.text-link { display: inline-flex; align-items: center; gap: 5px; width: fit-content; margin-top: auto; color: var(--accent-deep); font-size: 12px; font-weight: 800; text-decoration: none; }.text-link:hover { color: #514c8c; }.radar-method { margin: 5px 0 0; color: var(--muted); font-size: 11px; line-height: 1.5; }.radar-updated { color: var(--muted); font-size: 11px; }.radar-layout { display: grid; grid-template-columns: minmax(300px, .7fr) minmax(0, 1.3fr); gap: 32px; align-items: center; }.radar-chart { display: block; width: 100%; max-width: 340px; height: auto; margin: 0 auto; overflow: visible; }.radar-ring { fill: none; stroke: #d9d7e8; stroke-width: 1; }.radar-axis { stroke: #d9d7e8; stroke-width: 1; }.radar-area { fill: rgba(64, 61, 136, .16); stroke: #403d88; stroke-width: 2; stroke-linejoin: round; }.radar-point { fill: #403d88; stroke: var(--paper); stroke-width: 2; }.radar-label { fill: #514c8c; font-size: 11px; }.radar-list { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 18px 28px; }.radar-item { display: grid; gap: 5px; }.radar-item-heading { display: flex; justify-content: space-between; gap: 10px; color: var(--ink); font-size: 12px; }.radar-item-heading strong { color: #403d88; font-size: 12px; }.radar-item small { color: var(--muted); font-size: 10px; }.radar-track { height: 5px; overflow: hidden; border-radius: 99px; background: #e8e6f2; }.radar-track span { display: block; height: 100%; border-radius: inherit; background: #403d88; }.radar-item:nth-child(2n) .radar-track span { background: #8a4c43; }.radar-item:nth-child(3n) .radar-track span { background: var(--accent-deep); }.trait-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 0; border-top: 1px solid rgba(63, 65, 70, .14); }.trait-item { min-height: 108px; padding: 17px 18px 14px 0; border-right: 1px solid rgba(63, 65, 70, .14); border-bottom: 1px solid rgba(63, 65, 70, .14); }.trait-item:not(:nth-child(3n + 1)) { padding-left: 18px; }.trait-item:nth-child(3n) { padding-right: 0; border-right: 0; }.trait-item:nth-child(3n + 2) .trait-label { color: #514c8c; }.trait-item:nth-child(3n) .trait-label { color: #8a4c43; }.trait-item p { margin: 8px 0 7px; color: var(--ink); font-size: 13px; line-height: 1.6; }.trait-item small { color: var(--muted); font-size: 10px; }.profile-state, .profile-empty { display: flex; align-items: center; gap: 10px; color: var(--muted); font-size: 12px; line-height: 1.6; }.profile-state { padding: 24px; }.profile-empty { min-height: 160px; justify-content: center; }.spin { animation: spin 1s linear infinite; } @keyframes spin { to { transform: rotate(360deg); } }
@media (max-width: 760px) { .profile-layout { grid-template-columns: 1fr; }.profile-summary, .portrait-radar, .portrait-traits { grid-column: 1; } }
@media (max-width: 620px) { .profile-summary, .portrait-radar, .portrait-traits, .profile-snapshot, .profile-next-step { padding: 19px; }.profile-hero { align-items: flex-start; }.portrait-facts { grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px 0; }.portrait-fact:nth-child(3) { padding-left: 0; border-left: 0; }.snapshot-grid { grid-template-columns: 1fr; }.snapshot-item, .snapshot-item:first-child { padding: 12px 0; border-bottom: 1px solid rgba(63, 65, 70, .12); border-left: 0; }.snapshot-item:last-child { border-bottom: 0; }.radar-layout { grid-template-columns: 1fr; gap: 12px; }.radar-chart { max-width: 270px; }.radar-list { grid-template-columns: 1fr; gap: 13px; }.trait-grid { grid-template-columns: 1fr; }.trait-item, .trait-item:not(:nth-child(3n + 1)) { padding: 15px 0; border-right: 0; }.trait-item:last-child { border-bottom: 0; } }
.portrait-traits .trait-grid { grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 14px; border-top: 0; }
.portrait-traits .trait-item, .portrait-traits .trait-item:not(:nth-child(3n + 1)), .portrait-traits .trait-item:nth-child(3n) { display: flex; min-height: 126px; flex-direction: column; padding: 17px; border: 1px solid rgba(63, 91, 49, .16); border-radius: 8px; background: rgba(255, 255, 255, .72); box-shadow: 0 5px 14px rgba(30, 60, 52, .08); transition: transform .18s ease, box-shadow .18s ease; }
.portrait-traits .trait-item:hover { box-shadow: 0 8px 19px rgba(30, 60, 52, .13); transform: translateY(-2px); }
.portrait-traits .trait-item p { margin: 9px 0; }
.portrait-traits .trait-item small { margin-top: auto; }
@media (max-width: 620px) { .portrait-traits .trait-grid { grid-template-columns: 1fr; gap: 10px; }.portrait-traits .trait-item, .portrait-traits .trait-item:not(:nth-child(3n + 1)), .portrait-traits .trait-item:nth-child(3n) { min-height: 0; padding: 15px; border-right: 1px solid rgba(63, 91, 49, .16); border-bottom: 1px solid rgba(63, 91, 49, .16); } }
.profile-avatar-wrap { position: relative; flex: 0 0 68px; }
.profile-avatar-wrap .profile-large-avatar { width: 68px; }
.profile-status-dot { position: absolute; right: 1px; bottom: 1px; width: 13px; height: 13px; border: 3px solid #f7f8ed; border-radius: 50%; background: #67a56a; }
.profile-summary-footer { display: grid; grid-template-columns: minmax(0, 1fr) auto; align-items: end; gap: 26px; margin-top: 22px; padding-top: 18px; border-top: 1px solid rgba(63, 65, 70, .12); }
.profile-completion { display: grid; gap: 8px; min-width: 0; }
.traits-help { max-width: 620px; margin: 6px 0 0; color: var(--muted); font-size: 11px; line-height: 1.55; }
.profile-completion-heading { display: flex; justify-content: space-between; gap: 12px; color: var(--muted); font-size: 11px; }
.profile-completion-heading strong { color: var(--accent-deep); font-size: 12px; }
.profile-completion-track, .trait-confidence-track { height: 6px; overflow: hidden; border-radius: 99px; background: rgba(63, 91, 49, .12); }
.profile-completion-track span, .trait-confidence-track span { display: block; height: 100%; border-radius: inherit; background: var(--accent-deep); transition: width .45s ease; }
.profile-sync { display: grid; gap: 5px; min-width: 130px; text-align: right; }
.profile-sync span { color: var(--muted); font-size: 10px; }
.profile-sync strong { color: var(--ink); font-size: 11px; font-weight: 700; }
.profile-pulse-grid { display: grid; grid-column: 1 / -1; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; }
.pulse-card { display: grid; min-width: 0; min-height: 151px; align-content: start; gap: 10px; padding: 18px; border: 1px solid var(--line); border-radius: 8px; background: var(--paper); box-shadow: 0 8px 22px rgba(30, 60, 52, .045); transition: transform .18s ease, box-shadow .18s ease; }
.pulse-card:hover { transform: translateY(-2px); box-shadow: 0 12px 26px rgba(30, 60, 52, .09); }
.pulse-card--score { background: #f4f8e9; border-color: #dce9ba; }
.pulse-card--strength { background: #f7f5fd; border-color: #e5e1f4; }
.pulse-card--focus { background: #fbf4ef; border-color: #eeddd3; }
.pulse-card--updated { background: #f2f7f5; border-color: #dce9e3; }
.pulse-card-heading { display: flex; align-items: center; justify-content: space-between; gap: 8px; color: var(--muted); font-size: 11px; }
.pulse-card-heading svg { color: var(--accent-deep); }
.pulse-card--strength .pulse-card-heading svg { color: #62599b; }
.pulse-card--focus .pulse-card-heading svg { color: #a15d45; }
.pulse-card--updated .pulse-card-heading svg { color: #4d806b; }
.pulse-value { display: flex; align-items: baseline; gap: 4px; color: var(--ink); font-size: 32px; font-weight: 850; letter-spacing: -.04em; line-height: 1; }
.pulse-value small { color: var(--muted); font-size: 12px; font-weight: 700; letter-spacing: 0; }
.pulse-value--text { display: block; overflow: hidden; font-size: 21px; text-overflow: ellipsis; white-space: nowrap; }
.pulse-card p { min-height: 30px; margin: 0; color: var(--muted); font-size: 10px; line-height: 1.5; }
.pulse-accent { overflow: hidden; margin-top: auto; color: var(--accent-deep); font-size: 10px; font-weight: 800; text-overflow: ellipsis; white-space: nowrap; }
.pulse-card--strength .pulse-accent { color: #62599b; }
.pulse-card--focus .pulse-accent { color: #a15d45; }
.pulse-card--updated .pulse-accent { color: #4d806b; }
.pulse-track { height: 6px; overflow: hidden; border-radius: 99px; background: rgba(63, 91, 49, .12); }
.pulse-track span { display: block; height: 100%; border-radius: inherit; background: var(--accent-deep); transition: width .45s ease; }
.radar-legend { display: flex; flex-wrap: wrap; justify-content: flex-end; gap: 11px; color: var(--muted); font-size: 10px; }
.radar-legend span { display: inline-flex; align-items: center; gap: 5px; }
.radar-legend__swatch { display: inline-block; width: 8px; height: 8px; border-radius: 2px; }
.radar-legend__swatch--current { background: #403d88; }
.radar-legend__swatch--previous { border: 1px dashed #8c87b5; background: rgba(140, 135, 181, .16); }
.radar-previous-area { fill: rgba(140, 135, 181, .08); stroke: #8c87b5; stroke-width: 1.5; stroke-dasharray: 4 3; stroke-linejoin: round; }
.radar-item-heading em { margin-left: 3px; font-size: 10px; font-style: normal; font-weight: 800; }
.radar-item-heading em.is-up { color: #4e8a55; }
.radar-item-heading em.is-down { color: #a15d45; }
.radar-track { position: relative; }
.radar-track i { position: absolute; top: 0; left: 0; display: block; height: 100%; border: 1px dashed #8c87b5; border-radius: inherit; background: transparent; box-sizing: border-box; }
.trait-item-heading { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.trait-confidence { color: var(--accent-deep); font-size: 10px; font-weight: 800; }
.trait-confidence-track { height: 4px; margin-top: auto; background: rgba(63, 91, 49, .1); }
.trait-confidence-track span { background: #7e9c46; }
@media (max-width: 920px) { .profile-pulse-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
@media (max-width: 620px) { .profile-summary-footer { grid-template-columns: 1fr; gap: 15px; }.profile-sync { min-width: 0; text-align: left; }.profile-pulse-grid { grid-template-columns: 1fr; gap: 10px; }.pulse-card { min-height: 132px; }.radar-legend { justify-content: flex-start; } }
:global(.app-content:has(.profile-page)) { background: #f7f7f7; }
:global(.app-content:has(.profile-page) .app-header) { border-bottom-color: #e8e8e8; background: #f7f7f7; }
</style>

<style scoped>
.radar-legend { display: flex; flex-wrap: wrap; align-items: center; justify-content: flex-end; gap: 10px; color: var(--muted); font-size: 10px; }
.radar-legend span { display: inline-flex; align-items: center; gap: 5px; }
.radar-legend__swatch { width: 9px; height: 9px; border-radius: 2px; }
.radar-legend__swatch--current { background: #403d88; }
.radar-legend__swatch--previous { border: 1px solid #9b98be; background: rgba(155, 152, 190, .18); }
.radar-previous-area { fill: rgba(155, 152, 190, .12); stroke: #9b98be; stroke-width: 1.5; stroke-dasharray: 4 3; stroke-linejoin: round; }
.radar-item-heading em { margin-left: 4px; font-size: 10px; font-style: normal; font-weight: 800; }
.radar-item-heading em.is-up { color: #4d8b59; }
.radar-item-heading em.is-down { color: #a35b50; }
.radar-track { position: relative; }
.radar-track span, .radar-track i { position: absolute; top: 0; left: 0; display: block; height: 100%; border-radius: inherit; }
.radar-track span { z-index: 1; }
.radar-track i { z-index: 0; background: #b7b4cf; }
@media (max-width: 620px) { .radar-legend { justify-content: flex-start; margin-top: 8px; } }

.portrait-puzzle { background: #f2f7ed; }
.puzzle-heading { display: flex; align-items: flex-start; justify-content: space-between; gap: 20px; margin-bottom: 22px; }
.puzzle-heading h2 { margin: 0; color: var(--ink); font-size: 25px; letter-spacing: -.035em; }
.puzzle-intro { max-width: 620px; margin: 7px 0 0; color: var(--muted); font-size: 12px; line-height: 1.65; }
.puzzle-count { flex: 0 0 auto; padding-top: 3px; color: var(--muted); font-size: 12px; }
.puzzle-layout { display: grid; grid-template-columns: minmax(0, 1.55fr) minmax(235px, .45fr); gap: 28px; align-items: stretch; }
.puzzle-board { min-width: 0; padding: 18px; border: 1px solid rgba(63, 91, 49, .15); border-radius: 16px; background: rgba(255, 255, 255, .42); }
.puzzle-board-heading { display: flex; align-items: baseline; justify-content: space-between; gap: 12px; margin: 0 3px 14px; color: var(--ink); font-size: 12px; font-weight: 800; }
.puzzle-board-heading small { color: var(--muted); font-size: 10px; font-weight: 500; }
.puzzle-pieces { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 4px; }
.puzzle-piece { position: relative; display: flex; min-width: 0; min-height: 156px; flex-direction: column; align-items: flex-start; padding: 20px 18px 17px; overflow: hidden; border: 1px solid rgba(63, 91, 49, .15); border-radius: 12px; background: var(--piece-bg); color: var(--ink); text-align: left; cursor: pointer; isolation: isolate; animation: puzzle-piece-place .72s var(--piece-delay) both cubic-bezier(.2, .85, .3, 1.2); transition: transform .22s ease, border-color .22s ease, filter .22s ease; }
.puzzle-piece::before, .puzzle-piece::after { position: absolute; z-index: -1; width: 26px; height: 26px; border-radius: 50%; background: inherit; content: ''; transition: transform .22s ease; }
.puzzle-piece::before { right: -13px; top: 50%; transform: translateY(-50%); }
.puzzle-piece::after { bottom: -13px; left: 50%; transform: translateX(-50%); }
.puzzle-piece:nth-child(3n)::before { display: none; }
.puzzle-piece:nth-child(-n + 3)::after { display: none; }
.puzzle-piece:hover, .puzzle-piece:focus-visible { z-index: 2; border-color: rgba(63, 91, 49, .42); filter: saturate(1.1); outline: 0; transform: translateY(-5px) rotate(var(--piece-tilt)); }
.puzzle-piece.is-selected { z-index: 3; border-color: var(--accent-deep); box-shadow: 0 9px 20px rgba(45, 76, 38, .16); transform: translateY(-4px) rotate(0deg); }
.puzzle-piece--tone-0 { --piece-bg: #e7f0d8; }
.puzzle-piece--tone-1 { --piece-bg: #e8e5f4; }
.puzzle-piece--tone-2 { --piece-bg: #f5e5dc; }
.puzzle-piece--tone-3 { --piece-bg: #e1eee9; }
.puzzle-piece__label { color: var(--accent-deep); font-size: 11px; font-weight: 800; }
.puzzle-piece--tone-1 .puzzle-piece__label { color: #514c8c; }
.puzzle-piece--tone-2 .puzzle-piece__label { color: #995b48; }
.puzzle-piece--tone-3 .puzzle-piece__label { color: #4d806b; }
.puzzle-piece__value { display: -webkit-box; margin: 11px 0 13px; overflow: hidden; color: var(--ink); font-size: 15px; font-weight: 650; line-height: 1.55; -webkit-box-orient: vertical; -webkit-line-clamp: 3; }
.puzzle-piece__meta { margin-top: auto; color: var(--muted); font-size: 10px; }
.puzzle-piece__bar { display: block; width: 100%; height: 4px; margin-top: 8px; overflow: hidden; border-radius: 99px; background: rgba(63, 91, 49, .12); }
.puzzle-piece__bar i { display: block; width: var(--confidence); height: 100%; border-radius: inherit; background: var(--accent-deep); transition: width .45s ease; }
.puzzle-detail { display: flex; min-width: 0; flex-direction: column; justify-content: center; padding: 22px 4px 22px 4px; }
.puzzle-detail__eyebrow { color: var(--accent-deep); font-size: 10px; font-weight: 800; letter-spacing: .08em; text-transform: uppercase; }
.puzzle-detail h3 { margin: 9px 0 11px; color: var(--ink); font-size: 23px; letter-spacing: -.03em; }
.puzzle-detail p { margin: 0; color: var(--ink); font-size: 16px; line-height: 1.65; }
.puzzle-detail__confidence { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-top: 28px; color: var(--muted); font-size: 11px; }
.puzzle-detail__confidence strong { color: var(--accent-deep); font-size: 19px; }
.puzzle-detail__track { height: 6px; margin-top: 9px; overflow: hidden; border-radius: 99px; background: rgba(63, 91, 49, .12); }
.puzzle-detail__track span { display: block; height: 100%; border-radius: inherit; background: var(--accent-deep); transition: width .35s ease; }
.puzzle-detail small { margin-top: 16px; color: var(--muted); font-size: 10px; line-height: 1.7; }
@keyframes puzzle-piece-place { 0% { opacity: 0; transform: translateY(-22px) rotate(-6deg) scale(.94); } 70% { transform: translateY(3px) rotate(2deg) scale(1.01); } 100% { opacity: 1; transform: translateY(0) rotate(0) scale(1); } }
@media (prefers-reduced-motion: reduce) { .puzzle-piece { animation: none; transition: none; } }
@media (max-width: 820px) { .puzzle-layout { grid-template-columns: 1fr; gap: 16px; }.puzzle-detail { padding: 8px 4px 2px; }.puzzle-detail__confidence { margin-top: 18px; } }
@media (max-width: 620px) { .puzzle-heading { display: block; }.puzzle-count { display: block; margin-top: 9px; }.puzzle-board { padding: 11px; }.puzzle-pieces { grid-template-columns: repeat(2, minmax(0, 1fr)); }.puzzle-piece { min-height: 142px; padding: 16px 14px 14px; }.puzzle-piece:nth-child(3n)::before { display: block; }.puzzle-piece:nth-child(2n)::before { display: none; }.puzzle-piece:nth-child(-n + 3)::after { display: block; }.puzzle-piece:nth-child(-n + 2)::after { display: none; } }
</style>
