<template>
  <div>
    <PageTitle eyebrow="计划本" title="把今天要做的事放在这里" description="这是你的个人待办清单，完成一项就划掉一项。" />
    <section class="planner-panel surface">
      <form class="todo-form" @submit.prevent="addTodo">
        <input v-model.trim="draft" type="text" placeholder="添加一个待办事项" aria-label="添加待办事项" />
        <button class="button button--accent" type="submit" :disabled="!draft">添加</button>
      </form>
      <div class="todo-list">
        <label v-for="todo in todos" :key="todo.id" class="todo-row" :class="{ done: todo.done }">
          <input v-model="todo.done" type="checkbox" @change="persist" />
          <span>{{ todo.text }}</span>
          <button type="button" aria-label="删除待办" @click="removeTodo(todo.id)">×</button>
        </label>
        <p v-if="!todos.length" class="todo-empty">还没有待办事项。</p>
      </div>
    </section>
  </div>
</template>
<script setup>
import { ref } from 'vue'
import PageTitle from '@/shared/ui/PageTitle.vue'
const storageKey = 'learnmate_todos'
const draft = ref('')
const todos = ref(readTodos())
function readTodos() { try { const value = JSON.parse(localStorage.getItem(storageKey) || '[]'); return Array.isArray(value) ? value : [] } catch { return [] } }
function persist() { localStorage.setItem(storageKey, JSON.stringify(todos.value)) }
function addTodo() { if (!draft.value) return; todos.value.unshift({ id: `${Date.now()}-${Math.random()}`, text: draft.value, done: false }); draft.value = ''; persist() }
function removeTodo(id) { todos.value = todos.value.filter((todo) => todo.id !== id); persist() }
</script>
<style scoped>
.planner-panel { max-width:820px; padding:22px; }.todo-form { display:flex; gap:10px; padding-bottom:20px; border-bottom:1px solid var(--line); }.todo-form input { min-width:0; flex:1; min-height:42px; padding:0 13px; border:1px solid var(--line); border-radius:5px; outline:none; background:#fff; color:var(--ink); }.todo-form input:focus { border-color:var(--accent-deep); }.todo-list { display:grid; }.todo-row { display:grid; grid-template-columns:20px minmax(0,1fr) 28px; align-items:center; gap:11px; min-height:56px; border-bottom:1px solid var(--line); font-size:13px; }.todo-row:last-child { border-bottom:0; }.todo-row input { width:16px; height:16px; accent-color:var(--accent-deep); }.todo-row.done span { color:var(--muted); text-decoration:line-through; }.todo-row button { width:28px; height:28px; border:0; background:transparent; color:var(--muted); font-size:20px; }.todo-row button:hover { color:var(--ink); }.todo-empty { margin:24px 0 4px; color:var(--muted); font-size:13px; }
@media (max-width:560px) { .todo-form { align-items:stretch; flex-direction:column; } }
</style>
