<template>
  <section class="chapter-check surface" aria-live="polite">
    <header class="check-header">
      <button class="icon-button" type="button" title="返回正文" aria-label="返回正文" @click="$emit('close')">
        <ArrowLeft :size="18" />
      </button>
      <div>
        <p class="eyebrow">本章检查</p>
        <h2>{{ chapterTitle }}</h2>
      </div>
      <span v-if="questions.length && !result" class="check-count">{{ currentIndex + 1 }} / {{ questions.length }}</span>
    </header>

    <div v-if="isLoading" class="check-state">
      <LoaderCircle class="spin" :size="25" />
      <strong>{{ loadingMessage }}</strong>
      <p>检查题会围绕本章节点生成，完成后才能解锁下一章。</p>
    </div>

    <div v-else-if="errorMessage" class="check-state check-state--error">
      <CircleAlert :size="25" />
      <strong>本章检查暂时不可用</strong>
      <p>{{ errorMessage }}</p>
      <button class="button button--quiet" type="button" @click="loadQuiz">重新加载</button>
    </div>

    <div v-else-if="result" class="result-state">
      <span class="result-mark" :class="{ 'is-passed': result.passed }">
        <CircleCheck v-if="result.passed" :size="30" />
        <RotateCcw v-else :size="27" />
      </span>
      <p class="eyebrow">{{ result.passed ? '本章已完成' : '还需要再巩固' }}</p>
      <h2>{{ result.score }} 分</h2>
      <p>{{ result.passed ? '你的理解已经达到本章要求，下一章现已解锁。' : `本章通过线为 ${passScore} 分。回到正文梳理薄弱点后，可以重新作答。` }}</p>
      <div class="result-actions">
        <button v-if="!result.passed" class="button button--quiet" type="button" @click="retryQuiz">重新作答</button>
        <button class="button button--primary" type="button" @click="finishResult">{{ result.passed ? '进入下一章' : '返回正文' }}</button>
      </div>
    </div>

    <div v-else-if="currentQuestion" class="question-panel">
      <div class="question-progress progress-track"><div class="progress-value" :style="{ width: `${questionProgress}%` }"></div></div>
      <span class="question-type">{{ questionTypeLabel(currentQuestion.question_type) }}</span>
      <h2>{{ currentQuestion.content }}</h2>

      <div v-if="isChoiceQuestion(currentQuestion)" class="option-list">
        <label v-for="option in normalizedOptions(currentQuestion)" :key="option.value" class="option-item" :class="{ 'is-selected': isOptionSelected(currentQuestion, option.value) }">
          <input
            v-if="currentQuestion.question_type === 'multi_choice'"
            v-model="answers[currentQuestion.question_id]"
            type="checkbox"
            :value="option.value"
          />
          <input v-else v-model="answers[currentQuestion.question_id]" type="radio" :value="option.value" />
          <span class="option-key">{{ option.key }}</span>
          <span>{{ option.label }}</span>
        </label>
      </div>

      <label v-else class="text-answer">
        <span>你的回答</span>
        <textarea v-model="answers[currentQuestion.question_id]" rows="5" maxlength="800" placeholder="用自己的话写下答案…"></textarea>
      </label>

      <footer class="question-actions">
        <button class="button button--quiet" type="button" :disabled="currentIndex === 0" @click="currentIndex -= 1">上一题</button>
        <button v-if="currentIndex < questions.length - 1" class="button button--primary" type="button" :disabled="!hasCurrentAnswer" @click="currentIndex += 1">下一题</button>
        <button v-else class="button button--primary" type="button" :disabled="!allAnswered || isSubmitting" @click="submitQuiz">
          {{ isSubmitting ? '正在评分…' : '提交本章检查' }}
        </button>
      </footer>
    </div>
  </section>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { ArrowLeft, CircleAlert, CircleCheck, LoaderCircle, RotateCcw } from 'lucide-vue-next'
import { fundamentalsApi } from '@/shared/api/fundamentalsApi'

const props = defineProps({
  pathId: { type: [Number, String], required: true },
  nodeId: { type: [Number, String], required: true },
  sessionId: { type: String, default: '' },
  chapterTitle: { type: String, default: '' },
  quizConfig: { type: Object, default: () => ({}) },
})

const emit = defineEmits(['close', 'passed'])
const answers = reactive({})
const questions = ref([])
const currentIndex = ref(0)
const isLoading = ref(true)
const isSubmitting = ref(false)
const loadingMessage = ref('正在准备本章检查')
const errorMessage = ref('')
const result = ref(null)
const activeSessionId = ref(props.sessionId || '')
let requestController = null

const currentQuestion = computed(() => questions.value[currentIndex.value] || null)
const questionProgress = computed(() => questions.value.length ? Math.round((currentIndex.value + 1) / questions.value.length * 100) : 0)
const passScore = computed(() => Math.round(Number(props.quizConfig?.threshold ?? 0.7) * 100))
const hasCurrentAnswer = computed(() => hasAnswer(currentQuestion.value))
const allAnswered = computed(() => questions.value.length > 0 && questions.value.every(hasAnswer))

function hasAnswer(question) {
  if (!question) return false
  const answer = answers[question.question_id]
  return Array.isArray(answer) ? answer.length > 0 : Boolean(String(answer || '').trim())
}

function questionTypeLabel(type) {
  return ({ single_choice: '单选题', multi_choice: '多选题', true_false: '判断题', fill_blank: '填空题' })[type] || '理解题'
}

function isChoiceQuestion(question) {
  return ['single_choice', 'multi_choice', 'true_false'].includes(question.question_type)
}

function normalizedOptions(question) {
  const fallback = question.question_type === 'true_false' ? ['正确', '错误'] : []
  const options = Array.isArray(question.options) && question.options.length
    ? question.options
    : question.options && typeof question.options === 'object'
      ? Object.entries(question.options).map(([key, label]) => ({ key, value: key, label }))
      : fallback
  return options.map((option, index) => {
    const key = String.fromCharCode(65 + index)
    if (option && typeof option === 'object') {
      return { key, value: String(option.value || option.key || key).toUpperCase(), label: option.label || option.text || String(option.value || '') }
    }
    const text = String(option)
    const match = text.match(/^\s*([A-F])[).、]\s*(.*)$/i)
    return { key: match?.[1]?.toUpperCase() || key, value: match?.[1]?.toUpperCase() || key, label: match?.[2] || text }
  })
}

function isOptionSelected(question, value) {
  const answer = answers[question.question_id]
  return Array.isArray(answer) ? answer.includes(value) : answer === value
}

function prepareAnswers() {
  questions.value.forEach((question) => {
    if (answers[question.question_id] === undefined) {
      answers[question.question_id] = question.question_type === 'multi_choice' ? [] : ''
    }
  })
}

async function loadQuiz() {
  requestController?.abort()
  requestController = new AbortController()
  isLoading.value = true
  errorMessage.value = ''
  result.value = null
  currentIndex.value = 0

  try {
    if (!activeSessionId.value) {
      await fundamentalsApi.generateQuiz(props.pathId, props.nodeId, (event) => {
        if (event?.type === 'status') loadingMessage.value = event.msg || event.message || loadingMessage.value
        if (event?.type === 'blocked') throw new Error(event.reason || '请先完成本章阅读')
        if (event?.type === 'error') throw new Error(event.detail || event.message || '检查题生成失败')
        if (event?.type === 'done' && event.session_id) activeSessionId.value = event.session_id
      }, requestController.signal)
    }

    if (!activeSessionId.value) throw new Error('检查题生成完成，但没有返回有效会话')
    const session = await fundamentalsApi.getQuizSession(activeSessionId.value)
    questions.value = (session?.records || []).map((record) => record.question).filter(Boolean)
    if (!questions.value.length) throw new Error('本章暂时没有可用的检查题')
    prepareAnswers()
  } catch (error) {
    if (error.name !== 'AbortError') errorMessage.value = error.response?.data?.detail || error.message || '本章检查加载失败'
  } finally {
    isLoading.value = false
  }
}

async function submitQuiz() {
  if (!allAnswered.value || isSubmitting.value) return
  isSubmitting.value = true
  errorMessage.value = ''
  try {
    result.value = await fundamentalsApi.completeNode(props.nodeId, activeSessionId.value, { ...answers })
  } catch (error) {
    errorMessage.value = error.response?.data?.detail || error.message || '提交失败，请稍后重试。'
  } finally {
    isSubmitting.value = false
  }
}

function retryQuiz() {
  Object.keys(answers).forEach((key) => {
    answers[key] = questions.value.find((question) => String(question.question_id) === String(key))?.question_type === 'multi_choice' ? [] : ''
  })
  currentIndex.value = 0
  result.value = null
}

function finishResult() {
  if (result.value?.passed) emit('passed', result.value)
  else emit('close')
}

onMounted(loadQuiz)
onBeforeUnmount(() => requestController?.abort())
</script>

<style scoped>
.chapter-check { min-height: 680px; overflow: hidden; }
.check-header { display: grid; grid-template-columns: 36px minmax(0, 1fr) auto; align-items: center; gap: 14px; padding: 20px 24px; border-bottom: 1px solid var(--line); background: #fbfcfa; }
.check-header .eyebrow { margin-bottom: 5px; }
.check-header h2 { margin: 0; overflow: hidden; font-size: 16px; text-overflow: ellipsis; white-space: nowrap; }
.check-count { color: var(--muted); font-size: 11px; }
.icon-button { display: grid; width: 34px; height: 34px; place-items: center; border: 1px solid var(--line); border-radius: 5px; background: var(--paper); color: var(--ink); }
.icon-button:hover { background: var(--soft); }
.check-state, .result-state { display: grid; min-height: 570px; place-items: center; align-content: center; gap: 10px; padding: 42px; text-align: center; }
.check-state { color: var(--accent-deep); }
.check-state strong { color: var(--ink); font-size: 16px; }
.check-state p, .result-state > p:last-of-type { max-width: 430px; margin: 0; color: var(--muted); font-size: 12px; line-height: 1.7; }
.check-state--error { color: #a66442; }
.check-state .button { margin-top: 8px; }
.question-panel { max-width: 760px; margin: 0 auto; padding: 42px clamp(24px, 5vw, 54px) 48px; }
.question-progress { height: 5px; margin-bottom: 30px; }
.question-type { color: var(--accent-deep); font-size: 11px; font-weight: 800; }
.question-panel h2 { margin: 10px 0 28px; font-size: clamp(20px, 2.5vw, 27px); line-height: 1.5; }
.option-list { display: grid; gap: 10px; }
.option-item { display: grid; grid-template-columns: 18px 27px minmax(0, 1fr); min-height: 58px; align-items: center; gap: 10px; padding: 11px 14px; border: 1px solid var(--line); border-radius: 6px; background: #fff; cursor: pointer; font-size: 13px; line-height: 1.55; }
.option-item:hover { border-color: #b9c9b2; background: #fbfcfa; }
.option-item.is-selected { border-color: #789267; background: #f1f6eb; }
.option-item input { accent-color: var(--accent-deep); }
.option-key { display: grid; width: 25px; height: 25px; place-items: center; border-radius: 50%; background: var(--soft); color: var(--accent-deep); font-size: 10px; font-weight: 900; }
.text-answer { display: grid; gap: 9px; color: var(--muted); font-size: 11px; }
.text-answer textarea { width: 100%; min-height: 150px; resize: vertical; padding: 13px 14px; border: 1px solid var(--line); border-radius: 6px; color: var(--ink); outline: none; font-size: 13px; line-height: 1.65; }
.text-answer textarea:focus { border-color: var(--accent-deep); }
.question-actions { display: flex; justify-content: space-between; gap: 10px; margin-top: 32px; padding-top: 22px; border-top: 1px solid var(--line); }
.result-mark { display: grid; width: 62px; height: 62px; place-items: center; border-radius: 50%; background: #f1e6dc; color: #a66442; }
.result-mark.is-passed { background: #e8f2de; color: var(--accent-deep); }
.result-state .eyebrow { margin: 8px 0 0; }
.result-state h2 { margin: 0; font-size: 42px; }
.result-actions { display: flex; gap: 9px; margin-top: 16px; }
.spin { animation: spin .8s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
@media (max-width: 560px) { .question-panel { padding: 30px 18px 38px; }.question-actions { align-items: stretch; flex-direction: column-reverse; }.question-actions .button { width: 100%; }.check-header { padding: 16px; } }
</style>
