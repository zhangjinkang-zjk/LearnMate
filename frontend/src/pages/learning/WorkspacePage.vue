<template>
  <div class="workspace-page">
    <div v-if="loading" class="page-state surface" aria-live="polite">
      <LoaderCircle class="spin" :size="25" />
      <strong>正在打开任务工作区</strong>
      <p>同步任务背景、主讲文档和当前节点资料。</p>
    </div>

    <div v-else-if="errorMessage" class="page-state page-state--error surface">
      <CircleAlert :size="25" />
      <strong>任务工作区暂时不可用</strong>
      <p>{{ errorMessage }}</p>
      <button class="button button--quiet" type="button" @click="loadWorkspace">重新加载</button>
    </div>

    <div v-else-if="!context.nodeId" class="page-state surface">
      <Route :size="25" />
      <strong>还没有选中的进阶任务</strong>
      <p>请从学习进阶进入任务工作区，系统才能加载对应的任务资料和交付要求。</p>
      <RouterLink class="button button--primary" to="/learning/advanced">返回学习进阶 <ArrowLeft :size="15" /></RouterLink>
    </div>

    <template v-else>
      <header class="workspace-header">
        <div class="workspace-header__copy">
          <RouterLink class="back-link" to="/learning/advanced"><ArrowLeft :size="15" /> 返回学习进阶</RouterLink>
          <p class="eyebrow">进阶任务工作区</p>
          <h1>{{ task.title || node.topic }}</h1>
          <p>{{ task.brief || '阅读材料，记录判断，并留下可复查的阶段成果。' }}</p>
        </div>
        <div class="save-status" :class="{ 'is-saved': saved }"><span></span>{{ saved ? '草稿已保存' : '自动保存中' }}</div>
      </header>

      <div class="workspace-layout">
        <aside class="workspace-materials">
          <section class="surface material-panel">
            <div class="panel-heading"><div><p class="eyebrow">任务资料</p><h2>先看这些材料</h2></div><span>{{ resources.length }} 份</span></div>
            <button v-for="resource in resources" :key="resource.resource_id || resource.id" class="material-item" type="button" :class="{ 'is-active': selectedResourceId === resourceKey(resource) }" @click="selectResource(resource)">
              <span class="material-icon"><FileText v-if="resource.resource_type === 'document'" :size="15" /><Network v-else :size="15" /></span>
              <span><strong>{{ resource.topic || resource.title || '节点材料' }}</strong><small>{{ resourceTypeLabel(resource.resource_type) }}</small></span>
              <Check v-if="readResourceIds.has(resourceKey(resource))" :size="14" />
            </button>
            <div v-if="!resources.length" class="material-empty"><FileText :size="18" /><p>当前节点还没有材料，先返回基础讲解生成主讲文档。</p><RouterLink class="text-link" to="/learning/fundamentals">打开基础讲解 →</RouterLink></div>
          </section>

          <section class="surface rubric-panel">
            <p class="eyebrow">阶段要求</p>
            <h2>本阶段需要留下</h2>
            <ul>
              <li v-for="item in deliverables" :key="item.id"><span></span>{{ item.label }}</li>
            </ul>
          </section>
        </aside>

        <main class="workspace-main">
          <div class="document-toolbar">
            <div class="document-tabs"><button type="button" :class="{ 'is-active': view === 'document' }" @click="view = 'document'"><BookOpenText :size="15" />主讲文档</button><button type="button" :class="{ 'is-active': view === 'task' }" @click="view = 'task'"><ClipboardCheck :size="15" />任务说明</button></div>
            <span>{{ view === 'document' ? (selectedResource?.topic || node.topic) : '交付要求与验收标准' }}</span>
          </div>

          <MarkdownDocument v-if="view === 'document'" :title="selectedResource?.topic || node.topic" :content="documentContent" :tags="node.knowledge_tags || []" :chapter-number="node.order_index || 1" empty-message="当前材料还没有正文内容，请先生成节点文档。" />
          <section v-else class="surface task-document">
            <p class="eyebrow">任务情境</p><h2>{{ task.problem || `围绕“${node.topic}”完成一次目标验证。` }}</h2><p class="task-brief">{{ task.brief }}</p>
            <h3>验收标准</h3><ol><li v-for="(criterion, index) in criteria" :key="criterion"><span>{{ index + 1 }}</span>{{ criterion }}</li></ol>
          </section>

          <section class="surface submission-panel">
            <div class="panel-heading"><div><p class="eyebrow">当前交付</p><h2>把你的判断写下来</h2></div><span>{{ draft.length }} 字</span></div>
            <textarea v-model="draft" maxlength="6000" placeholder="记录问题判断、材料依据、方案取舍和下一步验证……"></textarea>
            <div class="submission-footer"><span>内容会保存在当前浏览器草稿中，后续接入评价服务后可提交验收。</span><button class="button button--primary" type="button" :disabled="!draft.trim()" @click="saveDraft"><Save :size="15" />保存阶段成果</button></div>
            <p v-if="savedMessage" class="saved-message"><Check :size="14" />{{ savedMessage }}</p>
          </section>
        </main>

        <LearningAssistant v-if="context.pathId && context.nodeId" :path-id="context.pathId" :node-id="context.nodeId" :chapter-title="node.topic" :chapter-content="documentContent" :knowledge-tags="node.knowledge_tags || []" />
      </div>
    </template>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { ArrowLeft, BookOpenText, Check, CircleAlert, ClipboardCheck, FileText, LoaderCircle, Network, Route, Save } from 'lucide-vue-next'
import LearningAssistant from '@/features/fundamentals/LearningAssistant.vue'
import MarkdownDocument from '@/features/fundamentals/MarkdownDocument.vue'
import { advancedLearningApi } from '@/shared/api/advancedLearningApi'
import { fundamentalsApi } from '@/shared/api/fundamentalsApi'

const route = useRoute()
const loading = ref(true)
const errorMessage = ref('')
const saved = ref(false)
const savedMessage = ref('')
const draft = ref('')
const view = ref('document')
const selectedResourceId = ref(null)
const selectedResource = ref(null)
const documentContent = ref('')
const resources = ref([])
const readResourceIds = reactive(new Set())
const context = reactive({ pathId: Number(route.query.pathId) || null, nodeId: Number(route.query.nodeId) || null })
const node = reactive({ topic: '', order_index: 1, knowledge_tags: [], progress: {} })
const task = reactive({ title: '', brief: '', problem: '', deliverables: [], criteria: [] })
let readStartedAt = 0

const deliverables = computed(() => task.deliverables || [])
const criteria = computed(() => task.criteria || [])
const draftKey = computed(() => context.nodeId ? `learnmate_advanced_draft_${context.nodeId}` : '')
const resourceKey = (resource) => String(resource?.resource_id || resource?.id || '')
const resourceTypeLabel = (type) => ({ document: '主讲文档', mindmap: '知识结构', case: '案例材料', exercise: '练习材料' })[type] || '学习材料'

function normalizeContent(content) {
  if (!content) return ''
  if (typeof content !== 'string') return String(content)
  const trimmed = content.trim()
  if (!trimmed.startsWith('{')) return trimmed
  try {
    const parsed = JSON.parse(trimmed)
    return parsed.markdown || parsed.content || parsed.document || parsed.body || trimmed
  } catch { return trimmed }
}

function errorDetail(error, fallback) { return error.response?.data?.detail || error.message || fallback }

async function selectResource(resource) {
  selectedResource.value = resource
  selectedResourceId.value = resourceKey(resource)
  readStartedAt = Date.now()
  documentContent.value = ''
  try {
    const detail = await fundamentalsApi.getResource(resource.resource_id || resource.id)
    documentContent.value = normalizeContent(detail?.content)
    if (documentContent.value) {
      readResourceIds.add(resourceKey(resource))
      await fundamentalsApi.markResourceRead(resource.resource_id || resource.id, 1)
    }
  } catch (error) {
    errorMessage.value = errorDetail(error, '材料加载失败，请稍后重试。')
  }
}

async function loadWorkspace() {
  loading.value = true
  errorMessage.value = ''
  try {
    const advanced = await advancedLearningApi.getCurrentTask()
    const payload = advanced?.data?.data ?? advanced?.data ?? {}
    const currentTask = payload.task || {}
    Object.assign(task, currentTask)
    const workspace = currentTask.workspace || {}
    if (!context.pathId) context.pathId = Number(workspace.path_id) || null
    if (!context.nodeId) context.nodeId = Number(workspace.node_id) || null
    if (!context.pathId || !context.nodeId) return

    const detail = await fundamentalsApi.getNode(context.pathId, context.nodeId)
    Object.assign(node, detail || {})
    resources.value = detail?.progress?.resources || []
    const firstDocument = resources.value.find((item) => item.resource_type === 'document') || resources.value[0]
    if (firstDocument) await selectResource(firstDocument)
    const stored = draftKey.value ? localStorage.getItem(draftKey.value) : ''
    if (stored) draft.value = stored
  } catch (error) {
    errorMessage.value = errorDetail(error, '无法读取当前任务工作区。')
  } finally {
    loading.value = false
  }
}

function saveDraft() {
  if (!draftKey.value || !draft.value.trim()) return
  localStorage.setItem(draftKey.value, draft.value.trim())
  saved.value = true
  savedMessage.value = '阶段成果已保存为草稿。'
  window.setTimeout(() => { savedMessage.value = '' }, 2600)
}

watch(draft, () => { saved.value = false })
onMounted(loadWorkspace)
onBeforeUnmount(() => {
  if (draft.value.trim() && draftKey.value) localStorage.setItem(draftKey.value, draft.value.trim())
  if (selectedResource.value && readStartedAt) fundamentalsApi.markResourceRead(selectedResource.value.resource_id || selectedResource.value.id, Math.max(1, Math.round((Date.now() - readStartedAt) / 1000))).catch(() => {})
})
</script>

<style scoped>
.workspace-page { min-width: 0; }.button { gap: 7px; }.page-state { display: grid; min-height: 520px; place-items: center; align-content: center; gap: 11px; padding: 48px; color: var(--accent-deep); text-align: center; }.page-state strong { color: var(--ink); font-size: 16px; }.page-state p { max-width: 430px; margin: 0; color: var(--muted); font-size: 12px; line-height: 1.7; }.page-state--error { color: #a66442; }.page-state .button { margin-top: 7px; }.spin { animation: spin .8s linear infinite; }
.workspace-header { display: flex; align-items: flex-end; justify-content: space-between; gap: 24px; margin-bottom: 24px; }.workspace-header__copy { min-width: 0; }.back-link { display: inline-flex; align-items: center; gap: 5px; margin-bottom: 23px; color: var(--muted); font-size: 11px; text-decoration: none; }.back-link:hover { color: var(--accent-deep); }.workspace-header h1 { max-width: 850px; margin: 0; font-size: clamp(24px, 3vw, 34px); line-height: 1.25; }.workspace-header__copy > p:last-child { max-width: 720px; margin: 10px 0 0; color: var(--muted); font-size: 13px; line-height: 1.7; }.save-status { display: inline-flex; align-items: center; gap: 7px; flex: 0 0 auto; color: var(--muted); font-size: 11px; }.save-status span { width: 7px; height: 7px; border-radius: 50%; background: #c3cbc2; }.save-status.is-saved { color: var(--accent-deep); }.save-status.is-saved span { background: #70aa63; }
.workspace-layout { display: grid; grid-template-columns: 220px minmax(420px, 1fr) minmax(250px, 286px); align-items: start; gap: 14px; }.workspace-materials, .workspace-main { display: grid; min-width: 0; gap: 14px; }.material-panel, .rubric-panel { padding: 17px; }.panel-heading { display: flex; align-items: flex-start; justify-content: space-between; gap: 10px; }.panel-heading h2 { margin: 0; font-size: 16px; }.panel-heading > span { color: var(--muted); font-size: 10px; }.material-item { display: grid; grid-template-columns: 27px minmax(0, 1fr) auto; align-items: center; gap: 8px; width: 100%; min-height: 54px; padding: 8px 0; border: 0; border-bottom: 1px solid var(--line); background: transparent; color: var(--ink); text-align: left; }.material-item:last-of-type { border-bottom: 0; }.material-item:hover, .material-item.is-active { color: var(--accent-deep); }.material-item.is-active strong { font-weight: 900; }.material-icon { display: grid; width: 27px; height: 27px; place-items: center; border-radius: 5px; background: var(--soft); color: var(--accent-deep); }.material-item strong, .material-item small { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }.material-item strong { font-size: 11px; }.material-item small { margin-top: 3px; color: var(--muted); font-size: 9px; }.material-item > svg { color: var(--accent-deep); }.material-empty { display: grid; justify-items: start; gap: 8px; padding: 18px 0 3px; color: var(--muted); }.material-empty p { margin: 0; font-size: 11px; line-height: 1.6; }.text-link { color: var(--accent-deep); font-size: 11px; font-weight: 800; text-decoration: none; }.rubric-panel h2 { margin: 0; font-size: 16px; }.rubric-panel ul { display: grid; gap: 12px; margin: 18px 0 0; padding: 0; list-style: none; }.rubric-panel li { display: flex; align-items: flex-start; gap: 8px; color: var(--muted); font-size: 11px; line-height: 1.55; }.rubric-panel li span { flex: 0 0 auto; width: 14px; height: 14px; border: 1px solid #b8c4b9; border-radius: 3px; }
.document-toolbar { display: flex; align-items: center; justify-content: space-between; min-height: 38px; gap: 12px; }.document-toolbar > span { overflow: hidden; color: var(--muted); font-size: 10px; text-overflow: ellipsis; white-space: nowrap; }.document-tabs { display: flex; gap: 4px; }.document-tabs button { display: inline-flex; align-items: center; gap: 7px; min-height: 32px; padding: 0 10px; border: 0; border-radius: 4px; background: transparent; color: var(--muted); font-size: 11px; }.document-tabs button:hover { background: #e9eeea; color: var(--ink); }.document-tabs button.is-active { background: #e4ecdd; color: var(--accent-deep); font-weight: 800; }.task-document { min-height: 520px; padding: 34px clamp(24px, 5vw, 50px); }.task-document h2 { max-width: 680px; margin: 0; font-size: 24px; line-height: 1.45; }.task-brief { color: var(--muted); font-size: 13px; line-height: 1.8; }.task-document h3 { margin: 36px 0 14px; font-size: 16px; }.task-document ol { display: grid; gap: 12px; margin: 0; padding: 0; list-style: none; }.task-document li { display: flex; gap: 10px; color: var(--muted); font-size: 12px; line-height: 1.6; }.task-document li span { display: grid; flex: 0 0 auto; width: 22px; height: 22px; place-items: center; border-radius: 50%; background: var(--soft); color: var(--accent-deep); font-size: 10px; font-weight: 800; }.submission-panel { padding: 18px; }.submission-panel textarea { display: block; width: 100%; min-height: 170px; margin-top: 18px; resize: vertical; padding: 13px; border: 1px solid var(--line); border-radius: 5px; outline: none; color: var(--ink); font-size: 13px; line-height: 1.7; }.submission-panel textarea:focus { border-color: var(--accent-deep); box-shadow: 0 0 0 2px rgba(63, 91, 49, .1); }.submission-footer { display: flex; align-items: center; justify-content: space-between; gap: 14px; margin-top: 11px; }.submission-footer > span { color: var(--muted); font-size: 10px; line-height: 1.5; }.submission-footer .button:disabled { cursor: not-allowed; opacity: .45; }.saved-message { display: flex; align-items: center; gap: 5px; margin: 11px 0 0; color: var(--accent-deep); font-size: 11px; }
@keyframes spin { to { transform: rotate(360deg); } }
@media (max-width: 1120px) { .workspace-layout { grid-template-columns: 200px minmax(0, 1fr); }.workspace-layout > :last-child { grid-column: 1 / -1; } }
@media (max-width: 760px) { .workspace-header { align-items: flex-start; flex-direction: column; }.workspace-layout { grid-template-columns: 1fr; }.workspace-materials { grid-template-columns: 1fr 1fr; align-items: start; }.workspace-layout > :last-child { grid-column: auto; }.submission-footer { align-items: flex-start; flex-direction: column; }.submission-footer .button { width: 100%; } }
@media (max-width: 520px) { .workspace-materials { grid-template-columns: 1fr; }.task-document { padding: 27px 20px; }.document-toolbar { align-items: flex-start; flex-direction: column; }.workspace-header h1 { font-size: 25px; } }
</style>
