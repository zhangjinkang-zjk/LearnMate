<template>
  <div class="profile-page">
    <PageTitle eyebrow="学习档案" title="个人画像" />

    <div v-if="loading" class="profile-state surface" aria-live="polite"><LoaderCircle class="spin" :size="20" /> 正在读取你的用户画像</div>
    <div v-else class="profile-layout">
      <section class="profile-summary surface">
        <div class="profile-hero">
          <div class="profile-large-avatar">{{ initial }}</div>
          <div class="profile-hero-copy"><span class="profile-label">学习者画像</span><h2>{{ username }}</h2><p>{{ portrait.profile_summary || '完成画像访谈后，这里会显示你的学习特点和提升方向。' }}</p></div>
        </div>
        <div class="portrait-facts">
          <div class="portrait-fact"><span>学习方向</span><strong>{{ direction || '尚未设置' }}</strong></div>
          <div class="portrait-fact"><span>学习目标</span><strong>{{ portrait.learning_goal || '尚未识别' }}</strong></div>
          <div class="portrait-fact"><span>认知偏好</span><strong>{{ portrait.cognition || '尚未识别' }}</strong></div>
          <div class="portrait-fact"><span>身份</span><strong>{{ identity }}</strong></div>
        </div>
      </section>

      <section class="portrait-radar surface" aria-labelledby="radar-title">
        <div class="section-heading"><div><p class="eyebrow">学习能力</p><h2 id="radar-title">能力画像</h2><p class="radar-method">综合参考练习表现、知识覆盖与学习投入</p></div><span class="radar-updated">{{ radarUpdatedLabel }}</span></div>
        <div v-if="hasRadarData" class="radar-layout">
          <svg class="radar-chart" viewBox="0 0 300 280" role="img" aria-label="六维能力雷达图">
            <polygon v-for="level in radarLevels" :key="level" :points="radarRingPoints(level)" class="radar-ring" />
            <line v-for="(point, index) in radarVertices" :key="`axis-${index}`" :x1="radarCenter.x" :y1="radarCenter.y" :x2="point.x" :y2="point.y" class="radar-axis" />
            <polygon :points="radarDataPoints" class="radar-area" />
            <circle v-for="(point, index) in radarVertices" :key="`point-${index}`" :cx="point.x" :cy="point.y" r="4" class="radar-point" />
            <text v-for="(point, index) in radarVertices" :key="`label-${index}`" :x="point.labelX" :y="point.labelY" class="radar-label" :text-anchor="point.anchor">{{ point.label }}</text>
          </svg>
          <div class="radar-list"><div v-for="item in radarDimensions" :key="item.key" class="radar-item"><div class="radar-item-heading"><span>{{ item.label }}</span><strong>{{ item.score }}%</strong></div><div class="radar-track"><span :style="{ width: `${item.score}%` }"></span></div><small>{{ item.desc }}</small></div></div>
        </div>
        <div v-else class="profile-empty"><BarChart3 :size="20" /> 完成一些诊断或练习后，这里会生成你的能力雷达图。</div>
      </section>

      <section class="portrait-traits surface" aria-labelledby="traits-title">
        <div class="section-heading"><div><p class="eyebrow">学习特征</p><h2 id="traits-title">学习特征</h2></div><span class="radar-updated">{{ displayTraitItems.length }} 项记录</span></div>
        <div v-if="displayTraitItems.length" class="trait-grid"><article v-for="item in displayTraitItems" :key="item.key" class="trait-item"><span class="trait-label">{{ item.label }}</span><p>{{ item.value }}</p></article></div>
        <div v-else class="profile-empty"><UserRound :size="20" /> 完成画像访谈后，这里会显示你的学习特征。</div>
      </section>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { BarChart3, LoaderCircle, UserRound } from 'lucide-vue-next'
import PageTitle from '@/shared/ui/PageTitle.vue'
import { readPortrait, readPortraitRadar } from '@/shared/api/portraitApi'

const loading = ref(true)
const username = ref(localStorage.getItem('learnmate_username') || '我的学习者')
const identity = ref(localStorage.getItem('learnmate_identity') || '尚未选择')
const direction = ref(localStorage.getItem('learnmate_direction') || '')
const portrait = reactive({ cognition: '', learning_goal: '', profile_summary: '', traits: {} })
const radar = ref(null)

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

const fallbackDimensions = [{ key: 'memory', label: '记忆', score: 0, desc: '基础回忆与知识提取表现' }, { key: 'understanding', label: '理解', score: 0, desc: '概念理解与知识关联表现' }, { key: 'application', label: '应用', score: 0, desc: '场景迁移与实际应用表现' }, { key: 'analysis', label: '分析', score: 0, desc: '问题拆解与综合判断表现' }, { key: 'breadth', label: '广度', score: 0, desc: '知识覆盖与探索范围' }, { key: 'persistence', label: '坚持', score: 0, desc: '学习投入与持续参与' }]
const radarDimensions = computed(() => { const dimensions = Array.isArray(radar.value?.dimensions) ? radar.value.dimensions : []; return fallbackDimensions.map((fallback) => { const current = dimensions.find((item) => item.key === fallback.key) || {}; return { ...fallback, ...current, desc: fallback.desc, score: Math.max(0, Math.min(100, Math.round(Number(current.score ?? fallback.score) || 0))) } }) })
const hasRadarData = computed(() => {
  const dimensions = radar.value?.dimensions
  if (!Array.isArray(dimensions) || !dimensions.length) return false

  // 已作答但全错时，六个维度可能都是 0；这仍然是一份真实测试结果，必须展示雷达图。
  const answeredCount = Number(radar.value?.answered_count)
  if (Number.isFinite(answeredCount)) return answeredCount > 0

  // 兼容尚未升级 answered_count 字段的历史接口，避免已有雷达记录被误判为空。
  return dimensions.some((item) => Number(item.score) > 0) || Boolean(radar.value?.updated_at)
})
const radarUpdatedLabel = computed(() => radar.value?.updated_at ? `更新于 ${new Date(radar.value.updated_at).toLocaleDateString('zh-CN')}` : '等待数据')
const radarCenter = { x: 150, y: 132 }; const radarRadius = 88; const radarLevels = [25, 50, 75, 100]
const radarVertices = computed(() => radarDimensions.value.map((item, index) => { const angle = -Math.PI / 2 + index * (Math.PI * 2 / 6); const x = radarCenter.x + Math.cos(angle) * radarRadius; const y = radarCenter.y + Math.sin(angle) * radarRadius; const labelRadius = radarRadius + 21; return { ...item, x, y, labelX: radarCenter.x + Math.cos(angle) * labelRadius, labelY: radarCenter.y + Math.sin(angle) * labelRadius + (index === 0 ? -2 : 4), anchor: Math.abs(Math.cos(angle)) < 0.2 ? 'middle' : Math.cos(angle) > 0 ? 'start' : 'end' } }))
const radarRingPoints = (level) => radarVertices.value.map((point) => `${radarCenter.x + (point.x - radarCenter.x) * level / 100},${radarCenter.y + (point.y - radarCenter.y) * level / 100}`).join(' ')
const radarDataPoints = computed(() => radarVertices.value.map((point) => `${radarCenter.x + (point.x - radarCenter.x) * point.score / 100},${radarCenter.y + (point.y - radarCenter.y) * point.score / 100}`).join(' '))

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
:global(.app-content:has(.profile-page)) { background: #f7f7f7; }
:global(.app-content:has(.profile-page) .app-header) { border-bottom-color: #e8e8e8; background: #f7f7f7; }
</style>
