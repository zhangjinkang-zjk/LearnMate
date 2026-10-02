<template>
  <ActionDialog title="推送学习资源" :busy="isSending" @close="emit('close')">
    <div class="admin-dialog-content">
      <p>接收人：{{ recipients.map(user => user.username).join('、') }}（{{ recipients.length }} 人）</p>
      <p class="admin-hint">资源将发送到站内通知，并加入每位用户的学习任务。已有相同任务的用户会自动跳过。</p>
      <form class="admin-toolbar" @submit.prevent="searchResources"><label class="admin-search"><span>选择已审核的公开资源</span><input v-model.trim="search" maxlength="100" placeholder="搜索资源标题" :disabled="isSending" /></label><button class="button button--quiet" :disabled="isLoading || isSending">查询</button></form>
      <p v-if="error" class="admin-error" role="alert">{{ error }}</p>
      <p v-if="isLoading" role="status">正在读取资源…</p>
      <div v-else class="admin-options">
        <label v-for="resource in resources" :key="resource.resource_id" class="admin-option"><input v-model="selectedId" type="radio" name="push-resource" :value="resource.resource_id" :disabled="isSending" /><span>{{ resource.topic }}<small>{{ resource.resource_type }} · #{{ resource.resource_id }}</small></span></label>
        <p v-if="!resources.length" class="admin-empty">暂无可推送资源，请先完成资源审核。</p>
      </div>
      <div class="admin-pagination"><span>共 {{ total }} 份 · 第 {{ page }} 页</span><button class="button button--quiet" :disabled="page === 1 || isLoading || isSending" @click="changePage(-1)">上一页</button><button class="button button--quiet" :disabled="page * 20 >= total || isLoading || isSending" @click="changePage(1)">下一页</button></div>
      <label><span>学习建议（可选）</span><textarea v-model.trim="message" rows="3" maxlength="1000" :disabled="isSending" placeholder="例如：建议先阅读前两节，再完成课后练习。" /></label>
      <div class="admin-dialog-actions"><button class="button button--quiet" :disabled="isSending" @click="emit('close')">取消</button><button class="button button--primary" :disabled="!selectedId || isSending || isLoading" @click="send">{{ isSending ? '推送中…' : '推送并创建任务' }}</button></div>
    </div>
  </ActionDialog>
</template>
<script setup>
import { onMounted, ref } from 'vue'
import ActionDialog from '@/shared/ui/ActionDialog.vue'
import { adminApi } from '@/shared/api/adminApi'
const props = defineProps({ recipients: { type: Array, required: true } })
const emit = defineEmits(['close', 'sent'])
const resources = ref([]), search = ref(''), page = ref(1), total = ref(0), selectedId = ref(null), message = ref('')
const isLoading = ref(false), isSending = ref(false), error = ref('')
let loadVersion = 0
async function load() {
  const version = ++loadVersion
  isLoading.value = true; error.value = ''; selectedId.value = null
  try {
    const result = await adminApi.resources({ search: search.value, pushable: true, page: page.value })
    if (version === loadVersion) { resources.value = result.items; total.value = result.total }
  } catch (cause) { if (version === loadVersion) { error.value = cause.message; resources.value = [] } }
  finally { if (version === loadVersion) isLoading.value = false }
}
function searchResources() { page.value = 1; load() }
function changePage(step) { page.value += step; load() }
async function send() {
  if (isSending.value || !selectedId.value) return
  isSending.value = true; error.value = ''
  try {
    const result = await adminApi.push({ resource_id: selectedId.value, user_ids: props.recipients.map(user => user.id), message: message.value })
    emit('sent', result)
  } catch (cause) { error.value = cause.message }
  finally { isSending.value = false }
}
onMounted(load)
</script>
