<template>
  <aside class="learning-assistant surface" aria-label="LearnMate 章节助教">
    <header class="assistant-header">
      <span class="assistant-mark"><Sparkles :size="16" /></span>
      <div>
        <strong>LearnMate</strong>
        <small>正在陪你学习本章</small>
      </div>
    </header>

    <div ref="messageList" class="assistant-messages" aria-live="polite">
      <template v-for="(message, index) in messages" :key="`${message.role}-${index}`">
        <div v-if="message.text || message.role === 'user'" class="assistant-message" :class="`is-${message.role}`">
          <span v-if="message.role === 'assistant'" class="message-avatar">LM</span>
          <div class="message-bubble" v-html="renderMarkdown(message.text)"></div>
        </div>
      </template>
      <div v-if="isStreaming" class="assistant-message is-assistant">
        <span class="message-avatar">LM</span>
        <div class="message-bubble typing" aria-label="正在回复"><span></span><span></span><span></span></div>
      </div>
    </div>

    <div v-if="messages.length === 1" class="question-starters">
      <button type="button" @click="useStarter('用一个具体例子解释本章最重要的概念。')">举个例子</button>
      <button type="button" @click="useStarter('本章内容和上一章有什么联系？')">联系前文</button>
      <button type="button" @click="useStarter('我应该重点记住哪三个要点？')">提炼要点</button>
    </div>

    <p v-if="errorMessage" class="assistant-error">{{ errorMessage }}</p>

    <form class="assistant-composer" @submit.prevent="sendMessage">
      <label class="sr-only" for="assistant-question">围绕本章提问</label>
      <textarea
        id="assistant-question"
        v-model="draft"
        rows="3"
        maxlength="1200"
        :disabled="isStreaming"
        placeholder="围绕本章继续追问…"
        @keydown.ctrl.enter.prevent="sendMessage"
        @keydown.meta.enter.prevent="sendMessage"
      ></textarea>
      <div class="composer-actions">
        <span>{{ draft.length }} / 1200</span>
        <button type="submit" :disabled="!draft.trim() || isStreaming" title="发送问题" aria-label="发送问题">
          <LoaderCircle v-if="isStreaming" class="spin" :size="17" />
          <Send v-else :size="17" />
        </button>
      </div>
    </form>
  </aside>
</template>

<script setup>
import { nextTick, onBeforeUnmount, reactive, ref, watch } from 'vue'
import { LoaderCircle, Send, Sparkles } from 'lucide-vue-next'
import { fundamentalsApi } from '@/shared/api/fundamentalsApi'
import { renderMarkdown } from '@/shared/lib/markdown'

const props = defineProps({
  pathId: { type: [Number, String], required: true },
  nodeId: { type: [Number, String], required: true },
  chapterTitle: { type: String, default: '' },
  chapterContent: { type: String, default: '' },
  knowledgeTags: { type: Array, default: () => [] },
})

const draft = ref('')
const errorMessage = ref('')
const isStreaming = ref(false)
const messageList = ref(null)
const messages = ref([])
let requestController = null

function createWelcomeMessage() {
  return {
    role: 'assistant',
    text: `我已经读到“${props.chapterTitle || '当前章节'}”。你可以问概念、例子，也可以把自己的理解讲给我听。`,
  }
}

function resetConversation() {
  requestController?.abort()
  requestController = null
  isStreaming.value = false
  errorMessage.value = ''
  draft.value = ''
  messages.value = [createWelcomeMessage()]
}

async function scrollToLatest() {
  await nextTick()
  if (messageList.value) messageList.value.scrollTop = messageList.value.scrollHeight
}

function useStarter(text) {
  draft.value = text
  sendMessage()
}

async function sendMessage() {
  const question = draft.value.trim()
  if (!question || isStreaming.value) return

  messages.value.push({ role: 'user', text: question })
  const responseMessage = reactive({ role: 'assistant', text: '' })
  messages.value.push(responseMessage)
  draft.value = ''
  errorMessage.value = ''
  isStreaming.value = true
  requestController = new AbortController()
  await scrollToLatest()

  try {
    await fundamentalsApi.streamAssistantReply({
      path_id: Number(props.pathId),
      node_id: Number(props.nodeId),
      scenario: 'free',
      text: question,
      segment: {
        id: 'concept',
        type: 'document',
        title: props.chapterTitle,
        script: props.chapterContent.slice(0, 1800),
        points: props.knowledgeTags.slice(0, 6),
      },
    }, (event) => {
      if (event?.error) throw new Error(event.error)
      if ((event?.type === 'chunk' || event?.type === 'content') && event.content) {
        responseMessage.text += String(event.content)
        scrollToLatest()
      }
    }, requestController.signal)

    if (!responseMessage.text.trim()) throw new Error('LearnMate 暂时没有返回有效内容')
  } catch (error) {
    if (error.name === 'AbortError') return
    messages.value = messages.value.filter((message) => message !== responseMessage)
    errorMessage.value = error.response?.data?.detail || error.message || '回复失败，请稍后重试。'
  } finally {
    isStreaming.value = false
    requestController = null
    scrollToLatest()
  }
}

watch(() => props.nodeId, resetConversation, { immediate: true })
onBeforeUnmount(() => requestController?.abort())
</script>

<style scoped>
.learning-assistant { position: sticky; top: 84px; display: flex; flex-direction: column; height: calc(100vh - 108px); min-height: 540px; overflow: hidden; }
.assistant-header { display: flex; flex: 0 0 auto; align-items: center; gap: 10px; padding: 17px 18px; border-bottom: 1px solid var(--line); }
.assistant-mark, .message-avatar { display: grid; flex: 0 0 auto; place-items: center; border-radius: 50%; background: var(--accent); color: #294234; }
.assistant-mark { width: 31px; height: 31px; }
.assistant-header > div { display: grid; gap: 3px; }
.assistant-header strong { font-size: 13px; }
.assistant-header small { color: var(--muted); font-size: 10px; }
.assistant-messages { display: flex; flex: 1 1 auto; flex-direction: column; gap: 15px; min-height: 0; overflow-y: auto; padding: 18px 15px; scrollbar-width: thin; }
.assistant-message { display: flex; align-items: flex-start; gap: 7px; max-width: 94%; }
.assistant-message.is-user { align-self: flex-end; }
.message-avatar { width: 24px; height: 24px; font-size: 8px; font-weight: 900; }
.message-bubble { padding: 10px 11px; border-radius: 6px; background: #edf2ed; color: var(--ink); font-size: 12px; line-height: 1.65; overflow-wrap: anywhere; }
.is-user .message-bubble { background: #28473b; color: #fff; }
.message-bubble :deep(p) { margin: 0 0 8px; }
.message-bubble :deep(p:last-child), .message-bubble :deep(ul:last-child), .message-bubble :deep(ol:last-child) { margin-bottom: 0; }
.message-bubble :deep(ul), .message-bubble :deep(ol) { margin: 6px 0 10px; padding-left: 18px; }
.question-starters { display: flex; flex: 0 0 auto; flex-wrap: wrap; gap: 6px; padding: 0 15px 13px; }
.question-starters button { min-height: 29px; padding: 0 9px; border: 1px solid var(--line); border-radius: 4px; background: #fbfcfa; color: var(--accent-deep); font-size: 10px; }
.question-starters button:hover { border-color: #b6c9ab; background: #f2f6ee; }
.assistant-error { flex: 0 0 auto; margin: 0; padding: 9px 15px; border-top: 1px solid #ead8c9; background: #fff9f4; color: #9b5d3d; font-size: 10px; line-height: 1.5; }
.assistant-composer { flex: 0 0 auto; padding: 13px 14px 14px; border-top: 1px solid var(--line); background: #fbfcfa; }
.assistant-composer textarea { display: block; width: 100%; height: 66px; resize: none; padding: 9px 10px; border: 1px solid var(--line); border-radius: 5px; background: var(--paper); color: var(--ink); outline: none; font-size: 12px; line-height: 1.55; }
.assistant-composer textarea:focus { border-color: var(--accent-deep); box-shadow: 0 0 0 2px rgba(63, 91, 49, .1); }
.assistant-composer textarea:disabled { cursor: wait; opacity: .65; }
.composer-actions { display: flex; align-items: center; justify-content: space-between; gap: 10px; margin-top: 8px; }
.composer-actions > span { color: var(--muted); font-size: 9px; }
.composer-actions button { display: grid; width: 31px; height: 31px; place-items: center; border: 0; border-radius: 5px; background: var(--ink); color: #fff; }
.composer-actions button:hover:not(:disabled) { background: #345447; }
.composer-actions button:focus-visible { outline: 2px solid var(--accent-deep); outline-offset: 2px; }
.composer-actions button:disabled { cursor: not-allowed; opacity: .38; }
.typing { display: flex; align-items: center; gap: 4px; min-height: 34px; }
.typing span { width: 4px; height: 4px; border-radius: 50%; background: var(--muted); animation: pulse 1s infinite; }
.typing span:nth-child(2) { animation-delay: .16s; }
.typing span:nth-child(3) { animation-delay: .32s; }
.spin { animation: spin .8s linear infinite; }
.sr-only { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); white-space: nowrap; }
@keyframes pulse { 0%, 70%, 100% { opacity: .3; transform: translateY(0); } 35% { opacity: 1; transform: translateY(-2px); } }
@keyframes spin { to { transform: rotate(360deg); } }
@media (max-width: 840px) { .learning-assistant { position: relative; top: auto; height: 560px; min-height: 0; } }
</style>
