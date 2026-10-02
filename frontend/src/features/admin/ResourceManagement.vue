<template>
  <section class="admin-panel surface">
    <header class="admin-section-heading"><h2>资源审核与维护</h2><p>查看完整内容后审核公开申请，也可以修改已有资源或删除不再适用的材料。</p></header>
    <form class="admin-toolbar" @submit.prevent="searchResources">
      <label class="admin-search"><span>查找资源</span><input v-model.trim="search" maxlength="100" placeholder="输入资源标题" /></label>
      <label><span>审核状态</span><select v-model="visibility" @change="searchResources"><option value="">全部资源</option><option v-for="(label, key) in visibilityLabels" :key="key" :value="key">{{ label }}</option></select></label>
      <button class="button button--quiet" :disabled="isLoading">查询</button>
      <span class="admin-meta">待审核 {{ pending }} 份</span>
    </form>
    <p v-if="notice" class="admin-notice" role="status">{{ notice }}</p>
    <p v-if="error" class="admin-error" role="alert">{{ error }} <button class="admin-link" @click="load">重试</button></p>
    <div v-if="isLoading" class="admin-empty" role="status">正在读取资源…</div>
    <div v-else-if="!items.length && !error" class="admin-empty">没有符合条件的资源</div>
    <div v-else-if="!error" class="admin-table-wrap">
      <table class="admin-table"><thead><tr><th>资源</th><th>状态</th><th>提交者</th><th>更新时间</th><th>操作</th></tr></thead>
        <tbody><tr v-for="item in items" :key="item.resource_id">
          <td><strong>{{ item.topic }}</strong><small>#{{ item.resource_id }} · {{ formatResourceType(item.resource_type) }}</small></td>
          <td><span class="admin-badge" :class="{ 'is-pending': item.visibility === 'pending' }">{{ visibilityLabels[item.visibility] }}</span></td>
          <td>#{{ item.owner_user_id }}</td><td>{{ formatDate(item.updated_at) }}</td>
          <td><div class="admin-row-actions"><button class="admin-link" @click="openEditor(item)">{{ item.visibility === 'pending' ? '查看 / 审核' : '查看 / 编辑' }}</button><button class="admin-link admin-danger" @click="openDelete(item)">删除</button></div></td>
        </tr></tbody>
      </table>
    </div>
    <footer class="admin-pagination"><span>共 {{ total }} 份 · 第 {{ page }} 页</span><button class="button button--quiet" :disabled="page === 1 || isLoading" @click="changePage(-1)">上一页</button><button class="button button--quiet" :disabled="page * 20 >= total || isLoading" @click="changePage(1)">下一页</button></footer>
  </section>
  <ActionDialog v-if="editorOpen" title="资源详情与审核" :busy="isSaving" :is-dirty="Boolean(hasEdits)" @close="closeEditor">
    <div class="admin-dialog-content">
      <p v-if="isReading" class="admin-empty">正在加载完整内容…</p>
      <p v-if="dialogError" class="admin-error" role="alert">{{ dialogError }} <button v-if="!record && !isReading" class="admin-link" @click="openEditor({ resource_id: editorResourceId })">重试</button></p>
      <template v-if="record && !isReading">
        <div class="admin-row-actions"><span class="admin-badge">{{ visibilityLabels[record.visibility] }}</span><button class="admin-link" :disabled="isSaving" @click="showSource = !showSource">{{ showSource ? '预览内容' : '编辑原文' }}</button></div>
        <label><span>资源标题</span><input v-model.trim="draft.topic" maxlength="255" :disabled="isSaving" /></label>
        <label v-if="showSource"><span>资源正文</span><textarea v-model="draft.content" rows="14" maxlength="2000000" :disabled="isSaving" /></label>
        <ResourceContent v-else :resource="{ ...record, ...draft }" />
        <label v-if="record.visibility === 'pending'"><span>驳回原因（可选）</span><textarea v-model.trim="reason" rows="2" maxlength="1000" :disabled="isSaving" placeholder="告知提交者需要修改的内容" /></label>
        <p v-if="hasEdits" class="admin-hint">内容已修改，请先保存后再审核。</p>
        <div class="admin-dialog-actions"><button class="button button--quiet" :disabled="isSaving || !hasEdits || !draft.topic" @click="save">{{ isSaving ? '处理中…' : '保存修改' }}</button><template v-if="record.visibility === 'pending'"><button class="button button--quiet" :disabled="isSaving || hasEdits" @click="review(false)">驳回申请</button><button class="button button--primary" :disabled="isSaving || hasEdits" @click="review(true)">审核通过并公开</button></template></div>
      </template>
    </div>
  </ActionDialog>
  <ActionDialog v-if="deleteTarget" title="删除资源" :busy="isSaving" @close="deleteTarget = null">
    <div class="admin-dialog-content"><p>确定删除《{{ deleteTarget.topic }}》？此操作无法撤销。</p><p v-if="dialogError" class="admin-error" role="alert">{{ dialogError }}</p><div class="admin-dialog-actions"><button class="button button--quiet" :disabled="isSaving" @click="deleteTarget = null">取消</button><button class="button button--primary" :disabled="isSaving" @click="remove">{{ isSaving ? '删除中…' : '确认删除' }}</button></div></div>
  </ActionDialog>
</template>
<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { adminApi } from '@/shared/api/adminApi'
import ActionDialog from '@/shared/ui/ActionDialog.vue'
import ResourceContent from '@/features/resources/ResourceContent.vue'
import { formatDate, visibilityLabels, formatResourceType } from './adminFormat'
const items = ref([]), search = ref(''), visibility = ref('pending'), page = ref(1), total = ref(0), pending = ref(0)
const isLoading = ref(false), error = ref(''), notice = ref(''), dialogError = ref(''), isSaving = ref(false)
const editorOpen = ref(false), isReading = ref(false), record = ref(null), deleteTarget = ref(null), showSource = ref(false), reason = ref('')
const draft = reactive({ topic: '', content: '' })
const editorResourceId = ref(null)
const hasEdits = computed(() => record.value && (record.value.topic !== draft.topic || record.value.content !== draft.content))
let loadVersion = 0, editorVersion = 0
async function load() {
  const version = ++loadVersion
  isLoading.value = true; error.value = ''
  try {
    const result = await adminApi.resources({ search: search.value, visibility: visibility.value || undefined, page: page.value })
    if (version !== loadVersion) return
    items.value = result.items; total.value = result.total; pending.value = result.pending
    if (!items.value.length && page.value > 1) { page.value--; await load() }
  } catch (cause) { if (version === loadVersion) error.value = cause.message }
  finally { if (version === loadVersion) isLoading.value = false }
}
async function searchResources() { page.value = 1; await load() }
async function changePage(step) { page.value += step; await load() }
function openDelete(item) { dialogError.value = ''; deleteTarget.value = item }
function closeEditor() { editorVersion++; editorOpen.value = false; record.value = null }
async function openEditor(item) {
  editorResourceId.value = item.resource_id
  const version = ++editorVersion
  editorOpen.value = true; isReading.value = true; dialogError.value = ''; record.value = null; showSource.value = false; reason.value = ''
  try {
    const result = await adminApi.resource(item.resource_id)
    if (version !== editorVersion) return
    record.value = result; Object.assign(draft, { topic: result.topic, content: result.content })
  } catch (cause) { if (version === editorVersion) dialogError.value = cause.message }
  finally { if (version === editorVersion) isReading.value = false }
}
async function save() {
  if (isSaving.value || !draft.topic) return
  isSaving.value = true; dialogError.value = ''
  try { await adminApi.updateResource(record.value.resource_id, { ...draft }); record.value = { ...record.value, ...draft }; notice.value = '资源修改已保存'; await load() }
  catch (cause) { dialogError.value = cause.message }
  finally { isSaving.value = false }
}
async function review(approved) {
  if (isSaving.value || hasEdits.value) return
  isSaving.value = true; dialogError.value = ''
  try { await adminApi.review(record.value.resource_id, approved, reason.value); notice.value = approved ? '审核通过，资源已公开' : '申请已驳回，已通知提交者'; closeEditor(); await load() }
  catch (cause) { dialogError.value = cause.message }
  finally { isSaving.value = false }
}
async function remove() {
  if (isSaving.value) return
  isSaving.value = true; dialogError.value = ''
  try { await adminApi.deleteResource(deleteTarget.value.resource_id); deleteTarget.value = null; notice.value = '资源已删除'; await load() }
  catch (cause) { dialogError.value = cause.message }
  finally { isSaving.value = false }
}
onMounted(load)
</script>
