<template>
  <section class="practice-dialogue surface" aria-label="学习巩固对话">
    <header class="practice-dialogue__header">
      <div>
        <p class="eyebrow">学习巩固 · {{ task.kind_label || '实践任务' }}</p>
        <h2>先想清楚，再给方案</h2>
        <p>LearnMate 会根据你的回答追问证据、假设和取舍，不会直接替你完成任务。</p>
        <small class="practice-agent-note">本轮由学习助教 Agent 负责追问；任务生成与资源审核属于独立流程。</small>
      </div>
      <div class="phase-progress" aria-label="巩固阶段进度">
        <span class="phase-progress__count">{{ currentPhaseIndex + 1 }} / {{ phases.length }}</span>
        <strong>{{ currentPhase.label }}</strong>
        <div class="phase-progress__track"><span :style="{ width: `${phaseProgress}%` }"></span></div>
      </div>
    </header>

    <div v-if="isLoadingSession" class="practice-session-loading" role="status">正在恢复本次巩固会话…</div>
    <div v-else class="practice-dialogue__body">
      <div ref="messageList" class="practice-messages" aria-live="polite">
        <template v-for="(message, index) in messages" :key="`${message.role}-${index}`">
          <div v-if="message.text || message.role === 'user'" class="practice-message" :class="`is-${message.role}`">
            <span v-if="message.role === 'assistant'" class="practice-avatar">LM</span>
            <div class="practice-bubble" v-html="renderMarkdown(message.text)"></div>
          </div>
        </template>
        <div v-if="isStreaming" class="practice-message is-assistant">
          <span class="practice-avatar">LM</span>
          <div class="practice-bubble typing" aria-label="正在回复"><span></span><span></span><span></span></div>
        </div>
      </div>

      <aside class="practice-guide">
        <div class="guide-block"><p class="eyebrow">当前任务</p><strong>{{ task.title }}</strong><p>{{ task.problem }}</p></div>
        <div class="guide-block"><p class="eyebrow">阶段</p>
          <button v-for="(phase, index) in phases" :key="phase.id" type="button" :disabled="!isPhaseAvailable(index)" :class="{ 'is-active': phase.id === currentPhase.id, 'is-complete': isPhaseComplete(index) }" @click="selectPhase(phase)"><span class="phase-button__title"><span>{{ String(index + 1).padStart(2, '0') }}</span>{{ phase.label }}</span><small>{{ isPhaseComplete(index) ? '已完成' : phase.hint }}</small></button>
        </div>
        <div class="guide-block"><p class="eyebrow">需要留下</p><ul><li v-for="item in task.deliverables || []" :key="item.id">{{ item.label }}</li></ul></div>
      </aside>
    </div>

    <section v-if="evaluation" class="practice-evaluation" aria-live="polite">
      <div><p class="eyebrow">提交结果</p><strong>{{ evaluation.label }}</strong><p>{{ evaluation.passed ? '这次方案已经达到当前任务的验收线。' : '方案已经保存，下面是下一轮需要补强的地方。' }}</p></div>
      <strong class="practice-evaluation__score">{{ evaluation.score }}<small>分</small></strong>
      <ul><li v-for="item in evaluation.next_steps || []" :key="item">{{ item }}</li></ul>
    </section>
    <p v-if="errorMessage" class="practice-error" role="status">{{ errorMessage }}</p>
    <form v-if="!evaluation" class="practice-composer" @submit.prevent="sendMessage()">
      <label class="sr-only" for="practice-answer">你的方案思考</label>
      <textarea id="practice-answer" v-model="draft" rows="4" maxlength="1800" :disabled="isStreaming || isLoadingSession || isSubmitting" :placeholder="`围绕“${currentPhase.label}”写下你的判断…`" @keydown.ctrl.enter.prevent="sendMessage()" @keydown.meta.enter.prevent="sendMessage()"></textarea>
      <div class="practice-actions">
        <span>{{ draft.length }} / 1800</span>
        <div>
          <button class="button button--quiet" type="button" :disabled="isStreaming || isLoadingSession || isSubmitting" @click="requestHint">请求一个提示</button>
          <button class="button button--quiet" type="button" :disabled="isStreaming || isLoadingSession || isSubmitting || !sessionId" @click="endSession">结束本次巩固</button>
          <button class="button button--secondary" type="button" :disabled="!canSubmit || isStreaming || isLoadingSession || isSubmitting" @click="submitSolution"><LoaderCircle v-if="isSubmitting" class="spin" :size="16" /><CheckCircle2 v-else :size="16" />提交方案并完成</button>
          <button class="button button--primary" type="submit" :disabled="!draft.trim() || isStreaming || isLoadingSession || isSubmitting"><LoaderCircle v-if="isStreaming" class="spin" :size="16" /><Send v-else :size="16" />发送</button>
        </div>
      </div>
    </form>
  </section>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, reactive, ref, watch } from 'vue'
import { CheckCircle2, LoaderCircle, Send } from 'lucide-vue-next'
import { fundamentalsApi } from '@/shared/api/fundamentalsApi'
import { advancedLearningApi } from '@/shared/api/advancedLearningApi'
import { renderMarkdown } from '@/shared/lib/markdown'

const props = defineProps({
  pathId: { type: [Number, String], required: true },
  nodeId: { type: [Number, String], required: true },
  task: { type: Object, required: true },
  chapterContent: { type: String, default: '' },
  resourceId: { type: [Number, String], default: null },
})
const emit = defineEmits(['end', 'completed'])

const phases = [
  { id: 'understand', label: '理解问题', hint: '界定目标与限制' },
  { id: 'evidence', label: '寻找证据', hint: '从材料提取依据' },
  { id: 'hypothesis', label: '提出假设', hint: '说明可能原因' },
  { id: 'compare', label: '比较方案', hint: '解释取舍关系' },
  { id: 'verify', label: '验证结果', hint: '设计检查方法' },
  { id: 'review', label: '总结', hint: '留下可复查结论' },
]
const currentPhase = ref(phases[0])
const completedPhaseIds = ref([])
const messages = ref([])
const draft = ref('')
const errorMessage = ref('')
const isStreaming = ref(false)
const isLoadingSession = ref(false)
const isSubmitting = ref(false)
const sessionId = ref('')
const evaluation = ref(null)
const confirmedFacts = ref([])
const assumptions = ref([])
const messageList = ref(null)
let requestController = null
let sessionLoadVersion = 0
const currentPhaseIndex = computed(() => phases.findIndex((phase) => phase.id === currentPhase.value.id))
const phaseProgress = computed(() => Math.round((completedPhaseIds.value.length / phases.length) * 100))
const canSubmit = computed(() => messages.value.some((message) => message.role === 'user' && message.text?.trim()))

function createWelcome() {
  return { role: 'assistant', text: `我们从“${currentPhase.value.label}”开始。先说说这个任务要解决的核心问题，以及你准备依据哪些信息判断。` }
}

function resetConversation() {
  requestController?.abort()
  requestController = null
  currentPhase.value = phases[0]
  completedPhaseIds.value = []
  messages.value = [createWelcome()]
  draft.value = ''
  errorMessage.value = ''
  isStreaming.value = false
  isSubmitting.value = false
  sessionId.value = ''
  evaluation.value = null
  confirmedFacts.value = []
  assumptions.value = []
}

function unwrap(response) {
  return response?.data?.data ?? response?.data ?? response
}

function hydrateSession(session) {
  sessionId.value = String(session?.session_id || '')
  const phase = phases.find((item) => item.id === session?.current_phase)
  currentPhase.value = phase || phases[0]
  completedPhaseIds.value = Array.isArray(session?.completed_phase_ids)
    ? session.completed_phase_ids.filter((id) => phases.some((item) => item.id === id))
    : []
  const restoredMessages = Array.isArray(session?.messages)
    ? session.messages.filter((message) => message && ['user', 'assistant'].includes(message.role) && String(message.text || '').trim())
    : []
  messages.value = restoredMessages.length ? restoredMessages : [createWelcome()]
  confirmedFacts.value = Array.isArray(session?.confirmed_facts) ? session.confirmed_facts : []
  assumptions.value = Array.isArray(session?.assumptions) ? session.assumptions : []
  evaluation.value = session?.evaluation || null
}

async function initializeSession() {
  const loadVersion = ++sessionLoadVersion
  resetConversation()
  if (!props.pathId || !props.nodeId || !props.task?.id) return
  isLoadingSession.value = true
  try {
    const response = await advancedLearningApi.openPracticeSession({
      task_id: String(props.task.id),
      path_id: Number(props.pathId),
      node_id: Number(props.nodeId),
      task: props.task,
    })
    if (loadVersion !== sessionLoadVersion) return
    hydrateSession(unwrap(response))
    await scrollToLatest()
  } catch (error) {
    if (loadVersion === sessionLoadVersion) {
      errorMessage.value = error.response?.data?.detail || error.message || '巩固会话暂时无法打开，请稍后重试。'
    }
  } finally {
    if (loadVersion === sessionLoadVersion) isLoadingSession.value = false
  }
}

function sessionPayload() {
  return {
    current_phase: currentPhase.value.id,
    completed_phase_ids: completedPhaseIds.value,
    messages: messages.value.map((message) => ({ role: message.role, text: message.text })),
    confirmed_facts: confirmedFacts.value,
    assumptions: assumptions.value,
  }
}

async function saveSessionState() {
  if (!sessionId.value || evaluation.value) return
  await advancedLearningApi.savePracticeSession(sessionId.value, sessionPayload())
}

function selectPhase(phase) {
  const index = phases.findIndex((item) => item.id === phase.id)
  if (!isPhaseAvailable(index)) return
  currentPhase.value = phase
}

function isPhaseComplete(index) {
  return completedPhaseIds.value.includes(phases[index]?.id)
}

function isPhaseAvailable(index) {
  return index >= 0 && (index <= completedPhaseIds.value.length || isPhaseComplete(index))
}

function requestHint() {
  sendMessage(`请围绕“${currentPhase.value.label}”给我一个不直接泄露答案的提示。`, { advancesPhase: false })
}

async function scrollToLatest() {
  await nextTick()
  if (messageList.value) messageList.value.scrollTop = messageList.value.scrollHeight
}

async function sendMessage(forcedText = '', options = { advancesPhase: true }) {
  const text = String(forcedText || draft.value).trim()
  if (!text || isStreaming.value || isLoadingSession.value || isSubmitting.value || !sessionId.value || evaluation.value) return
  messages.value.push({ role: 'user', text })
  const responseMessage = reactive({ role: 'assistant', text: '' })
  messages.value.push(responseMessage)
  draft.value = ''
  errorMessage.value = ''
  isStreaming.value = true
  requestController = new AbortController()
  await scrollToLatest()
  try {
    await saveSessionState()
    await fundamentalsApi.streamAssistantReply({
      path_id: Number(props.pathId),
      node_id: Number(props.nodeId),
      resource_id: props.resourceId ? Number(props.resourceId) : null,
      practice_session_id: sessionId.value,
      scenario: 'practice',
      text,
      segment: {
        id: `practice-${props.task.id}`,
        type: 'practice',
        title: props.task.title,
        phase: currentPhase.value.label,
        script: [props.task.brief, props.task.problem, `当前阶段：${currentPhase.value.label}`, `重点能力：${props.task.focus}`, `验收标准：${(props.task.criteria || []).join('；')}`, props.chapterContent ? `主讲材料摘要：${props.chapterContent.slice(0, 1200)}` : '当前没有可用主讲材料'].filter(Boolean).join('\n'),
        points: (props.task.constraints || []).slice(0, 6),
        question: { prompt: `请围绕${currentPhase.value.label}推进任务。` },
      },
    }, (event) => {
      if (event?.error) throw new Error(event.error)
      if ((event?.type === 'chunk' || event?.type === 'content') && event.content) {
        responseMessage.text += String(event.content)
        scrollToLatest()
      }
    }, requestController.signal)
    if (!responseMessage.text.trim()) throw new Error('LearnMate 暂时没有返回有效追问')
    if (options.advancesPhase !== false) advancePhase()
    await saveSessionState()
  } catch (error) {
    if (error.name === 'AbortError') return
    if (responseMessage.text.trim()) responseMessage.text += '\n\n> 回复中断了，你可以继续补充。'
    else messages.value = messages.value.filter((message) => message !== responseMessage)
    errorMessage.value = error.response?.data?.detail || error.message || '巩固对话失败，请稍后重试。'
  } finally {
    isStreaming.value = false
    requestController = null
    scrollToLatest()
  }
}

async function endSession() {
  if (!sessionId.value || isStreaming.value || isSubmitting.value) return
  errorMessage.value = ''
  try {
    await saveSessionState()
    const response = await advancedLearningApi.endPracticeSession(sessionId.value)
    hydrateSession(unwrap(response))
    emit('end')
  } catch (error) {
    errorMessage.value = error.response?.data?.detail || error.message || '巩固状态保存失败，请稍后重试。'
  }
}

async function submitSolution() {
  if (!sessionId.value || !canSubmit.value || isStreaming.value || isSubmitting.value || evaluation.value) return
  isSubmitting.value = true
  errorMessage.value = ''
  const finalSubmission = draft.value.trim() || [...messages.value].reverse().find((message) => message.role === 'user')?.text || ''
  try {
    const response = await advancedLearningApi.submitPracticeSession(sessionId.value, {
      ...sessionPayload(),
      final_submission: finalSubmission,
    })
    const saved = unwrap(response)
    hydrateSession(saved)
    emit('completed', saved?.evaluation || null)
  } catch (error) {
    errorMessage.value = error.response?.data?.detail || error.message || '方案提交失败，请稍后重试。'
  } finally {
    isSubmitting.value = false
  }
}

function advancePhase() {
  const index = currentPhaseIndex.value
  if (index < 0) return
  if (!completedPhaseIds.value.includes(currentPhase.value.id)) completedPhaseIds.value = [...completedPhaseIds.value, currentPhase.value.id]
  const nextPhase = phases[index + 1]
  if (nextPhase) currentPhase.value = nextPhase
}

watch(() => props.task?.id, () => { void initializeSession() }, { immediate: true })
onBeforeUnmount(() => {
  sessionLoadVersion += 1
  requestController?.abort()
})
</script>

<style scoped>
.practice-dialogue { display: grid; min-height: 700px; grid-template-rows: auto minmax(360px, 1fr) auto auto; overflow: hidden; }.practice-dialogue__header { display: flex; align-items: flex-start; justify-content: space-between; gap: 18px; padding: 24px; border-bottom: 1px solid var(--line); background: #fbfcfa; }.practice-dialogue__header .eyebrow { margin-bottom: 6px; }.practice-dialogue__header h2 { margin: 0; font-size: 20px; }.practice-dialogue__header p:last-child { max-width: 640px; margin: 8px 0 0; color: var(--muted); font-size: 12px; line-height: 1.7; }.phase-progress { display: grid; flex: 0 0 150px; gap: 4px; padding: 7px 9px; border: 1px solid #d7e3c9; border-radius: 6px; background: #f3f8ea; color: var(--accent-deep); }.phase-progress__count { color: var(--muted); font-size: 10px; }.phase-progress strong { font-size: 11px; }.phase-progress__track { height: 4px; overflow: hidden; border-radius: 99px; background: #dfe9d4; }.phase-progress__track span { display: block; height: 100%; border-radius: inherit; background: var(--accent-deep); transition: width .25s ease; }.practice-dialogue__body { display: grid; grid-template-columns: minmax(0, 1fr) 260px; min-height: 0; }.practice-messages { display: grid; align-content: start; gap: 15px; overflow-y: auto; padding: 24px; border-right: 1px solid var(--line); }.practice-message { display: flex; align-items: flex-start; gap: 9px; max-width: min(720px, 90%); }.practice-message.is-user { justify-self: end; flex-direction: row-reverse; }.practice-avatar { display: grid; flex: 0 0 28px; width: 28px; height: 28px; place-items: center; border-radius: 50%; background: var(--accent); color: var(--accent-deep); font-size: 10px; font-weight: 900; }.practice-bubble { padding: 11px 14px; border-radius: 5px 12px 12px 12px; background: #edf3ed; color: var(--ink); font-size: 13px; line-height: 1.7; }.practice-message.is-user .practice-bubble { border-radius: 12px 5px 12px 12px; background: var(--ink); color: #fff; }.practice-bubble :deep(p) { margin: 0 0 8px; }.practice-bubble :deep(p:last-child) { margin-bottom: 0; }.practice-bubble :deep(ul), .practice-bubble :deep(ol) { margin: 7px 0 0; padding-left: 20px; }.typing { display: flex; gap: 4px; padding: 14px; }.typing span { width: 5px; height: 5px; border-radius: 50%; background: var(--muted); animation: pulse 1s infinite ease-in-out; }.typing span:nth-child(2) { animation-delay: .15s; }.typing span:nth-child(3) { animation-delay: .3s; }.practice-guide { padding: 20px 18px; background: #fbfcfa; }.guide-block { padding: 0 0 18px; margin-bottom: 18px; border-bottom: 1px solid var(--line); }.guide-block:last-child { margin-bottom: 0; border-bottom: 0; }.guide-block .eyebrow { margin-bottom: 7px; }.guide-block > strong { display: block; font-size: 13px; line-height: 1.5; }.guide-block > p:last-child { margin: 7px 0 0; color: var(--muted); font-size: 11px; line-height: 1.65; }.guide-block button { display: grid; width: 100%; gap: 3px; padding: 8px 9px; border: 0; border-radius: 4px; background: transparent; color: var(--muted); text-align: left; font-size: 11px; }.guide-block button:hover, .guide-block button.is-active { background: #e8efdf; color: var(--accent-deep); }.guide-block button:disabled { cursor: not-allowed; opacity: .48; }.phase-button__title { display: flex; align-items: center; gap: 7px; }.phase-button__title > span { color: var(--muted); font-size: 10px; font-variant-numeric: tabular-nums; }.guide-block button.is-complete .phase-button__title > span { color: var(--accent-deep); }.guide-block button small { font-size: 10px; }.guide-block ul { display: grid; gap: 7px; margin: 0; padding: 0; list-style: none; color: var(--muted); font-size: 11px; line-height: 1.5; }.guide-block li::before { margin-right: 6px; color: var(--accent-deep); content: '•'; }.practice-error { margin: 0; padding: 0 24px 10px; color: #a66442; font-size: 11px; }.practice-composer { padding: 14px 24px 20px; border-top: 1px solid var(--line); }.practice-composer textarea { width: 100%; min-height: 105px; resize: vertical; padding: 12px 13px; border: 1px solid var(--line); border-radius: 6px; color: var(--ink); outline: none; font-size: 13px; line-height: 1.7; }.practice-composer textarea:focus { border-color: var(--accent-deep); }.practice-actions { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-top: 10px; color: var(--muted); font-size: 10px; }.practice-actions > div { display: flex; flex-wrap: wrap; gap: 8px; }.practice-actions .button { gap: 7px; }@keyframes pulse { 0%, 60%, 100% { opacity: .3; transform: translateY(0); } 30% { opacity: 1; transform: translateY(-2px); } }@keyframes spin { to { transform: rotate(360deg); } }.spin { animation: spin .8s linear infinite; }
@media (max-width: 780px) { .practice-dialogue__header { flex-direction: column; padding: 18px; }.practice-dialogue__body { grid-template-columns: 1fr; }.practice-messages { min-height: 360px; border-right: 0; border-bottom: 1px solid var(--line); }.practice-guide { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 14px; padding: 16px 18px; }.guide-block { margin: 0; padding: 0; border: 0; }.guide-block:last-child { grid-column: 1 / -1; }.practice-composer { padding: 12px 18px 18px; }.practice-actions { align-items: flex-start; flex-direction: column; }.practice-actions > div { width: 100%; }.practice-actions .button { flex: 1; } }
/* Keep the conversation workspace within the viewport; long replies and phase lists scroll inside it. */
.practice-dialogue { height: clamp(430px, calc(100vh - 330px), 700px); min-height: 0; grid-template-rows: auto minmax(0, 1fr) auto auto; }
.practice-dialogue__header { min-width: 0; padding: 18px 20px; }
.practice-dialogue__header > div { min-width: 0; }
.practice-dialogue__header h2 { font-size: 18px; line-height: 1.35; }
.phase-progress { flex-basis: 150px; max-width: 180px; padding: 6px 9px; font-size: 10px; line-height: 1.35; }
.practice-dialogue__body { min-height: 0; overflow: hidden; }
.practice-messages { min-width: 0; min-height: 0; gap: 14px; overflow-y: auto; padding: 20px; }
.practice-message { min-width: 0; max-width: min(720px, 92%); }
.practice-bubble { min-width: 0; overflow-wrap: anywhere; line-height: 1.65; }
.practice-guide { min-width: 0; overflow-y: auto; padding: 16px 15px; }
.guide-block { padding-bottom: 15px; margin-bottom: 15px; }
.guide-block > strong, .guide-block li { overflow-wrap: anywhere; }
.practice-error { padding: 0 20px 8px; }
.practice-composer { padding: 11px 20px 15px; }
.practice-composer textarea { min-height: 74px; max-height: 145px; padding: 11px 12px; line-height: 1.65; }
.practice-actions { margin-top: 8px; }
.practice-actions > div { gap: 7px; }
.practice-actions .button { min-height: 36px; }
@media (max-width: 780px) {
  .practice-dialogue { height: clamp(420px, calc(100vh - 300px), 620px); }
  .practice-dialogue__header { padding: 17px 18px; }
  .phase-progress { width: 100%; max-width: none; }
  .practice-dialogue__body { overflow: hidden; }
  .practice-guide { max-height: 150px; gap: 12px; padding: 13px 18px; }
  .practice-composer { padding: 10px 18px 15px; }
}
</style>

<style scoped>
.practice-agent-note { display: block; margin-top: 7px; color: var(--muted); font-size: 10px; line-height: 1.5; }
.practice-dialogue .button--secondary { border-color: #d5e2c8; background: #eef5e6; color: var(--accent-deep); }
.practice-dialogue .button--secondary:hover { border-color: #b9c9b2; background: #e3eed9; }
.practice-session-loading { display: grid; min-height: 280px; place-items: center; color: var(--muted); font-size: 12px; }
.practice-evaluation { display: grid; grid-template-columns: minmax(0, 1fr) auto minmax(180px, .8fr); align-items: center; gap: 18px; padding: 18px 22px; border-top: 1px solid var(--line); background: #f3f8ea; }
.practice-evaluation .eyebrow { margin-bottom: 5px; }
.practice-evaluation > div > strong { color: var(--accent-deep); font-size: 15px; }
.practice-evaluation p:not(.eyebrow) { margin: 5px 0 0; color: var(--muted); font-size: 11px; line-height: 1.55; }
.practice-evaluation__score { color: var(--accent-deep); font-size: 30px; line-height: 1; }
.practice-evaluation__score small { margin-left: 3px; font-size: 11px; }
.practice-evaluation ul { display: grid; gap: 5px; margin: 0; padding-left: 17px; color: var(--muted); font-size: 11px; line-height: 1.5; }
@media (max-width: 780px) { .practice-evaluation { grid-template-columns: 1fr auto; gap: 12px; padding: 15px 18px; }.practice-evaluation ul { grid-column: 1 / -1; } }
</style>
