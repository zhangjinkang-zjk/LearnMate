<template>
  <div
    ref="root"
    class="xiaozhi"
    :class="{ 'is-dragging': isDragging, 'is-open': isOpen }"
    :style="positionStyle"
  >
    <Transition name="xiaozhi-panel">
      <section v-if="isOpen" class="xiaozhi-panel" role="dialog" aria-label="小知答疑">
        <header class="xiaozhi-panel__header">
          <div class="xiaozhi-panel__title">
            <span class="xiaozhi-panel__status"></span>
            <div>
              <strong>小知</strong>
              <small>答疑与资源助手</small>
            </div>
          </div>
          <button class="icon-button" type="button" aria-label="关闭小知" title="关闭" @click="isOpen = false">
            <X :size="16" />
          </button>
        </header>

        <div ref="messagesEl" class="xiaozhi-panel__messages" aria-live="polite">
          <div v-for="message in messages" :key="message.id" class="xiaozhi-message" :class="`is-${message.role}`">
            <div v-if="message.role === 'assistant'" class="xiaozhi-message__avatar">知</div>
            <div class="xiaozhi-message__bubble">
              <p>{{ message.text }}</p>
              <a v-if="message.downloadUrl" :href="message.downloadUrl" target="_blank" rel="noopener" class="resource-link">
                <FileDown :size="14" /> 下载生成资源
              </a>
            </div>
          </div>
          <div v-if="isLoading" class="xiaozhi-message is-assistant">
            <div class="xiaozhi-message__avatar">知</div>
            <div class="xiaozhi-message__bubble typing"><i></i><i></i><i></i></div>
          </div>
        </div>

        <div class="xiaozhi-panel__quick">
          <button type="button" @click="usePrompt('请用一个简单例子解释当前学习内容')">举例解释</button>
          <button type="button" @click="usePrompt('帮我整理一份当前主题的学习文档和思维导图')">生成资源</button>
        </div>

        <p v-if="errorMessage" class="xiaozhi-panel__error">{{ errorMessage }}</p>
        <form class="xiaozhi-panel__composer" @submit.prevent="sendMessage">
          <textarea v-model="draft" :disabled="isLoading" maxlength="1200" rows="2" placeholder="问问小知，或让它生成学习资源…" @keydown.ctrl.enter.prevent="sendMessage" @keydown.meta.enter.prevent="sendMessage"></textarea>
          <div class="xiaozhi-panel__composer-row">
            <span>{{ draft.length }} / 1200</span>
            <button type="submit" :disabled="!draft.trim() || isLoading" aria-label="发送消息" title="发送">
              <LoaderCircle v-if="isLoading" class="spin" :size="16" />
              <Send v-else :size="16" />
            </button>
          </div>
        </form>
      </section>
    </Transition>

    <button
      class="xiaozhi-fab"
      type="button"
      aria-label="打开小知答疑"
      :aria-expanded="isOpen"
      @pointerdown="startDrag"
      @pointermove="moveDrag"
      @pointerup="stopDrag"
      @pointercancel="stopDrag"
      @click="toggleOpen"
    >
      <span class="xiaozhi-fab__halo"></span>
      <img :src="robotImage" alt="小知" draggable="false" />
      <span class="xiaozhi-fab__label">小知</span>
    </button>
  </div>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { FileDown, LoaderCircle, Send, X } from 'lucide-vue-next'
import { chatApi } from '@/shared/api/chatApi'
import robotImage from '@/shared/assets/xiaozhi-robot.png'

const root = ref(null)
const messagesEl = ref(null)
const isOpen = ref(false)
const isDragging = ref(false)
const hasMoved = ref(false)
const draft = ref('')
const isLoading = ref(false)
const errorMessage = ref('')
const chatGroupId = ref(Number(sessionStorage.getItem('learnmate_xiaozhi_group')) || null)
const position = ref({ x: null, y: null })
const dragOffset = ref({ x: 0, y: 0 })
const pointerStart = ref({ x: 0, y: 0 })
const messages = ref([{ id: 'welcome', role: 'assistant', text: '你好，我是小知。可以帮你答疑解惑，也可以整理并生成学习资源。' }])

const positionStyle = computed(() => {
  if (position.value.x === null) return {}
  return { left: `${position.value.x}px`, top: `${position.value.y}px`, right: 'auto', bottom: 'auto' }
})

function clampPosition(x, y) {
  const size = root.value?.getBoundingClientRect().width || 82
  return {
    x: Math.max(8, Math.min(window.innerWidth - size - 8, x)),
    y: Math.max(8, Math.min(window.innerHeight - size - 8, y)),
  }
}

function startDrag(event) {
  if (event.button !== 0 || !root.value) return
  const rect = root.value.getBoundingClientRect()
  pointerStart.value = { x: event.clientX, y: event.clientY }
  dragOffset.value = { x: event.clientX - rect.left, y: event.clientY - rect.top }
  position.value = { x: rect.left, y: rect.top }
  hasMoved.value = false
  isDragging.value = true
  event.currentTarget.setPointerCapture?.(event.pointerId)
}

function moveDrag(event) {
  if (!isDragging.value) return
  if (Math.hypot(event.clientX - pointerStart.value.x, event.clientY - pointerStart.value.y) > 6) hasMoved.value = true
  position.value = clampPosition(event.clientX - dragOffset.value.x, event.clientY - dragOffset.value.y)
}

function stopDrag() {
  isDragging.value = false
}

function toggleOpen() {
  if (hasMoved.value) {
    hasMoved.value = false
    return
  }
  isOpen.value = !isOpen.value
}

function usePrompt(text) {
  draft.value = text
  sendMessage()
}

function appendMessage(role, text, extra = {}) {
  messages.value.push({ id: `${role}-${Date.now()}-${Math.random()}`, role, text, ...extra })
}

async function scrollToLatest() {
  await nextTick()
  if (messagesEl.value) messagesEl.value.scrollTop = messagesEl.value.scrollHeight
}

function isResourceRequest(text) {
  return /(生成|制作|整理|创建).{0,12}(资源|文档|资料|思维导图|笔记)/.test(text)
}

async function sendMessage() {
  const text = draft.value.trim()
  if (!text || isLoading.value) return
  draft.value = ''
  errorMessage.value = ''
  appendMessage('user', text)
  const reply = { id: `assistant-${Date.now()}`, role: 'assistant', text: '' }
  messages.value.push(reply)
  isLoading.value = true
  const controller = new AbortController()
  try {
    const onEvent = (event) => {
      if (event?.error) throw new Error(event.error)
      if (event?.chat_group_id) {
        chatGroupId.value = Number(event.chat_group_id)
        sessionStorage.setItem('learnmate_xiaozhi_group', String(chatGroupId.value))
      }
      if (event?.content && ['chunk', 'content'].includes(event.type)) reply.text += String(event.content)
      const resource = event?.resource || (Array.isArray(event?.resources) ? event.resources[0] : null)
      if (event?.resource_id || resource?.id || resource?.resource_id) {
        const id = event.resource_id || resource.id || resource.resource_id
        reply.downloadUrl = event.download_url || `/resource/${id}/download`
      }
      if (event?.download_url) reply.downloadUrl = event.download_url
    }
    if (isResourceRequest(text)) {
      reply.text = '正在整理主题并生成学习文档与思维导图，请稍候…'
      await chatApi.generateResource(text, chatGroupId.value, onEvent, controller.signal)
      if (!reply.downloadUrl) reply.text = '资源已生成并保存到资料库。'
    } else if (chatGroupId.value) {
      await chatApi.streamMessage(chatGroupId.value, text, onEvent, controller.signal)
    } else {
      await chatApi.streamNewHistory(text, onEvent, controller.signal)
    }
    if (!reply.text.trim()) reply.text = '我暂时没有生成有效回复，请换个方式再问我一次。'
  } catch (error) {
    messages.value = messages.value.filter((item) => item !== reply)
    errorMessage.value = error?.message || '请求失败，请稍后重试。'
  } finally {
    isLoading.value = false
    await scrollToLatest()
  }
}

function handleResize() {
  if (position.value.x !== null) position.value = clampPosition(position.value.x, position.value.y)
}

onMounted(() => {
  window.addEventListener('resize', handleResize)
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', handleResize)
})
</script>

<style scoped>
.xiaozhi { position: fixed; right: 24px; bottom: 24px; z-index: 1000; width: 86px; user-select: none; touch-action: none; }
.xiaozhi.is-open { z-index: 1100; }
.xiaozhi-fab { position: relative; display: grid; width: 86px; height: 86px; padding: 0; place-items: center; border: 1px solid rgba(55, 76, 65, .18); border-radius: 50%; background: #f8f9f5; box-shadow: 0 12px 28px rgba(17, 39, 28, .2), inset 0 1px 0 #fff; cursor: grab; }
.xiaozhi-fab:active { cursor: grabbing; }
.xiaozhi-fab img { position: relative; z-index: 1; width: 76px; height: 76px; object-fit: contain; border-radius: 50%; pointer-events: none; }
.xiaozhi-fab__halo { position: absolute; inset: -5px; border: 1px solid rgba(103, 133, 107, .32); border-radius: 50%; animation: halo 3s ease-in-out infinite; }
.xiaozhi-fab__label { position: absolute; right: -5px; bottom: -7px; z-index: 2; padding: 3px 7px; border: 1px solid var(--line); border-radius: 9px; background: var(--paper); color: var(--accent-deep); font-size: 10px; font-weight: 800; }
.xiaozhi-panel { position: absolute; right: 0; bottom: 101px; display: grid; width: min(360px, calc(100vw - 32px)); max-height: min(610px, calc(100vh - 130px)); grid-template-rows: auto minmax(180px, 1fr) auto auto auto; overflow: hidden; border: 1px solid var(--line); border-radius: 10px; background: var(--paper); box-shadow: 0 22px 55px rgba(14, 36, 23, .22); pointer-events: auto; }
.xiaozhi-panel__header { display: flex; align-items: center; justify-content: space-between; padding: 13px 15px; border-bottom: 1px solid var(--line); background: #f7f9f4; }
.xiaozhi-panel__title { display: flex; align-items: center; gap: 9px; }.xiaozhi-panel__title strong,.xiaozhi-panel__title small { display: block; }.xiaozhi-panel__title strong { font-size: 13px; }.xiaozhi-panel__title small { margin-top: 2px; color: var(--muted); font-size: 10px; }.xiaozhi-panel__status { width: 8px; height: 8px; border-radius: 50%; background: #71a76b; box-shadow: 0 0 0 4px rgba(113, 167, 107, .14); }
.icon-button { display: grid; width: 28px; height: 28px; place-items: center; border: 0; border-radius: 4px; background: transparent; color: var(--muted); cursor: pointer; }.icon-button:hover { background: #e9eee8; color: var(--ink); }
.xiaozhi-panel__messages { min-height: 0; overflow-y: auto; padding: 14px; }.xiaozhi-message { display: flex; align-items: flex-start; gap: 7px; margin-bottom: 12px; }.xiaozhi-message.is-user { justify-content: flex-end; }.xiaozhi-message__avatar { display: grid; flex: 0 0 23px; width: 23px; height: 23px; place-items: center; border-radius: 50%; background: #dfe8d6; color: var(--accent-deep); font-size: 10px; font-weight: 900; }.xiaozhi-message__bubble { max-width: 85%; padding: 8px 10px; border-radius: 6px; background: #eef2ec; color: var(--ink); font-size: 12px; line-height: 1.6; overflow-wrap: anywhere; }.xiaozhi-message__bubble p { margin: 0; }.is-user .xiaozhi-message__bubble { background: #29473a; color: #fff; }.typing { display: flex; gap: 4px; align-items: center; min-height: 34px; }.typing i { width: 4px; height: 4px; border-radius: 50%; background: var(--muted); animation: pulse 1s infinite; }.typing i:nth-child(2) { animation-delay: .15s; }.typing i:nth-child(3) { animation-delay: .3s; }.resource-link { display: inline-flex; align-items: center; gap: 5px; margin-top: 8px; color: var(--accent-deep); font-size: 11px; font-weight: 800; text-decoration: none; }.is-user .resource-link { color: #e2f452; }
.xiaozhi-panel__quick { display: flex; flex-wrap: wrap; gap: 5px; padding: 0 14px 10px; }.xiaozhi-panel__quick button { padding: 5px 8px; border: 1px solid var(--line); border-radius: 4px; background: #fbfcfa; color: var(--accent-deep); font-size: 10px; cursor: pointer; }.xiaozhi-panel__quick button:hover { border-color: #adc1a4; background: #f0f5ec; }.xiaozhi-panel__error { margin: 0; padding: 8px 14px; border-top: 1px solid #ead8c9; background: #fff9f4; color: #9b5d3d; font-size: 10px; }
.xiaozhi-panel__composer { padding: 10px 12px 12px; border-top: 1px solid var(--line); background: #fbfcfa; }.xiaozhi-panel__composer textarea { display: block; width: 100%; box-sizing: border-box; resize: none; padding: 8px 9px; border: 1px solid var(--line); border-radius: 5px; outline: none; background: var(--paper); color: var(--ink); font: inherit; font-size: 12px; line-height: 1.5; }.xiaozhi-panel__composer textarea:focus { border-color: var(--accent-deep); box-shadow: 0 0 0 2px rgba(63, 91, 49, .1); }.xiaozhi-panel__composer-row { display: flex; align-items: center; justify-content: space-between; margin-top: 7px; }.xiaozhi-panel__composer-row span { color: var(--muted); font-size: 9px; }.xiaozhi-panel__composer-row button { display: grid; width: 30px; height: 30px; place-items: center; border: 0; border-radius: 5px; background: var(--ink); color: #fff; cursor: pointer; }.xiaozhi-panel__composer-row button:disabled { opacity: .4; cursor: not-allowed; }.spin { animation: spin .8s linear infinite; }
.xiaozhi-panel-enter-active,.xiaozhi-panel-leave-active { transition: opacity .2s ease, transform .2s ease; }.xiaozhi-panel-enter-from,.xiaozhi-panel-leave-to { opacity: 0; transform: translateY(8px) scale(.97); }
@keyframes pulse { 0%,70%,100% { opacity: .3; transform: translateY(0); } 35% { opacity: 1; transform: translateY(-2px); } } @keyframes spin { to { transform: rotate(360deg); } } @keyframes halo { 0%,100% { transform: scale(1); opacity: .6; } 50% { transform: scale(1.05); opacity: 1; } }
@media (max-width: 620px) { .xiaozhi { right: 15px; bottom: 15px; }.xiaozhi-panel { position: fixed; right: 15px; bottom: 111px; width: calc(100vw - 30px); max-height: calc(100vh - 130px); } }
@media (prefers-reduced-motion: reduce) { .xiaozhi-fab__halo { animation: none; } }
</style>
