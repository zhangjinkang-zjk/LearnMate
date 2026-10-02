<template>
  <div class="assignments-page">
    <PageTitle eyebrow="学习任务" title="为你安排的学习资源" description="管理员推荐的资源会保存在这里，学完后可以标记完成。" />
    <div class="assignment-toolbar"><label>任务状态 <select v-model="filter"><option value="pending">待完成（{{ pendingCount }}）</option><option value="all">全部任务</option><option value="completed">已完成</option></select></label><button class="button button--quiet" :disabled="isLoading" @click="load(false)">刷新</button></div>
    <p v-if="error" class="assignment-error" role="alert">{{ error }}</p>
    <p v-if="notice" class="assignment-notice" role="status">{{ notice }}</p>
    <p v-if="isLoading" class="assignment-empty" role="status">正在读取学习任务…</p>
    <p v-else-if="!filtered.length && !error" class="assignment-empty surface">当前没有{{ filter === 'completed' ? '已完成' : filter === 'pending' ? '待完成' : '' }}的学习任务。</p>
    <div v-else class="assignment-list"><article v-for="task in filtered" :key="task.id" class="assignment-card surface" :class="{ 'is-selected': Number(route.query.task) === task.id }">
      <div><span class="assignment-status">{{ task.completed_at ? '已完成' : task.is_available ? '待学习' : '资源已下架' }}</span><h2>{{ task.title }}</h2><p v-if="task.message">{{ task.message }}</p><p v-if="!task.is_available">这份资源暂时无法查看，请等待管理员更新。</p><small>安排时间：{{ formatDate(task.created_at) }}</small><small v-if="task.completed_at">完成时间：{{ formatDate(task.completed_at) }}</small></div>
      <div class="assignment-actions"><button class="button button--quiet" :disabled="!task.is_available" @click="openResource(task)">查看资源</button><button v-if="!task.completed_at" class="button button--primary" :disabled="!task.is_available || completingId !== null" @click="complete(task)">{{ completingId === task.id ? '保存中…' : '标记完成' }}</button></div>
    </article></div>
    <ActionDialog v-if="previewTask" :title="previewTask.title" @close="closePreview">
      <p v-if="isReading" role="status">正在读取资源…</p><p v-if="previewError" class="assignment-error" role="alert">{{ previewError }} <button class="button button--quiet" @click="openResource(previewTask)">重试</button></p><ResourceContent v-if="resource" :resource="resource" />
    </ActionDialog>
  </div>
</template>
<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { assignmentApi } from '@/shared/api/adminApi'
import PageTitle from '@/shared/ui/PageTitle.vue'
import ActionDialog from '@/shared/ui/ActionDialog.vue'
import ResourceContent from '@/features/resources/ResourceContent.vue'
import { formatDate } from '@/features/admin/adminFormat'
const route = useRoute()
const items = ref([]), filter = ref('pending'), isLoading = ref(false), error = ref(''), notice = ref(''), completingId = ref(null)
const previewTask = ref(null), resource = ref(null), isReading = ref(false), previewError = ref('')
const pendingCount = computed(() => items.value.filter(task => !task.completed_at).length)
const filtered = computed(() => items.value.filter(task => filter.value === 'all' || Boolean(task.completed_at) === (filter.value === 'completed')))
let previewVersion = 0
async function load(shouldOpenLinkedTask = true) {
  if (isLoading.value) return
  isLoading.value = true; error.value = ''
  try { items.value = await assignmentApi.list(); if (shouldOpenLinkedTask) await openLinkedTask() }
  catch (cause) { error.value = cause.message }
  finally { isLoading.value = false }
}
async function openLinkedTask() {
  if (!route.query.task) return
  const task = items.value.find(item => item.id === Number(route.query.task))
  if (task) { filter.value = 'all'; if (task.is_available) await openResource(task) }
  else { notice.value = '这条通知对应的学习任务已不存在。' }
}
function closePreview() { previewVersion++; previewTask.value = null; resource.value = null }
async function openResource(task) {
  const version = ++previewVersion
  previewTask.value = task; resource.value = null; previewError.value = ''; isReading.value = true
  try { const result = await assignmentApi.resource(task.resource_id); if (version === previewVersion) resource.value = result }
  catch (cause) { if (version === previewVersion) previewError.value = cause.message }
  finally { if (version === previewVersion) isReading.value = false }
}
async function complete(task) {
  if (completingId.value !== null) return
  completingId.value = task.id; error.value = ''
  try { const result = await assignmentApi.complete(task.id); items.value = items.value.map(item => item.id === task.id ? result : item); notice.value = `《${task.title}》已完成` }
  catch (cause) { error.value = cause.message }
  finally { completingId.value = null }
}
watch(() => route.query.task, openLinkedTask)
onMounted(load)
</script>
<style scoped>
.assignment-toolbar { display:flex; justify-content:space-between; align-items:center; gap:16px; margin:24px 0; color:var(--muted); font-size:13px; }
.assignment-toolbar select { padding:8px; margin-left:8px; border:1px solid var(--line); border-radius:6px; color:var(--ink); background:var(--paper); }
.assignment-list { display:grid; gap:14px; }.assignment-card { display:flex; justify-content:space-between; gap:24px; padding:24px; }.assignment-card > div { min-width:0; }.assignment-card.is-selected { border-color:var(--accent-deep); }.assignment-card h2 { margin:12px 0; font-size:19px; overflow-wrap:anywhere; }.assignment-card p { color:var(--muted); font-size:13px; line-height:1.8; white-space:pre-wrap; overflow-wrap:anywhere; }.assignment-card small { display:block; margin-top:7px; color:var(--muted); font-size:11px; }.assignment-status { color:var(--accent-deep); background:var(--soft); padding:4px 8px; border-radius:5px; font-size:11px; }.assignment-actions { display:flex; flex-shrink:0; align-items:center; gap:10px; }.assignment-empty { padding:48px 16px; color:var(--muted); text-align:center; }.assignment-error { color:#a33d34; font-size:13px; }.assignment-notice { color:var(--accent-deep); font-size:13px; }button:disabled { opacity:.5; cursor:not-allowed; }button:focus-visible, select:focus-visible { outline:2px solid var(--accent-deep); outline-offset:3px; }
@media(max-width:700px) { .assignment-card { flex-direction:column; padding:18px; }.assignment-actions { flex-wrap:wrap; } }
</style>
