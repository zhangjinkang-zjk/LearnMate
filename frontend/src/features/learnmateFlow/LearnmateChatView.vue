<template>
  <main class="learn-chat-page">
    <div class="learn-chat-wash" aria-hidden="true"></div>
    <div class="learn-chat-word" aria-hidden="true">
      <span>LEARN</span>
      <span>MATE</span>
    </div>

    <router-link class="learn-chat-back" to="/select-identity" @click.prevent="router.push('/select-identity')">
      <span aria-hidden="true">←</span>
      <span>BACK</span>
    </router-link>

    <section class="conversation-shell" aria-label="LearnMate conversation">
      <div class="conversation-track">
        <div ref="conversationList" class="conversation-list" role="log" aria-live="polite">
          <div v-for="(message, index) in messages" :key="`${message.role}-${index}`" class="chat-message" :class="`chat-message--${message.role}`">
            {{ message.text }}
          </div>
          <!-- 正在生成的题面：字是一个一个上来的，还没出一个字时先占住位置，
               免得看上去像没反应。 -->
          <div
            v-if="liveQuestionStep >= 0"
            class="chat-message chat-message--assistant"
            :class="{ 'chat-message--typing': !liveQuestion }"
            aria-live="polite"
          >{{ liveQuestion || '···' }}</div>
        </div>

        <!-- 五问答完还没拿到方向或目标：换成补填，而不是继续假装在聊天。
             诊断的 /learning/diagnosis/start 要求两者非空，缺一个就是必然 422 的请求；
             而"没有方向"这件事本来也不该由兜底文案替学生编一个出来。 -->
        <form v-if="needsSlots" class="conversation-input conversation-input--slots" @submit.prevent="submitSlots">
          <p class="slots-hint">{{ slotsHint }}</p>
          <input
            v-model="slotsDraft.direction"
            type="text"
            autocomplete="off"
            placeholder="想学什么？一个词也行，比如机械制图"
            aria-label="学习方向"
          />
          <input
            v-model="slotsDraft.goal"
            type="text"
            autocomplete="off"
            placeholder="想拿它做成什么？比如做出一个零件图"
            aria-label="学习目标"
          />
          <button type="submit" :disabled="!slotsReady" aria-label="继续">
            <span aria-hidden="true">↗</span>
          </button>
          <p v-if="slotsError" class="slots-error" role="alert">{{ slotsError }}</p>
        </form>

        <form v-else class="conversation-input" @submit.prevent="sendMessage">
          <input
            v-model="messageDraft"
            type="text"
            autocomplete="off"
            :placeholder="inputPlaceholder"
            aria-label="Message LearnMate"
          />
          <button type="submit" :disabled="!messageDraft.trim()" aria-label="Send message">
            <span aria-hidden="true">↗</span>
          </button>
        </form>
      </div>
    </section>
  </main>
</template>

<script setup>
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { streamNextPortraitInterviewQuestion } from '../../shared/api/portraitApi'
import { learningState, persistLearningProfile } from '@/entities/learning/learningState'

const router = useRouter()
const PORTRAIT_MAX_STEPS = 5
const step = ref(0)
const messageDraft = ref('')
const portraitQuestions = ref([])
const portraitAnswers = ref([])
// 没有 isLoading：下一问不再等网络（本地兜底题立刻显示，模型版本在后台替换），
// 用户答完就能接着答，输入框和气泡都没有需要禁用的等待窗口。
const isSaving = ref(false)
const messages = ref([])
const conversationList = ref(null)
// 访谈问不出方向/目标时启用的补填入口（见 finishInterview）
const needsSlots = ref(false)
const slotsDraft = ref({ direction: '', goal: '' })
const slotsHint = ref('')
const slotsError = ref('')
const slotsReady = computed(() => Boolean(slotsDraft.value.direction.trim() && slotsDraft.value.goal.trim()))

// 第 5 题答完后 step 就满了，此时 sendMessage 会直接跳到能力诊断，
// 原来的文案「Type start to enter your path...」会诱导用户继续输入，看起来像卡死。
const inputPlaceholder = computed(() => (
  step.value < PORTRAIT_MAX_STEPS ? 'Reply to LearnMate...' : '正在进入下一步…'
))

const scrollToLatest = async () => {
  await nextTick()
  requestAnimationFrame(() => {
    const element = conversationList.value
    if (!element) return
    element.scrollTop = element.scrollHeight
    requestAnimationFrame(() => {
      element.scrollTop = element.scrollHeight
    })
  })
}

watch(
  () => [messages.value.length, isSaving.value],
  () => void scrollToLatest(),
  { flush: 'post' },
)

const fallbackQuestionVariants = [
  // 第 1 问的题面是写死的，不走模型（后端 _DIRECTION_QUESTION）：它前面没有对话可依据，
  // 模型加不了东西，却要学生先等一次首字延迟。这里放的是**同一句话**，有跨语言字面量
  // 测试钉着两边一字不差 —— 后端现在也会把这句当流式分片推过来，所以这一份只在
  // 整个请求都没打通（网络断了）时才会显示，措辞分叉等于给学生两个不同的第一问。
  [
    '你现在最想系统学哪一个方向或主题？可以说一门学科、一个技术领域或一项工作技能，比如 Python 数据分析、智能体应用开发、机械制图。'
  ],
  [
    first => `如果把「${first}」做好了，你最想拿它解决什么？可以说会用到的人、场景，或你希望看到的结果。`,
    first => `你为什么现在想把「${first}」学会？是要交付一个东西、应对一项工作，还是想先做出自己的作品？`,
    first => `想象一下「${first}」真正派上用场的那天：你希望它替你完成哪件事？`
  ],
  [
    first => `你以前试过「${first}」吗？可以从最近一次尝试说起，不管是照着教程做，还是只看懂了一部分。`,
    first => `现在把「${first}」交给你，你能先自己完成哪一步？说到具体动作就好。`,
    first => `关于「${first}」，有没有一个小成果是你已经做出来的？哪怕只是跟着示例跑通也算。`,
    first => `上次做「${first}」时，你实际先做了什么？可以从准备资料、数据或动手写第一步说起。`
  ],
  [
    first => `做「${first}」时，哪一个动作最容易让你停住或返工？比如拆需求、选方案、调试、检查结果。`,
    first => `「${first}」第一次没做好时，你最不知道该看哪里？可以说一个具体场面。`,
    first => `从「${first}」的开始到交付，中间哪一段你最没把握？比如判断方向、动手实现，或确认效果。`,
    first => `如果把「${first}」换一个相近场景，你最担心哪一步不会迁移？可以说一个遇到过的变化。`
  ],
  [
    '你希望什么时候能真正用上这项能力？可以说一个日期、一个项目节点，或大概的时间范围。',
    '为了把这件事练到能用，你每周能稳定留出多少时间？比如零散的几次半小时，或周末集中练。',
    '你想先练一个多大的小任务？比如先做一个最小版本，再逐步加功能。'
  ]
]

// 第 1 题答成这些时，"答案"里没有可用的方向。模板里的「如果把「{first}」做好了」
// 会把它原样嵌进去，于是"这句回答没有信息量"被后面几问各复读一遍 —— 这是"五个
// 问题过于生硬"的主要来源（第 1 问本身就允许回答"还没想好"）。
// 这份表要和后端 _NON_DIRECTION_ANSWERS 保持一致。
const NON_DIRECTION_ANSWERS = new Set([
  '无', '没有', '暂无', '不知道', '还不知道', '不知道学什么', '不清楚', '不确定',
  '不明白', '随便', '都行', '都可以', '什么都行', '还没想好', '没想好',
  '嗯', '哦', '好的', '好', '是', '否', 'test', '测试',
  '1', '2', '3', '4', '5', '0', '。', '？', '?', '.', '无。', '不知道。', '还没想好。',
])

// 一句话能不能当学习方向用。判定要和后端 is_usable_direction 逐字对齐（两份表有
// 一致性测试钉着）——判定只服务"这一问怎么问"是旧写法，现在落盘那条路也要过它。
const isUsableDirection = value => {
  const answer = String(value || '').replace(/\s+/g, ' ').trim()
  // 比对去空白：把「不 知道」「还没 想好」敲进来时，和连着写是同一句废话（后端同此）。
  const compact = answer.replace(/\s+/g, '')
  if (!compact || NON_DIRECTION_ANSWERS.has(compact.toLowerCase())) return false
  // 单个数字或符号（"1"、"？"）不是方向；单个汉字或字母（"学"、"a"）可能是。
  if (compact.length < 2 && !/^[a-zA-Z一-龥]$/.test(compact)) return false
  return true
}

const usableDirection = () => {
  const answer = String(portraitAnswers.value[0] || '').replace(/\s+/g, ' ').trim()
  return isUsableDirection(answer) ? answer.slice(0, 24) : ''
}

// 从整场访谈里抽出方向和目标。
//
// 两个值各自对应访谈的哪一问是**写死的**：第 1 问问方向，第 2 问问用途；只有第 1 问答不出
// 方向时，后端才会把第 2 问换成"换一种问法再问一次方向"（`_stage_instruction_for`），用途
// 顺延到第 3 问。所以：
//   方向 = 前两问里第一个可用的回答（后端 DIRECTION_SLOTS 是同一个数字）
//   目标 = **用途那一问**的回答，不看别的题
//
// 绝不能写成"两个值都扫全部回答取第一个可用的"：学生第 1 问答「机械制图」、第 2 问答
// 「用来就业」时，那样写会把两者对调 —— 而它们一个决定学什么、一个只影响怎么问，
// 对调的后果是整套课程按"用来就业"生成。同理，第 2 问答不出用途时也不能顺手拿第 3 问
// （起点）的回答顶上：那不是目标。拿不到就留空，由补填入口收（finishInterview）。
const DIRECTION_SLOTS = 2
const resolveInterviewSlots = answers => {
  const values = (answers || []).map(answer => String(answer || '').replace(/\s+/g, ' ').trim())
  let directionAt = -1
  for (let index = 0; index < Math.min(values.length, DIRECTION_SLOTS); index += 1) {
    if (isUsableDirection(values[index])) { directionAt = index; break }
  }
  // 第 1 问给出了方向 → 用途在第 2 问；第 1 问没给出 → 第 2 问是追问，用途顺延到第 3 问。
  const goalAt = directionAt === 0 ? 1 : 2
  const goal = isUsableDirection(values[goalAt]) ? values[goalAt].slice(0, 160) : ''
  if (directionAt < 0) return { direction: '', goal }
  return { direction: values[directionAt].slice(0, 120), goal }
}

// 拿不到可用的方向时改问这些：不引用用户的回答，也就不会把一句无意义的话放大。
// 与后端 _GENERIC_QUESTION_VARIANTS 对应。
const genericQuestionVariants = [
  [],
  [
    '你希望把想学的这件事用在什么地方？可以是课程作业、实习任务、竞赛项目，或者工作里的某件事。',
    '你打算先拿它做成点什么？说一个你希望看到的结果就够了。'
  ],
  [
    '你以前试过这个方向吗？可以从最近一次尝试说起，照着教程做一遍也算。',
    '现在把这个方向交给你，你能先自己做完哪一步？说个具体动作就好。'
  ],
  [
    '做这件事的时候，哪个动作最容易让你停住或者返工？比如拆需求、选方案、调试、检查结果。',
    '从开始到交付，中间哪一段你最没把握？比如判断方向、动手实现，或者确认效果。'
  ],
  []
]

const fallbackQuestionForStep = currentStep => {
  const first = usableDirection()
  const seedText = portraitAnswers.value.slice(0, currentStep).join('')
  const seed = [...seedText].reduce((sum, char) => sum + char.charCodeAt(0), 0)
  const index = Math.min(currentStep, fallbackQuestionVariants.length - 1)
  const variants = first
    ? fallbackQuestionVariants[index]
    : (genericQuestionVariants[index]?.length ? genericQuestionVariants[index] : fallbackQuestionVariants[index])
  const selected = variants[(seed + currentStep) % variants.length]
  return typeof selected === 'function' ? selected(first) : selected
}

const INTERVIEW_KEY = 'learnmate_portrait_dialogue'

// upTo 用来在请求下一问时只送"已经答完"的轮次：当前这一问刚显示出来、还没作答，
// 一起送过去会让模型以为用户看过它却答不出来。
const buildDialogue = (upTo = portraitQuestions.value.length) => portraitQuestions.value
  .slice(0, upTo)
  .map((question, index) => ({
    question,
    answer: portraitAnswers.value[index] || ''
  }))
  .filter(turn => turn.question || turn.answer)

// 每答一轮就落一次盘。原先只在答完第 5 题那一刻才写 sessionStorage，
// 于是中途刷新或切走会把前面几轮回答全部丢掉，回来只能从第 0 题重来。
const persistInterview = () => {
  try {
    sessionStorage.setItem(INTERVIEW_KEY, JSON.stringify(buildDialogue()))
  } catch { /* 隐私模式等写不进去的情况退化成原来的行为，不打断访谈 */ }
}

// 只接续"答到一半"的访谈：已答完的那次是用户主动回来改答案，
// 继续保持原来的从头重来语义，不动它。
const restoreInterview = () => {
  let saved
  try {
    saved = JSON.parse(sessionStorage.getItem(INTERVIEW_KEY) || '[]')
  } catch {
    return false
  }
  if (!Array.isArray(saved) || !saved.length) return false
  const questions = saved.map(turn => String(turn?.question || ''))
  const answers = saved.map(turn => String(turn?.answer || ''))
  const answered = answers.filter(answer => answer.trim()).length
  // 0 轮没有可接续的内容；答满了说明这份访谈已经用过，交给上面的"重来"语义。
  if (!answered || answered >= PORTRAIT_MAX_STEPS) return false
  portraitQuestions.value = questions
  portraitAnswers.value = answers
  step.value = answered
  messages.value = []
  for (let index = 0; index < answered; index += 1) {
    if (questions[index]) messages.value.push({ role: 'assistant', text: questions[index] })
    if (answers[index]) messages.value.push({ role: 'user', text: answers[index] })
  }
  return true
}

// 正在边写边显示的题面，以及它属于哪一问（-1 表示当前没有在生成的题面）。
const liveQuestion = ref('')
const liveQuestionStep = ref(-1)

// 把"正在生成"的那一问定稿：题面取屏幕上已经显示出来的那段 —— 用户看到的就是它，
// 事后再换成别的等于在他眼皮底下改题。一个字都没流出来（模型报错/超时）时
// 才退回本地兜底题，访谈本身不中断。
const settleLiveQuestion = text => {
  const at = liveQuestionStep.value
  liveQuestionStep.value = -1
  liveQuestion.value = ''
  if (at < 0) return
  const question = String(text || '').trim() || fallbackQuestionForStep(at)
  portraitQuestions.value[at] = question
  // 用户在这一问还没写完时就作答了（step 已经往前走）：消息流里已经有他的回答，
  // 这时候再补一条问题会变成"答在问前"，所以只记进对话、不补气泡。
  if (step.value === at) messages.value.push({ role: 'assistant', text: question })
  persistInterview()
}

// 题面由模型边写边推。以前是"本地兜底题先上屏、模型那版回来再替换"，而模型要几十秒
// 才回来，学生通常已经动笔 —— 替换的前提（step 没变、输入框还是空的）判不成立，
// 屏幕上留下的就永远是那句本地模板，看起来就是"题目是写死的"。
const askNextQuestion = async () => {
  if (step.value >= PORTRAIT_MAX_STEPS) return
  const currentStep = step.value
  let streamed = ''
  liveQuestion.value = ''
  liveQuestionStep.value = currentStep
  try {
    await streamNextPortraitInterviewQuestion(
      {
        dialogue: buildDialogue(currentStep),
        step: currentStep,
        max_steps: PORTRAIT_MAX_STEPS
      },
      event => {
        // 用户已经作答（这一问定稿了）之后到的分段不再改屏幕。
        if (event?.type !== 'reply_delta' || liveQuestionStep.value !== currentStep) return
        streamed += String(event.text || '')
        liveQuestion.value = streamed
        void scrollToLatest()
      }
    )
  } catch (error) {
    // 流断了也把已经显示出来的那段留下，实在一个字都没有才用兜底题。
    console.warn('[LearnMate] portrait question stream failed:', error)
  }
  if (liveQuestionStep.value === currentStep) settleLiveQuestion(streamed)
}

// 方向/目标现在由访谈问出来（DirectionSetupPage 那一步只强制身份，方向和目标允许
// 留空并注明"交给访谈补齐"），必须在跳诊断页之前落盘：诊断的 /learning/diagnosis/start
// 要求两者非空，否则就是一个必然 422 的请求。
//
// **拿不到就一个都不写。** 以前这里是 `if (answers[0])`，等于不管答的是什么照单全收：
// 第 1 问答了「不知道」，它就变成学习方向，一路传到科目拆解和路径生成。
// 不写还顺带保住了定向页填过的值（context 的兜底顺序是 learningState → localStorage）。
const persistInterviewDirection = () => {
  const { direction, goal } = resolveInterviewSlots(portraitAnswers.value)
  if (direction) learningState.direction = direction
  if (goal) learningState.goal = goal
  persistLearningProfile()
}

// 诊断要用的那两个值，取的是"最终生效"的那一份：访谈问出来的优先，其次定向页填过的。
// 只认可用的值——上一轮跑坏留下的 localStorage（比如 direction='不知道'）不算数，
// 否则补填入口永远不会出现。
const effectiveSlots = () => {
  const stored = key => String(localStorage.getItem(key) || '').replace(/\s+/g, ' ').trim()
  const direction = String(learningState.direction || stored('learnmate_direction') || '').trim()
  const goal = String(learningState.goal || stored('learnmate_goal') || '').trim()
  return {
    direction: isUsableDirection(direction) ? direction : '',
    goal: isUsableDirection(goal) ? goal : '',
  }
}

// 访谈走完了。两个值都齐就直接进诊断；缺哪个就把输入换成补填入口。
const finishInterview = () => {
  persistInterviewDirection()
  const { direction, goal } = effectiveSlots()
  if (direction && goal) return true
  slotsDraft.value = { direction, goal }
  slotsHint.value = !direction
    ? '就差一个学习方向：想学什么？给我一个词也行。'
    : '再补一句想拿它做成什么，就可以开始基础检测了。'
  needsSlots.value = true
  return false
}

const submitSlots = () => {
  const direction = slotsDraft.value.direction.trim()
  const goal = slotsDraft.value.goal.trim()
  if (!isUsableDirection(direction)) {
    slotsError.value = '这一句还看不出你想学什么，换一个说法：一门课、一个工具、一类问题都可以。'
    return
  }
  if (!isUsableDirection(goal)) {
    slotsError.value = '再说一句你想拿它做成什么就行，哪怕只是"做出一个小作品"。'
    return
  }
  slotsError.value = ''
  learningState.direction = direction.slice(0, 120)
  learningState.goal = goal.slice(0, 160)
  persistLearningProfile()
  messages.value.push({ role: 'user', text: direction })
  needsSlots.value = false
  sessionStorage.removeItem('learnmate_portrait_summary')
  sessionStorage.removeItem('learnmate_diagnosis_result')
  router.push('/onboarding/diagnosis')
}

const sendMessage = async () => {
  const value = messageDraft.value.trim()
  if (!value) return
  // 题面还在生成时就作答了：先把屏幕上当时那段定稿，保证消息流里"问在前、答在后"。
  if (liveQuestionStep.value === step.value) settleLiveQuestion(liveQuestion.value)
  messages.value.push({ role: 'user', text: value })
  messageDraft.value = ''

  if (step.value < PORTRAIT_MAX_STEPS) {
    portraitAnswers.value[step.value] = value
    step.value += 1
    persistInterview()
    if (step.value < PORTRAIT_MAX_STEPS) {
      void askNextQuestion()
    } else if (finishInterview()) {
      sessionStorage.removeItem('learnmate_portrait_summary')
      sessionStorage.removeItem('learnmate_diagnosis_result')
      router.push('/onboarding/diagnosis')
    } else {
      // 五问答完还是没拿到方向/目标：上面已经换成补填入口，填完再走。
      void scrollToLatest()
    }
    return
  }

  window.dispatchEvent(new CustomEvent('learnmate:learning-profile-ready', { detail: buildDialogue() }))
  router.push('/chat')
}

onMounted(() => {
  void scrollToLatest()
  // 答到一半就切走/刷新：接着那一轮问下去，而不是把前面几轮回答一起清空重来。
  if (restoreInterview()) {
    const pending = portraitQuestions.value[step.value]
    if (pending) {
      messages.value.push({ role: 'assistant', text: pending })
      void scrollToLatest()
      return
    }
  }
  void askNextQuestion()
})
</script>

<style scoped>
.learn-chat-page {
  position: relative;
  min-height: 100vh;
  overflow: hidden;
  isolation: isolate;
  padding: clamp(28px, 5vw, 64px) clamp(20px, 6vw, 90px) 56px;
  color: #1e3c34;
  background: #1e3c34;
  font-family: Inter, "Helvetica Neue", Arial, sans-serif;
}

.learn-chat-page::before {
  content: "";
  position: absolute;
  inset: 0;
  z-index: -3;
  background:
    linear-gradient(120deg, rgba(3, 18, 13, 0.86) 0%, rgba(28, 68, 53, 0.68) 34%, rgba(5, 24, 17, 0.92) 68%, rgba(53, 93, 69, 0.56) 100%),
    radial-gradient(ellipse 80% 68% at 8% 92%, rgba(151, 184, 137, 0.5), transparent 66%),
    radial-gradient(ellipse 62% 62% at 92% 8%, rgba(2, 13, 10, 0.92), transparent 70%),
    #1e3c34;
  background-size: 180% 180%, 100% 100%, 100% 100%, 100% 100%;
  animation: metalShift 18s ease-in-out infinite alternate;
}

.learn-chat-page::after {
  content: "";
  position: absolute;
  inset: -30%;
  z-index: -1;
  pointer-events: none;
  background: linear-gradient(112deg, transparent 30%, rgba(216, 239, 187, 0.08) 44%, rgba(255, 255, 255, 0.14) 48%, rgba(216, 239, 187, 0.04) 54%, transparent 68%);
  transform: translate3d(-18%, 0, 0) rotate(-3deg);
  animation: metalSheen 14s ease-in-out infinite alternate;
}

.learn-chat-wash {
  position: absolute;
  inset: -18%;
  z-index: -1;
  pointer-events: none;
  opacity: 0.62;
  filter: blur(96px);
  background:
    radial-gradient(ellipse at 35% 30%, rgba(209, 239, 148, 0.34), transparent 46%),
    radial-gradient(ellipse at 72% 72%, rgba(82, 147, 104, 0.38), transparent 52%);
  animation: washDrift 12s ease-in-out infinite alternate;
}

.learn-chat-word {
  position: absolute;
  inset: 8% 0 0;
  z-index: -2;
  display: grid;
  align-content: center;
  justify-items: center;
  color: rgba(173, 198, 178, 0.28);
  font-family: Georgia, "Times New Roman", serif;
  font-size: clamp(116px, 17.5vw, 282px);
  line-height: 0.76;
  user-select: none;
  pointer-events: none;
}

.learn-chat-word span {
  display: block;
  transform: scaleX(1.08);
}

.learn-chat-back {
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

.learn-chat-back:hover {
  color: #e2f452;
  transform: translateX(-4px);
}

.learn-chat-back span:first-child {
  font-size: 20px;
  line-height: 0.6;
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

.conversation-list::-webkit-scrollbar {
  width: 4px;
}

.conversation-list::-webkit-scrollbar-track {
  background: transparent;
}

.conversation-list::-webkit-scrollbar-thumb {
  border-radius: 2px;
  background: rgba(226, 244, 82, 0.36);
}

.conversation-list::-webkit-scrollbar-thumb:hover {
  background: rgba(226, 244, 82, 0.58);
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

.conversation-input input:disabled {
  cursor: wait;
}

/* 补填方向/目标：同一套输入语言，但要点填两行，所以胶囊形改成圆角块，
   按钮挪到右下角。 */
.conversation-input--slots {
  align-items: stretch;
  flex-wrap: wrap;
  gap: 10px 12px;
  padding: 18px 18px 14px;
  border-radius: 20px;
}

.slots-hint {
  flex: 1 0 100%;
  margin: 0;
  color: rgba(243, 240, 231, 0.82);
  font-size: 13px;
  line-height: 1.6;
}

.conversation-input--slots input {
  flex: 1 1 44%;
  min-width: 180px;
  padding: 10px 14px;
  border: 1px solid rgba(243, 240, 231, 0.22);
  border-radius: 999px;
  background: rgba(243, 240, 231, 0.06);
}

.conversation-input--slots input:focus {
  border-color: rgba(226, 244, 82, 0.6);
}

.conversation-input--slots button {
  align-self: flex-end;
  margin-left: auto;
}

.slots-error {
  flex: 1 0 100%;
  margin: 0;
  color: #f2c49b;
  font-size: 12px;
  line-height: 1.6;
}

.learn-dialog {
  width: min(520px, 100%);
  overflow: hidden;
  border-radius: 28px;
  background: #e2f452;
  box-shadow: 0 30px 70px rgba(3, 17, 12, 0.36);
  animation: dialogIn 0.8s cubic-bezier(0.16, 1, 0.3, 1) both;
}

.dialog-bar {
  display: flex;
  justify-content: space-between;
  padding: 22px 28px 0;
  color: rgba(30, 60, 52, 0.56);
  font-size: 10px;
  font-weight: 900;
  letter-spacing: 0.16em;
}

.dialog-content {
  padding: 28px;
}

.chat-thread {
  display: grid;
  gap: 10px;
  margin-bottom: 22px;
}

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

.dialog-greeting {
  margin: 0 0 12px;
  color: rgba(30, 60, 52, 0.58);
  font-size: 10px;
  font-weight: 900;
  letter-spacing: 0.16em;
}

.dialog-content h1 {
  margin: 0;
  color: #1e3c34;
  font-size: clamp(30px, 4vw, 44px);
  font-weight: 800;
  letter-spacing: 0;
  line-height: 1.02;
}

.dialog-prompt {
  margin: 14px 0 24px;
  color: rgba(30, 60, 52, 0.7);
  font-size: 14px;
}

.direction-options {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
}

.direction-option {
  min-height: 48px;
  border: 1px solid rgba(30, 60, 52, 0.24);
  border-radius: 999px;
  background: rgba(243, 240, 231, 0.28);
  color: #1e3c34;
  font-size: 12px;
  font-weight: 800;
  cursor: pointer;
  transition: transform 0.35s cubic-bezier(0.16, 1, 0.3, 1), background 0.35s ease, border-color 0.35s ease, box-shadow 0.35s ease;
}

.direction-option:hover,
.direction-option.selected {
  border-color: #1e3c34;
  background: #f3f0e7;
  transform: translateY(-3px);
  box-shadow: 0 8px 16px rgba(30, 60, 52, 0.16);
}

.goal-field {
  display: grid;
  gap: 9px;
  margin-top: 22px;
  color: rgba(30, 60, 52, 0.72);
  font-size: 12px;
  font-weight: 800;
}

.goal-field textarea {
  width: 100%;
  resize: vertical;
  box-sizing: border-box;
  min-height: 76px;
  padding: 13px 15px;
  border: 1px solid rgba(30, 60, 52, 0.25);
  border-radius: 16px;
  outline: none;
  background: rgba(243, 240, 231, 0.48);
  color: #1e3c34;
  font: inherit;
  font-size: 13px;
  line-height: 1.5;
  transition: border-color 0.25s ease, background 0.25s ease, box-shadow 0.25s ease;
}

.goal-field textarea:focus {
  border-color: #1e3c34;
  background: #f3f0e7;
  box-shadow: 0 0 0 3px rgba(30, 60, 52, 0.12);
}

.dialog-submit {
  min-height: 50px;
  display: inline-flex;
  align-items: center;
  gap: 13px;
  margin-top: 22px;
  padding: 0 20px 0 22px;
  border: 0;
  border-radius: 999px;
  background: #1e3c34;
  color: #e2f452;
  font-size: 11px;
  font-weight: 900;
  letter-spacing: 0.13em;
  cursor: pointer;
  box-shadow: 0 12px 22px rgba(30, 60, 52, 0.22);
  transition: transform 0.4s cubic-bezier(0.16, 1, 0.3, 1), background 0.3s ease, box-shadow 0.4s ease;
}

.dialog-submit:hover:not(:disabled) {
  background: #112a22;
  transform: translateY(-4px) scale(1.03);
  box-shadow: 0 18px 30px rgba(30, 60, 52, 0.3);
}

.dialog-submit:disabled {
  opacity: 0.42;
  cursor: not-allowed;
  box-shadow: none;
}

.dialog-submit span:last-child {
  font-size: 20px;
  line-height: 0.65;
}

@keyframes dialogIn {
  from { opacity: 0; transform: translate3d(-46px, 18px, 0) scale(0.97); }
  to { opacity: 1; transform: translate3d(0, 0, 0) scale(1); }
}

@keyframes messageIn {
  from { opacity: 0; transform: translateY(8px) scale(0.98); }
  to { opacity: 1; transform: translateY(0) scale(1); }
}

@keyframes washDrift {
  from { transform: translate3d(-3%, -2%, 0) scale(0.98); }
  to { transform: translate3d(3%, 2%, 0) scale(1.04); }
}

@keyframes metalShift {
  from { background-position: 0% 50%, 0 0, 0 0, 0 0; filter: saturate(0.94) contrast(1.02); }
  to { background-position: 100% 50%, 0 0, 0 0, 0 0; filter: saturate(1.1) contrast(1.08); }
}

@keyframes metalSheen {
  from { transform: translate3d(-18%, 0, 0) rotate(-3deg); opacity: 0.45; }
  to { transform: translate3d(18%, 0, 0) rotate(-3deg); opacity: 0.88; }
}

@media (max-width: 640px) {
  .learn-chat-page {
    padding: 26px 18px 34px;
  }

  .learn-chat-layout {
    min-height: calc(100vh - 100px);
    align-items: center;
    padding-top: 20px;
  }

  .conversation-list {
    top: 23%;
    max-height: 52vh;
    gap: 18px;
  }

  .conversation-track {
    left: 18px;
    width: calc(100% - 36px);
  }

  .conversation-input {
    bottom: 20px;
    padding-left: 15px;
  }

  .learn-dialog {
    border-radius: 22px;
  }

  .dialog-bar,
  .dialog-content {
    padding-left: 20px;
    padding-right: 20px;
  }

  .direction-options {
    grid-template-columns: 1fr;
  }
}

@media (prefers-reduced-motion: reduce) {
  .learn-chat-page::before,
  .learn-chat-page::after,
  .learn-chat-wash,
  .learn-dialog {
    animation: none !important;
  }
}
</style>
