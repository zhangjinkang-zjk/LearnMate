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
        </div>

        <form class="conversation-input" @submit.prevent="sendMessage">
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
import { getNextPortraitInterviewQuestion } from '../../shared/api/portraitApi'
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
  [
    '你现在最想系统学哪一个方向或主题？可以说一门学科、一个技术领域或一项工作技能，比如 Python 数据分析、智能体应用开发、机械制图。',
    '如果先选一个方向开始学，你会选什么？说关键词就可以，比如前端开发、产品设计、数据分析；还没想好也可以直接说。',
    '最近最想弄懂哪一类知识或技能？不用想得很完整，先告诉我一个方向，例如编程、项目管理或知识库应用。'
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

const usableDirection = () => {
  const answer = String(portraitAnswers.value[0] || '').replace(/\s+/g, ' ').trim()
  if (!answer || NON_DIRECTION_ANSWERS.has(answer.toLowerCase())) return ''
  // 单个数字或符号（"1"、"？"）不是方向；单个汉字或字母（"学"、"a"）可能是。
  if (answer.length < 2 && !/^[a-zA-Z一-龥]$/.test(answer)) return ''
  return answer.slice(0, 24)
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

const getResponseData = result => result?.data?.data ?? result?.data ?? result

// 题面先由本地兜底表立刻给出，不等模型：这一问实测要 ~50 秒（提示词 1662 字、
// 输出只有一行 JSON，慢在模型本身），让访谈卡在 "..." 上一分钟比模板题更难看。
// 模型那一版如果赶在用户动笔之前回来，再由 upgradeQuestion 替换掉屏幕上的题面。
const askNextQuestion = () => {
  if (step.value >= PORTRAIT_MAX_STEPS) return
  const currentStep = step.value
  const question = fallbackQuestionForStep(currentStep)
  portraitQuestions.value[currentStep] = question
  messages.value.push({ role: 'assistant', text: question })
  persistInterview()
  void upgradeQuestion(currentStep, question)
}

const upgradeQuestion = async (currentStep, shown) => {
  try {
    const result = await getNextPortraitInterviewQuestion({
      dialogue: buildDialogue(currentStep),
      step: currentStep,
      max_steps: PORTRAIT_MAX_STEPS
    })
    const data = getResponseData(result)
    const question = String(data?.question || '').trim()
    // 只认模型写的那一版：后端拿不到模型时也会回一句兜底题，直接替换等于把一句
    // 模板换成另一句模板，题面会在用户眼皮底下改样。
    if (data?.source !== 'agent' || !question || question === shown) return
    // 用户已经动笔、或者这一轮已经答完：不再改题面。
    if (step.value !== currentStep || messageDraft.value.trim()) return
    const index = messages.value.findIndex(message => message.role === 'assistant' && message.text === shown)
    if (index < 0) return
    messages.value[index] = { role: 'assistant', text: question }
    portraitQuestions.value[currentStep] = question
    persistInterview()
  } catch (error) {
    // 拿不到就用手上这句兜底题，访谈本身不中断。
    console.warn('[LearnMate] portrait question unavailable, keeping the local question:', error)
  }
}

// 方向/目标现在由访谈问出来（DirectionSetupPage 那一步只强制身份，方向和目标允许
// 留空并注明"交给访谈补齐"），必须在跳诊断页之前落盘：诊断的 /learning/diagnosis/start
// 要求两者非空，否则就是一个必然 422 的请求。
// 第 1 问固定问方向、第 2 问固定问用途 —— prompts/portrait/interview_next.yaml 把
// 这条顺序写成了"必须遵守"的硬规则，所以按下标取是稳的。
const persistInterviewDirection = () => {
  const answers = portraitAnswers.value.map(answer => String(answer || '').trim())
  if (answers[0]) learningState.direction = answers[0].slice(0, 120)
  if (answers[1]) learningState.goal = answers[1].slice(0, 160)
  persistLearningProfile()
}

const sendMessage = async () => {
  const value = messageDraft.value.trim()
  if (!value) return
  messages.value.push({ role: 'user', text: value })
  messageDraft.value = ''

  if (step.value < PORTRAIT_MAX_STEPS) {
    portraitAnswers.value[step.value] = value
    step.value += 1
    persistInterview()
    if (step.value < PORTRAIT_MAX_STEPS) {
      askNextQuestion()
    } else {
      persistInterviewDirection()
      sessionStorage.removeItem('learnmate_portrait_summary')
      sessionStorage.removeItem('learnmate_diagnosis_result')
      router.push('/onboarding/diagnosis')
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
