<template>
  <div class="ppt-workspace">
    <PageTitle eyebrow="PRESENTATION STUDIO" title="PPT 工作台" description="选择视觉风格，生成课程幻灯片，并在生成后继续编辑或导出。">
      <template #actions>
        <RouterLink class="button button--quiet" to="/resources">资源库</RouterLink>
      </template>
    </PageTitle>

    <div class="ppt-workspace__grid" :class="{ 'ppt-workspace__grid--editor': resource }">
      <section v-if="!resource" class="ppt-request surface" aria-label="PPT 生成设置">
        <div class="section-heading"><span class="section-heading__number">01</span><div><p class="eyebrow">CONTENT</p><h2>课程内容</h2></div></div>
        <label class="field"><span>PPT 主题</span><input v-model.trim="topic" type="text" placeholder="例如：线性代数矩阵基础" :disabled="isGenerating" /></label>
        <label class="field"><span>制作要求 <small>可选</small></span><textarea v-model.trim="requirements" rows="5" placeholder="例如：面向大一学生，包含概念图、例题和章节总结。" :disabled="isGenerating"></textarea></label>

        <div class="section-heading section-heading--theme"><span class="section-heading__number">02</span><div><p class="eyebrow">STYLE</p><h2>选择风格</h2></div></div>
        <div class="theme-filters" role="tablist" aria-label="PPT 风格分类">
          <button v-for="category in THEME_CATEGORIES" :key="category" type="button" :class="{ 'is-active': activeCategory === category }" @click="activeCategory = category">{{ category }}</button>
        </div>
        <div class="theme-grid">
          <button v-for="theme in filteredThemes" :key="theme.id" class="theme-card" :class="{ 'is-selected': selectedThemeId === theme.id, 'is-dark': theme.dark }" type="button" :aria-pressed="selectedThemeId === theme.id" @click="selectedThemeId = theme.id">
            <span class="theme-card__preview" :style="{ background: theme.palette[3] }"><i :style="{ background: theme.palette[0] }"></i><b :style="{ background: theme.palette[1] }"></b><b :style="{ background: theme.palette[2] }"></b></span>
            <span class="theme-card__label">{{ theme.label }}</span>
          </button>
        </div>

        <p v-if="errorMessage" class="form-error" role="alert">{{ errorMessage }}</p>
        <button class="button button--primary generate-button" type="button" :disabled="!topic || isGenerating" @click="generatePpt">
          <LoaderCircle v-if="isGenerating" class="spin" :size="16" /><Presentation v-else :size="16" />
          {{ isGenerating ? generationLabel : '生成 PPT' }}
        </button>
      </section>

      <section class="ppt-result surface" :class="{ 'ppt-result--ready': resource }" aria-live="polite">
        <template v-if="resource">
          <div class="result-header"><div><p class="eyebrow">READY</p><h2>{{ resource.topic || topic }}</h2><p>{{ selectedTheme.label }} · {{ slidesCount }} 页</p></div><span class="result-theme" :style="{ background: selectedTheme.palette[0] }"></span></div>
          <PptEditorFrame :content="resource.content" :title="resource.topic || topic" :theme-id="selectedThemeId" />
          <div class="result-actions">
            <button class="button button--quiet" type="button" :disabled="isDownloading" @click="downloadPpt"><Download :size="15" />{{ isDownloading ? '导出中' : '导出 PPTX' }}</button>
            <button class="button button--primary" type="button" @click="resetWorkspace"><Pencil :size="15" />新建演示文稿</button>
          </div>
        </template>
        <template v-else>
          <div class="result-empty"><Presentation :size="32" /><strong>{{ isGenerating ? generationLabel : '等待生成' }}</strong><p>{{ isGenerating ? '生成过程会保留在后台，完成后自动载入。' : '设置内容与风格后，即可生成可编辑的 PPT。' }}</p></div>
        </template>
      </section>
    </div>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, ref } from 'vue'
import { Download, LoaderCircle, Pencil, Presentation } from 'lucide-vue-next'
import PageTitle from '@/shared/ui/PageTitle.vue'
import PptEditorFrame from '@/features/fundamentals/PptEditorFrame.vue'
import { PPT_THEMES, THEME_CATEGORIES, getThemeById } from '@/data/pptThemes'
import { parsePptResourceSlides } from '@/utils/pptistAdapter'
import { resourceApi } from '@/shared/api/resourceApi'

const topic = ref('')
const requirements = ref('')
const selectedThemeId = ref('minimal-white')
const activeCategory = ref('全部')
const resource = ref(null)
const errorMessage = ref('')
const isGenerating = ref(false)
const isDownloading = ref(false)
const generationLabel = ref('正在创建生成任务')
let taskTimer = null

const selectedTheme = computed(() => getThemeById(selectedThemeId.value))
const filteredThemes = computed(() => activeCategory.value === '全部'
  ? PPT_THEMES
  : PPT_THEMES.filter((theme) => theme.category === activeCategory.value))
const slidesCount = computed(() => parseSlides(resource.value?.content).length)

function parseSlides(content) {
  return parsePptResourceSlides(content)
}

async function generatePpt() {
  errorMessage.value = ''
  resource.value = null
  isGenerating.value = true
  generationLabel.value = '正在创建生成任务'
  try {
    const task = await resourceApi.createPptTask({ topic: topic.value, requirements: requirements.value, pptThemeId: selectedThemeId.value })
    await waitForTask(task.task_id)
  } catch (error) {
    errorMessage.value = error?.response?.data?.detail || error?.message || 'PPT 生成失败，请稍后重试。'
  } finally {
    isGenerating.value = false
    clearTaskTimer()
  }
}

function waitForTask(taskId) {
  return new Promise((resolve, reject) => {
    const poll = async () => {
      try {
        const task = await resourceApi.getGenerationTask(taskId)
        generationLabel.value = task.progress_msg || (task.status === 'pending' ? '等待生成队列' : '正在生成 PPT')
        if (task.status === 'failed') throw new Error(task.error || 'PPT 生成失败')
        if (task.status === 'success') {
          const entries = Array.isArray(task.result) ? task.result : []
          const ppt = entries.find((entry) => entry.file_type === 'ppt' || entry.resource_type === 'ppt')
          if (!ppt?.resource_id) throw new Error('PPT 已完成，但没有返回资源标识')
          resource.value = await resourceApi.get(ppt.resource_id)
          resolve()
          return
        }
        taskTimer = window.setTimeout(poll, 1500)
      } catch (error) {
        reject(error)
      }
    }
    void poll()
  })
}

async function downloadPpt() {
  if (!resource.value?.resource_id) return
  isDownloading.value = true
  errorMessage.value = ''
  try {
    const { blob, filename } = await resourceApi.download(resource.value.resource_id)
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = filename
    document.body.append(link)
    link.click()
    link.remove()
    window.setTimeout(() => URL.revokeObjectURL(url), 0)
  } catch (error) {
    errorMessage.value = error?.message || '导出 PPTX 失败，请稍后重试。'
  } finally {
    isDownloading.value = false
  }
}

function resetWorkspace() {
  resource.value = null
  errorMessage.value = ''
}

function clearTaskTimer() {
  if (taskTimer) window.clearTimeout(taskTimer)
  taskTimer = null
}

onBeforeUnmount(clearTaskTimer)
</script>

<style scoped>
.ppt-workspace__grid { display: grid; grid-template-columns: minmax(330px, .86fr) minmax(0, 1.3fr); gap: 18px; align-items: start; }.ppt-workspace__grid--editor { grid-template-columns: minmax(0, 1fr); }
.ppt-request { padding: 20px; }.section-heading { display: flex; align-items: center; gap: 10px; margin-bottom: 16px; }.section-heading--theme { margin-top: 26px; }.section-heading__number { color: var(--accent-deep); font-size: 11px; font-weight: 800; }.eyebrow { margin: 0 0 3px; color: var(--muted); font-size: 10px; font-weight: 800; }.section-heading h2, .result-header h2 { margin: 0; color: var(--ink); font-size: 16px; }
.field { display: grid; gap: 7px; margin-top: 14px; color: var(--ink); font-size: 12px; font-weight: 750; }.field small { color: var(--muted); font-size: 10px; font-weight: 500; }.field input, .field textarea { width: 100%; box-sizing: border-box; border: 1px solid var(--line); border-radius: 5px; background: var(--paper); color: var(--ink); font: inherit; font-weight: 500; outline: 0; }.field input { height: 40px; padding: 0 11px; }.field textarea { padding: 10px 11px; line-height: 1.55; resize: vertical; }.field input:focus, .field textarea:focus { border-color: var(--accent); box-shadow: 0 0 0 3px rgba(112, 146, 96, .14); }
.theme-filters { display: flex; flex-wrap: wrap; gap: 5px; margin-bottom: 12px; }.theme-filters button { min-height: 28px; padding: 0 9px; border: 1px solid var(--line); border-radius: 4px; background: var(--paper); color: var(--muted); font-size: 11px; }.theme-filters button:hover, .theme-filters button.is-active { border-color: var(--accent-deep); background: var(--accent-deep); color: #fff; }
.theme-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 7px; max-height: 296px; overflow-y: auto; padding-right: 3px; }.theme-card { position: relative; overflow: hidden; padding: 0; border: 1px solid var(--line); border-radius: 5px; background: var(--paper); color: var(--ink); text-align: left; }.theme-card:hover { border-color: var(--accent); }.theme-card.is-selected { border: 2px solid var(--accent-deep); }.theme-card__preview { position: relative; display: block; height: 45px; overflow: hidden; }.theme-card__preview i { display: block; height: 10px; }.theme-card__preview b { position: absolute; width: 18px; height: 18px; border-radius: 50%; opacity: .75; }.theme-card__preview b:nth-of-type(1) { top: 17px; right: 26px; }.theme-card__preview b:nth-of-type(2) { top: 23px; right: 10px; }.theme-card__label { display: block; overflow: hidden; padding: 7px; font-size: 10px; font-weight: 700; text-overflow: ellipsis; white-space: nowrap; }.theme-card.is-dark .theme-card__label { background: #20232d; color: #fff; }
.generate-button { width: 100%; justify-content: center; margin-top: 18px; }.form-error { margin: 13px 0 0; color: #a03f35; font-size: 12px; }.spin { animation: spin 1s linear infinite; }
.ppt-result { min-height: 660px; padding: 16px; }.result-empty { display: grid; min-height: 620px; place-items: center; align-content: center; gap: 10px; color: var(--muted); text-align: center; }.result-empty svg { color: var(--accent-deep); }.result-empty strong { color: var(--ink); font-size: 15px; }.result-empty p { max-width: 260px; margin: 0; font-size: 12px; line-height: 1.6; }.result-header { display: flex; justify-content: space-between; gap: 16px; margin: 4px 4px 15px; }.result-header p:last-child { margin: 5px 0 0; color: var(--muted); font-size: 11px; }.result-theme { width: 34px; height: 34px; border: 4px solid var(--paper); border-radius: 50%; box-shadow: 0 0 0 1px var(--line); }.result-actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 12px; }
@media (max-width: 980px) { .ppt-workspace__grid { grid-template-columns: 1fr; }.ppt-result { min-height: auto; }.result-empty { min-height: 300px; } }
@media (max-width: 560px) { .ppt-request, .ppt-result { padding: 13px; }.theme-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }.result-actions { justify-content: stretch; }.result-actions .button { flex: 1; justify-content: center; padding: 0 7px; } }
@keyframes spin { to { transform: rotate(360deg); } }
</style>
