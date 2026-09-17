<template>
  <main class="diagnosis-page">
    <ImmersiveOnboardingBackdrop />

    <RouterLink class="diagnosis-back" to="/onboarding/direction">
      <span aria-hidden="true">←</span>
      <span>BACK</span>
    </RouterLink>
    <p class="diagnosis-progress">{{ isFinished ? '诊断完成' : `第 ${Math.min(answeredCount + 1, totalQuestions)} / ${totalQuestions} 题` }}</p>

    <section class="conversation-shell" aria-label="能力诊断">
      <div class="conversation-track">
        <div class="conversation-list" role="log" aria-live="polite">
          <div v-for="(message, index) in messages" :key="`${message.role}-${index}`" class="chat-message" :class="`chat-message--${message.role}`">
            {{ message.text }}
          </div>
          <div v-if="isLoading" class="chat-message chat-message--assistant chat-message--typing">...</div>
        </div>

        <form v-if="currentQuestion && !isFinished" class="conversation-input" @submit.prevent="submitAnswer">
          <input
            v-model="answerDraft"
            type="text"
            autocomplete="off"
            maxlength="2000"
            :disabled="isLoading"
            placeholder="用你自己的话回答，想到什么先说什么…"
            aria-label="回答诊断问题"
          />
          <button type="submit" :disabled="!canSubmit || isLoading" aria-label="发送回答">
            <span aria-hidden="true">↗</span>
          </button>
        </form>
      </div>
    </section>

    <p v-if="isLoading" class="conversation-status" role="status">
      <span>{{ loadingMessage }}</span>
      <!-- 前 3 秒不显示：一闪而过的秒数只是噪音。之后它替用户回答"是不是卡住了"。 -->
      <span v-if="elapsedSeconds >= 3" class="conversation-status__elapsed">已等待 {{ elapsedSeconds }} 秒</span>
    </p>
    <p v-else-if="errorMessage" class="conversation-status conversation-status--error" role="alert">
      <span>{{ errorMessage }}</span>
      <button class="diagnosis-retry" type="button" @click="retryFailedStep">重试</button>
    </p>
  </main>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { diagnosisApi } from '@/shared/api/diagnosisApi'
import { applyWorkflowEvent, finishWorkflow, resetWorkflow } from '@/entities/agent/agentWorkflowState'
import { learningState } from '@/entities/learning/learningState'
import ImmersiveOnboardingBackdrop from '@/shared/ui/ImmersiveOnboardingBackdrop.vue'

const router = useRouter()
// 5 题：后端 _MAX_QUESTIONS 就是 5，之前这里写死 3，白白少问了两题。
const totalQuestions = 5
const isLoading = ref(false)
const isFinished = ref(false)
const errorMessage = ref('')
const answeredCount = ref(0)
const answerDraft = ref('')
// 失败的是哪一步，决定"重试"要重发什么：整个诊断重开会把已经答完的题丢掉。
const failedStep = ref('start')
const currentQuestion = ref(null)
const messages = ref([])
const sessionId = ref('')
const loadingMessage = ref('正在分析你的回答')

// 模型是边写边推的（SSE 的 reply_delta）：一轮里有两段 —— 先判分那句回复，再下一题。
// 每来一段就往对应气泡里追加，所以第一个字一出现就顶掉了"正在等一整段返回"。
// 值是气泡在 messages 里的下标，收到最终结果时按它把那句话改成服务端认定的版本。
const liveBubbles = ref({})

function appendDelta(channel, text) {
  const key = channel === 'question' ? 'question' : 'reply'
  if (!text) return
  const index = liveBubbles.value[key]
  if (index === undefined || index >= messages.value.length) {
    messages.value.push({ role: 'assistant', text: '' })
    liveBubbles.value[key] = messages.value.length - 1
    messages.value[liveBubbles.value[key]].text = text
    return
  }
  messages.value[index].text = (messages.value[index].text || '') + text
}

// 结果里的那句话是权威版本：流式那段可能被超时截断，或者模型没按格式写。
function setChannelText(channel, text) {
  const index = liveBubbles.value[channel]
  if (index !== undefined && index < messages.value.length) {
    messages.value[index].text = text
    return
  }
  messages.value.push({ role: 'assistant', text })
  liveBubbles.value[channel] = messages.value.length - 1
}

// 出题要等模型，实测同一个提示词 9 秒到 156 秒不等（供应商那边负载波动），等待本身
// 去不掉。这里只把等待变可见 —— 不画进度条：进度是编的，秒数是真的。
const elapsedSeconds = ref(0)
let elapsedTimer = null

function startWaiting() {
  stopWaiting()
  const startedAt = Date.now()
  elapsedSeconds.value = 0
  elapsedTimer = window.setInterval(() => {
    elapsedSeconds.value = Math.floor((Date.now() - startedAt) / 1000)
  }, 1000)
}

function stopWaiting() {
  if (elapsedTimer !== null) {
    window.clearInterval(elapsedTimer)
    elapsedTimer = null
  }
}

const canSubmit = computed(() => Boolean(answerDraft.value.trim()))
const context = computed(() => ({
  identity: learningState.identity || localStorage.getItem('learnmate_identity') || '',
  direction: learningState.direction || localStorage.getItem('learnmate_direction') || '',
  goal: learningState.goal || localStorage.getItem('learnmate_goal') || '',
}))

// /learning/diagnosis/start 要求身份、学习方向、学习目标都非空。方向/目标是画像访谈
// 问出来再写回本地的（DirectionSetupPage 那一步只强制身份），所以正常走完访谈这里
// 一定有值；万一没有（直接打开这个地址、或本地存储被清过），就在本地拦住。
const missingContext = computed(() => [
  !context.value.identity && '身份',
  !context.value.direction && '学习方向',
  !context.value.goal && '学习目标',
].filter(Boolean))

function questionText(question) {
  return question?.content || question?.title || ''
}

async function startDiagnosis() {
  isFinished.value = false
  answeredCount.value = 0
  answerDraft.value = ''
  currentQuestion.value = null
  errorMessage.value = ''
  messages.value = [{ role: 'assistant', text: '我会根据你的学习方向，从基础理解开始了解你的起点。每次只回答一个问题即可。' }]
  liveBubbles.value = {}
  // 诊断是独立的一条工作流（workflowKind='diagnosis'），阶段表只有"学情诊断"。
  resetWorkflow({ title: '学情诊断', workflowKind: 'diagnosis' })

  const missing = missingContext.value
  if (missing.length) {
    // 不发这个注定 422 的请求，也别让 Pydantic 的校验结构体画到页面上。
    isLoading.value = false
    errorMessage.value = `还缺少${missing.join('、')}，请返回上一步完成学习访谈后再开始诊断。`
    return
  }

  isLoading.value = true
  loadingMessage.value = '正在根据你的学习方向生成第一道诊断题'
  startWaiting()
  try {
    const result = await diagnosisApi.startStream({ ...context.value, max_steps: totalQuestions }, handleStreamEvent)
    sessionId.value = result.session_id
    currentQuestion.value = result.question
    // 第一题在流式里已经边写边显示了，这里只把最后那句定稿，不再多推一个气泡。
    setChannelText('question', questionText(result.question))
  } catch (error) {
    failedStep.value = 'start'
    errorMessage.value = error.response?.data?.detail || error.message || '暂时无法开始能力诊断，请检查网络后重试。'
    finishWorkflow(true)
  } finally {
    isLoading.value = false
    stopWaiting()
  }
}

function retryFailedStep() {
  if (failedStep.value === 'answer') return submitAnswer()
  return startDiagnosis()
}

async function submitAnswer() {
  const answer = answerDraft.value.trim()
  if (!answer || !currentQuestion.value || isLoading.value) return
  messages.value.push({ role: 'user', text: answer })
  liveBubbles.value = {}
  isLoading.value = true
  loadingMessage.value = '正在结合你的回答调整下一道题'
  startWaiting()
  errorMessage.value = ''
  try {
    const result = await diagnosisApi.answerStream({
      session_id: sessionId.value,
      question_id: currentQuestion.value.question_id,
      answer,
      max_steps: totalQuestions,
    }, handleStreamEvent)
    // 用服务端的进度而不是本地自增：重复提交时服务端会接着已经落库的作答往下走，
    // 自增会把题号算重。
    answeredCount.value = Number.isInteger(result.current_index)
      ? result.current_index
      : answeredCount.value + 1
    const feedback = result.feedback || {}
    // 服务端现在直接给一句平铺的 reply（它自己保证非空，真拿不到也会说"已记录你的回答"）。
    // 这句通常在流式里已经写出来了，这里是定稿（流被超时截断时也是它兜住），所以走
    // setChannelText 复用同一个气泡，而不是再多推一个。后面两个字段是旧响应的写法，
    // 留着兼容老版本后端。
    const reply = String(result.reply || feedback.feedback || feedback.analysis || '').trim()
    setChannelText('reply', reply || '已记录你的回答。')
    answerDraft.value = ''
    if (result.finished) {
      isFinished.value = true
      finishWorkflow(false)
      sessionStorage.setItem('learnmate_diagnosis_result', JSON.stringify(result.result || {}))
      messages.value.push({ role: 'assistant', text: result.result?.message || '正在生成诊断结果…' })
      window.setTimeout(() => router.push('/learnmate-summary'), 500)
    } else {
      currentQuestion.value = result.question
      setChannelText('question', questionText(result.question))
    }
  } catch (error) {
    // 重发的是同一题（answerDraft 没被清空），不是整轮重开：服务端会把已经落库的
    // 那次作答接着往下推，所以翻车之后仍然能从当前题继续，而不是被"该题已经提交过"钉死。
    failedStep.value = 'answer'
    errorMessage.value = error.response?.data?.detail || error.message || '回答提交失败，请重试。'
    messages.value.pop()
    // 弹掉气泡会让记住的下标全部错位，下一次追加就会写到别人身上。
    liveBubbles.value = {}
  } finally {
    isLoading.value = false
    stopWaiting()
  }
}

function handleStreamEvent(event) {
  // 同一条流同时喂给全局"智能体流程"抽屉，学情诊断才能作为协同闭环里的第一个
  // 角色被看见（写法与资料生成弹窗、学习路径页一致）。
  if (event?.type === 'agent_event') applyWorkflowEvent(event)
  if (event?.type === 'reply_delta') appendDelta(event.channel, String(event.text || ''))
  if (event?.type === 'status' && event.message) loadingMessage.value = event.message
  if (event?.type === 'keepalive') loadingMessage.value = '仍在分析中，请稍候'
}

onMounted(startDiagnosis)
// 切页/刷新时把计时器收掉，别让它挂在后台空转。
onUnmounted(stopWaiting)
</script>

<!-- 前景刻意与画像访谈页（LearnmateChatView）保持一致：全幅气泡 + 底部胶囊输入框，
     不用卡片/头像/进度条。背景由 ImmersiveOnboardingBackdrop 提供，和访谈页那套是同一份。 -->
<style scoped>
@font-face { font-family: "Smiley Sans"; src: url("../../shared/assets/fonts/SmileySans-Oblique.woff2") format("woff2"); font-style: normal; font-display: swap; }

.diagnosis-page {
  position: relative;
  min-height: 100vh;
  overflow: hidden;
  isolation: isolate;
  padding: clamp(28px, 5vw, 64px) clamp(20px, 6vw, 90px) 56px;
  color: #1e3c34;
  background: #1e3c34;
  font-family: Inter, "Helvetica Neue", Arial, sans-serif;
}

.diagnosis-back {
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
  transition: color 0.25s ease, transform 0.35s cubic-bezier(0.16, 1, 0.3, 1);
}

.diagnosis-back:hover {
  color: #e2f452;
  transform: translateX(-4px);
}

.diagnosis-back span:first-child {
  font-size: 20px;
  line-height: 0.6;
}

.diagnosis-progress {
  position: absolute;
  z-index: 2;
  top: clamp(28px, 5vw, 64px);
  right: clamp(20px, 6vw, 90px);
  margin: 0;
  color: rgba(243, 240, 231, 0.66);
  font-size: 11px;
  font-weight: 800;
  letter-spacing: 0.16em;
}

.conversation-shell {
  position: absolute;
  inset: 0;
  pointer-events: none;
}

.conversation-track {
  position: absolute;
  inset-block: 0;
  left: clamp(200px, 22vw, 460px);
  width: min(900px, 68vw);
}

.conversation-list {
  position: absolute;
  top: clamp(150px, 24vh, 260px);
  left: 0;
  display: grid;
  gap: 22px;
  width: 100%;
  max-height: 58vh;
  overflow-y: auto;
  padding: 2px clamp(32px, 5vw, 72px) 18px 0;
  box-sizing: border-box;
  pointer-events: auto;
  scrollbar-width: thin;
  scrollbar-color: rgba(226, 244, 82, 0.36) transparent;
}

.conversation-list::-webkit-scrollbar { width: 4px; }
.conversation-list::-webkit-scrollbar-track { background: transparent; }
.conversation-list::-webkit-scrollbar-thumb { border-radius: 2px; background: rgba(226, 244, 82, 0.36); }
.conversation-list::-webkit-scrollbar-thumb:hover { background: rgba(226, 244, 82, 0.58); }

.chat-message {
  width: fit-content;
  max-width: 88%;
  padding: 12px 15px;
  border-radius: 18px;
  font-size: 14px;
  line-height: 1.45;
  white-space: pre-line;
  animation: messageIn 0.45s cubic-bezier(0.16, 1, 0.3, 1) both;
}

.chat-message--typing {
  width: 58px;
  min-height: 42px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  box-sizing: border-box;
  letter-spacing: 0.22em;
  text-indent: 0.22em;
}

.chat-message--assistant {
  border-bottom-left-radius: 5px;
  background: rgba(243, 240, 231, 0.72);
  color: #1e3c34;
}

.chat-message--user {
  justify-self: end;
  border-bottom-right-radius: 5px;
  background: rgba(226, 244, 82, 0.78);
  color: #1e3c34;
  box-shadow: 0 14px 28px rgba(3, 20, 13, 0.2);
}

.conversation-input {
  position: absolute;
  bottom: clamp(24px, 5vh, 56px);
  left: 50%;
  display: flex;
  align-items: center;
  width: min(660px, 100%);
  padding: 7px 8px 7px 20px;
  box-sizing: border-box;
  border: 1px solid rgba(226, 244, 82, 0.48);
  border-radius: 999px;
  background: rgba(7, 26, 19, 0.84);
  box-shadow: 0 18px 38px rgba(2, 15, 10, 0.32), inset 0 1px 0 rgba(243, 240, 231, 0.08);
  transform: translateX(-50%);
  pointer-events: auto;
  backdrop-filter: blur(12px);
  transition: border-color 0.3s ease, box-shadow 0.4s ease;
}

.conversation-input:focus-within {
  border-color: #e2f452;
  box-shadow: 0 22px 46px rgba(2, 15, 10, 0.4), 0 0 0 4px rgba(226, 244, 82, 0.1);
}

.conversation-input input {
  min-width: 0;
  flex: 1;
  border: 0;
  outline: none;
  background: transparent;
  color: #f3f0e7;
  font: inherit;
  font-size: 14px;
}

.conversation-input input::placeholder {
  color: rgba(243, 240, 231, 0.48);
}

.conversation-input input:disabled {
  cursor: wait;
}

.conversation-input button {
  display: grid;
  place-items: center;
  flex: 0 0 42px;
  width: 42px;
  height: 42px;
  border: 0;
  border-radius: 50%;
  background: #e2f452;
  color: #1e3c34;
  font-size: 22px;
  line-height: 1;
  cursor: pointer;
  transition: transform 0.35s cubic-bezier(0.16, 1, 0.3, 1), background 0.25s ease, opacity 0.25s ease;
}

.conversation-input button:hover:not(:disabled) {
  background: #f0ff75;
  transform: scale(1.1) rotate(-4deg);
}

.conversation-input button:disabled {
  opacity: 0.36;
  cursor: not-allowed;
}

.conversation-status {
  position: absolute;
  z-index: 2;
  bottom: calc(clamp(24px, 5vh, 56px) + 62px);
  left: 50%;
  display: flex;
  align-items: center;
  gap: 12px;
  margin: 0;
  transform: translateX(-50%);
  color: rgba(243, 240, 231, 0.66);
  font-size: 12px;
  letter-spacing: 0.02em;
  pointer-events: none;
}

.conversation-status__elapsed {
  /* 等宽数字：秒数从 9 跳到 10 时宽度不变，提示文字不会左右抽动 */
  font-variant-numeric: tabular-nums;
  color: rgba(226, 244, 82, 0.75);
}

.conversation-status--error {
  color: #ffb5a8;
  pointer-events: auto;
}

.diagnosis-retry {
  flex: 0 0 auto;
  min-height: 30px;
  padding: 0 14px;
  border: 1px solid rgba(255, 181, 168, 0.5);
  border-radius: 999px;
  background: transparent;
  color: #ffb5a8;
  font-size: 11px;
  font-weight: 800;
  cursor: pointer;
  transition: background 0.25s ease;
}

.diagnosis-retry:hover {
  background: rgba(255, 181, 168, 0.16);
}

@keyframes messageIn {
  from { opacity: 0; transform: translateY(8px) scale(0.98); }
  to { opacity: 1; transform: translateY(0) scale(1); }
}

@media (max-width: 640px) {
  .diagnosis-page { padding: 26px 18px 34px; }
  .diagnosis-progress { top: 26px; right: 18px; }
  .conversation-track { left: 18px; width: calc(100% - 36px); }
  .conversation-list { top: 23%; max-height: 52vh; gap: 18px; padding-right: 0; }
  .conversation-input { bottom: 20px; padding-left: 15px; }
  .conversation-status { bottom: 84px; width: calc(100% - 36px); justify-content: center; text-align: center; }
}

@media (prefers-reduced-motion: reduce) {
  .chat-message { animation: none; }
}
</style>
