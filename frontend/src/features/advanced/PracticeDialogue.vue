<template>
  <section class="practice-dialogue surface" :class="{ 'is-compact': compact }" aria-label="学习巩固对话">
    <header class="practice-dialogue__header">
      <p class="eyebrow practice-dialogue__eyebrow">学习巩固 · {{ task.kind_label || '实践任务' }}</p>
      <div class="practice-dialogue__tools">
        <div v-if="currentPhase" class="phase-progress" aria-label="巩固阶段进度">
          <span class="phase-progress__count">{{ currentPhaseIndex + 1 }} / {{ phases.length }}</span>
          <strong>{{ currentPhase.label }}</strong>
          <div class="phase-progress__track"><span :style="{ width: `${phaseProgress}%` }"></span></div>
        </div>
        <!-- 提交是判分入口，四个动作里只有它配得上一块带字的按钮，所以放头部常驻可见。
             以前它混在发送旁边，而且评价一出来整条输入区连同它一起消失。 -->
        <button
          v-if="!evaluation"
          class="button button--secondary practice-dialogue__submit"
          type="button"
          :disabled="!canSubmit || isBusy"
          @click="submitSolution"
        >
          <LoaderCircle v-if="isSubmitting" class="spin" :size="13" /><CheckCircle2 v-else :size="13" />提交方案
        </button>
        <!-- 会话级动作收进溢出菜单。VS Code 那边「新建对话 / 历史」也不在输入框里。 -->
        <div v-if="!evaluation" class="practice-menu">
          <button class="practice-menu__trigger" type="button" :aria-expanded="menuOpen" aria-haspopup="menu" aria-label="更多会话操作" title="更多" @click="menuOpen = !menuOpen"><Ellipsis :size="16" /></button>
          <!-- 点外面就收起来。这里不用 focusout：菜单项一被点会先失焦，收得比点击快 -->
          <div v-if="menuOpen" class="practice-menu__backdrop" @click="menuOpen = false"></div>
          <ul v-if="menuOpen" class="practice-menu__list" role="menu">
            <li><button type="button" role="menuitem" :disabled="isBusy || !sessionId" @click="endSessionFromMenu">结束本次巩固</button></li>
          </ul>
        </div>
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
    </div>

    <section v-if="evaluation" class="practice-evaluation" aria-live="polite">
      <div class="practice-evaluation__head">
        <div>
          <p class="eyebrow">提交结果</p>
          <strong>{{ evaluation.label }}</strong>
          <p>{{ evaluation.passed ? '这次方案已经达到当前任务的验收线。' : '方案已经保存，下面是下一轮需要补强的地方。' }}</p>
          <p v-if="evaluationStatus === 'reviewing'" class="practice-evaluation__note"><LoaderCircle class="spin" :size="12" />智能体正在复核这份评价，结果出来会自动更新</p>
          <p v-else-if="evaluation.source === 'agent'" class="practice-evaluation__note"><CheckCircle2 :size="12" />已由智能体复核</p>
        </div>
        <strong class="practice-evaluation__score">{{ evaluation.score }}<small>分</small></strong>
      </div>
      <ul v-if="evaluationCriteria.length" class="practice-criteria">
        <li v-for="item in evaluationCriteria" :key="item.label" :class="{ 'is-passed': item.passed }"><CheckCircle2 v-if="item.passed" :size="13" /><Circle v-else :size="13" />{{ item.label }}</li>
      </ul>
      <div class="practice-evaluation__notes">
        <div v-if="evaluation.strengths?.length"><p class="eyebrow">已经做到</p><ul><li v-for="item in evaluation.strengths" :key="item">{{ item }}</li></ul></div>
        <div v-if="evaluation.next_steps?.length"><p class="eyebrow">下一步</p><ul><li v-for="item in evaluation.next_steps" :key="item">{{ item }}</li></ul></div>
      </div>
    </section>
    <p v-if="errorMessage" class="practice-error" role="status">{{ errorMessage }}</p>
    <form v-if="!evaluation && currentPhase" class="practice-composer" @submit.prevent="sendMessage()">
      <!-- 提示本质是预设提问（它发的就是一句固定话术，见 requestHint），所以做成一角建议，
           不跟发送并排。VS Code 那边同类东西走 `/` 命令，这里退一步用建议角更直白。
           顺带修掉 hintIsProminent 的老毛病：同一个位置按 support_level 在 quiet/secondary
           之间变形，本身就是"这按钮放错地方了"的信号 —— 建议角天然可选，只换配色就够了。 -->
      <button class="practice-suggest" :class="{ 'is-prominent': hintIsProminent }" type="button" :disabled="isBusy" @click="requestHint">
        <Lightbulb :size="13" />{{ hintIsProminent ? '先要一个提示' : '要一个提示' }}
      </button>

      <div class="practice-composer__box">
        <label class="sr-only" for="practice-answer">你的方案思考</label>
        <textarea id="practice-answer" v-model="draft" rows="3" maxlength="1800" :disabled="isLoadingSession || isSubmitting" :placeholder="`围绕“${currentPhase.label}”写下你的判断…`" @keydown.ctrl.enter.prevent="sendMessage()" @keydown.meta.enter.prevent="sendMessage()"></textarea>
        <!-- 发送和停止是同一个位置的两个状态。以前流式期间只是把发送置灰，
             等于用户根本没有中断手段。 -->
        <button v-if="!isStreaming" class="practice-send" type="submit" :disabled="!draft.trim() || isLoadingSession || isSubmitting" aria-label="发送" title="发送（Ctrl + Enter）"><Send :size="16" /></button>
        <button v-else class="practice-send practice-send--stop" type="button" aria-label="停止生成" title="停止生成" @click="stopStreaming"><Square :size="13" /></button>
      </div>
    </form>
  </section>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, reactive, ref, watch } from 'vue'
import { CheckCircle2, Circle, Ellipsis, Lightbulb, LoaderCircle, Send, Square } from 'lucide-vue-next'
import { fundamentalsApi } from '@/shared/api/fundamentalsApi'
import { advancedLearningApi } from '@/shared/api/advancedLearningApi'
import { renderMarkdown } from '@/shared/lib/markdown'

const props = defineProps({
  pathId: { type: [Number, String], required: true },
  nodeId: { type: [Number, String], required: true },
  task: { type: Object, required: true },
  chapterContent: { type: String, default: '' },
  resourceId: { type: [Number, String], default: null },
  // 放进 IDE 右栏时打开。默认布局按视口宽度决定几栏，而右栏宽度和视口无关 ——
  // 视口 1440px 时这个组件的容器只有 420px，媒体查询根本不会触发，两栏会挤成一栏宽。
  compact: { type: Boolean, default: false },
})
const emit = defineEmits(['end', 'completed'])

// 阶段列表由**服务端**下发（session.phases）—— 阶段词汇跟着任务类型走（案例诊断 /
// 迁移练习 / 项目实训各一套 4 阶段），这里以前抄了一份全局 6 阶段，于是三种任务的
// 操作方式一字不差。词汇只能有一处，所以这里是空的，等会话加载。
const phases = ref([])
// 会话还没加载完（或加载失败）时没有当前阶段，读它的地方都要有守卫。
const currentPhase = ref(null)
const completedPhaseIds = ref([])
const messages = ref([])
const draft = ref('')
const errorMessage = ref('')
const isStreaming = ref(false)
const isLoadingSession = ref(false)
const isSubmitting = ref(false)
const sessionId = ref('')
const evaluation = ref(null)
const evaluationStatus = ref('none')
const confirmedFacts = ref([])
const assumptions = ref([])
const messageList = ref(null)
// 服务端说这次会话还在等教练开口（见 practice_service._opening_pending）
const openingPending = ref(false)
let requestController = null
let openingController = null
let sessionLoadVersion = 0
// 提交后先拿到一份确定性评价（不用等），智能体的复核在后台跑完会覆盖它 ——
// 判分实测要几十秒，而 httpClient 超时只有 15 秒，所以同步判分必然失败。
const EVALUATION_POLL_INTERVAL_MS = 3000
const EVALUATION_POLL_MAX_TRIES = 40
let evaluationPoll = 0
let evaluationTries = 0
const currentPhaseIndex = computed(() => phases.value.findIndex((phase) => phase.id === currentPhase.value?.id))
// 四个评分维度的 label 由服务端给（判分器只填 passed），前端不自己拼一份
const evaluationCriteria = computed(() => (Array.isArray(evaluation.value?.criteria) ? evaluation.value.criteria : []))
const phaseProgress = computed(() => (
  phases.value.length ? Math.round((completedPhaseIds.value.length / phases.value.length) * 100) : 0
))
const canSubmit = computed(() => messages.value.some((message) => message.role === 'user' && message.text?.trim()))
// 支持强度决定提示的分量：引导练习（high）把提示摆在明面上，开放挑战（low）保持低调 ——
// 这两种任务本来就该由不同分量的脚手架陪着做。
const hintIsProminent = computed(() => props.task?.support_level === 'high')
// 三个按钮原来各自写一遍「流式中 / 会话加载中 / 提交中」的禁用条件，口径迟早会分叉。
const isBusy = computed(() => isStreaming.value || isLoadingSession.value || isSubmitting.value)
const menuOpen = ref(false)

function resetConversation() {
  requestController?.abort()
  requestController = null
  abortOpening()
  clearEvaluationPoll()
  phases.value = []
  currentPhase.value = null
  completedPhaseIds.value = []
  // 开场那句不在这里造。以前这里抄了一份和后来服务端一样的话，两处各自漂移 ——
  // 学生看到的第一句和库里存的对不上。现在只有服务端种（见 practice_service
  // ._welcome_message），前端负责让教练把它换成真的读过任务的那一句。
  messages.value = []
  openingPending.value = false
  draft.value = ''
  errorMessage.value = ''
  isStreaming.value = false
  isSubmitting.value = false
  sessionId.value = ''
  evaluation.value = null
  evaluationStatus.value = 'none'
  confirmedFacts.value = []
  assumptions.value = []
}

function clearEvaluationPoll() {
  if (evaluationPoll) { window.clearTimeout(evaluationPoll); evaluationPoll = 0 }
}

// 开场那一轮不占 isStreaming：学生不该为了看教练开口而等 —— 种下的那句开场已经
// 显示着了，学生随时可以先说话，说话就把这一轮掐掉（见 requestOpening）。
function abortOpening() {
  openingController?.abort()
  openingController = null
}

// 服务端的评价还在复核时轮询它。取不到就等下一轮 —— 界面上那份基线评价一直是有效的，
// 轮询失败不该把它变成错误态。
function scheduleEvaluationPoll() {
  clearEvaluationPoll()
  if (evaluationStatus.value !== 'reviewing' || !sessionId.value) return
  if (evaluationTries >= EVALUATION_POLL_MAX_TRIES) return
  evaluationPoll = window.setTimeout(async () => {
    evaluationTries += 1
    try {
      hydrateSession(unwrap(await advancedLearningApi.getPracticeSession(sessionId.value)))
    } catch {
      // 忽略：下一轮再试，或者用户在别处已经看到基线评价
    }
    scheduleEvaluationPoll()
  }, EVALUATION_POLL_INTERVAL_MS)
}

function unwrap(response) {
  return response?.data?.data ?? response?.data ?? response
}

function hydrateSession(session) {
  sessionId.value = String(session?.session_id || '')
  // 阶段词汇由服务端给（跟着任务类型走）。拿不到就保留空数组 —— 宁可少显示一块，
  // 也不要让前端自己编一套词汇出来，那样进度会落在服务端不认识的 id 上。
  phases.value = Array.isArray(session?.phases)
    ? session.phases.filter((phase) => phase && phase.id && phase.label)
    : []
  const phase = phases.value.find((item) => item.id === session?.current_phase)
  currentPhase.value = phase || phases.value[0] || null
  completedPhaseIds.value = Array.isArray(session?.completed_phase_ids)
    ? session.completed_phase_ids.filter((id) => phases.value.some((item) => item.id === id))
    : []
  const restoredMessages = Array.isArray(session?.messages)
    ? session.messages.filter((message) => message && ['user', 'assistant'].includes(message.role) && String(message.text || '').trim())
    : []
  messages.value = restoredMessages
  openingPending.value = Boolean(session?.opening_pending)
  confirmedFacts.value = Array.isArray(session?.confirmed_facts) ? session.confirmed_facts : []
  assumptions.value = Array.isArray(session?.assumptions) ? session.assumptions : []
  evaluation.value = session?.evaluation || null
  evaluationStatus.value = session?.evaluation_status || 'none'
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
    // 新会话（学生还没说过话）才让教练开口；老会话里开场早就生成过了。
    void requestOpening()
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
    current_phase: currentPhase.value?.id || '',
    completed_phase_ids: completedPhaseIds.value,
    messages: messages.value.map((message) => ({ role: message.role, text: message.text })),
    confirmed_facts: confirmedFacts.value,
    assumptions: assumptions.value,
  }
}

// 阶段进度是服务端的账本：`completed_phase_ids` 由智能体回复里的 [[PHASE:done]] 标记
// 推进，客户端传的值服务端会忽略。这里只做展示同步。
function applyPhaseState(state) {
  const ids = Array.isArray(state?.completed_phase_ids)
    ? state.completed_phase_ids.filter((id) => phases.value.some((item) => item.id === id))
    : null
  if (ids) completedPhaseIds.value = ids
  const phase = phases.value.find((item) => item.id === state?.current_phase)
  if (phase) currentPhase.value = phase
}

async function saveSessionState() {
  if (!sessionId.value || evaluation.value) return
  const saved = unwrap(await advancedLearningApi.savePracticeSession(sessionId.value, sessionPayload()))
  // 用服务端返回的状态校准本地：这次回复可能没有触发标记，服务端手里才是真实进度。
  if (saved?.session_id) applyPhaseState(saved)
}

// 阶段由服务端推进（智能体回复里的 [[PHASE:done]]），前端不再提供手动跳转 ——
// 原来那个可点的阶段列表已经删掉，头部只读显示当前进度。


function requestHint() {
  if (!currentPhase.value) return
  sendMessage(`请围绕“${currentPhase.value.label}”给我一个不直接泄露答案的提示。`, { advancesPhase: false })
}

// 中断当前这一轮。开场白也算一轮 —— 它虽然不占 requestController，但同样是用户在等的一段回复。
// 已经吐出来的文字留着（见 sendMessage 的 AbortError 分支），只是不再往下接。
function stopStreaming() {
  requestController?.abort()
  abortOpening()
}

function endSessionFromMenu() {
  menuOpen.value = false
  endSession()
}

async function scrollToLatest() {
  await nextTick()
  if (messageList.value) messageList.value.scrollTop = messageList.value.scrollHeight
}

function practiceSegment(advancesPhase) {
  // 阶段名一定来自服务端下发的那份（跟着任务类型走），本地不认词汇表。
  const phaseLabel = currentPhase.value?.label || ''
  return {
    id: `practice-${props.task.id}`,
    type: 'practice',
    title: props.task.title,
    phase: phaseLabel,
    // 请求提示这一轮不该记进度，服务端据此不认这一轮的阶段标记。
    phase_advance: advancesPhase !== false,
    script: [props.task.brief, props.task.problem, `当前阶段：${phaseLabel}`, `重点能力：${props.task.focus}`, `验收标准：${(props.task.criteria || []).join('；')}`, props.chapterContent ? `主讲材料摘要：${props.chapterContent.slice(0, 1200)}` : '当前没有可用主讲材料'].filter(Boolean).join('\n'),
    points: (props.task.constraints || []).slice(0, 6),
    question: { prompt: `请围绕${phaseLabel}推进任务。` },
  }
}

// 学生发言和教练开场走的是同一条流式接口，只有 scenario 和 segment 上的开关不同
// （服务端按 scenario 拼提示词，见 classroom_chat._compose_user_prompt）。
function streamCoachReply({ scenario, text, advancesPhase, signal, onChunk }) {
  return fundamentalsApi.streamAssistantReply({
    path_id: Number(props.pathId),
    node_id: Number(props.nodeId),
    resource_id: props.resourceId ? Number(props.resourceId) : null,
    practice_session_id: sessionId.value,
    scenario,
    text,
    segment: practiceSegment(advancesPhase),
  }, (event) => {
    if (event?.error) throw new Error(event.error)
    if (event?.type === 'phase') {
      applyPhaseState(event)
      return
    }
    if ((event?.type === 'chunk' || event?.type === 'content') && event.content) onChunk(String(event.content))
  }, signal)
}

// 教练开口那一轮：任务刚打开时服务端只种了一句同步的开场，它读得到任务名但不读
// 任务内容。真正"读过任务再开口"的是教练，以前要等学生先说一句才会被调用 ——
// 于是第一问永远是同一句通用话术，学生看完只能回"你在说啥"。现在把它提前到第一轮。
async function requestOpening() {
  // 没有当前阶段就没法告诉教练"把他引进哪一步" —— 服务端没给阶段列表时宁可不开口。
  if (!openingPending.value || !sessionId.value || !currentPhase.value) return
  if (isStreaming.value || isSubmitting.value || evaluation.value) return
  openingPending.value = false
  let bubble = messages.value[messages.value.length - 1]
  if (!bubble || bubble.role !== 'assistant') {
    bubble = reactive({ role: 'assistant', text: '' })
    messages.value.push(bubble)
  }
  const seeded = bubble.text
  let received = false
  let completed = false
  openingController = new AbortController()
  try {
    await streamCoachReply({
      scenario: 'practice_opening',
      text: '',
      advancesPhase: false,
      signal: openingController.signal,
      onChunk: (content) => {
        // 原地替换那句话而不是新插一条气泡 —— 否则学生会同时看到两个开场问题。
        bubble.text = received ? bubble.text + content : content
        received = true
        scrollToLatest()
      },
    })
    completed = true
  } catch {
    // 开场生成失败不该让整个任务看起来是坏的：下面回退到种下的那句，不弹错误。
  } finally {
    openingController = null
  }
  if (!completed || !received) {
    // 半句话的开场比那句通用开场更难回答（学生发言时这一轮会被掐掉）。
    bubble.text = seeded
    return
  }
  try {
    await saveSessionState()
  } catch {
    // 存不上不影响这次使用；下次进这个会话会重新开口一次。
  }
}

async function sendMessage(forcedText = '', options = { advancesPhase: true }) {
  const text = String(forcedText || draft.value).trim()
  if (!text || isStreaming.value || isLoadingSession.value || isSubmitting.value || !sessionId.value || evaluation.value) return
  // 学生先开口就把教练那一轮掐掉：种下的开场已经够他回答，而两路回复会交叉着落到
  // 同一条气泡上。
  abortOpening()
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
    await streamCoachReply({
      scenario: 'practice',
      text,
      advancesPhase: options.advancesPhase,
      signal: requestController.signal,
      onChunk: (content) => {
        responseMessage.text += content
        scrollToLatest()
      },
    })
    if (!responseMessage.text.trim()) throw new Error('LearnMate 暂时没有返回有效追问')
    // 阶段推进交给服务端：它读智能体回复末尾的 [[PHASE:done]] 标记（见 applyPhaseState）。
    // 这里以前会无条件 advancePhase()，等于学生每说一句话就自动过一关。
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
  abortOpening()
  errorMessage.value = ''
  try {
    await saveSessionState()
    const response = await advancedLearningApi.endPracticeSession(sessionId.value)
    hydrateSession(unwrap(response))
    // 带上 session id：父组件要拿它请服务端按会话记录写一份过程小结。
    emit('end', sessionId.value)
  } catch (error) {
    errorMessage.value = error.response?.data?.detail || error.message || '巩固状态保存失败，请稍后重试。'
  }
}

async function submitSolution() {
  if (!sessionId.value || !canSubmit.value || isStreaming.value || isSubmitting.value || evaluation.value) return
  abortOpening()
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
    scheduleEvaluationPoll()
  } catch (error) {
    errorMessage.value = error.response?.data?.detail || error.message || '方案提交失败，请稍后重试。'
  } finally {
    isSubmitting.value = false
  }
}

watch(() => props.task?.id, () => { void initializeSession() }, { immediate: true })
onBeforeUnmount(() => {
  sessionLoadVersion += 1
  requestController?.abort()
  abortOpening()
  clearEvaluationPoll()
})
</script>


<style scoped>
/* 一层样式。这里原来有两个 <style> 块，第一层是一整行 7000 多字符的压缩 CSS，
   第二层又对**同样的选择器**再写一遍（头部 4 次、输入区 4 次……），读到某条规则
   根本没法判断它最终生不生效。合并时按后写的覆盖先写的取值，行为与合并前一致。 */

.practice-dialogue {
  display: grid;
  height: clamp(430px, calc(100vh - 330px), 700px);
  min-height: 0;
  grid-template-rows: auto minmax(0, 1fr) auto auto;
  overflow: hidden;
}

/* ── 头部 ───────────────────────────────────────────── */
.practice-dialogue__header {
  display: flex;
  min-width: 0;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 11px 15px;
  border-bottom: 1px solid var(--line);
  background: #fbfcfa;
}
.practice-dialogue__eyebrow { margin: 0; flex: 0 1 auto; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.practice-dialogue__tools { display: flex; min-width: 0; flex: 0 0 auto; align-items: center; gap: 8px; }
.phase-progress {
  display: grid;
  flex: 0 1 150px;
  gap: 4px;
  min-width: 0;
  max-width: 170px;
  padding: 5px 9px;
  border: 1px solid #d7e3c9;
  border-radius: 6px;
  background: #f3f8ea;
  color: var(--accent-deep);
  font-size: 10px;
  line-height: 1.35;
}
.phase-progress strong { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
/* 提交按钮比全局 .button 矮一档 —— 它是页头里的一枚控件，不是页面级主按钮，
   40px 的全局高度会把这一行撑得比面板标题还重。 */
.practice-dialogue__submit { flex: 0 0 auto; min-height: 30px; padding: 0 11px; gap: 6px; font-size: 11px; }
.practice-menu { position: relative; flex: 0 0 auto; }
.practice-menu__trigger { display: grid; width: 30px; height: 30px; place-items: center; border: 1px solid transparent; border-radius: 6px; background: transparent; color: var(--muted); }
.practice-menu__trigger:hover, .practice-menu__trigger[aria-expanded="true"] { border-color: var(--line); background: #fff; color: var(--ink); }
.practice-menu__backdrop { position: fixed; inset: 0; z-index: 20; }
.practice-menu__list { position: absolute; z-index: 21; top: calc(100% + 6px); right: 0; display: grid; width: max-content; min-width: 150px; gap: 4px; margin: 0; padding: 6px; border: 1px solid var(--line); border-radius: 10px; background: var(--paper); box-shadow: 0 14px 34px rgba(31, 49, 40, .16); list-style: none; }
.practice-menu__list button { width: 100%; padding: 8px 10px; border: 0; border-radius: 6px; background: transparent; color: var(--ink); font-size: 12px; text-align: left; }
.practice-menu__list button:hover:not(:disabled) { background: #f1f6eb; color: var(--accent-deep); }
.practice-menu__list button:disabled { color: var(--muted); cursor: not-allowed; }
.phase-progress__count { color: var(--muted); font-size: 10px; }
.phase-progress strong { font-size: 11px; }
.phase-progress__track { height: 4px; overflow: hidden; border-radius: 99px; background: #dfe9d4; }
.phase-progress__track span { display: block; height: 100%; border-radius: inherit; background: var(--accent-deep); transition: width .25s ease; }

/* ── 消息区 ─────────────────────────────────────────── */
.practice-dialogue__body { display: grid; min-height: 0; grid-template-columns: minmax(0, 1fr); overflow: hidden; }
.practice-messages {
  display: grid;
  min-width: 0;
  min-height: 0;
  align-content: start;
  gap: 14px;
  overflow-y: auto;
  padding: 20px;
}
.practice-message { display: flex; min-width: 0; align-items: flex-start; gap: 9px; max-width: min(720px, 92%); }
.practice-message.is-user { justify-self: end; flex-direction: row-reverse; }
.practice-avatar {
  display: grid;
  flex: 0 0 28px;
  width: 28px;
  height: 28px;
  place-items: center;
  border-radius: 50%;
  background: var(--accent);
  color: var(--accent-deep);
  font-size: 10px;
  font-weight: 900;
}
.practice-bubble {
  min-width: 0;
  padding: 11px 14px;
  border-radius: 5px 12px 12px 12px;
  background: #edf3ed;
  color: var(--ink);
  font-size: 13px;
  line-height: 1.65;
  overflow-wrap: anywhere;
}
.practice-message.is-user .practice-bubble { border-radius: 12px 5px 12px 12px; background: var(--ink); color: #fff; }
.practice-bubble :deep(p) { margin: 0 0 8px; }
.practice-bubble :deep(p:last-child) { margin-bottom: 0; }
.practice-bubble :deep(ul), .practice-bubble :deep(ol) { margin: 7px 0 0; padding-left: 20px; }
.typing { display: flex; gap: 4px; padding: 14px; }
.typing span { width: 5px; height: 5px; border-radius: 50%; background: var(--muted); animation: pulse 1s infinite ease-in-out; }
.typing span:nth-child(2) { animation-delay: .15s; }
.typing span:nth-child(3) { animation-delay: .3s; }
.practice-session-loading { display: grid; min-height: 280px; place-items: center; color: var(--muted); font-size: 12px; }

/* ── 输入区 ─────────────────────────────────────────── */
.practice-error { margin: 0; padding: 0 20px 8px; color: #a66442; font-size: 11px; }
.practice-composer { padding: 10px 15px 13px; border-top: 1px solid var(--line); }
/* 建议角：一条可选的预设提问，不占按钮位，也不抢发送的视觉重量。 */
.practice-suggest { display: inline-flex; align-items: center; gap: 6px; margin-bottom: 8px; padding: 4px 10px; border: 1px solid var(--line); border-radius: 99px; background: #fff; color: var(--muted); font-size: 11px; }
.practice-suggest:hover:not(:disabled) { border-color: #b9c9b2; background: #f1f6eb; color: var(--accent-deep); }
.practice-suggest:disabled { cursor: not-allowed; opacity: .55; }
.practice-suggest svg { color: var(--accent-deep); }
/* support_level=high（迁移练习）本该有人扶着走，所以这一角提示给它上色 —— 只是配色不同，
   位置和尺寸都不变，不像以前那样整块控件换一种样式。 */
.practice-suggest.is-prominent { border-color: #c8d9b7; background: #eef5e6; color: var(--accent-deep); font-weight: 700; }

/* 输入框和发送是同一块：发送贴在框内右下角。发出去之后同一个位置变成停止。 */
.practice-composer__box { position: relative; }
.practice-composer textarea {
  display: block;
  width: 100%;
  height: 62px;
  min-height: 62px;
  max-height: 120px;
  resize: none;
  padding: 10px 48px 10px 12px;
  border: 1px solid var(--line);
  border-radius: 12px;
  color: var(--ink);
  outline: none;
  font-size: 13px;
  line-height: 1.6;
}
.practice-composer__box:focus-within textarea { border-color: var(--accent-deep); }
.practice-send { position: absolute; right: 8px; bottom: 8px; display: grid; width: 30px; height: 30px; place-items: center; border: 1px solid #c4df3d; border-radius: 50%; background: var(--accent); color: #1e3c34; }
.practice-send:hover:not(:disabled) { border-color: #a9ca27; background: #a9ca27; }
.practice-send:disabled { border-color: var(--line); background: var(--soft); color: #a8b2aa; cursor: not-allowed; }
/* 停止用中性色，不要跟发送一样亮 —— 它是个打断动作，不是主行动 */
.practice-send--stop { border-color: var(--line); background: #fff; color: var(--accent-deep); }
.practice-send--stop:hover { border-color: #b9c9b2; background: #f1f6eb; }
.practice-dialogue .button--secondary { border-color: #d5e2c8; background: #eef5e6; color: var(--accent-deep); }
.practice-dialogue .button--secondary:hover { border-color: #b9c9b2; background: #e3eed9; }

/* ── 提交结果 ───────────────────────────────────────── */
.practice-evaluation { display: grid; max-height: 164px; min-height: 0; gap: 8px; overflow-y: auto; padding: 12px 20px; border-top: 1px solid var(--line); background: #f3f8ea; }
.practice-evaluation__head { display: flex; align-items: flex-start; justify-content: space-between; gap: 14px; }
.practice-evaluation .eyebrow { margin-bottom: 5px; }
.practice-evaluation__head > div > strong { color: var(--accent-deep); font-size: 15px; }
.practice-evaluation p:not(.eyebrow) { margin: 5px 0 0; color: var(--muted); font-size: 11px; line-height: 1.55; }
.practice-evaluation__note { display: flex; align-items: center; gap: 5px; }
.practice-evaluation__score { flex: 0 0 auto; color: var(--accent-deep); font-size: 30px; line-height: 1; }
.practice-evaluation__score small { margin-left: 3px; font-size: 11px; }
/* 四个维度的判定：这是判分器真正算出来的东西，之前算完就丢了 */
.practice-criteria { display: flex; flex-wrap: wrap; gap: 7px; margin: 0; padding: 0; list-style: none; }
.practice-criteria li { display: flex; align-items: center; gap: 4px; padding: 4px 9px; border: 1px solid #dfe6d8; border-radius: 99px; background: #fff; color: var(--muted); font-size: 11px; }
.practice-criteria li.is-passed { border-color: #c8d9b7; background: #eef5e6; color: var(--accent-deep); }
.practice-evaluation__notes { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px 20px; }
.practice-evaluation__notes ul { display: grid; gap: 5px; margin: 0; padding-left: 17px; color: var(--muted); font-size: 11px; line-height: 1.5; }

/* ── 紧凑模式：放进 IDE 右半屏 ──────────────────────────
   高度撑满容器（由外层栅格决定），而不是按视口算出来的那个 clamp。 */
.practice-dialogue.is-compact { height: 100%; min-height: 0; border-radius: 14px; }
.practice-dialogue.is-compact .phase-progress { flex: 0 1 170px; }
.practice-dialogue.is-compact .practice-messages { padding: 16px; }
.practice-dialogue.is-compact .practice-message { max-width: 100%; }
.practice-dialogue.is-compact .practice-evaluation { max-height: 190px; padding: 12px 15px; }
.practice-dialogue.is-compact .practice-evaluation__notes { grid-template-columns: 1fr; }

@keyframes pulse { 0%, 60%, 100% { opacity: .3; transform: translateY(0); } 30% { opacity: 1; transform: translateY(-2px); } }
@keyframes spin { to { transform: rotate(360deg); } }
.spin { animation: spin .8s linear infinite; }

/* 面板宽度是用户拖出来的，跟视口无关 —— 所以头部按**容器**宽度退化，不是按媒体查询。
   实测拖到 302px 时：眉标 + 阶段进度 + 提交 + 溢出菜单一行放不下，会顶出右边界。 */
.practice-dialogue { container-type: inline-size; }
@container (max-width: 430px) {
  /* 眉标是三者里唯一冗余的（上面任务条已经写着任务类型），先撤它 */
  .practice-dialogue__eyebrow { display: none; }
  .practice-dialogue__tools { flex: 1; justify-content: flex-end; }
  .phase-progress { flex: 1 1 auto; max-width: none; }
}
@container (max-width: 300px) {
  /* 再窄就只剩提交和菜单；阶段进度退化成一行小字，描述性的进度条让位给可操作的东西 */
  .phase-progress { padding: 4px 7px; }
  .phase-progress__track { display: none; }
  .practice-dialogue__submit { padding: 0 9px; }
}

@media (max-width: 780px) {
  .practice-dialogue { height: clamp(420px, calc(100vh - 300px), 620px); }
  .practice-messages { min-height: 360px; }
  .practice-evaluation { padding: 15px 18px; }
  .practice-evaluation__notes { grid-template-columns: 1fr; }
}
</style>
