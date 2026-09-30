<template>
  <section class="practice-dialogue surface" :class="{ 'is-compact': compact }" aria-label="学习巩固对话">
    <header class="practice-dialogue__header">
      <div class="practice-dialogue__titlebar">
        <p class="eyebrow practice-dialogue__eyebrow">学习巩固 · {{ task.kind_label || '实践任务' }}</p>
        <div class="practice-dialogue__tools">
          <!-- 会话级动作收进溢出菜单。VS Code 那边「新建对话 / 历史」也不在输入框里。 -->
          <div class="practice-menu">
            <button class="practice-menu__trigger" type="button" :aria-expanded="menuOpen" aria-haspopup="menu" aria-label="更多会话操作" title="更多" @click="menuOpen = !menuOpen"><Ellipsis :size="16" /></button>
            <!-- 点外面就收起来。这里不用 focusout：菜单项一被点会先失焦，收得比点击快 -->
            <div v-if="menuOpen" class="practice-menu__backdrop" @click="menuOpen = false"></div>
            <ul v-if="menuOpen" class="practice-menu__list" role="menu">
              <li><button type="button" role="menuitem" :disabled="isBusy || !sessionId" @click="endSessionFromMenu">结束本次巩固</button></li>
            </ul>
          </div>
        </div>
      </div>

      <!-- 教练能看到什么，得写出来。跟"新建到底建在哪儿"是同一个教训：状态不可见就只能靠猜，
         而学生已经在问了（"能不能看到我的工作区"）。摘要取自**发送时**读的那份快照，
         所以它说的是"这一轮教练看到的是这个"，不是"此刻编辑器里是什么" —— 两回事。
         这一条长在 header 里而不是另起一行 grid 子元素：另起一行要动 .practice-dialogue
         的 grid-template-rows，那是上一轮为了高度塌陷踩过坑的地方。 -->
      <div class="practice-visibility">
        <button
          v-if="workspaceSummary.details.length"
          class="practice-visibility__toggle"
          type="button"
          :aria-expanded="workspaceDetailOpen"
          @click="workspaceDetailOpen = !workspaceDetailOpen"
        >
          <Eye :size="13" />
          <span class="practice-visibility__headline">{{ workspaceSummary.headline }}</span>
          <component :is="workspaceDetailOpen ? ChevronUp : ChevronDown" :size="13" />
        </button>
        <p v-else class="practice-visibility__blind"><EyeOff :size="13" /><span>{{ workspaceSummary.headline }}</span></p>
        <ul v-if="workspaceDetailOpen" class="practice-visibility__details">
          <li v-for="(detail, index) in workspaceSummary.details" :key="index">{{ detail }}</li>
        </ul>
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

    <p v-if="errorMessage" class="practice-error" role="status">{{ errorMessage }}</p>
    <form v-if="!isLoadingSession" class="practice-composer" @submit.prevent="sendMessage()">
      <!-- 提示本质是预设提问（它发的就是一句固定话术，见 requestHint），所以做成一角建议，
           不跟发送并排。VS Code 那边同类东西走 `/` 命令，这里退一步用建议角更直白。
           顺带修掉 hintIsProminent 的老毛病：同一个位置按 support_level 在 quiet/secondary
           之间变形，本身就是"这按钮放错地方了"的信号 —— 建议角天然可选，只换配色就够了。 -->
      <button class="practice-suggest" :class="{ 'is-prominent': hintIsProminent }" type="button" :disabled="isBusy" @click="requestHint">
        <Lightbulb :size="13" />{{ hintIsProminent ? '先要一个提示' : '要一个提示' }}
      </button>

      <div ref="composerBox" class="practice-composer__box">
        <label class="sr-only" for="practice-answer">你的方案思考</label>
        <!-- 1800 → 10000（2026-09-30）。原来的额度是按"写一段判断"定的，可这个框现在是
             学生报错、贴栈、贴片段的地方，1800 字符粘一段 traceback 就被浏览器静默截掉了。
             服务端那条路没有长度限制（chat_history.req 是 TextField，只有 .strip()），
             卡点一直只在这个 maxlength 上。 -->
        <textarea ref="composerInput" id="practice-answer" v-model="draft" rows="1" maxlength="10000" :disabled="isLoadingSession" placeholder="写下你的判断…（Ctrl + Enter 发送）" @keydown.ctrl.enter.prevent="sendMessage()" @keydown.meta.enter.prevent="sendMessage()"></textarea>
        <!-- 发送和停止是同一个位置的两个状态。以前流式期间只是把发送置灰，
             等于用户根本没有中断手段。 -->
        <button v-if="!isStreaming" class="practice-send" type="submit" :disabled="!draft.trim() || isLoadingSession" aria-label="发送" title="发送（Ctrl + Enter）"><Send :size="16" /></button>
        <button v-else class="practice-send practice-send--stop" type="button" aria-label="停止生成" title="停止生成" @click="stopStreaming"><Square :size="13" /></button>
      </div>
    </form>
  </section>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { ChevronDown, ChevronUp, Ellipsis, Eye, EyeOff, Lightbulb, Send, Square } from 'lucide-vue-next'
import { fundamentalsApi } from '@/shared/api/fundamentalsApi'
import { advancedLearningApi } from '@/shared/api/advancedLearningApi'
import { renderMarkdown } from '@/shared/lib/markdown'
import { describeWorkspaceSnapshot } from './workspace/workspaceSnapshot'

const props = defineProps({
  pathId: { type: [Number, String], required: true },
  nodeId: { type: [Number, String], required: true },
  task: { type: Object, required: true },
  chapterContent: { type: String, default: '' },
  resourceId: { type: [Number, String], default: null },
  // 放进 IDE 右栏时打开。默认布局按视口宽度决定几栏，而右栏宽度和视口无关 ——
  // 视口 1440px 时这个组件的容器只有 420px，媒体查询根本不会触发，两栏会挤成一栏宽。
  compact: { type: Boolean, default: false },
  // 读学生工作区快照的函数，由页面持有（见 AdvancedLearningPage.readWorkspaceSnapshot）。
  // **它是函数不是对象**：快照只在"按下发送那一刻"取才有意义，而正文随每次击键变，
  // 做成响应式 prop 会让这个组件每敲一个字符就重渲染一次。别"顺手"改成响应式数据。
  workspaceReader: { type: Function, default: null },
})
const emit = defineEmits(['end'])

const messages = ref([])
const draft = ref('')
const errorMessage = ref('')
const isStreaming = ref(false)
const isLoadingSession = ref(false)
const sessionId = ref('')
const confirmedFacts = ref([])
const assumptions = ref([])
const messageList = ref(null)
// 服务端说这次会话还在等教练开口（见 practice_service._opening_pending）
const openingPending = ref(false)
let requestController = null
let openingController = null
let sessionLoadVersion = 0
// 支持强度决定提示的分量：引导练习（high）把提示摆在明面上，开放挑战（low）保持低调 ——
// 这两种任务本来就该由不同分量的脚手架陪着做。
const hintIsProminent = computed(() => props.task?.support_level === 'high')
const isBusy = computed(() => isStreaming.value || isLoadingSession.value)
const menuOpen = ref(false)
// 本轮教练能看到的工作区。**只在发送时（含开场轮）刷新** —— 页头那条提示显示的就是
// 这一份，语义是"这一轮教练看到的是这个"，不是"此刻编辑器里是什么"。
// 会话恢复后也要读一次：否则还没发过话时会显示成"看不到"，而学生明明已经打开了文件夹。
const workspaceShown = ref({ available: false })
const workspaceDetailOpen = ref(false)
const workspaceSummary = computed(() => describeWorkspaceSnapshot(workspaceShown.value))
const composerInput = ref(null)
const composerBox = ref(null)
// 输入框高度跟着内容长。原来写死 height: 62px + resize: none，学生写长一点就只能在
// 那个小框里滚，看不到自己写了什么 —— 而这个练习的答案本来就是成段的。
const COMPOSER_MIN_HEIGHT = 62
const COMPOSER_MAX_HEIGHT = 200

function growComposer() {
  const el = composerInput.value
  if (!el) return
  // 先归零再量 scrollHeight：不归零的话量到的是「当前高度」，只会越涨越高、缩不回去。
  el.style.height = 'auto'
  // box-sizing 是 border-box，scrollHeight 不含上下边框，补回来（否则短一行就出滚动条）
  const needed = el.scrollHeight + 2
  el.style.height = `${Math.min(Math.max(needed, COMPOSER_MIN_HEIGHT), COMPOSER_MAX_HEIGHT)}px`
  el.style.overflowY = needed > COMPOSER_MAX_HEIGHT ? 'auto' : 'hidden'
}

// 右栏宽度是用户拖出来的。拖窄之后同一段文字会重排成更多行，而上面那个 watch 只在
// 草稿变化时量高度 —— 不动键盘只拖分隔条，框不会跟着长，文字就被挤进滚动条里。
// 所以再盯一层容器宽度：只在**宽度**变了时才重量，不然 growComposer 改高度会把
// 观察器自己再触发一次，转成死循环。
//
// 盯的是 composerBox 这个 ref 而不是 onMounted —— 输入区是 v-if="!isLoadingSession"
// 渲染的，挂载那一刻它还不存在，挂上去等于挂了个 null（实测拖窄之后文字照样被截）。
let composerResizeObserver = null

watch(composerBox, (el) => {
  composerResizeObserver?.disconnect()
  composerResizeObserver = null
  if (!el || typeof ResizeObserver === 'undefined') return
  let lastWidth = el.clientWidth
  composerResizeObserver = new ResizeObserver(() => {
    if (el.clientWidth === lastWidth) return
    lastWidth = el.clientWidth
    growComposer()
  })
  composerResizeObserver.observe(el)
  // 元素刚出现时也量一次（此时草稿可能是恢复出来的历史内容）
  nextTick(growComposer)
})

function resetConversation() {
  requestController?.abort()
  requestController = null
  abortOpening()
  // 开场那句不在这里造。以前这里抄了一份和后来服务端一样的话，两处各自漂移 ——
  // 学生看到的第一句和库里存的对不上。现在只有服务端种（见 practice_service
  // ._welcome_message），前端负责让教练把它换成真的读过任务的那一句。
  messages.value = []
  openingPending.value = false
  draft.value = ''
  errorMessage.value = ''
  isStreaming.value = false
  sessionId.value = ''
  confirmedFacts.value = []
  assumptions.value = []
}

// 开场那一轮不占 isStreaming：学生不该为了看教练开口而等 —— 种下的那句开场已经
// 显示着了，学生随时可以先说话，说话就把这一轮掐掉（见 requestOpening）。
function abortOpening() {
  openingController?.abort()
  openingController = null
}

function unwrap(response) {
  return response?.data?.data ?? response?.data ?? response
}

function hydrateSession(session) {
  sessionId.value = String(session?.session_id || '')
  const restoredMessages = Array.isArray(session?.messages)
    ? session.messages.filter((message) => message && ['user', 'assistant'].includes(message.role) && String(message.text || '').trim())
    : []
  messages.value = restoredMessages
  openingPending.value = Boolean(session?.opening_pending)
  confirmedFacts.value = Array.isArray(session?.confirmed_facts) ? session.confirmed_facts : []
  assumptions.value = Array.isArray(session?.assumptions) ? session.assumptions : []
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
    // 恢复出来的老会话不会走开场那一轮（见下面 requestOpening 的守卫），所以这里得自己
    // 读一次 —— 否则页头会显示"教练看不到你的文件"，而学生明明已经打开了文件夹。
    readWorkspaceShown()
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
    messages: messages.value.map((message) => ({ role: message.role, text: message.text })),
    confirmed_facts: confirmedFacts.value,
    assumptions: assumptions.value,
  }
}

// 保存只做持久化，不再拿返回值回写任何进度 —— 阶段账本已经删掉了。
async function saveSessionState() {
  if (!sessionId.value) return
  await advancedLearningApi.savePracticeSession(sessionId.value, sessionPayload())
}


function requestHint() {
  sendMessage(`请围绕“${props.task.title}”给我一个不直接泄露答案的提示。`)
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

// 主讲材料有两条路进上下文：服务端按本次提问挑出的相关段落（带 resource_id 时，
// 见 classroom_chat._build_classroom_path_context），和这里客户端截一段塞进 script。
// 同一份教材喂两遍是纯浪费 —— 服务端那份更强（按问题选段、预算 3600 对我们这 1200、
// 而且是权威副本）。所以只在**服务端拿不到**的时候才带这一份。
function clientChapterSummary() {
  if (props.resourceId) return ''
  return props.chapterContent ? `主讲材料摘要：${props.chapterContent.slice(0, 1200)}` : '当前没有可用主讲材料'
}

// 分段信息里不再有 phase / phase_advance —— 阶段账本和服务端那份「当前阶段是「…」」
// 的提示词都删了（见 classroom_chat 的 `_compose_user_prompt` 注释：那段话在**生产**
// 一个不存在的议程）。这里少传两个字段完全没影响，因为服务端已经不看它们了。
//
// `script` 同理：任务说明现在**以服务端账本为准**（`AdvancedPracticeSession.task_snapshot`），
// 这里这一行只是历史字段，服务端不采信。任务本身改由 TaskBar 直接展示给学生看。
//
// `workspace` 是**发送这一刻**现取的工作区只读快照（见 workspaceReader）。永远给一份
// 带 available 字段的对象，绝不漏字段 —— 让后端去猜"这个键为什么没有"是丢信息的做法。
function practiceSegment() {
  readWorkspaceShown()
  return {
    id: `practice-${props.task.id}`,
    type: 'practice',
    title: props.task.title,
    script: [props.task.brief, props.task.problem, `重点能力：${props.task.focus}`, `验收标准：${(props.task.criteria || []).join('；')}`, clientChapterSummary()].filter(Boolean).join('\n'),
    points: (props.task.constraints || []).slice(0, 6),
    question: { prompt: '请围绕这个任务推进对话。' },
    workspace: workspaceShown.value,
  }
}

// 读一份新的工作区快照，同时把它记下来给页头那条提示用 —— 两处必须是同一份，
// 否则"教练看到的是这个"就和实际发出去的请求对不上了。
function readWorkspaceShown() {
  workspaceShown.value = props.workspaceReader?.() ?? { available: false }
}

// 学生发言和教练开场走的是同一条流式接口，只有 scenario 不同
// （服务端按 scenario 拼提示词，见 classroom_chat._compose_user_prompt）。
function streamCoachReply({ scenario, text, signal, onChunk }) {
  return fundamentalsApi.streamAssistantReply({
    path_id: Number(props.pathId),
    node_id: Number(props.nodeId),
    resource_id: props.resourceId ? Number(props.resourceId) : null,
    practice_session_id: sessionId.value,
    scenario,
    text,
    segment: practiceSegment(),
  }, (event) => {
    if (event?.error) throw new Error(event.error)
    // 只认文本增量。以前这里要显式忽略服务端推的 type='phase' 进度事件；
    // 阶段机删掉后已经没有任何地方会推它了。
    if ((event?.type === 'chunk' || event?.type === 'content') && event.content) onChunk(String(event.content))
  }, signal)
}

// 教练开口那一轮：任务刚打开时服务端只种了一句同步的开场，它读得到任务名但不读
// 任务内容。真正"读过任务再开口"的是教练，以前要等学生先说一句才会被调用 ——
// 于是第一问永远是同一句通用话术，学生看完只能回"你在说啥"。现在把它提前到第一轮。
async function requestOpening() {
  if (!openingPending.value || !sessionId.value) return
  if (isStreaming.value) return
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

async function sendMessage(forcedText = '') {
  const text = String(forcedText || draft.value).trim()
  if (!text || isStreaming.value || isLoadingSession.value || !sessionId.value) return
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
      signal: requestController.signal,
      onChunk: (content) => {
        responseMessage.text += content
        scrollToLatest()
      },
    })
    if (!responseMessage.text.trim()) throw new Error('LearnMate 暂时没有返回有效追问')
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
  if (!sessionId.value || isStreaming.value) return
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

// 草稿一变就重新量高度。监听而不是只挂在 @input 上，是因为发完之后 draft 被清空 ——
// 只处理输入事件的话，框会停在上一句撑开的高度上缩不回去。
watch(draft, () => nextTick(growComposer))
// 输入区出现前的那段时间也要能量一次（会话加载中它还不存在）
onMounted(() => nextTick(growComposer))

watch(() => props.task?.id, () => { void initializeSession() }, { immediate: true })
onBeforeUnmount(() => {
  sessionLoadVersion += 1
  requestController?.abort()
  abortOpening()
  composerResizeObserver?.disconnect()
  composerResizeObserver = null
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
  grid-template-rows: auto minmax(0, 1fr) auto;
  overflow: hidden;
}

/* ── 头部 ───────────────────────────────────────────── */
.practice-dialogue__header {
  display: grid;
  min-width: 0;
  gap: 7px;
  padding: 11px 15px;
  border-bottom: 1px solid var(--line);
  background: #fbfcfa;
}
/* 标题那一行原样保留，只是外面多包了一层：页头还要纵向放下"教练能看到什么"那一条，
   而它不该挤进标题行。这样也不必去动 .practice-dialogue 的 grid-template-rows ——
   那是上一轮为高度塌陷踩过坑的地方（可选行会把它下面的行错位）。 */
.practice-dialogue__titlebar {
  display: flex;
  min-width: 0;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}
.practice-dialogue__eyebrow { margin: 0; flex: 0 1 auto; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.practice-dialogue__tools { display: flex; min-width: 0; flex: 0 0 auto; align-items: center; gap: 8px; }
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

/* ── 教练能看到什么（页头第二行）────────────────────────
   一条常驻的窄条。它在说"这一轮教练看到的是这个" —— 与学生猜的那件事直接对应，
   所以不藏进菜单、也不做成悬浮提示。 */
.practice-visibility { min-width: 0; }
.practice-visibility__toggle,
.practice-visibility__blind {
  display: flex;
  width: 100%;
  min-width: 0;
  align-items: center;
  gap: 6px;
  margin: 0;
  padding: 4px 9px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: #f6f9f2;
  color: var(--muted);
  font-size: 11px;
  line-height: 1.5;
  text-align: left;
}
.practice-visibility__toggle { cursor: pointer; }
.practice-visibility__toggle:hover { border-color: #c8d9b7; background: #f1f6eb; color: var(--accent-deep); }
.practice-visibility__blind { border-style: dashed; background: transparent; }
.practice-visibility__toggle svg,
.practice-visibility__blind svg { flex: 0 0 auto; }
.practice-visibility__toggle svg { color: var(--accent-deep); }
/* 文案可能很长（文件多、名字长），截断而不是换行 —— 它是一行摘要，展开看细节。 */
.practice-visibility__headline { min-width: 0; flex: 1 1 auto; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.practice-visibility__details {
  display: grid;
  gap: 3px;
  margin: 6px 0 0;
  padding: 8px 10px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: #fff;
  color: var(--muted);
  font-size: 11px;
  line-height: 1.6;
  list-style: none;
}

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
  /* 高度由 growComposer() 按内容算（见脚本）。这里只兜底 min/max：JS 没跑起来时
     也不至于塌成一条线；resize: none 是因为手动拖拽会和自动高度打架。 */
  height: 62px;
  min-height: 62px;
  max-height: 200px;
  resize: none;
  overflow-y: hidden;
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

/* ── 紧凑模式：放进 IDE 右半屏 ──────────────────────────
   高度撑满容器（由外层栅格决定），而不是按视口算出来的那个 clamp。 */
.practice-dialogue.is-compact { height: 100%; min-height: 0; border-radius: 14px; }
.practice-dialogue.is-compact .practice-messages { padding: 16px; }
.practice-dialogue.is-compact .practice-message { max-width: 100%; }

@keyframes pulse { 0%, 60%, 100% { opacity: .3; transform: translateY(0); } 30% { opacity: 1; transform: translateY(-2px); } }
@keyframes spin { to { transform: rotate(360deg); } }
.spin { animation: spin .8s linear infinite; }

/* 这里原来有一组 @container 查询，是因为头部挤着眉标 + 阶段进度 + 提交 + 溢出菜单四样，
   面板拖到 302px 就会顶出右边界。现在头部只剩眉标（可省略号）+ 一个菜单按钮，
   任何宽度都放得下 —— 容器查询连同 container-type 一起撤掉，别留着做无用功。 */

@media (max-width: 780px) {
  .practice-dialogue { height: clamp(420px, calc(100vh - 300px), 620px); }
  .practice-messages { min-height: 360px; }
}
</style>
