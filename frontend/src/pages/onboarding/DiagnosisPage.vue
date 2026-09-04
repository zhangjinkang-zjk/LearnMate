<template>
  <main class="diagnosis-page">
    <ImmersiveOnboardingBackdrop />
    <RouterLink class="back-link" to="/onboarding/direction"><span aria-hidden="true">←</span><span>BACK</span></RouterLink>
    <header class="diagnosis-heading"><p class="eyebrow">能力诊断 · 学习起点</p><h1>和 LearnMate 聊聊你的起点</h1><p>系统会围绕你的学习方向逐步提问，回答会用于调整后续讲解深度和练习难度。</p></header>
    <section class="surface diagnosis-card" aria-live="polite">
      <div class="diagnosis-meta">
        <span>{{ isFinished ? '诊断完成' : `第 ${Math.min(answeredCount + 1, totalQuestions)} / ${totalQuestions} 题` }}</span>
        <div class="progress-track"><div class="progress-value" :style="{ width: `${progress}%` }"></div></div>
      </div>

      <div class="conversation-list">
        <div v-for="(message, index) in messages" :key="`${message.role}-${index}`" class="chat-message" :class="`chat-message--${message.role}`">
          <span v-if="message.role === 'assistant'" class="message-avatar">LM</span>
          <p>{{ message.text }}</p>
        </div>
        <div v-if="isLoading" class="chat-message chat-message--assistant"><span class="message-avatar">LM</span><p class="typing">{{ loadingMessage }}<span>·</span><span>·</span><span>·</span></p></div>
      </div>

      <div v-if="currentQuestion && !isFinished" class="answer-panel">
        <p class="answer-label">选择最符合你当前理解的一项</p>
        <div class="answer-list">
          <button v-for="(option, optionIndex) in currentQuestion.options" :key="option" class="answer-option" :class="{ selected: selectedAnswer === answerKey(option, optionIndex) }" type="button" :disabled="isLoading" @click="selectedAnswer = answerKey(option, optionIndex)">
            <span class="answer-dot"></span>{{ option }}
          </button>
        </div>
        <div class="diagnosis-actions"><button class="button button--primary" type="button" :disabled="!selectedAnswer || isLoading" @click="submitAnswer">提交回答 <span>→</span></button></div>
      </div>

      <div v-if="errorMessage" class="diagnosis-error"><span>{{ errorMessage }}</span><button class="button button--quiet" type="button" @click="startDiagnosis">重试</button></div>
    </section>
  </main>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { diagnosisApi } from '@/shared/api/diagnosisApi'
import { learningState } from '@/entities/learning/learningState'
import ImmersiveOnboardingBackdrop from '@/shared/ui/ImmersiveOnboardingBackdrop.vue'

const router = useRouter()
const totalQuestions = 3
const isLoading = ref(false)
const isFinished = ref(false)
const errorMessage = ref('')
const answeredCount = ref(0)
const selectedAnswer = ref('')
const currentQuestion = ref(null)
const messages = ref([])
const sessionId = ref('')
const loadingMessage = ref('正在分析你的回答')

const progress = computed(() => isFinished.value ? 100 : Math.round((answeredCount.value / totalQuestions) * 100))
const context = computed(() => ({
  identity: learningState.identity || localStorage.getItem('learnmate_identity') || '',
  direction: learningState.direction || localStorage.getItem('learnmate_direction') || '',
  goal: learningState.goal || localStorage.getItem('learnmate_goal') || '',
}))

function answerKey(option, index = 0) {
  const match = String(option).match(/^\s*([A-D])(?:[.、)）]|\s)/i)
  return match ? match[1].toUpperCase() : String.fromCharCode(65 + index)
}

function questionText(question) {
  return question?.content || question?.title || ''
}

async function startDiagnosis() {
  isLoading.value = true
  isFinished.value = false
  errorMessage.value = ''
  answeredCount.value = 0
  selectedAnswer.value = ''
  currentQuestion.value = null
  loadingMessage.value = '正在根据你的学习方向生成第一道诊断题'
  messages.value = [{ role: 'assistant', text: '我会根据你的学习方向，从基础理解开始了解你的起点。每次只回答一个问题即可。' }]
  try {
    const result = await diagnosisApi.startStream({ ...context.value, max_steps: totalQuestions }, handleStreamEvent)
    sessionId.value = result.session_id
    currentQuestion.value = result.question
    messages.value.push({ role: 'assistant', text: questionText(result.question) })
  } catch (error) {
    errorMessage.value = error.response?.data?.detail || error.message || '暂时无法开始能力诊断，请检查网络后重试。'
  } finally {
    isLoading.value = false
  }
}

async function submitAnswer() {
  if (!selectedAnswer.value || !currentQuestion.value || isLoading.value) return
  const selectedOption = currentQuestion.value.options?.find((option, index) => answerKey(option, index) === selectedAnswer.value) || selectedAnswer.value
  messages.value.push({ role: 'user', text: selectedOption })
  isLoading.value = true
  loadingMessage.value = '正在结合你的回答调整下一道题'
  errorMessage.value = ''
  try {
    const result = await diagnosisApi.answerStream({
      session_id: sessionId.value,
      question_id: currentQuestion.value.question_id,
      answer: selectedAnswer.value,
      max_steps: totalQuestions,
    }, handleStreamEvent)
    answeredCount.value += 1
    const feedback = result.feedback || {}
    messages.value.push({ role: 'assistant', text: feedback.is_correct ? '这道题回答正确，我继续确认你在实际应用中的判断。' : (feedback.analysis || '这道题能看出你已经接触过相关概念，我们换一个角度继续确认。') })
    selectedAnswer.value = ''
    if (result.finished) {
      isFinished.value = true
      localStorage.setItem('learnmate_diagnosis_result', JSON.stringify(result.result || {}))
      messages.value.push({ role: 'assistant', text: result.result?.message || '诊断完成，我已经整理好你的学习起点。' })
      window.setTimeout(() => router.push('/onboarding/diagnosis/result'), 500)
    } else {
      currentQuestion.value = result.question
      messages.value.push({ role: 'assistant', text: questionText(result.question) })
    }
  } catch (error) {
    errorMessage.value = error.response?.data?.detail || error.message || '回答提交失败，请重试。'
    messages.value.pop()
  } finally {
    isLoading.value = false
  }
}

function handleStreamEvent(event) {
  if (event?.type === 'status' && event.message) loadingMessage.value = event.message
  if (event?.type === 'keepalive') loadingMessage.value = '仍在分析中，请稍候'
}

onMounted(startDiagnosis)
</script>

<style scoped>
@font-face { font-family: "Smiley Sans"; src: url("../../shared/assets/fonts/SmileySans-Oblique.woff2") format("woff2"); font-style: normal; font-display: swap; }
.diagnosis-page { position: relative; min-height: 100vh; overflow: hidden; isolation: isolate; padding: clamp(28px, 5vw, 64px) clamp(20px, 6vw, 90px) 56px; color: #f3f0e7; background: #1e3c34; }
.back-link { position: relative; z-index: 2; display: inline-flex; align-items: center; gap: 10px; color: rgba(243, 240, 231, .8); font-size: 11px; font-weight: 800; letter-spacing: .16em; text-decoration: none; }.back-link:hover { color: #e2f452; }.back-link span:first-child { font-size: 20px; line-height: .6; }
.diagnosis-heading { position: relative; z-index: 1; width: min(820px, 100%); margin: clamp(38px, 8vh, 86px) auto 26px; }.diagnosis-heading .eyebrow { color: #d9ed9a; }.diagnosis-heading h1 { margin: 0; color: #f3f0e7; font-family: "Smiley Sans", Georgia, serif; font-size: clamp(30px, 4.5vw, 52px); font-weight: 500; letter-spacing: .01em; line-height: 1.15; }.diagnosis-heading > p:last-child { max-width: 600px; margin: 14px 0 0; color: rgba(243, 240, 231, .72); font-size: 14px; line-height: 1.8; }
.diagnosis-card { position: relative; z-index: 1; width: min(820px, 100%); margin: 0 auto; overflow: hidden; padding: 0; border: 1px solid rgba(243, 240, 231, .22); border-radius: 8px; background: rgba(9, 29, 21, .72); box-shadow: 0 20px 55px rgba(2, 15, 10, .22); }
.diagnosis-meta { display: flex; align-items: center; gap: 14px; padding: 22px 28px; border-bottom: 1px solid rgba(243, 240, 231, .16); color: rgba(243, 240, 231, .72); font-size: 12px; }
.diagnosis-meta .progress-track { flex: 1; }
.conversation-list { display: grid; gap: 18px; min-height: 390px; max-height: 52vh; overflow-y: auto; padding: 28px; }
.chat-message { display: flex; align-items: flex-start; gap: 10px; max-width: 84%; }
.chat-message p { margin: 0; padding: 12px 14px; border-radius: 8px; font-size: 14px; line-height: 1.7; white-space: pre-wrap; }
.chat-message--assistant p { background: rgba(232, 241, 224, .94); color: var(--ink); }
.chat-message--user { align-self: flex-end; justify-content: flex-end; }
.chat-message--user p { background: var(--ink); color: #fff; }
.message-avatar { display: grid; flex: 0 0 auto; width: 27px; height: 27px; place-items: center; border-radius: 50%; background: var(--accent); color: var(--accent-deep); font-size: 11px; font-weight: 900; }
.typing { color: var(--muted) !important; }.typing span { display: inline-block; animation: blink 1.1s infinite; }.typing span:nth-child(2) { animation-delay: .15s; }.typing span:nth-child(3) { animation-delay: .3s; }
.answer-panel { padding: 20px 28px 28px; border-top: 1px solid rgba(243, 240, 231, .16); }.answer-label { margin: 0 0 13px; color: rgba(243, 240, 231, .72); font-size: 12px; }.answer-list { display: grid; gap: 10px; }.answer-option { display: flex; align-items: center; gap: 12px; min-height: 52px; padding: 0 15px; border: 1px solid rgba(243, 240, 231, .22); border-radius: 5px; background: rgba(243, 240, 231, .08); color: #f3f0e7; text-align: left; font-size: 13px; }.answer-option:hover, .answer-option.selected { border-color: #e2f452; background: rgba(226, 244, 82, .16); }.answer-option:disabled { cursor: wait; opacity: .65; }.answer-dot { width: 13px; height: 13px; border: 1px solid rgba(243, 240, 231, .68); border-radius: 50%; }.selected .answer-dot { border: 4px solid #e2f452; }.diagnosis-actions { display: flex; justify-content: flex-end; margin-top: 22px; }.diagnosis-actions .button--primary { background: #e2f452; color: #1e3c34; }.diagnosis-error { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 14px 28px; border-top: 1px solid rgba(243, 240, 231, .16); color: #f2c49b; font-size: 12px; }.diagnosis-error .button--quiet { border-color: rgba(243, 240, 231, .3); background: transparent; color: #f3f0e7; }.diagnosis-error .button { flex: 0 0 auto; }
@keyframes blink { 0%, 60%, 100% { opacity: .25; } 30% { opacity: 1; } }
@media (max-width: 600px) { .conversation-list { min-height: 330px; padding: 20px 16px; }.chat-message { max-width: 94%; }.diagnosis-meta, .answer-panel, .diagnosis-error { padding-left: 16px; padding-right: 16px; }.diagnosis-error { align-items: flex-start; flex-direction: column; } }
</style>
