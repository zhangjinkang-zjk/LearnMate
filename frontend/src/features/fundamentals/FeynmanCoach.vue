<template>
  <section class="feynman-coach surface" aria-label="费曼反讲">
    <header class="feynman-header">
      <div>
        <p class="eyebrow">费曼反讲</p>
        <h2>把这一章讲给 LearnMate 听</h2>
        <p>先用自己的话讲清楚，助教会围绕一个薄弱点追问。你可以随时结束，本次结束不会直接标记章节完成。</p>
      </div>
      <span class="feynman-topic">{{ chapterTitle || '当前章节' }}</span>
    </header>

    <div ref="messageList" class="feynman-messages" aria-live="polite">
      <template v-for="(message, index) in messages" :key="`${message.role}-${index}`">
        <div v-if="message.text || message.role === 'user'" class="feynman-message" :class="`is-${message.role}`">
          <span v-if="message.role === 'assistant'" class="feynman-avatar">LM</span>
          <div class="feynman-bubble" v-html="renderMarkdown(message.text)"></div>
        </div>
      </template>
      <div v-if="isStreaming" class="feynman-message is-assistant">
        <span class="feynman-avatar">LM</span>
        <div class="feynman-bubble typing" aria-label="正在回复"><span></span><span></span><span></span></div>
      </div>
    </div>

    <div v-if="messages.length === 1" class="feynman-starters">
      <button type="button" @click="useStarter('我来用自己的话解释这一章的核心概念：')">开始反讲</button>
      <button type="button" @click="useStarter('这章最容易混淆的地方是：')">先讲难点</button>
    </div>

    <p v-if="errorMessage" class="feynman-error" role="status">{{ errorMessage }}</p>
    <form class="feynman-composer" @submit.prevent="sendMessage">
      <label class="sr-only" for="feynman-answer">你的反讲</label>
      <textarea
        id="feynman-answer"
        v-model="draft"
        rows="4"
        maxlength="1600"
        :disabled="isStreaming"
        placeholder="用自己的话讲讲你怎么理解这一章…"
        @keydown.ctrl.enter.prevent="sendMessage"
        @keydown.meta.enter.prevent="sendMessage"
      ></textarea>
      <div class="feynman-actions">
        <span>{{ draft.length }} / 1600</span>
        <div>
          <button class="button button--quiet" type="button" :disabled="isStreaming" @click="$emit('end')">结束本次反讲</button>
          <button class="button button--primary" type="submit" :disabled="!draft.trim() || isStreaming">
            <LoaderCircle v-if="isStreaming" class="spin" :size="16" />
            <Send v-else :size="16" />
            发送
          </button>
        </div>
      </div>
    </form>
  </section>
</template>

<script setup>
import { nextTick, onBeforeUnmount, reactive, ref, watch } from 'vue'
import { LoaderCircle, Send } from 'lucide-vue-next'
import { fundamentalsApi } from '@/shared/api/fundamentalsApi'
import { renderMarkdown } from '@/shared/lib/markdown'

const props = defineProps({
  pathId: { type: [Number, String], required: true },
  nodeId: { type: [Number, String], required: true },
  chapterTitle: { type: String, default: '' },
  chapterContent: { type: String, default: '' },
  knowledgeTags: { type: Array, default: () => [] },
  resourceId: { type: [Number, String], default: null },
})

defineEmits(['end'])

const draft = ref('')
const errorMessage = ref('')
const isStreaming = ref(false)
const messageList = ref(null)
const messages = ref([])
let requestController = null

const draftKey = () => `learnmate_feynman_draft_${props.pathId}_${props.nodeId}`

function createWelcomeMessage() {
  return { role: 'assistant', text: `我们来做“${props.chapterTitle || '当前章节'}”的费曼反讲。先用自己的话说明：它要解决什么问题、关键步骤是什么。` }
}

function resetConversation() {
  requestController?.abort()
  requestController = null
  isStreaming.value = false
  errorMessage.value = ''
  draft.value = localStorage.getItem(draftKey()) || ''
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
  const answer = draft.value.trim()
  if (!answer || isStreaming.value) return
  messages.value.push({ role: 'user', text: answer })
  const responseMessage = reactive({ role: 'assistant', text: '' })
  messages.value.push(responseMessage)
  draft.value = ''
  localStorage.removeItem(draftKey())
  errorMessage.value = ''
  isStreaming.value = true
  requestController = new AbortController()
  await scrollToLatest()

  try {
    await fundamentalsApi.streamAssistantReply({
      path_id: Number(props.pathId),
      node_id: Number(props.nodeId),
      resource_id: props.resourceId ? Number(props.resourceId) : null,
      scenario: 'feynman',
      text: answer,
      segment: {
        id: 'feynman',
        type: 'feynman',
        title: props.chapterTitle,
        script: props.chapterContent.slice(0, 2200),
        points: props.knowledgeTags.slice(0, 8),
      },
    }, (event) => {
      if (event?.error) throw new Error(event.error)
      if ((event?.type === 'chunk' || event?.type === 'content') && event.content) {
        responseMessage.text += String(event.content)
        scrollToLatest()
      }
    }, requestController.signal)
    if (!responseMessage.text.trim()) throw new Error('LearnMate 暂时没有返回有效追问')
  } catch (error) {
    if (error.name === 'AbortError') return
    if (responseMessage.text.trim()) responseMessage.text += '\n\n> 回复中断了，你可以继续补充。'
    else messages.value = messages.value.filter((message) => message !== responseMessage)
    errorMessage.value = error.response?.data?.detail || error.message || '反讲追问失败，请稍后重试。'
  } finally {
    isStreaming.value = false
    requestController = null
    scrollToLatest()
  }
}

watch(draft, (value) => {
  if (value) localStorage.setItem(draftKey(), value)
  else localStorage.removeItem(draftKey())
})
watch(() => [props.pathId, props.nodeId], resetConversation, { immediate: true })
onBeforeUnmount(() => requestController?.abort())
</script>

<style scoped>
.feynman-coach { display: grid; height: clamp(430px, calc(100vh - 420px), 650px); min-height: 0; grid-template-rows: auto minmax(0, 1fr) auto auto; overflow: hidden; }
.feynman-header { display: flex; align-items: flex-start; justify-content: space-between; gap: 18px; min-width: 0; padding: 20px 24px; border-bottom: 1px solid var(--line); background: #fbfcfa; }
.feynman-header .eyebrow { margin-bottom: 6px; }
.feynman-header h2 { margin: 0; font-size: 18px; line-height: 1.35; }
.feynman-header p:last-child { max-width: 660px; margin: 8px 0 0; color: var(--muted); font-size: 12px; line-height: 1.7; }
.feynman-topic { flex: 0 0 auto; max-width: 220px; padding: 7px 9px; border: 1px solid #d7e3c9; border-radius: 4px; background: #f3f8ea; color: var(--accent-deep); font-size: 11px; font-weight: 800; }
.feynman-messages { display: grid; align-content: start; gap: 15px; overflow-y: auto; padding: 24px; }
.feynman-message { display: flex; align-items: flex-start; gap: 9px; max-width: min(760px, 88%); }
.feynman-message.is-user { justify-self: end; flex-direction: row-reverse; }
.feynman-avatar { display: grid; flex: 0 0 28px; width: 28px; height: 28px; place-items: center; border-radius: 50%; background: var(--accent); color: var(--accent-deep); font-size: 10px; font-weight: 900; }
.feynman-bubble { padding: 11px 14px; border-radius: 5px 12px 12px 12px; background: #edf3ed; color: var(--ink); font-size: 13px; line-height: 1.7; }
.is-user .feynman-bubble { border-radius: 12px 5px 12px 12px; background: var(--ink); color: #fff; }
.feynman-bubble :deep(p) { margin: 0 0 8px; }.feynman-bubble :deep(p:last-child) { margin-bottom: 0; }.feynman-bubble :deep(ul), .feynman-bubble :deep(ol) { margin: 7px 0 0; padding-left: 20px; }
.typing { display: flex; gap: 4px; padding: 14px; }.typing span { width: 5px; height: 5px; border-radius: 50%; background: var(--muted); animation: pulse 1s infinite ease-in-out; }.typing span:nth-child(2) { animation-delay: .15s; }.typing span:nth-child(3) { animation-delay: .3s; }
.feynman-starters { display: flex; flex-wrap: wrap; gap: 8px; padding: 0 24px 13px; }.feynman-starters button { padding: 7px 9px; border: 1px solid var(--line); border-radius: 4px; background: var(--paper); color: var(--muted); font-size: 11px; }.feynman-starters button:hover { border-color: var(--accent-deep); color: var(--accent-deep); }
.feynman-error { margin: 0; padding: 0 24px 10px; color: #a66442; font-size: 11px; }
.feynman-composer { padding: 12px 24px 18px; border-top: 1px solid var(--line); }.feynman-composer textarea { width: 100%; min-height: 78px; max-height: 150px; resize: vertical; padding: 11px 13px; border: 1px solid var(--line); border-radius: 6px; color: var(--ink); outline: none; font-size: 13px; line-height: 1.65; }.feynman-composer textarea:focus { border-color: var(--accent-deep); }.feynman-actions { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-top: 9px; color: var(--muted); font-size: 10px; }.feynman-actions > div { display: flex; gap: 8px; }.feynman-actions .button { gap: 7px; }
@keyframes pulse { 0%, 60%, 100% { opacity: .3; transform: translateY(0); } 30% { opacity: 1; transform: translateY(-2px); } }
@media (max-width: 640px) { .feynman-coach { height: clamp(420px, calc(100vh - 350px), 620px); }.feynman-header { flex-direction: column; padding: 17px 18px; }.feynman-topic { max-width: 100%; }.feynman-messages { padding: 18px; }.feynman-starters { padding: 0 18px 12px; }.feynman-composer { padding: 11px 18px 16px; }.feynman-actions { align-items: flex-start; flex-direction: column; }.feynman-actions > div { width: 100%; }.feynman-actions .button { flex: 1; } }
</style>
