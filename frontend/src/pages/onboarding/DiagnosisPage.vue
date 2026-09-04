<template>
  <div class="onboarding-page">
    <PageTitle eyebrow="能力诊断" title="和知伴聊聊你的起点" description="系统会围绕你的学习方向逐步提问，回答会用于调整后续讲解深度和练习难度。" />
    <section class="surface diagnosis-card" aria-live="polite">
      <div class="diagnosis-meta">
        <span>{{ isFinished ? '诊断完成' : `第 ${Math.min(answeredCount + 1, totalQuestions)} / ${totalQuestions} 题` }}</span>
        <div class="progress-track"><div class="progress-value" :style="{ width: `${progress}%` }"></div></div>
      </div>

      <div class="conversation-list">
        <div v-for="(message, index) in messages" :key="`${message.role}-${index}`" class="chat-message" :class="`chat-message--${message.role}`">
          <span v-if="message.role === 'assistant'" class="message-avatar">知</span>
          <p>{{ message.text }}</p>
        </div>
        <div v-if="isLoading" class="chat-message chat-message--assistant"><span class="message-avatar">知</span><p class="typing">正在分析你的回答<span>·</span><span>·</span><span>·</span></p></div>
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
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import PageTitle from '@/shared/ui/PageTitle.vue'
import { diagnosisApi } from '@/shared/api/diagnosisApi'
import { learningState } from '@/entities/learning/learningState'

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
  messages.value = [{ role: 'assistant', text: '我会根据你的学习方向，从基础理解开始了解你的起点。每次只回答一个问题即可。' }]
  try {
    const result = await diagnosisApi.start({ ...context.value, max_steps: totalQuestions })
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
  errorMessage.value = ''
  try {
    const result = await diagnosisApi.answer({
      session_id: sessionId.value,
      question_id: currentQuestion.value.question_id,
      answer: selectedAnswer.value,
      max_steps: totalQuestions,
    })
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

onMounted(startDiagnosis)
</script>

<style scoped>
.onboarding-page { max-width: 820px; margin: 0 auto; }
.diagnosis-card { overflow: hidden; padding: 0; }
.diagnosis-meta { display: flex; align-items: center; gap: 14px; padding: 22px 28px; border-bottom: 1px solid var(--line); color: var(--muted); font-size: 12px; }
.diagnosis-meta .progress-track { flex: 1; }
.conversation-list { display: grid; gap: 18px; min-height: 390px; max-height: 52vh; overflow-y: auto; padding: 28px; }
.chat-message { display: flex; align-items: flex-start; gap: 10px; max-width: 84%; }
.chat-message p { margin: 0; padding: 12px 14px; border-radius: 8px; font-size: 14px; line-height: 1.7; white-space: pre-wrap; }
.chat-message--assistant p { background: var(--soft); color: var(--ink); }
.chat-message--user { align-self: flex-end; justify-content: flex-end; }
.chat-message--user p { background: var(--ink); color: #fff; }
.message-avatar { display: grid; flex: 0 0 auto; width: 27px; height: 27px; place-items: center; border-radius: 50%; background: var(--accent); color: var(--accent-deep); font-size: 11px; font-weight: 900; }
.typing { color: var(--muted) !important; }.typing span { display: inline-block; animation: blink 1.1s infinite; }.typing span:nth-child(2) { animation-delay: .15s; }.typing span:nth-child(3) { animation-delay: .3s; }
.answer-panel { padding: 20px 28px 28px; border-top: 1px solid var(--line); }.answer-label { margin: 0 0 13px; color: var(--muted); font-size: 12px; }.answer-list { display: grid; gap: 10px; }.answer-option { display: flex; align-items: center; gap: 12px; min-height: 52px; padding: 0 15px; border: 1px solid var(--line); border-radius: 5px; background: var(--paper); color: var(--ink); text-align: left; font-size: 13px; }.answer-option:hover, .answer-option.selected { border-color: var(--accent-deep); background: #f8fbf2; }.answer-option:disabled { cursor: wait; opacity: .65; }.answer-dot { width: 13px; height: 13px; border: 1px solid #aeb8ad; border-radius: 50%; }.selected .answer-dot { border: 4px solid var(--accent-deep); }.diagnosis-actions { display: flex; justify-content: flex-end; margin-top: 22px; }.diagnosis-error { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 14px 28px; border-top: 1px solid var(--line); color: #a66b47; font-size: 12px; }.diagnosis-error .button { flex: 0 0 auto; }
@keyframes blink { 0%, 60%, 100% { opacity: .25; } 30% { opacity: 1; } }
@media (max-width: 600px) { .conversation-list { min-height: 330px; padding: 20px 16px; }.chat-message { max-width: 94%; }.diagnosis-meta, .answer-panel, .diagnosis-error { padding-left: 16px; padding-right: 16px; }.diagnosis-error { align-items: flex-start; flex-direction: column; } }
</style>
