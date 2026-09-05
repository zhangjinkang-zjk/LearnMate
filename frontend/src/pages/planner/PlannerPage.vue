<template>
  <div class="planner-page">
    <PageTitle eyebrow="计划本" title="把今天要做的事放在这里" description="这是你的个人待办清单，完成一项就划掉一项。" />
    <section class="planner-panel surface">
      <form class="todo-form" @submit.prevent="addTodo">
        <input v-model.trim="draft" type="text" placeholder="添加一个待办事项" aria-label="添加待办事项" />
        <label class="duration-picker"><span>专注 {{ draftMinutes }} 分钟</span><input v-model.number="draftMinutes" type="range" min="5" max="120" step="5" aria-label="默认专注时长" /></label>
        <button class="button button--accent" type="submit" :disabled="!draft">添加</button>
      </form>
      <Transition name="planner-notice"><p v-if="notice" class="planner-notice" role="status">{{ notice }}</p></Transition>
      <div class="todo-list">
        <div v-for="todo in todos" :key="todo.id" class="todo-row" :class="{ done: todo.done, 'is-timing': activeTimerId === todo.id }">
          <input v-model="todo.done" type="checkbox" @change="persist" />
          <div class="todo-main"><span class="todo-text">{{ todo.text }}</span><label class="todo-duration"><span>{{ todo.minutes }} 分钟</span><input v-model.number="todo.minutes" type="range" min="5" max="120" step="5" aria-label="调整专注时长" @change="persist" /></label></div>
          <div class="todo-timer"><strong v-if="activeTimerId === todo.id">{{ formatTimer(todo.remainingSeconds) }}</strong><button class="timer-button" type="button" :aria-label="activeTimerId === todo.id && timerRunning ? '暂停计时' : '开始计时'" :title="activeTimerId === todo.id && timerRunning ? '暂停计时' : '开始计时'" @click="toggleTimer(todo)"><Pause v-if="activeTimerId === todo.id && timerRunning" :size="14" /><Timer v-else :size="14" /></button><button v-if="activeTimerId === todo.id" class="timer-reset" type="button" aria-label="重置计时" title="重置计时" @click="resetTimer(todo)"><RotateCcw :size="13" /></button></div>
          <button class="todo-delete" type="button" aria-label="删除待办" title="删除待办" @click="removeTodo(todo.id)">×</button>
        </div>
        <p v-if="!todos.length" class="todo-empty">还没有待办事项。</p>
      </div>
    </section>
  </div>
</template>
<script setup>
import { onBeforeUnmount, ref } from 'vue'
import { Pause, RotateCcw, Timer } from 'lucide-vue-next'
import PageTitle from '@/shared/ui/PageTitle.vue'
const storageKey = 'learnmate_todos'
const draft = ref('')
const draftMinutes = ref(25)
const todos = ref(readTodos())
const activeTimerId = ref(null)
const timerRunning = ref(false)
const notice = ref('')
let timerHandle = null
let noticeHandle = null
function readTodos() { try { const value = JSON.parse(localStorage.getItem(storageKey) || '[]'); return Array.isArray(value) ? value.map((todo) => ({ ...todo, minutes: Number(todo.minutes) || 25, remainingSeconds: 0 })) : [] } catch { return [] } }
function persist() { localStorage.setItem(storageKey, JSON.stringify(todos.value)) }
function addTodo() { if (!draft.value) return; todos.value.unshift({ id: `${Date.now()}-${Math.random()}`, text: draft.value, done: false, minutes: draftMinutes.value, remainingSeconds: 0 }); draft.value = ''; persist() }
function removeTodo(id) { if (activeTimerId.value === id) stopTimer(); todos.value = todos.value.filter((todo) => todo.id !== id); persist() }
function showNotice(message) { notice.value = message; window.clearTimeout(noticeHandle); noticeHandle = window.setTimeout(() => { notice.value = '' }, 2800) }
function stopTimer() { window.clearInterval(timerHandle); timerHandle = null; timerRunning.value = false; activeTimerId.value = null }
function finishTimer(todo) { stopTimer(); playAlarm(); showNotice(`“${todo.text}”的专注时间到了`) }
function startTimer(todo) { if (activeTimerId.value !== todo.id) { stopTimer(); activeTimerId.value = todo.id; todo.remainingSeconds = (Number(todo.minutes) || 25) * 60 } if (todo.remainingSeconds <= 0) todo.remainingSeconds = (Number(todo.minutes) || 25) * 60; timerRunning.value = true; window.clearInterval(timerHandle); timerHandle = window.setInterval(() => { if (todo.remainingSeconds <= 1) { todo.remainingSeconds = 0; finishTimer(todo) } else { todo.remainingSeconds -= 1 } }, 1000) }
function toggleTimer(todo) { if (activeTimerId.value === todo.id && timerRunning.value) { window.clearInterval(timerHandle); timerHandle = null; timerRunning.value = false; showNotice('计时已暂停') } else startTimer(todo) }
function resetTimer(todo) { if (activeTimerId.value === todo.id) stopTimer(); todo.remainingSeconds = 0; showNotice('计时已重置') }
function formatTimer(seconds) { const value = Math.max(0, Number(seconds) || 0); return `${String(Math.floor(value / 60)).padStart(2, '0')}:${String(value % 60).padStart(2, '0')}` }
function playAlarm() { navigator.vibrate?.([180, 90, 180]); try { const context = new AudioContext(); const oscillator = context.createOscillator(); const gain = context.createGain(); oscillator.frequency.value = 880; gain.gain.setValueAtTime(.08, context.currentTime); gain.gain.exponentialRampToValueAtTime(.001, context.currentTime + .5); oscillator.connect(gain); gain.connect(context.destination); oscillator.start(); oscillator.stop(context.currentTime + .5); oscillator.addEventListener('ended', () => context.close(), { once: true }) } catch { /* 浏览器禁止音频时保留页面提醒 */ } }
onBeforeUnmount(() => { stopTimer(); window.clearTimeout(noticeHandle) })
</script>
<style scoped>
.planner-panel { max-width:820px; padding:22px; }.todo-form { display:flex; align-items:end; gap:10px; padding-bottom:20px; border-bottom:1px solid var(--line); }.todo-form > input { min-width:0; flex:1; min-height:42px; padding:0 13px; border:1px solid var(--line); border-radius:5px; outline:none; background:#fff; color:var(--ink); }.todo-form > input:focus { border-color:var(--accent-deep); }.duration-picker { display:grid; width:145px; flex:0 0 145px; gap:6px; color:var(--muted); font-size:10px; }.duration-picker input, .todo-duration input { width:100%; height:5px; margin:6px 0; accent-color:var(--accent-deep); cursor:pointer; }.todo-list { display:grid; }.todo-row { display:grid; grid-template-columns:20px minmax(0,1fr) auto 28px; align-items:center; gap:11px; min-height:67px; border-bottom:1px solid var(--line); font-size:13px; }.todo-row:last-child { border-bottom:0; }.todo-row > input { width:16px; height:16px; accent-color:var(--accent-deep); }.todo-row.done .todo-text { color:var(--muted); text-decoration:line-through; }.todo-main { display:grid; min-width:0; gap:5px; }.todo-text { overflow:hidden; color:var(--ink); text-overflow:ellipsis; white-space:nowrap; }.todo-duration { display:flex; align-items:center; gap:9px; color:var(--muted); font-size:10px; }.todo-duration input { flex:1; min-width:80px; margin:4px 0; }.todo-timer { display:flex; align-items:center; gap:4px; min-width:72px; justify-content:flex-end; }.todo-timer strong { color:var(--accent-deep); font-size:12px; font-variant-numeric:tabular-nums; }.timer-button, .timer-reset, .todo-delete { display:grid; width:28px; height:28px; place-items:center; border:0; border-radius:50%; background:transparent; color:var(--muted); cursor:pointer; }.timer-button:hover, .timer-reset:hover, .todo-delete:hover { background:var(--soft); color:var(--ink); }.todo-row.is-timing { background:rgba(250,255,196,.16); }.todo-row.is-timing .timer-button { background:var(--accent); color:var(--ink); }.todo-delete { font-size:20px; }.planner-notice { margin:14px 0 0; color:var(--accent-deep); font-size:11px; }.planner-notice-enter-active, .planner-notice-leave-active { transition:opacity .18s ease, transform .18s ease; }.planner-notice-enter-from, .planner-notice-leave-to { opacity:0; transform:translateY(-4px); }.todo-empty { margin:24px 0 4px; color:var(--muted); font-size:13px; }
@keyframes timer-pulse { 50% { box-shadow:0 0 0 4px rgba(63,91,49,.1); } }
.todo-row.is-timing .timer-button { animation:timer-pulse 1.8s ease-in-out infinite; }
@media (prefers-reduced-motion: reduce) { .todo-row.is-timing .timer-button { animation:none; } }
@media (max-width:560px) { .todo-form { align-items:stretch; flex-direction:column; }.duration-picker { width:100%; flex-basis:auto; }.todo-form .button { width:100%; }.todo-row { grid-template-columns:20px minmax(0,1fr) auto; gap:9px; padding:10px 0; }.todo-main { grid-column:2 / -1; grid-row:1; }.todo-row > input { grid-column:1; grid-row:1; }.todo-timer { grid-column:2; justify-content:flex-start; }.todo-delete { grid-column:3; grid-row:2; }.todo-duration input { min-width:50px; } }
</style>
