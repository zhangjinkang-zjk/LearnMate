<template>
  <div>
    <div v-if="view === 'activity'" class="admin-metrics"><div class="surface"><span>全站账号</span><strong>{{ metricReady ? summary.total_users : '—' }}</strong></div><div class="surface"><span>近 {{ days }} 天活跃用户</span><strong>{{ metricReady ? summary.active_users : '—' }}</strong></div><div class="surface"><span>近 {{ days }} 天学习时长</span><strong>{{ metricReady ? formatDuration(summary.study_seconds) : '—' }}</strong></div></div>
    <section class="admin-panel surface">
      <header class="admin-section-heading"><h2>{{ viewTitles[view] }}</h2><p>{{ viewDescriptions[view] }}</p></header>
      <form class="admin-toolbar" @submit.prevent="searchUsers">
        <label class="admin-search"><span>查找账号</span><input v-model.trim="search" maxlength="100" placeholder="用户名、邮箱或 ID" /></label>
        <label v-if="view !== 'accounts'"><span>时间范围</span><select v-model.number="days" @change="searchUsers"><option :value="7">近 7 天</option><option :value="30">近 30 天</option></select></label>
        <label v-if="view !== 'accounts'"><span>活跃状态</span><select v-model="activity" @change="searchUsers"><option value="all">全部用户</option><option value="active">活跃用户</option><option value="inactive">不活跃用户</option></select></label>
        <label v-if="view !== 'accounts'"><span>全站排行</span><select v-model="sort" @change="searchUsers"><option value="study_seconds">按学习时长</option><option value="active_days">按学习天数</option></select></label>
        <button class="button button--quiet" :disabled="isLoading">查询</button>
      </form>
      <div class="admin-selection"><span>已选 {{ selected.length }} 人（最多 100 人，可跨页选择）</span><button class="admin-link" :disabled="!selected.length" @click="selected = []">清空</button><button class="button button--primary" :disabled="!selected.length || isLoading" @click="pushRecipients = [...selected]">{{ view === 'push' ? '下一步：选择资源' : '推送资源' }}</button></div>
      <div v-if="selected.length" class="admin-selected-users" aria-label="已选接收人"><button v-for="user in selected" :key="user.id" type="button" :aria-label="`取消选择 ${user.username}`" @click="selectUser(user, false)">{{ user.username }} <span aria-hidden="true">×</span></button></div>
      <p v-if="view !== 'accounts'" class="admin-hint">活跃指所选时间内有学习时长或学习行为；排名在全站账号中计算。最近登录从此功能上线后记录。</p>
      <p v-if="notice" class="admin-notice" role="status">{{ notice }}</p><p v-if="error" class="admin-error" role="alert">{{ error }} <button class="admin-link" @click="load">重试</button></p>
      <div v-if="isLoading" class="admin-empty" role="status">正在读取账号与活跃度…</div>
      <div v-else-if="!items.length && !error" class="admin-empty">没有符合条件的账号</div>
      <div v-else-if="!error" class="admin-table-wrap"><table class="admin-table admin-table--users">
        <thead><tr>
          <th><input type="checkbox" :checked="isPageSelected" :indeterminate="isPagePartiallySelected" aria-label="选择本页账号" @change="selectPage($event.target.checked)" /></th>
          <th>{{ view === 'accounts' ? '账号' : '排名 / 账号' }}</th>
          <template v-if="view === 'accounts'"><th>学校 / 专业</th><th>注册时间</th></template>
          <template v-else><th>学习天数</th><th>学习时长</th></template>
          <th>最近登录 / 学习</th><th>操作</th>
        </tr></thead>
        <tbody><tr v-for="user in items" :key="user.id">
          <td><input type="checkbox" :checked="isSelected(user.id)" :disabled="!isSelected(user.id) && selected.length >= 100" :aria-label="`选择 ${user.username}`" @change="selectUser(user, $event.target.checked)" /></td>
          <td><strong><span v-if="view !== 'accounts'" class="admin-rank">{{ user.rank }}</span> {{ user.username }}</strong><small>#{{ user.id }} · {{ user.role === 'admin' ? '管理员' : '用户' }} · {{ user.email || '未设置邮箱' }}</small></td>
          <template v-if="view === 'accounts'"><td>{{ user.university || '未填写学校' }}<small>{{ [user.grade, user.major].filter(Boolean).join(' · ') || '未填写年级与专业' }}</small></td><td>{{ formatDate(user.created_at) }}</td></template>
          <template v-else><td>{{ user.active_days }} 天 <span v-if="user.is_active" class="admin-badge">活跃</span></td><td>{{ formatDuration(user.study_seconds) }}</td></template>
          <td><span>{{ formatDate(user.last_login_at) }}</span><small>学习：{{ formatDate(user.last_active_at) }}</small></td>
          <td><div class="admin-row-actions">
            <button class="admin-link" @click="openUser(user, 'activity')">学习详情</button>
            <template v-if="view === 'accounts'"><button class="admin-link" @click="openUser(user, 'edit')">编辑</button><button class="admin-link" @click="openUser(user, 'password')">重置密码</button><button v-if="user.role !== 'admin'" class="admin-link admin-danger" @click="openUser(user, 'delete')">删除</button></template>
            <button class="admin-link" @click="pushRecipients = [user]">推送资源</button>
          </div></td>
        </tr></tbody>
      </table></div>
      <footer class="admin-pagination"><span>共 {{ total }} 人 · 第 {{ page }} 页</span><button class="button button--quiet" :disabled="page === 1 || isLoading" @click="changePage(-1)">上一页</button><button class="button button--quiet" :disabled="page * 20 >= total || isLoading" @click="changePage(1)">下一页</button></footer>
    </section>
  </div>
  <ActionDialog v-if="target" :title="`${dialogTitles[mode]} · ${target.username}`" :busy="isSaving" @close="closeDialog">
    <div class="admin-dialog-content">
      <p v-if="dialogError" class="admin-error" role="alert">{{ dialogError }} <button v-if="mode === 'activity'" class="admin-link" @click="openUser(target, 'activity')">重试</button></p>
      <template v-if="mode === 'activity'">
        <p class="admin-hint">最近登录：{{ formatDate(target.last_login_at) }} · 注册时间：{{ formatDate(target.created_at) }}</p>
        <p v-if="isReading" role="status">正在读取学习记录…</p>
        <template v-else-if="detail">
          <h3>最近 30 天学习时长</h3>
          <div class="admin-activity-bars" aria-label="每日学习时长"><div v-for="day in detail.sessions" :key="day.date"><time>{{ day.date }}</time><meter :value="day.total_seconds" :max="maxSeconds">{{ formatDuration(day.total_seconds) }}</meter><span>{{ formatDuration(day.total_seconds) }}</span></div><p v-if="!detail.sessions.length" class="admin-hint">暂无学习时长记录</p></div>
          <h3>最近资源学习记录（最多 30 条）</h3>
          <div v-for="resource in detail.resources" :key="resource.resource_id" class="admin-history-row"><strong>{{ resource.title }}</strong><span>{{ resource.is_read ? '已读' : '未读' }} · {{ formatDuration(resource.duration_seconds) }}</span><small>{{ formatDate(resource.read_at) }}</small></div><p v-if="!detail.resources.length" class="admin-hint">暂无资源学习记录</p>
        </template>
      </template>
      <form v-else @submit.prevent="saveUser" class="admin-dialog-content">
        <template v-if="mode === 'edit'"><label><span>学校</span><input v-model.trim="draft.university" maxlength="100" /></label><label><span>年级</span><input v-model.trim="draft.grade" maxlength="20" /></label><label><span>专业</span><input v-model.trim="draft.major" maxlength="200" /></label></template>
        <template v-if="mode === 'password'"><p class="admin-hint">为此账号设置新密码，请通过可信渠道告知用户。</p><label><span>新密码（8–72 字节）</span><input v-model="password" type="password" minlength="8" maxlength="72" autocomplete="new-password" required /></label><label><span>再次输入新密码</span><input v-model="confirmation" type="password" minlength="8" maxlength="72" autocomplete="new-password" required /></label></template>
        <template v-if="mode === 'delete'"><p>删除账号会同时删除该用户的学习数据，此操作无法撤销。</p><label><span>输入用户名「{{ target.username }}」确认删除</span><input v-model="confirmation" autocomplete="off" required /></label></template>
        <div class="admin-dialog-actions"><button class="button button--quiet" type="button" :disabled="isSaving" @click="closeDialog">取消</button><button class="button button--primary" :disabled="isSaving || (mode === 'delete' && confirmation !== target.username)">{{ isSaving ? '处理中…' : mode === 'delete' ? '确认删除账号' : mode === 'password' ? '确认重置密码' : '保存修改' }}</button></div>
      </form>
    </div>
  </ActionDialog>
  <ResourcePushDialog v-if="pushRecipients.length" :recipients="pushRecipients" @close="pushRecipients = []" @sent="onSent" />
</template>
<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { adminApi } from '@/shared/api/adminApi'
import ActionDialog from '@/shared/ui/ActionDialog.vue'
import ResourcePushDialog from './ResourcePushDialog.vue'
import { formatDate, formatDuration } from './adminFormat'
defineProps({ view: { type: String, default: 'accounts' } })
const viewTitles = { accounts: '账号管理', activity: '全站学习活跃度', push: '为用户推荐学习资源' }
const viewDescriptions = {
  accounts: '查看账号资料，编辑学校信息，或为用户重置密码。',
  activity: '从学习天数、投入时长和最近学习记录了解用户的学习情况。',
  push: '先选择接收人，再选择资源，通过站内通知发送学习建议。',
}
const search = ref(''), days = ref(7), activity = ref('all'), sort = ref('study_seconds'), page = ref(1), total = ref(0), items = ref([])
const summary = ref({ total_users: 0, active_users: 0, study_seconds: 0 }), selected = ref([]), pushRecipients = ref([])
const isLoading = ref(false), error = ref(''), notice = ref(''), target = ref(null), mode = ref('activity'), detail = ref(null)
const isReading = ref(false), isSaving = ref(false), dialogError = ref(''), password = ref(''), confirmation = ref('')
const draft = reactive({ university: '', grade: '', major: '' })
const dialogTitles = { activity: '学习活跃度', edit: '编辑账号资料', password: '重置密码', delete: '删除账号' }
const maxSeconds = computed(() => Math.max(1, ...(detail.value?.sessions || []).map(day => day.total_seconds)))
const isPageSelected = computed(() => items.value.length > 0 && items.value.every(user => isSelected(user.id)))
const isPagePartiallySelected = computed(() => !isPageSelected.value && items.value.some(user => isSelected(user.id)))
const metricReady = computed(() => !isLoading.value && !error.value && hasLoaded.value)
const hasLoaded = ref(false)
let loadVersion = 0, detailVersion = 0
function isSelected(id) { return selected.value.some(user => user.id === id) }
function selectUser(user, checked) {
  if (!checked) { selected.value = selected.value.filter(item => item.id !== user.id); return }
  if (isSelected(user.id)) return
  if (selected.value.length >= 100) { notice.value = '单次最多选择 100 人'; return }
  selected.value.push(user)
}
function selectPage(checked) { items.value.forEach(user => selectUser(user, checked)) }
async function load() {
  const version = ++loadVersion
  isLoading.value = true; error.value = ''
  try {
    const result = await adminApi.users({ search: search.value, days: days.value, activity: activity.value, sort: sort.value, page: page.value })
    if (version !== loadVersion) return
    items.value = result.items; total.value = result.total; summary.value = result.summary
    hasLoaded.value = true
    if (!items.value.length && page.value > 1) { page.value--; await load() }
  } catch (cause) { if (version === loadVersion) error.value = cause.message }
  finally { if (version === loadVersion) isLoading.value = false }
}
async function searchUsers() { page.value = 1; await load() }
async function changePage(step) { page.value += step; await load() }
function closeDialog() { detailVersion++; target.value = null; password.value = ''; confirmation.value = ''; dialogError.value = '' }
async function openUser(user, nextMode) {
  const version = ++detailVersion
  target.value = user; mode.value = nextMode; dialogError.value = ''; password.value = ''; confirmation.value = ''; detail.value = null
  Object.assign(draft, { university: user.university || '', grade: user.grade || '', major: user.major || '' })
  if (nextMode !== 'activity') return
  isReading.value = true
  try { const result = await adminApi.userActivity(user.id); if (version === detailVersion) detail.value = result }
  catch (cause) { if (version === detailVersion) dialogError.value = cause.message }
  finally { if (version === detailVersion) isReading.value = false }
}
async function saveUser() {
  if (isSaving.value) return
  dialogError.value = ''
  if (mode.value === 'password' && (password.value !== confirmation.value || password.value.length < 8 || !password.value.trim() || new TextEncoder().encode(password.value).length > 72)) { dialogError.value = '两次密码必须一致，新密码至少 8 位且不能超过 72 字节'; return }
  if (mode.value === 'delete' && confirmation.value !== target.value.username) { dialogError.value = '请输入完整用户名确认删除'; return }
  isSaving.value = true
  try {
    if (mode.value === 'password') { await adminApi.resetPassword(target.value.id, password.value); notice.value = '密码已重置' }
    if (mode.value === 'edit') { await adminApi.updateUser(target.value.id, { ...draft }); notice.value = '账号资料已保存' }
    if (mode.value === 'delete') { await adminApi.deleteUser(target.value.id); selected.value = selected.value.filter(user => user.id !== target.value.id); notice.value = '账号已删除' }
    closeDialog(); await load()
  } catch (cause) { dialogError.value = cause.message }
  finally { isSaving.value = false }
}
function onSent(result) { pushRecipients.value = []; notice.value = `已为 ${result.created} 人发送资源推荐通知${result.skipped ? `，${result.skipped} 人已收到相同推荐，已跳过` : ''}` }
onMounted(load)
</script>
