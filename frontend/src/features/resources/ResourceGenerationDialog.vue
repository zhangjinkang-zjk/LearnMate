<template>
  <Teleport to="body">
    <div v-if="modelValue" class="generation-backdrop" @click.self="handleBackdropClick">
      <section class="generation-dialog" role="dialog" aria-modal="true" aria-labelledby="generation-title">
        <header class="generation-dialog__header">
          <div>
            <p class="eyebrow">CREATE RESOURCE</p>
            <h2 id="generation-title">{{ dialogTitle }}</h2>
            <p>{{ dialogDescription }}</p>
          </div>
          <button class="generation-close" type="button" :disabled="stage !== 'compose'" aria-label="关闭生成资料" title="关闭" @click="close">
            <X :size="18" />
          </button>
        </header>

        <form v-if="stage === 'compose'" class="generation-form" @submit.prevent="startGeneration">
          <fieldset>
            <legend>选择资料类型</legend>
            <div class="resource-kind-grid">
              <button v-for="kind in resourceKinds" :key="kind.key" class="resource-kind" :class="{ 'is-selected': selectedType === kind.key }" type="button" @click="selectedType = kind.key">
                <component :is="kind.icon" :size="20" />
                <span>{{ kind.label }}</span>
                <small>{{ kind.description }}</small>
              </button>
            </div>
          </fieldset>

          <fieldset v-if="selectedType === 'ppt'">
            <legend>PPT 风格</legend>
            <div class="theme-grid">
              <button v-for="theme in pptThemes" :key="theme.id" class="theme-option" :class="{ 'is-selected': pptThemeId === theme.id }" type="button" @click="pptThemeId = theme.id">
                <i :style="{ background: theme.swatch }"></i>
                <span>{{ theme.label }}</span>
              </button>
            </div>
          </fieldset>

          <label class="generation-description">
            <span>描述你想生成的资料</span>
            <textarea v-model.trim="description" rows="5" maxlength="1200" :placeholder="selectedKind.placeholder" autofocus></textarea>
            <small>{{ description.length }} / 1200</small>
          </label>
          <p v-if="errorMessage" class="generation-error" role="alert">{{ errorMessage }}</p>
          <footer class="generation-dialog__footer">
            <button class="button button--quiet" type="button" @click="close">取消</button>
            <button class="button button--primary" type="submit" :disabled="!description">开始生成 <Sparkles :size="15" /></button>
          </footer>
        </form>

        <div v-else-if="stage === 'generating'" class="generation-progress" aria-live="polite">
          <LoaderCircle class="spin" :size="30" />
          <div>
            <strong>正在生成{{ selectedKind.label }}</strong>
            <p>{{ taskMessage || '正在整理你的需求并生成内容…' }}</p>
          </div>
          <section class="generation-agent-flow" aria-label="多智能体协作过程">
            <header><strong>多智能体协作</strong><span>实时任务流</span></header>
            <div class="generation-agent-flow__nodes">
              <article v-for="agent in agentStages" :key="agent.id" :class="`is-${agent.status}`">
                <span class="generation-agent-flow__dot"></span>
                <div><strong>{{ agent.label }}</strong><small>{{ agent.message }}</small></div>
              </article>
            </div>
          </section>
          <div class="generation-progress__track"><span :style="{ width: `${taskProgress}%` }"></span></div>
          <small>{{ taskProgress }}%</small>
        </div>

        <div v-else class="generation-result">
          <div class="generation-result__notice">
            <CheckCircle2 :size="20" />
            <div><strong>资料已生成</strong><p>确认后保存进资料库；不保留会删除本次生成的资料。</p></div>
          </div>
          <div class="generation-result__list">
            <article v-for="resource in generatedResources" :key="resource.resource_id" class="generation-result__item">
              <div class="generation-result__icon"><component :is="iconFor(resource.resource_type)" :size="19" /></div>
              <div class="generation-result__body">
                <div><span>{{ labelFor(resource.resource_type) }}</span><strong>{{ resource.topic || description }}</strong></div>
                <img v-if="resource.resource_type === 'image' && resource.file_url" :src="resource.file_url" alt="生成的图片预览" />
                <p v-else>{{ previewFor(resource) }}</p>
              </div>
              <button class="generation-download" type="button" title="下载资料" aria-label="下载资料" @click="downloadResource(resource)"><Download :size="17" /></button>
            </article>
          </div>
          <p v-if="errorMessage" class="generation-error" role="alert">{{ errorMessage }}</p>
          <footer class="generation-dialog__footer">
            <button class="button button--quiet" type="button" :disabled="isDiscarding" @click="discardResources">{{ isDiscarding ? '正在丢弃…' : '不保存' }}</button>
            <button class="button button--primary" type="button" @click="saveResources">保存到资料库 <ArrowRight :size="15" /></button>
          </footer>
        </div>
      </section>
    </div>
  </Teleport>
</template>

<script setup>
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { ArrowRight, CheckCircle2, Download, FileImage, FileText, ListChecks, LoaderCircle, Network, Presentation, Sparkles, Video, X } from 'lucide-vue-next'
import { resourceApi } from '@/shared/api/resourceApi'

const props = defineProps({ modelValue: { type: Boolean, default: false } })
const emit = defineEmits(['update:modelValue', 'saved', 'discarded'])

const resourceKinds = [
  { key: 'ppt', label: 'PPT 演示文稿', description: '按主题生成演示内容', icon: Presentation, placeholder: '例如：为“语义检索与关键词检索的区别”制作一份 10 页课堂汇报 PPT，面向零基础大学生。' },
  { key: 'document', label: '学习文档', description: '生成结构化讲解资料', icon: FileText, placeholder: '例如：整理一份 RAG 入门学习文档，包含核心概念、工作流程、示例和练习建议。' },
  { key: 'mindmap', label: '思维导图', description: '梳理知识结构与关联', icon: Network, placeholder: '例如：为“机器学习模型评估”生成一张层级清晰的思维导图，包含指标、验证方法和常见误区。' },
  { key: 'exercise', label: '测试题', description: '生成针对性练习题', icon: ListChecks, placeholder: '例如：围绕 SQL JOIN 生成 8 道由浅入深的测试题，包含单选、多选和答案解析。' },
  { key: 'video', label: '学习视频', description: '生成视频学习内容', icon: Video, placeholder: '例如：生成一段 3 分钟的 Python 列表推导式讲解视频，节奏清晰，带一个实操示例。' },
  { key: 'image', label: '图片素材', description: '生成教学配图', icon: FileImage, placeholder: '例如：生成一张用于讲解神经网络工作流程的 16:9 科技风示意图，文字尽量少。' },
]
const pptThemes = [
  { id: 'minimal-white', label: '极简留白', swatch: 'linear-gradient(135deg, #ffffff 0 50%, #111216 50%)' },
  { id: 'academic-paper', label: '学术纸感', swatch: 'linear-gradient(135deg, #fdfcf8 0 50%, #1a3a7a 50%)' },
  { id: 'science-green', label: '自然绿色', swatch: 'linear-gradient(135deg, #f6fffb 0 50%, #11695f 50%)' },
  { id: 'editorial-serif', label: '编辑刊物', swatch: 'linear-gradient(135deg, #faf7f2 0 50%, #8a2a1c 50%)' },
]

const selectedType = ref('ppt')
const pptThemeId = ref('minimal-white')
const description = ref('')
const stage = ref('compose')
const errorMessage = ref('')
const taskProgress = ref(0)
const taskMessage = ref('')
const generatedResources = ref([])
const streamedResources = ref([])
const isDiscarding = ref(false)
const agentStages = ref([])
let taskId = ''
let pollTimer = 0
let taskEventController = null

const selectedKind = computed(() => resourceKinds.find((kind) => kind.key === selectedType.value) || resourceKinds[0])
const isGenerating = computed(() => stage.value === 'generating')
const dialogTitle = computed(() => stage.value === 'compose' ? '生成资料' : stage.value === 'generating' ? '正在生成资料' : '确认保存资料')
const dialogDescription = computed(() => stage.value === 'compose'
  ? '选择资料类型并描述你的需求，LearnMate 会结合当前学习情况生成内容。'
  : stage.value === 'generating'
    ? '生成完成后，你可以预览并决定是否保存到资料库。'
    : '本次内容已经生成，请确认是否保留。')

function labelFor(type) {
  return resourceKinds.find((kind) => kind.key === type)?.label || '学习资料'
}

function iconFor(type) {
  return resourceKinds.find((kind) => kind.key === type)?.icon || FileText
}

function previewFor(resource) {
  const content = String(resource?.content || resource?.preview || '').replace(/\s+/g, ' ').trim()
  if (content) return content.slice(0, 180)
  return resource?.resource_type === 'video' ? '视频学习内容已准备完成，可下载后查看。' : '内容已生成，可保存到资料库后继续学习。'
}

function resetDialog() {
  clearPoll()
  clearTaskEventStream()
  stage.value = 'compose'
  errorMessage.value = ''
  taskProgress.value = 0
  taskMessage.value = ''
  generatedResources.value = []
  streamedResources.value = []
  isDiscarding.value = false
  taskId = ''
  resetAgentStages()
}

function clearPoll() {
  if (pollTimer) window.clearTimeout(pollTimer)
  pollTimer = 0
}

function resetAgentStages() {
  agentStages.value = [
    { id: 'leader', label: 'LeaderAgent', message: '等待需求规划', status: 'pending' },
    { id: 'executor', label: `${selectedKind.value.label}智能体`, message: '等待并行生成', status: 'pending' },
    { id: 'reviewer', label: 'ReviewerAgent', message: '等待质量审核', status: 'pending' },
    { id: 'saver', label: 'ResourceService', message: '等待保存资源', status: 'pending' },
    { id: 'complete', label: '流程完成', message: '等待任务完成', status: 'pending' },
  ]
}

function clearTaskEventStream() {
  taskEventController?.abort()
  taskEventController = null
}

function updateAgentStage(id, status, message, agentName = '') {
  const stage = agentStages.value.find((item) => item.id === id)
  if (!stage) return
  stage.status = ['pending', 'running', 'reviewing', 'retrying', 'saving', 'done', 'failed', 'skipped'].includes(status) ? status : 'pending'
  if (message) stage.message = message
  if (agentName) stage.label = agentName
}

function applyGenerationEvent(event) {
  if (!event) return
  const type = String(event.type || '').toLowerCase()
  const message = String(event.message || event.progress_msg || event.msg || '')
  const progress = Number(event.progress)
  if (Number.isFinite(progress)) taskProgress.value = Math.max(taskProgress.value, Math.min(100, progress))
  if (message) taskMessage.value = message

  if (type === 'agent_event') {
    const phase = String(event.phase || '').toLowerCase()
    updateAgentStage(phase, String(event.status || 'running').toLowerCase(), message, event.agent_name || '')
    return
  }
  if (type === 'file' || type === 'resource') {
    collectStreamedResource(event)
    updateAgentStage('executor', 'done', message || '生成内容已就绪')
    return
  }
  if (type === 'external_videos') {
    const videos = Array.isArray(event.external_videos) ? event.external_videos : []
    videos.forEach(collectStreamedResource)
    updateAgentStage('executor', videos.length ? 'done' : 'running', message || '视频资源已就绪')
    return
  }
  if (type === 'done') updateAgentStage('complete', 'done', message || '任务已完成')
  if (type === 'error') updateAgentStage('complete', 'failed', message || event.error || '任务失败')
}

function collectStreamedResource(resource) {
  const resourceId = resource?.resource_id ?? resource?.id
  if (!resourceId) return
  if (streamedResources.value.some((item) => String(item.resource_id ?? item.id) === String(resourceId))) return
  streamedResources.value.push(resource)
}

function isRequestedResource(resource) {
  const type = String(resource?.resource_type || resource?.file_type || '')
  if (type === selectedType.value) return true
  return selectedType.value === 'video' && ['external_video', 'html'].includes(type)
}

async function resolveGeneratedResources(task) {
  const taskResult = Array.isArray(task?.result) ? task.result : []
  const candidates = taskResult.length ? taskResult : streamedResources.value
  if (candidates.length) {
    return Promise.all(candidates.map(async (item) => {
      const resourceId = item?.resource_id ?? item?.id
      if (!resourceId) return item
      try { return await resourceApi.get(resourceId) } catch { return item }
    }))
  }

  const resources = await resourceApi.list()
  const topic = description.value.trim()
  return (Array.isArray(resources) ? resources : [])
    .filter((resource) => isRequestedResource(resource) && String(resource?.topic || '').trim() === topic)
    .slice(0, 3)
}

function startTaskEventStream() {
  clearTaskEventStream()
  taskEventController = new AbortController()
  void resourceApi.watchGenerationTask(taskId, applyGenerationEvent, taskEventController.signal)
    .catch((error) => {
      if (error?.name !== 'AbortError') console.warn('[ResourceGenerationDialog] task event stream ended:', error)
    })
}

function close() {
  if (isGenerating.value) return
  resetDialog()
  emit('update:modelValue', false)
}

function handleBackdropClick() {
  if (stage.value === 'compose') close()
}

async function startGeneration() {
  if (!description.value || isGenerating.value) return
  errorMessage.value = ''
  stage.value = 'generating'
  taskProgress.value = 3
  taskMessage.value = '正在创建生成任务…'
  resetAgentStages()
  updateAgentStage('leader', 'running', '正在分析资料需求')
  try {
    const task = await resourceApi.createGenerationTask({
      topic: description.value,
      resourceTypes: [selectedType.value],
      ...(selectedType.value === 'ppt' ? { pptThemeId: pptThemeId.value } : {}),
    })
    taskId = String(task?.task_id || '')
    if (!taskId) throw new Error('未能创建生成任务')
    startTaskEventStream()
    await pollTask()
  } catch (error) {
    stage.value = 'compose'
    errorMessage.value = error?.response?.data?.detail || error?.message || '生成任务创建失败，请稍后重试'
  }
}

async function pollTask() {
  try {
    const task = await resourceApi.getGenerationTask(taskId)
    taskProgress.value = Math.max(taskProgress.value, Number(task?.progress) || 5)
    taskMessage.value = task?.progress_msg || taskMessage.value
    if (task?.status === 'success') {
      clearPoll()
      clearTaskEventStream()
      updateAgentStage('complete', 'done', '资料生成完成')
      generatedResources.value = await resolveGeneratedResources(task)
      if (!generatedResources.value.length) throw new Error('视频服务未返回可保存的资料。当前后端没有把视频写入资源任务结果，请确认服务已更新并重启。')
      stage.value = 'result'
      return
    }
    if (task?.status === 'failed') throw new Error(task?.error || '资料生成失败，请稍后重试')
    pollTimer = window.setTimeout(pollTask, 1000)
  } catch (error) {
    clearPoll()
    clearTaskEventStream()
    updateAgentStage('complete', 'failed', error?.message || '资料生成失败')
    stage.value = 'compose'
    errorMessage.value = error?.response?.data?.detail || error?.message || '生成过程出现问题，请稍后重试'
  }
}

function saveResources() {
  const saved = [...generatedResources.value]
  resetDialog()
  emit('update:modelValue', false)
  emit('saved', saved)
}

async function discardResources() {
  isDiscarding.value = true
  errorMessage.value = ''
  try {
    await Promise.all(generatedResources.value.map((resource) => resourceApi.remove(resource.resource_id)))
    resetDialog()
    emit('update:modelValue', false)
    emit('discarded')
  } catch (error) {
    errorMessage.value = error?.response?.data?.detail || error?.message || '未能删除全部资料，请稍后重试'
  } finally {
    isDiscarding.value = false
  }
}

async function downloadResource(resource) {
  try {
    const { blob, filename } = await resourceApi.download(resource.resource_id)
    const link = document.createElement('a')
    const url = URL.createObjectURL(blob)
    link.href = url
    link.download = filename
    link.click()
    URL.revokeObjectURL(url)
  } catch (error) {
    errorMessage.value = error?.message || '下载失败，请稍后重试'
  }
}

watch(() => props.modelValue, (isOpen) => {
  if (!isOpen && !isGenerating.value) resetDialog()
})

onBeforeUnmount(() => {
  clearPoll()
  clearTaskEventStream()
})
</script>

<style scoped>
.generation-backdrop { position: fixed; inset: 0; z-index: 100; display: grid; place-items: center; padding: 24px; background: rgba(14, 34, 25, .54); backdrop-filter: blur(5px); }
.generation-dialog { width: min(760px, 100%); max-height: min(760px, calc(100dvh - 48px)); overflow: auto; border: 1px solid rgba(220, 227, 220, .92); border-radius: 8px; background: var(--paper); box-shadow: 0 26px 75px rgba(9, 27, 18, .34); }
.generation-dialog__header { display: flex; align-items: flex-start; justify-content: space-between; gap: 20px; padding: 26px 28px 20px; border-bottom: 1px solid var(--line); }.generation-dialog__header h2 { margin: 0; font-size: 24px; }.generation-dialog__header p:last-child { max-width: 560px; margin: 7px 0 0; color: var(--muted); font-size: 13px; line-height: 1.65; }.generation-close { display: grid; width: 34px; height: 34px; flex: 0 0 34px; place-items: center; border: 1px solid var(--line); border-radius: 50%; background: var(--paper); color: var(--muted); }.generation-close:hover:not(:disabled) { border-color: #aebea7; color: var(--ink); }.generation-close:disabled { cursor: not-allowed; opacity: .4; }
.generation-form { display: grid; gap: 22px; padding: 24px 28px 26px; }.generation-form fieldset { min-width: 0; padding: 0; margin: 0; border: 0; }.generation-form legend, .generation-description > span { display: block; margin-bottom: 10px; color: var(--ink); font-size: 13px; font-weight: 800; }.resource-kind-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 10px; }.resource-kind { display: grid; min-height: 104px; align-content: start; gap: 7px; padding: 14px; border: 1px solid var(--line); border-radius: 7px; background: #fff; color: var(--accent-deep); text-align: left; transition: border-color .18s ease, background .18s ease, transform .18s ease; }.resource-kind:hover { border-color: #b6caac; transform: translateY(-1px); }.resource-kind.is-selected { border-color: #b1cf30; background: #f7fbe8; box-shadow: inset 0 0 0 1px #d7ed67; }.resource-kind span { color: var(--ink); font-size: 13px; font-weight: 800; }.resource-kind small { color: var(--muted); font-size: 10px; line-height: 1.45; }
.theme-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 9px; }.theme-option { display: flex; align-items: center; gap: 8px; min-width: 0; padding: 8px; border: 1px solid var(--line); border-radius: 6px; background: #fff; color: var(--muted); text-align: left; font-size: 11px; }.theme-option:hover, .theme-option.is-selected { border-color: #b1cf30; background: #f7fbe8; color: var(--ink); }.theme-option i { display: block; width: 24px; height: 24px; flex: 0 0 24px; border: 1px solid rgba(20, 40, 29, .12); border-radius: 4px; }.theme-option span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.generation-description { display: grid; }.generation-description textarea { width: 100%; min-height: 126px; resize: vertical; padding: 13px; border: 1px solid var(--line); border-radius: 7px; outline: 0; color: var(--ink); font-size: 13px; line-height: 1.7; }.generation-description textarea:focus { border-color: var(--accent-deep); box-shadow: 0 0 0 3px rgba(182, 216, 55, .18); }.generation-description small { justify-self: end; margin-top: 5px; color: var(--muted); font-size: 10px; }.generation-error { margin: 0; color: #a55342; font-size: 12px; }.generation-dialog__footer { display: flex; justify-content: flex-end; gap: 10px; }.generation-dialog__footer .button { gap: 7px; min-width: 110px; }
.generation-progress { display: grid; grid-template-columns: auto minmax(0, 1fr); align-items: center; gap: 16px; padding: 54px 28px; color: var(--accent-deep); }.generation-progress > div:nth-child(2) strong { color: var(--ink); font-size: 15px; }.generation-progress > div:nth-child(2) p { margin: 6px 0 0; color: var(--muted); font-size: 12px; }.generation-progress__track { grid-column: 1 / -1; height: 7px; overflow: hidden; border-radius: 99px; background: #edf1eb; }.generation-progress__track span { display: block; height: 100%; border-radius: inherit; background: var(--accent); transition: width .35s ease; }.generation-progress > small { grid-column: 1 / -1; justify-self: end; margin-top: -10px; color: var(--muted); font-size: 11px; }.spin { animation: spin .85s linear infinite; }
.generation-agent-flow { display: grid; grid-column: 1 / -1; gap: 10px; padding: 13px; border: 1px solid #dce5d6; border-radius: 7px; background: #fbfcf8; }.generation-agent-flow header { display: flex; align-items: center; justify-content: space-between; gap: 12px; }.generation-agent-flow header strong { color: var(--ink); font-size: 12px; }.generation-agent-flow header span { color: var(--muted); font-size: 10px; }.generation-agent-flow__nodes { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: 6px; }.generation-agent-flow__nodes article { position: relative; display: grid; min-width: 0; grid-template-columns: 9px minmax(0, 1fr); gap: 6px; align-items: start; padding: 7px 5px; border: 1px solid transparent; border-radius: 5px; }.generation-agent-flow__nodes article:not(:last-child)::after { position: absolute; top: 12px; right: -6px; width: 6px; height: 1px; background: var(--line); content: ''; }.generation-agent-flow__dot { width: 7px; height: 7px; margin-top: 4px; border-radius: 50%; background: #c5cdc5; }.generation-agent-flow__nodes article strong, .generation-agent-flow__nodes article small { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }.generation-agent-flow__nodes article strong { color: var(--ink); font-size: 10px; }.generation-agent-flow__nodes article small { margin-top: 3px; color: var(--muted); font-size: 9px; }.generation-agent-flow__nodes article.is-running, .generation-agent-flow__nodes article.is-reviewing, .generation-agent-flow__nodes article.is-retrying, .generation-agent-flow__nodes article.is-saving { border-color: #b5ca9d; background: #f3f8ea; }.generation-agent-flow__nodes article.is-running .generation-agent-flow__dot, .generation-agent-flow__nodes article.is-reviewing .generation-agent-flow__dot, .generation-agent-flow__nodes article.is-retrying .generation-agent-flow__dot, .generation-agent-flow__nodes article.is-saving .generation-agent-flow__dot { background: var(--accent); box-shadow: 0 0 0 3px rgba(182, 216, 55, .22); animation: agentPulse 1.1s ease-in-out infinite; }.generation-agent-flow__nodes article.is-done .generation-agent-flow__dot { background: #5e9b61; }.generation-agent-flow__nodes article.is-failed .generation-agent-flow__dot { background: #b96e4d; }
.generation-result { display: grid; gap: 18px; padding: 23px 28px 26px; }.generation-result__notice { display: flex; align-items: flex-start; gap: 10px; padding: 13px 14px; border: 1px solid #d7e7c2; border-radius: 7px; background: #f5faec; color: var(--accent-deep); }.generation-result__notice strong { display: block; color: var(--ink); font-size: 13px; }.generation-result__notice p { margin: 4px 0 0; color: var(--muted); font-size: 11px; line-height: 1.5; }.generation-result__list { display: grid; gap: 9px; }.generation-result__item { display: grid; grid-template-columns: 40px minmax(0, 1fr) auto; align-items: start; gap: 12px; padding: 13px; border: 1px solid var(--line); border-radius: 7px; background: #fcfdfb; }.generation-result__icon { display: grid; width: 38px; height: 38px; place-items: center; border-radius: 6px; background: #e8f0e2; color: var(--accent-deep); }.generation-result__body { min-width: 0; }.generation-result__body > div { display: flex; align-items: center; gap: 8px; }.generation-result__body span { flex: 0 0 auto; padding: 3px 6px; border-radius: 3px; background: #edf2ed; color: var(--muted); font-size: 10px; }.generation-result__body strong { overflow: hidden; color: var(--ink); font-size: 12px; text-overflow: ellipsis; white-space: nowrap; }.generation-result__body p { display: -webkit-box; overflow: hidden; margin: 7px 0 0; color: var(--muted); font-size: 11px; line-height: 1.55; -webkit-box-orient: vertical; -webkit-line-clamp: 2; }.generation-result__body img { display: block; width: min(250px, 100%); max-height: 170px; margin-top: 8px; object-fit: cover; border-radius: 5px; }.generation-download { display: grid; width: 34px; height: 34px; place-items: center; border: 1px solid var(--line); border-radius: 50%; background: #fff; color: var(--accent-deep); }.generation-download:hover { border-color: #afc5a2; background: #f2f7ee; }
@keyframes spin { to { transform: rotate(360deg); } }
@keyframes agentPulse { 0%,100% { opacity: .55; } 50% { opacity: 1; } }
@media (max-width: 680px) { .generation-backdrop { padding: 12px; }.generation-dialog { max-height: calc(100dvh - 24px); }.generation-dialog__header, .generation-form, .generation-result { padding-right: 18px; padding-left: 18px; }.resource-kind-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }.theme-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }.generation-dialog__header h2 { font-size: 21px; }.generation-dialog__footer { flex-direction: column-reverse; }.generation-dialog__footer .button { width: 100%; }.generation-progress { padding: 44px 18px; } }
@media (max-width: 680px) { .generation-agent-flow__nodes { grid-template-columns: 1fr; }.generation-agent-flow__nodes article { grid-template-columns: 10px minmax(0, 1fr); }.generation-agent-flow__nodes article:not(:last-child)::after { top: auto; right: auto; bottom: -6px; left: 8px; width: 1px; height: 6px; } }
</style>
