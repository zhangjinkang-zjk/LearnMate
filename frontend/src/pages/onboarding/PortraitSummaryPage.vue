<template>
  <main class="summary-page">
    <div class="summary-word" aria-hidden="true">
      <span>LEARN</span>
      <span>MATE</span>
    </div>

    <router-link class="summary-back" to="/learnmate-chat" @click.prevent="router.push('/learnmate-chat')">
      <span aria-hidden="true">↗</span>
      <span>返回</span>
    </router-link>

    <section class="summary-shell" aria-labelledby="summary-title">
      <p class="summary-kicker">LEARNMATE 画像</p>
      <h1 id="summary-title">这是我对你的了解</h1>
      <p class="summary-intro">我已经把刚才的对话整理成了一份画像，请确认内容是否准确。</p>

      <div class="summary-output" aria-live="polite">
        <span>{{ streamedText }}</span><span v-if="!isComplete" class="summary-caret" aria-hidden="true"></span>
      </div>

      <div class="summary-actions">
        <button class="summary-edit" type="button" @click="router.push('/learnmate-chat')">修改回答</button>
        <button class="summary-confirm" type="button" :disabled="!isComplete || isPreparing" @click="confirmProfile">
          <span>{{ isPreparing ? '生成学习概览…' : '确认画像' }}</span>
          <span aria-hidden="true">↗</span>
        </button>
      </div>
      <p v-if="isPreparing" class="summary-status">正在根据你的方向拆分科目并准备学习路径，完成后会自动进入学习概览。</p>
      <p v-if="generationError" class="summary-error" role="alert">{{ generationError }}</p>
    </section>
  </main>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { learningState, persistLearningProfile } from '@/entities/learning/learningState'
import { learningApi } from '@/shared/api/learningApi'

const router = useRouter()
const streamedText = ref('')
const isComplete = ref(false)
const isPreparing = ref(false)
const generationError = ref('')
let streamTimer

const readDialogue = () => {
  try {
    const saved = JSON.parse(sessionStorage.getItem('learnmate_portrait_dialogue') || '[]')
    return Array.isArray(saved) ? saved : []
  } catch {
    return []
  }
}

const dialogue = readDialogue()
const answerAt = index => dialogue[index]?.answer?.trim() || '未填写'
const identity = localStorage.getItem('learnmate_identity') || '未选择'

const readPortraitSummary = () => {
  try {
    const saved = JSON.parse(sessionStorage.getItem('learnmate_portrait_summary') || '{}')
    return saved && typeof saved === 'object' ? saved : {}
  } catch {
    return {}
  }
}

const portraitSummary = readPortraitSummary()
const aiSummary = String(portraitSummary.profile_summary || '').trim()
const cognition = String(portraitSummary.cognition || '').trim()
const learningGoal = String(portraitSummary.learning_goal || '').trim()
const traits = portraitSummary.traits && typeof portraitSummary.traits === 'object' ? portraitSummary.traits : {}
const onboarding = traits.onboarding && typeof traits.onboarding === 'object' ? traits.onboarding : {}
const traitText = key => {
  const value = traits[key]
  if (!value) return ''
  if (typeof value === 'string') return value
  return String(value.value || value.text || '').trim()
}
const direction = String(onboarding.direction || cognition || answerAt(0)).trim()
const goal = String(onboarding.goal || learningGoal || answerAt(1)).trim()

const fullSummary = computed(() => [
  aiSummary || '根据刚才的对话，我整理出了这份画像：',
  '',
  `身份：${identity}`,
  `学习方向：${direction}`,
  `学习目标：${goal}`,
  `当前基础：${traitText('knowbase') || answerAt(2)}`,
  `每周可投入时间：${answerAt(3)}`,
  `学习偏好：${traitText('learning_pace') || answerAt(4)}`,
  '',
  '以上内容准确吗？确认后，我会为你开始学习。'
].join('\n'))

const startStreaming = () => {
  let cursor = 0
  streamedText.value = ''
  isComplete.value = false
  const tick = () => {
    const nextCursor = Math.min(cursor + 1, fullSummary.value.length)
    streamedText.value = fullSummary.value.slice(0, nextCursor)
    cursor = nextCursor
    if (cursor >= fullSummary.value.length) {
      isComplete.value = true
      return
    }
    streamTimer = window.setTimeout(tick, 40)
  }
  tick()
}

const unwrap = response => response?.data?.data ?? response?.data ?? response
const hasOverviewContent = overview => Boolean(
  overview?.path?.id ||
  (Array.isArray(overview?.subjects) && overview.subjects.some(subject => subject?.id || subject?.name)),
)

const confirmProfile = async () => {
  if (!isComplete.value || isPreparing.value) return
  isPreparing.value = true
  generationError.value = ''

  learningState.identity = identity
  learningState.direction = direction
  learningState.goal = goal
  persistLearningProfile()

  try {
    const response = await learningApi.generatePathsFromDirection(direction, goal)
    const generated = unwrap(response)
    const paths = Array.isArray(generated?.paths) ? generated.paths : []
    const readyPath = paths.find(path => path && path.path_id)
    if (!readyPath) throw new Error('学习路径暂未生成成功，请稍后重试')

    // 路径生成完成后再读取一次概览快照，确保进入页面时目标、科目和节点已经可用。
    const overview = unwrap(await learningApi.getOverview())
    if (!hasOverviewContent(overview)) throw new Error('学习概览暂未准备完成，请稍后重试')

    localStorage.setItem('learnmate_onboarding_complete', '1')
    const profile = { identity, direction, goal, dialogue }
    sessionStorage.removeItem('learnmate_portrait_dialogue')
    sessionStorage.removeItem('learnmate_portrait_summary')
    window.dispatchEvent(new CustomEvent('learnmate:learning-profile-ready', { detail: profile }))
    await router.push('/learning/overview')
  } catch (error) {
    generationError.value = error?.response?.data?.detail || error?.message || '学习路径生成失败，请重试。'
  } finally {
    isPreparing.value = false
  }
}

onMounted(startStreaming)

onBeforeUnmount(() => {
  if (streamTimer) window.clearTimeout(streamTimer)
})
</script>

<style scoped>
.summary-page {
  position: relative;
  min-height: 100vh;
  overflow: hidden;
  isolation: isolate;
  padding: clamp(28px, 5vw, 64px) clamp(20px, 6vw, 90px) 56px;
  color: #f3f0e7;
  background: #1e3c34;
  font-family: Inter, "Helvetica Neue", Arial, sans-serif;
}

.summary-page::before {
  content: "";
  position: absolute;
  inset: 0;
  z-index: -3;
  background:
    linear-gradient(120deg, rgba(3, 18, 13, 0.86), rgba(28, 68, 53, 0.68) 34%, rgba(5, 24, 17, 0.92) 68%, rgba(53, 93, 69, 0.56)),
    radial-gradient(ellipse 80% 68% at 8% 92%, rgba(151, 184, 137, 0.5), transparent 66%),
    radial-gradient(ellipse 62% 62% at 92% 8%, rgba(2, 13, 10, 0.92), transparent 70%),
    #1e3c34;
  background-size: 180% 180%, 100% 100%, 100% 100%, 100% 100%;
  animation: metalShift 18s ease-in-out infinite alternate;
}

.summary-page::after {
  content: "";
  position: absolute;
  inset: -30%;
  z-index: -1;
  pointer-events: none;
  background: linear-gradient(112deg, transparent 30%, rgba(216, 239, 187, 0.08) 44%, rgba(255, 255, 255, 0.14) 48%, transparent 68%);
  transform: translate3d(-18%, 0, 0) rotate(-3deg);
  animation: metalSheen 14s ease-in-out infinite alternate;
}

.summary-back {
  position: relative;
  z-index: 2;
  display: inline-flex;
  align-items: center;
  gap: 10px;
  color: rgba(243, 240, 231, 0.8);
  font-size: 11px;
  font-weight: 800;
  letter-spacing: 0.16em;
  text-decoration: none;
  transition: color 0.3s ease, transform 0.4s ease;
}

.summary-back:hover { color: #e2f452; transform: translateX(-4px); }
.summary-back span:first-child { font-size: 18px; line-height: 0.6; }

.summary-word {
  position: absolute;
  inset: 8% 0 0;
  z-index: -2;
  display: grid;
  align-content: center;
  justify-items: center;
  color: rgba(173, 198, 178, 0.2);
  font-family: Georgia, "Times New Roman", serif;
  font-size: clamp(116px, 17.5vw, 282px);
  line-height: 0.76;
  user-select: none;
  pointer-events: none;
}

.summary-word span { display: block; transform: scaleX(1.08); }

.summary-shell {
  width: min(760px, 100%);
  margin: clamp(8vh, 10vh, 120px) auto 0;
  animation: summaryIn 0.8s cubic-bezier(0.22, 1, 0.36, 1) both;
}

.summary-kicker {
  margin: 0 0 14px;
  color: #e2f452;
  font-size: 10px;
  font-weight: 900;
  letter-spacing: 0.2em;
}

.summary-shell h1 {
  max-width: 620px;
  margin: 0;
  color: #f3f0e7;
  font-size: clamp(30px, 4vw, 54px);
  line-height: 1.05;
  letter-spacing: 0;
}

.summary-intro {
  max-width: 540px;
  margin: 18px 0 28px;
  color: rgba(243, 240, 231, 0.68);
  font-size: 14px;
  line-height: 1.7;
}

.summary-output {
  min-height: 242px;
  padding: 24px 26px;
  border: 1px solid rgba(226, 244, 82, 0.32);
  border-radius: 18px;
  background: rgba(7, 26, 19, 0.54);
  color: #f3f0e7;
  font-size: 16px;
  line-height: 1.8;
  white-space: pre-line;
  box-shadow: 0 22px 48px rgba(2, 15, 10, 0.28), inset 0 1px 0 rgba(243, 240, 231, 0.08);
  backdrop-filter: blur(8px);
}

.summary-caret {
  display: inline-block;
  width: 2px;
  height: 1.1em;
  margin-left: 3px;
  vertical-align: -0.15em;
  background: #e2f452;
  animation: caretBlink 0.85s steps(1) infinite;
}

.summary-actions {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 14px;
  margin-top: 24px;
}

.summary-status,
.summary-error {
  margin: 14px 0 0;
  font-size: 12px;
  line-height: 1.6;
}

.summary-status { color: rgba(243, 240, 231, 0.72); }
.summary-error { color: #ffb5a8; }

.summary-edit,
.summary-confirm {
  min-height: 48px;
  border: 0;
  border-radius: 999px;
  font-size: 11px;
  font-weight: 900;
  letter-spacing: 0.12em;
  cursor: pointer;
  transition: transform 0.4s cubic-bezier(0.16, 1, 0.3, 1), background 0.25s ease, box-shadow 0.4s ease, opacity 0.25s ease;
}

.summary-edit {
  padding: 0 18px;
  background: rgba(243, 240, 231, 0.1);
  color: rgba(243, 240, 231, 0.74);
}

.summary-edit:hover { color: #f3f0e7; background: rgba(243, 240, 231, 0.18); transform: translateY(-2px); }

.summary-confirm {
  display: inline-flex;
  align-items: center;
  gap: 13px;
  padding: 0 20px 0 22px;
  background: #e2f452;
  color: #1e3c34;
  box-shadow: 0 14px 28px rgba(4, 20, 15, 0.28);
}

.summary-confirm:hover:not(:disabled) { background: #f0ff75; transform: translateY(-3px); box-shadow: 0 18px 34px rgba(4, 20, 15, 0.4); }
.summary-confirm:disabled { cursor: wait; opacity: 0.38; box-shadow: none; }
.summary-confirm span:last-child { font-size: 19px; line-height: 0.65; }

@keyframes summaryIn { from { opacity: 0; transform: translateY(20px); } to { opacity: 1; transform: translateY(0); } }
@keyframes caretBlink { 0%, 45% { opacity: 1; } 46%, 100% { opacity: 0; } }
@keyframes metalShift { from { background-position: 0% 50%, 0 0, 0 0, 0 0; filter: saturate(0.94) contrast(1.02); } to { background-position: 100% 50%, 0 0, 0 0, 0 0; filter: saturate(1.1) contrast(1.08); } }
@keyframes metalSheen { from { transform: translate3d(-18%, 0, 0) rotate(-3deg); opacity: 0.45; } to { transform: translate3d(18%, 0, 0) rotate(-3deg); opacity: 0.88; } }

@media (max-width: 640px) {
  .summary-page { padding: 26px 18px 34px; }
  .summary-shell { margin-top: 14vh; }
  .summary-output { min-height: 280px; padding: 20px; font-size: 14px; }
  .summary-actions { align-items: stretch; flex-direction: column-reverse; }
  .summary-edit, .summary-confirm { width: 100%; justify-content: center; }
}

@media (prefers-reduced-motion: reduce) {
  .summary-shell, .summary-caret, .summary-page::before, .summary-page::after { animation: none !important; }
}
</style>
