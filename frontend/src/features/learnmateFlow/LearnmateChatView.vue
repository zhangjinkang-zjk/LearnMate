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
      <div class="conversation-list" role="log" aria-live="polite">
        <div v-for="(message, index) in messages" :key="`${message.role}-${index}`" class="chat-message" :class="`chat-message--${message.role}`">
          {{ message.text }}
        </div>
        <div v-if="isLoading" class="chat-message chat-message--assistant chat-message--typing">...</div>
      </div>

      <form class="conversation-input" @submit.prevent="sendMessage">
        <input
          v-model="messageDraft"
          type="text"
          autocomplete="off"
          :placeholder="step < PORTRAIT_MAX_STEPS ? 'Reply to LearnMate...' : 'Type start to enter your path...'"
          aria-label="Message LearnMate"
        />
        <button type="submit" :disabled="!messageDraft.trim() || isLoading || isSaving" aria-label="Send message">
          <span aria-hidden="true">↗</span>
        </button>
      </form>
    </section>
  </main>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { getNextPortraitInterviewQuestion, initPortraitFromDialogue } from '../../shared/api/portraitApi'

const router = useRouter()
const PORTRAIT_MAX_STEPS = 5
const step = ref(0)
const messageDraft = ref('')
const portraitQuestions = ref([])
const portraitAnswers = ref([])
const isLoading = ref(false)
const isSaving = ref(false)
const messages = ref([
  { role: 'assistant', text: 'Hi, I am LearnMate. Let\'s get to know how you learn.' }
])

const fallbackQuestions = [
  '最近你真正想学会、做成，或者认真搞明白的一件事是什么？',
  '围绕这件事，你最希望自己获得什么结果？',
  '学习过程中，哪一部分最容易让你卡住？',
  '当你卡住时，你希望我用什么方式帮你？',
  '最后，你希望我用什么节奏陪你推进学习？'
]

fallbackQuestions.splice(0, fallbackQuestions.length,
  '你想重点学习什么方向或主题？',
  '你希望通过学习最终达成什么目标？',
  '你目前对这个方向了解多少，最卡在哪里？',
  '你每周大约能投入多少时间学习？',
  '你更喜欢怎样的学习方式：讲解、练习还是项目实践？'
)

const buildDialogue = () => portraitQuestions.value.map((question, index) => ({
  question,
  answer: portraitAnswers.value[index] || ''
})).filter(turn => turn.question || turn.answer)

const getResponseData = result => result?.data?.data ?? result?.data ?? result

const askNextQuestion = async () => {
  if (step.value >= PORTRAIT_MAX_STEPS || isLoading.value) return
  isLoading.value = true
  const currentStep = step.value
  let question = fallbackQuestions[currentStep]
  try {
    const result = await getNextPortraitInterviewQuestion({
      dialogue: buildDialogue(),
      step: currentStep,
      max_steps: PORTRAIT_MAX_STEPS
    })
    const data = getResponseData(result)
    question = String(data?.question || question).trim()
  } catch (error) {
    console.warn('[LearnMate] portrait question unavailable, using fallback:', error)
  }
  portraitQuestions.value[currentStep] = question
  messages.value.push({ role: 'assistant', text: question })
  isLoading.value = false
}

const savePortrait = async () => {
  if (isSaving.value) return
  isSaving.value = true
  try {
    await initPortraitFromDialogue({ dialogue: buildDialogue() })
  } catch (error) {
    console.warn('[LearnMate] portrait save failed:', error)
  } finally {
    isSaving.value = false
  }
}

const sendMessage = async () => {
  const value = messageDraft.value.trim()
  if (!value || isLoading.value || isSaving.value) return
  messages.value.push({ role: 'user', text: value })
  messageDraft.value = ''

  if (step.value < PORTRAIT_MAX_STEPS) {
    portraitAnswers.value[step.value] = value
    step.value += 1
    if (step.value < PORTRAIT_MAX_STEPS) {
      await askNextQuestion()
    } else {
      await savePortrait()
      messages.value.push({ role: 'assistant', text: 'Thanks. I have a clear picture now. Type start when you are ready.' })
    }
    return
  }

  window.dispatchEvent(new CustomEvent('learnmate:learning-profile-ready', { detail: buildDialogue() }))
  router.push('/chat')
}

onMounted(() => {
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

.conversation-list {
  position: absolute;
  top: clamp(150px, 24vh, 260px);
  left: clamp(120px, 20vw, 380px);
  display: grid;
  gap: 22px;
  width: min(850px, 68vw);
  max-height: 58vh;
  overflow-y: auto;
  scrollbar-width: none;
}

.conversation-list::-webkit-scrollbar {
  display: none;
}

.conversation-input {
  position: absolute;
  bottom: clamp(24px, 5vh, 56px);
  left: 50%;
  display: flex;
  align-items: center;
  width: min(660px, calc(100% - 40px));
  padding: 7px 8px 7px 20px;
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
  animation: messageIn 0.45s cubic-bezier(0.16, 1, 0.3, 1) both;
}

.chat-message--typing {
  width: 30px;
  letter-spacing: 0.18em;
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
    left: 18px;
    width: calc(100% - 36px);
    max-height: 52vh;
    gap: 18px;
  }

  .conversation-input {
    bottom: 20px;
    width: calc(100% - 36px);
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
