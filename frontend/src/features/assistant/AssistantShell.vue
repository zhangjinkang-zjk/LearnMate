<template>
  <div
    ref="root"
    class="assistant"
    :class="{ 'is-dragging': isDragging, 'is-open': isOpen, 'is-robert': variant === 'robert' }"
    :style="positionStyle"
  >
    <Transition name="assistant-panel">
      <section v-if="isOpen" ref="panelEl" class="assistant-panel" role="dialog" :style="panelStyle" :aria-label="assistantName">
        <header class="assistant-panel__header">
          <div class="assistant-panel__title">
            <span class="assistant-panel__status"></span>
            <div>
              <strong>{{ assistantName }}</strong>
              <small>学习导师</small>
            </div>
          </div>
          <button class="icon-button" type="button" :aria-label="`关闭${assistantName}`" title="关闭" @click="isOpen = false">
            <X :size="16" />
          </button>
        </header>

        <Transition name="assistant-toast"><div v-if="resourceNotice" class="assistant-toast" role="status"><CheckCircle :size="14" />{{ resourceNotice }}</div></Transition>

        <div ref="messagesEl" class="assistant-panel__messages" aria-live="polite">
          <div v-for="message in messages" :key="message.id" class="assistant-message" :class="`is-${message.role}`">
            <div v-if="message.role === 'assistant'" class="assistant-message__avatar">{{ assistantBadge }}</div>
            <div class="assistant-message__bubble">
              <p>{{ message.text }}</p>
              <a v-if="message.downloadUrl" :href="message.downloadUrl" target="_blank" rel="noopener" class="resource-link">
                <FileDown :size="14" /> 下载生成资源
              </a>
            </div>
          </div>
          <!-- 三个点只在**还没出字**的时候出现（见 chatTyping）。 -->
          <div v-if="showTyping" class="assistant-message is-assistant">
            <div class="assistant-message__avatar">{{ assistantBadge }}</div>
            <div class="assistant-message__bubble typing"><i></i><i></i><i></i></div>
          </div>
        </div>

        <div class="assistant-panel__quick">
          <button type="button" @click="usePrompt('请用一个简单例子解释当前学习内容')">举例解释</button>
          <button type="button" @click="usePrompt('帮我整理一份当前主题的学习文档和思维导图')">生成资源</button>
        </div>

        <p v-if="errorMessage" class="assistant-panel__error">{{ errorMessage }}</p>
        <form class="assistant-panel__composer" @submit.prevent="sendMessage">
          <textarea v-model="draft" :disabled="isLoading" maxlength="1200" rows="2" :placeholder="`问问${assistantName}，或让它生成学习资源…（Enter 发送）`" @keydown="onComposerKeydown"></textarea>
          <div class="assistant-panel__composer-row">
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
      class="assistant-fab"
      type="button"
      :aria-label="`打开${assistantName}`"
      :aria-expanded="isOpen"
      @pointerdown="startDrag"
      @pointermove="moveDrag"
      @pointerup="stopDrag"
      @pointercancel="stopDrag"
      @click="toggleOpen"
    >
      <span class="assistant-fab__halo"></span>
      <img :src="displayedRobotImage" :alt="assistantName" draggable="false" />
      <span class="assistant-fab__label">{{ assistantName }}</span>
    </button>
  </div>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { CheckCircle, FileDown, LoaderCircle, Send, X } from 'lucide-vue-next'
import { chatApi } from '@/shared/api/chatApi'
import robotImage from '@/shared/assets/assistant-robot.png'
import { applyWorkflowEvent, applyWorkflowProgress, finishWorkflow, resetWorkflow } from '@/entities/agent/agentWorkflowState'
import { pageContextPayload } from '@/entities/learning/currentPageContext'
import { shouldSendOnKeydown } from '@/shared/lib/composerKeys'
import { shouldShowTyping } from '@/shared/lib/chatTyping'

const props = defineProps({
  assistantName: { type: String, default: '罗伯特' },
  robotImage: { type: String, default: '' },
  variant: { type: String, default: 'assistant' },
  sessionKey: { type: String, default: 'learnmate_assistant_group' },
})

// 面板与视口边缘的最小留白、面板与机器人之间的间距
const PANEL_MARGIN = 8
const PANEL_GAP = 16

const root = ref(null)
const assistantName = computed(() => props.assistantName.trim() || '罗伯特')
const assistantBadge = computed(() => assistantName.value.slice(0, 1))
const variant = computed(() => props.variant)
const displayedRobotImage = computed(() => props.robotImage || robotImage)
const messagesEl = ref(null)
const isOpen = ref(false)
const isDragging = ref(false)
const hasMoved = ref(false)
const draft = ref('')
const isLoading = ref(false)
const errorMessage = ref('')
const resourceNotice = ref('')
let resourceNoticeTimer = null
const chatGroupId = ref(Number(sessionStorage.getItem(props.sessionKey)) || null)
const position = ref({ x: null, y: null })
const dragOffset = ref({ x: 0, y: 0 })
const pointerStart = ref({ x: 0, y: 0 })
const messages = ref([{ id: 'welcome', role: 'assistant', text: `你好，我是${assistantName.value}，你的学习导师。可以问知识点、说说你在学什么，也可以让我整理资料或生成学习资源。` }])
// 这一处流式的标志叫 isLoading（见 sendMessage），判据本身和其它三个聊天框共用。
const showTyping = computed(() => shouldShowTyping(messages.value, isLoading.value))

const panelEl = ref(null)
// 面板相对机器人的补偿位移。只有默认落点会跑出视口时才用得上，见 placePanel。
const panelOffset = ref(null)
const positionStorageKey = computed(() => `learnmate_assistant_pos_${props.sessionKey}`)

const positionStyle = computed(() => {
  if (position.value.x === null) return {}
  return { left: `${position.value.x}px`, top: `${position.value.y}px`, right: 'auto', bottom: 'auto' }
})

const panelStyle = computed(() => {
  if (!panelOffset.value) return {}
  return {
    left: `${panelOffset.value.left}px`,
    top: `${panelOffset.value.top}px`,
    right: 'auto',
    bottom: 'auto',
  }
})

function clampPosition(x, y) {
  // 宽高要分别取：罗伯特是 136×154，拿宽度去夹 y 会有 18px 悬在视口外
  const rect = root.value?.getBoundingClientRect()
  const width = rect?.width || 82
  const height = rect?.height || 82
  return {
    x: Math.max(PANEL_MARGIN, Math.min(window.innerWidth - width - PANEL_MARGIN, x)),
    y: Math.max(PANEL_MARGIN, Math.min(window.innerHeight - height - PANEL_MARGIN, y)),
  }
}

/**
 * 面板落点跟随机器人。
 *
 * 面板是 root 的绝对定位子元素，CSS 里写死的是"右对齐、浮在上方"——那是给右下角
 * 默认位置定的。机器人一旦被拖到左上角，这个落点会把整块面板送到视口外
 * （实测 left=-216、top=-408，面板 360×392 全部不可见），表现成"拖完之后点不开了"。
 * 视口很矮时（实测 566px 高）右下角默认落点也会顶出上边界。
 *
 * 所以这里在面板打开时量一次：落点能装下就什么都不做（panelOffset 保持 null，
 * 外观与改动前完全一致），装不下才补偿 —— 右对齐放不下改左对齐，上方放不下改到下方，
 * 最后整体夹进视口。
 */
async function placePanel() {
  if (!isOpen.value) {
    panelOffset.value = null
    return
  }
  await nextTick()
  const panel = panelEl.value
  const host = root.value
  if (!panel || !host) return

  // 先清掉上次的补偿，量回 CSS 默认落点
  panelOffset.value = null
  await nextTick()

  const hostRect = host.getBoundingClientRect()
  // 尺寸取 offsetWidth/offsetHeight、位置取 offsetLeft/offsetTop，而不是
  // getBoundingClientRect()：面板进场过渡带 scale(.97)，量 rect 会小一圈
  // （实测高 392 量成 380），照那个数补偿仍然会溢出 12px。
  // offset* 是布局尺寸，不带 transform。
  const width = panel.offsetWidth
  const height = panel.offsetHeight
  const naturalLeft = hostRect.left + panel.offsetLeft
  const naturalTop = hostRect.top + panel.offsetTop
  const fits =
    naturalLeft >= PANEL_MARGIN &&
    naturalTop >= PANEL_MARGIN &&
    naturalLeft + width <= window.innerWidth - PANEL_MARGIN &&
    naturalTop + height <= window.innerHeight - PANEL_MARGIN
  if (fits) return

  const maxLeft = Math.max(PANEL_MARGIN, window.innerWidth - width - PANEL_MARGIN)
  const maxTop = Math.max(PANEL_MARGIN, window.innerHeight - height - PANEL_MARGIN)

  // 垂直优先浮在机器人上方；上方装不下才考虑翻到下方 —— 而且只有下方**真的**
  // 放得下才翻。否则翻过去照样要被夹回来，结果面板正好压在机器人身上
  // （矮视口实测重叠 154px，比不翻还糟）。
  let top = hostRect.top - PANEL_GAP - height
  if (top < PANEL_MARGIN && hostRect.bottom + height <= window.innerHeight - PANEL_MARGIN) {
    top = hostRect.bottom + PANEL_GAP
  }
  top = Math.min(Math.max(PANEL_MARGIN, top), maxTop)

  // 水平优先和机器人右对齐，放不下改左对齐
  let left = hostRect.right - width
  if (left < PANEL_MARGIN) left = hostRect.left
  // 视口太矮时上下都避不开机器人，面板会整个压在它身上 —— 那种情况改放左侧
  const verticalOverlap = Math.min(top + height, hostRect.bottom) - Math.max(top, hostRect.top)
  if (verticalOverlap > 0) {
    const beside = hostRect.left - PANEL_GAP - width
    if (beside >= PANEL_MARGIN) left = beside
  }
  left = Math.min(Math.max(PANEL_MARGIN, left), maxLeft)

  panelOffset.value = { left: left - hostRect.left, top: top - hostRect.top }
}

/** 记住拖到哪儿了，刷新后还在原地（纯本地偏好，不影响任何服务端状态）。 */
function savePosition() {
  if (position.value.x === null) return
  try {
    localStorage.setItem(positionStorageKey.value, JSON.stringify(position.value))
  } catch {
    // 隐私模式等写不进去的情况，忽略即可
  }
}

function restorePosition() {
  try {
    const saved = JSON.parse(localStorage.getItem(positionStorageKey.value) || 'null')
    if (!Number.isFinite(saved?.x) || !Number.isFinite(saved?.y)) return
    // 窗口尺寸可能和上次不同，恢复时要重新夹一遍
    position.value = clampPosition(saved.x, saved.y)
  } catch {
    // 存坏了就当没存过，回到默认角落
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
  if (!isDragging.value) return
  isDragging.value = false
  savePosition()
  // 拖动过程中面板是跟着走的，松手时把它重新摆回视口内
  placePanel()
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

function showResourceNotice(message) {
  resourceNotice.value = message
  window.clearTimeout(resourceNoticeTimer)
  resourceNoticeTimer = window.setTimeout(() => { resourceNotice.value = '' }, 2600)
}

// Enter 发送、Shift + Enter 换行，输入法选字期间的回车不算发送（见 composerKeys）。
function onComposerKeydown(event) {
  if (!shouldSendOnKeydown(event)) return
  event.preventDefault()
  sendMessage()
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
      if (event?.type === 'agent_event') applyWorkflowEvent(event)
      else applyWorkflowProgress(event)
      if (event?.chat_group_id) {
        chatGroupId.value = Number(event.chat_group_id)
        sessionStorage.setItem(props.sessionKey, String(chatGroupId.value))
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
      resetWorkflow({ title: text.slice(0, 60), resourceTypes: ['document', 'mindmap'] })
      reply.text = '正在整理主题并生成学习文档与思维导图，请稍候…'
      await chatApi.generateResource(text, chatGroupId.value, onEvent, controller.signal)
      finishWorkflow(false)
      if (!reply.downloadUrl) reply.text = '资源已生成并保存到资料库。'
      showResourceNotice('资源已生成并保存到资料库')
    } else if (chatGroupId.value) {
      await chatApi.streamMessage(chatGroupId.value, text, {
        onEvent, signal: controller.signal, pageContext: pageContextPayload(),
      })
    } else {
      await chatApi.streamNewHistory(text, {
        onEvent, signal: controller.signal, pageContext: pageContextPayload(),
      })
    }
    if (!reply.text.trim()) reply.text = '我暂时没有生成有效回复，请换个方式再问我一次。'
  } catch (error) {
    if (isResourceRequest(text) && error?.name !== 'AbortError') finishWorkflow(true)
    messages.value = messages.value.filter((item) => item !== reply)
    errorMessage.value = error?.message || '请求失败，请稍后重试。'
  } finally {
    isLoading.value = false
    await scrollToLatest()
  }
}

function handleResize() {
  if (position.value.x !== null) position.value = clampPosition(position.value.x, position.value.y)
  placePanel()
}

watch(isOpen, (open) => {
  if (open) placePanel()
})

onMounted(() => {
  restorePosition()
  window.addEventListener('resize', handleResize)
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', handleResize)
  window.clearTimeout(resourceNoticeTimer)
})
</script>

<style scoped>
.assistant { position: fixed; right: 24px; bottom: 24px; z-index: 1000; width: 86px; user-select: none; touch-action: none; }
.assistant.is-open { z-index: 1100; }
.assistant-fab { position: relative; display: grid; width: 86px; height: 86px; padding: 0; place-items: center; border: 1px solid rgba(55, 76, 65, .18); border-radius: 50%; background: #f8f9f5; box-shadow: 0 12px 28px rgba(17, 39, 28, .2), inset 0 1px 0 #fff; cursor: grab; }
.assistant-fab:active { cursor: grabbing; }
.assistant-fab img { position: relative; z-index: 1; width: 76px; height: 76px; object-fit: contain; border-radius: 50%; pointer-events: none; }
.assistant-fab__halo { position: absolute; inset: -5px; border: 1px solid rgba(103, 133, 107, .32); border-radius: 50%; animation: halo 3s ease-in-out infinite; }
.assistant-fab__label { position: absolute; right: -5px; bottom: -7px; z-index: 2; padding: 3px 7px; border: 1px solid var(--line); border-radius: 9px; background: var(--paper); color: var(--accent-deep); font-size: 10px; font-weight: 800; }
.assistant-panel { position: absolute; right: 0; bottom: 101px; display: grid; width: min(360px, calc(100vw - 32px)); max-height: min(610px, calc(100vh - 130px)); grid-template-rows: auto minmax(180px, 1fr) auto auto auto; overflow: hidden; border: 1px solid var(--line); border-radius: 10px; background: var(--paper); box-shadow: 0 22px 55px rgba(14, 36, 23, .22); pointer-events: auto; }
.assistant-panel__header { display: flex; align-items: center; justify-content: space-between; padding: 13px 15px; border-bottom: 1px solid var(--line); background: #f7f9f4; }
.assistant-panel__title { display: flex; align-items: center; gap: 9px; }.assistant-panel__title strong,.assistant-panel__title small { display: block; }.assistant-panel__title strong { font-size: 13px; }.assistant-panel__title small { margin-top: 2px; color: var(--muted); font-size: 10px; }.assistant-panel__status { width: 8px; height: 8px; border-radius: 50%; background: #71a76b; box-shadow: 0 0 0 4px rgba(113, 167, 107, .14); }
.icon-button { display: grid; width: 28px; height: 28px; place-items: center; border: 0; border-radius: 4px; background: transparent; color: var(--muted); cursor: pointer; }.icon-button:hover { background: #e9eee8; color: var(--ink); }
.assistant-panel__messages { min-height: 0; overflow-y: auto; padding: 14px; }.assistant-message { display: flex; align-items: flex-start; gap: 7px; margin-bottom: 12px; }.assistant-message.is-user { justify-content: flex-end; }.assistant-message__avatar { display: grid; flex: 0 0 23px; width: 23px; height: 23px; place-items: center; border-radius: 50%; background: #dfe8d6; color: var(--accent-deep); font-size: 10px; font-weight: 900; }.assistant-message__bubble { max-width: 85%; padding: 8px 10px; border-radius: 6px; background: #eef2ec; color: var(--ink); font-size: 12px; line-height: 1.6; overflow-wrap: anywhere; }.assistant-message__bubble p { margin: 0; }.is-user .assistant-message__bubble { background: #29473a; color: #fff; }.typing { display: flex; gap: 4px; align-items: center; min-height: 34px; }.typing i { width: 4px; height: 4px; border-radius: 50%; background: var(--muted); animation: pulse 1s infinite; }.typing i:nth-child(2) { animation-delay: .15s; }.typing i:nth-child(3) { animation-delay: .3s; }.resource-link { display: inline-flex; align-items: center; gap: 5px; margin-top: 8px; color: var(--accent-deep); font-size: 11px; font-weight: 800; text-decoration: none; }.is-user .resource-link { color: #e2f452; }
.assistant-panel__quick { display: flex; flex-wrap: wrap; gap: 5px; padding: 0 14px 10px; }.assistant-panel__quick button { padding: 5px 8px; border: 1px solid var(--line); border-radius: 4px; background: #fbfcfa; color: var(--accent-deep); font-size: 10px; cursor: pointer; }.assistant-panel__quick button:hover { border-color: #adc1a4; background: #f0f5ec; }.assistant-panel__error { margin: 0; padding: 8px 14px; border-top: 1px solid #ead8c9; background: #fff9f4; color: #9b5d3d; font-size: 10px; }
.assistant-panel__composer { padding: 10px 12px 12px; border-top: 1px solid var(--line); background: #fbfcfa; }.assistant-panel__composer textarea { display: block; width: 100%; box-sizing: border-box; resize: none; padding: 8px 9px; border: 1px solid var(--line); border-radius: 5px; outline: none; background: var(--paper); color: var(--ink); font: inherit; font-size: 12px; line-height: 1.5; }.assistant-panel__composer textarea:focus { border-color: var(--accent-deep); box-shadow: 0 0 0 2px rgba(63, 91, 49, .1); }.assistant-panel__composer-row { display: flex; align-items: center; justify-content: space-between; margin-top: 7px; }.assistant-panel__composer-row span { color: var(--muted); font-size: 9px; }.assistant-panel__composer-row button { display: grid; width: 30px; height: 30px; place-items: center; border: 0; border-radius: 5px; background: var(--ink); color: #fff; cursor: pointer; }.assistant-panel__composer-row button:disabled { opacity: .4; cursor: not-allowed; }.spin { animation: spin .8s linear infinite; }
.assistant-panel-enter-active,.assistant-panel-leave-active { transition: opacity .2s ease, transform .2s ease; }.assistant-panel-enter-from,.assistant-panel-leave-to { opacity: 0; transform: translateY(8px) scale(.97); }
@keyframes pulse { 0%,70%,100% { opacity: .3; transform: translateY(0); } 35% { opacity: 1; transform: translateY(-2px); } } @keyframes spin { to { transform: rotate(360deg); } } @keyframes halo { 0%,100% { transform: scale(1); opacity: .6; } 50% { transform: scale(1.05); opacity: 1; } }
/* Robert stays as a transparent, animated cutout without the assistant badge. */
.assistant.is-robert { right: 22px; bottom: 16px; width: 136px; }
.assistant.is-robert .assistant-fab { width: 136px; height: 154px; border: 0; border-radius: 0; background: transparent; box-shadow: none; animation: robert-float 3.6s ease-in-out infinite; }
.assistant.is-robert .assistant-fab img { width: 136px; height: 154px; border-radius: 0; filter: sepia(.2) saturate(1.25) hue-rotate(340deg) brightness(1.06) drop-shadow(0 14px 12px rgba(12, 24, 20, .26)); animation: robert-sway 4.8s ease-in-out infinite; }
.assistant.is-robert .assistant-panel { bottom: 178px; }
.assistant.is-robert .assistant-fab:hover img { animation: robert-greet .7s ease-in-out both; }
.assistant.is-robert .assistant-fab__halo, .assistant.is-robert .assistant-fab__label { display: none; }
@keyframes robert-float { 0%,100% { transform: translateY(0); } 50% { transform: translateY(-7px); } }
@keyframes robert-sway { 0%,100% { transform: rotate(-1.5deg) translateX(0); } 50% { transform: rotate(1.5deg) translateX(2px); } }
@keyframes robert-greet { 0% { transform: rotate(0); } 35% { transform: rotate(-5deg) translateY(-3px); } 70% { transform: rotate(4deg) translateY(-1px); } 100% { transform: rotate(0); } }
/* 拖动时停掉浮动/摇摆：这两个 transform 会让机器人从指针底下溜走，手感是"拖不住" */
.assistant.is-dragging { cursor: grabbing; }
.assistant.is-dragging .assistant-fab, .assistant.is-dragging .assistant-fab img { animation: none; }
@media (max-width: 620px) { .assistant { right: 15px; bottom: 15px; }.assistant-panel { position: fixed; right: 15px; bottom: 111px; width: calc(100vw - 30px); max-height: calc(100vh - 130px); } .assistant.is-robert { right: 10px; bottom: 8px; width: 112px; } .assistant.is-robert .assistant-fab, .assistant.is-robert .assistant-fab img { width: 112px; height: 128px; } .assistant.is-robert .assistant-panel { bottom: 146px; } }
@media (prefers-reduced-motion: reduce) { .assistant-fab__halo, .assistant.is-robert .assistant-fab, .assistant.is-robert .assistant-fab img { animation: none; } }
.assistant-toast { position: absolute; top: 58px; right: 12px; left: 12px; z-index: 2; display: flex; align-items: center; gap: 6px; padding: 8px 10px; border: 1px solid #d7e3c9; border-radius: 6px; background: #f3f8ea; box-shadow: 0 7px 16px rgba(45, 70, 40, .12); color: var(--accent-deep); font-size: 11px; }
.assistant-toast-enter-active, .assistant-toast-leave-active { transition: opacity .18s ease, transform .18s ease; }
.assistant-toast-enter-from, .assistant-toast-leave-to { opacity: 0; transform: translateY(-5px); }
</style>
