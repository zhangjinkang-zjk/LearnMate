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
      <p class="summary-intro">{{ introText }}</p>

      <div v-if="analysisMissing" class="summary-notice" role="alert">
        <span>下面是你访谈里说过的原话，可以直接确认，也可以重新分析一次。</span>
        <button class="summary-retry" type="button" :disabled="isReanalyzing" @click="reanalyze">
          {{ isReanalyzing ? '正在重新分析…' : '重新分析' }}
        </button>
      </div>
      <p v-if="reanalyzeError" class="summary-error" role="alert">{{ reanalyzeError }}</p>

      <div class="summary-output" aria-live="polite" @click="finishStreaming">
        <span>{{ streamedText }}</span><span v-if="!isComplete" class="summary-caret" aria-hidden="true"></span>
      </div>

      <div class="summary-actions">
        <button class="summary-edit" type="button" @click="router.push('/learnmate-chat')">重新访谈</button>
        <button class="summary-confirm" type="button" :disabled="!isComplete" @click="confirmProfile">
          <span>确认画像</span>
          <span aria-hidden="true">↗</span>
        </button>
      </div>
      <p class="summary-status">确认后先做一次能力诊断，再根据诊断结果生成你的学习路径。</p>
    </section>
  </main>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { learningState, persistLearningProfile } from '@/entities/learning/learningState'
import { initPortraitFromDialogue } from '@/shared/api/portraitApi'

// 每次 tick 出 2 个字，约 22ms 一轮 —— 十几秒的等待压到 3 秒左右。
const STREAM_INTERVAL_MS = 22

const router = useRouter()
const streamedText = ref('')
const isComplete = ref(false)
const isReanalyzing = ref(false)
const reanalyzeError = ref('')
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

// 分析结果要能重来，所以做成 ref 而不是一次性的常量。
const portraitSummary = ref(readPortraitSummary())

const aiSummary = computed(() => String(portraitSummary.value.profile_summary || '').trim())
// 后端 prompt 要求 profile_summary 为 60~140 字。缺失就说明这次分析没成功，
// 必须显式说出来：否则页面会静默回退成原始回答，看着却像一份正经画像。
const analysisMissing = computed(() => !aiSummary.value)
const introText = computed(() => analysisMissing.value
  ? '画像分析这次没有完成，以下是你在访谈中的原始回答。'
  : '我已经把刚才的对话整理成了一份画像，请确认内容是否准确。')
const cognition = computed(() => String(portraitSummary.value.cognition || '').trim())
const learningGoal = computed(() => String(portraitSummary.value.learning_goal || '').trim())
const traits = computed(() =>
  portraitSummary.value.traits && typeof portraitSummary.value.traits === 'object' ? portraitSummary.value.traits : {}
)
const onboarding = computed(() =>
  traits.value.onboarding && typeof traits.value.onboarding === 'object' ? traits.value.onboarding : {}
)
const traitText = key => {
  const value = traits.value[key]
  if (!value) return ''
  if (typeof value === 'string') return value
  return String(value.value || value.text || '').trim()
}
const direction = computed(() => String(onboarding.value.direction || cognition.value || answerAt(0)).trim())
const goal = computed(() => String(onboarding.value.goal || learningGoal.value || answerAt(1)).trim())

const fullSummary = computed(() => [
  aiSummary.value || '画像分析没有完成，以下是你在访谈中的原始回答：',
  '',
  `身份：${identity}`,
  `学习方向：${direction.value}`,
  `学习目标：${goal.value}`,
  `当前基础：${traitText('knowbase') || answerAt(2)}`,
  // 第 4、5 问按后端访谈 prompt 依次是「技能缺口」和「练习条件」。原来标成
  // 「每周可投入时间」「学习偏好」，一旦走兜底就会把答案挂到完全对不上的标签下。
  `当前卡点：${traitText('commonmis') || answerAt(3)}`,
  `练习安排：${traitText('learning_pace') || answerAt(4)}`,
  '',
  '以上内容准确吗？确认后先做一次能力诊断，再为你生成学习路径。'
].join('\n'))

const startStreaming = () => {
  // 重新分析会再调一次，先撤掉上一轮的计时器，否则两路打字机会互相打架。
  if (streamTimer) window.clearTimeout(streamTimer)
  let cursor = 0
  streamedText.value = ''
  isComplete.value = false
  const tick = () => {
    const nextCursor = Math.min(cursor + 2, fullSummary.value.length)
    streamedText.value = fullSummary.value.slice(0, nextCursor)
    cursor = nextCursor
    if (cursor >= fullSummary.value.length) {
      isComplete.value = true
      return
    }
    streamTimer = window.setTimeout(tick, STREAM_INTERVAL_MS)
  }
  tick()
}

// 确认画像在打完之前是 disabled 的，整段十几秒会让用户干等。点一下直接看全文，
// 保留了「先读再确认」的意图，但不强制等动画。
const finishStreaming = () => {
  if (isComplete.value) return
  if (streamTimer) window.clearTimeout(streamTimer)
  streamedText.value = fullSummary.value
  isComplete.value = true
}

// 分析失败时让用户能重来一次，而不是只能带着一份原始回答往下走。访谈内容还在
// sessionStorage 里，所以重试不用重新问 5 遍。
const reanalyze = async () => {
  if (isReanalyzing.value) return
  isReanalyzing.value = true
  reanalyzeError.value = ''
  try {
    const data = await initPortraitFromDialogue({
      dialogue,
      identity,
      direction: direction.value,
      goal: goal.value,
    })
    if (!data || typeof data !== 'object' || !String(data.profile_summary || '').trim()) {
      throw new Error('这次仍然没有分析出画像，请稍后再试。')
    }
    portraitSummary.value = data
    sessionStorage.setItem('learnmate_portrait_summary', JSON.stringify(data))
    startStreaming()
  } catch (error) {
    reanalyzeError.value = error?.response?.data?.detail || error?.message || '重新分析失败，请稍后重试。'
  } finally {
    isReanalyzing.value = false
  }
}

const confirmProfile = () => {
  if (!isComplete.value) return

  learningState.identity = identity
  learningState.direction = direction.value
  learningState.goal = goal.value
  persistLearningProfile()

  localStorage.setItem('learnmate_onboarding_complete', '1')
  const profile = { identity, direction: direction.value, goal: goal.value, dialogue }
  sessionStorage.removeItem('learnmate_portrait_dialogue')
  sessionStorage.removeItem('learnmate_portrait_summary')
  window.dispatchEvent(new CustomEvent('learnmate:learning-profile-ready', { detail: profile }))
  // 这一步只交接，不生成。学习路径由能力诊断答完后生成（后端
  // _generate_paths_after_diagnosis），在这里先生成会让资源在诊断之前就开始产出。
  // 标记留到诊断答完才清除，中途关掉标签页的用户下次进来仍会被送回诊断。
  localStorage.setItem('learnmate_diagnosis_pending', '1')
  router.push('/onboarding/diagnosis')
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
  cursor: pointer;
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

.summary-notice {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 12px;
  margin: 18px 0 0;
  padding: 14px 18px;
  border: 1px solid rgba(255, 181, 168, 0.42);
  border-radius: 14px;
  background: rgba(255, 181, 168, 0.1);
  color: #ffd9d0;
  font-size: 13px;
  line-height: 1.6;
}

.summary-retry {
  flex: 0 0 auto;
  min-height: 34px;
  padding: 0 16px;
  border: 1px solid rgba(255, 181, 168, 0.5);
  border-radius: 999px;
  background: transparent;
  color: #ffd9d0;
  font-size: 12px;
  font-weight: 800;
  cursor: pointer;
  transition: background 0.25s ease, color 0.25s ease;
}

.summary-retry:hover:not(:disabled) {
  background: rgba(255, 181, 168, 0.18);
}

.summary-retry:disabled {
  cursor: wait;
  opacity: 0.6;
}

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
