<template>
  <div class="import-page">
    <PageTitle
      eyebrow="KNOWLEDGE BASE"
      title="上传知识库"
      description="上传你自己的资料，系统会切片并逐段向量化入库；之后生成学习资料时会检索到它。"
    >
      <template #actions>
        <RouterLink class="button button--quiet" to="/resources"><ArrowLeft :size="15" />返回资料库</RouterLink>
      </template>
    </PageTitle>

    <div class="import-layout">
      <section class="surface surface-pad upload-panel">
        <div
          class="drop-zone"
          :class="{ 'is-dragging': isDragging, 'is-ready': selectedFile }"
          @dragenter.prevent="isDragging = true"
          @dragover.prevent="isDragging = true"
          @dragleave.prevent="isDragging = false"
          @drop.prevent="handleDrop"
        >
          <input
            ref="fileInputRef"
            class="file-input"
            type="file"
            :accept="KNOWLEDGE_ACCEPT"
            @change="handleFileChange"
          />
          <div class="upload-mark"><FileUp :size="20" /></div>
          <h2>{{ selectedFile ? selectedFile.name : '选择或拖入资料文件' }}</h2>
          <p>{{ selectedFile ? fileMetaText : `支持 ${KNOWLEDGE_ACCEPT.replaceAll('.', '').replaceAll(',', ' / ')} 文件` }}</p>
          <div class="upload-actions">
            <button class="button button--primary" type="button" @click="openFilePicker">选择文件</button>
            <button v-if="selectedFile" class="button button--quiet" type="button" @click="clearFile">重新选择</button>
          </div>
        </div>

        <form class="meta-form" @submit.prevent="submitMaterial">
          <label class="field">
            <span>资料标题</span>
            <input v-model="materialTitle" type="text" placeholder="例如：机械制图 剖视图与公差笔记" />
          </label>

          <fieldset class="option-group">
            <legend>资料可见性</legend>
            <label v-for="option in visibilityOptions" :key="option.value" class="radio-option">
              <input v-model="visibility" type="radio" :value="option.value" />
              <span>{{ option.label }}</span>
              <small>{{ option.hint }}</small>
            </label>
          </fieldset>

          <fieldset class="option-group">
            <legend>资料类型</legend>
            <div class="category-options">
              <label
                v-for="option in knowledgeCategoryOptions"
                :key="option.value"
                class="category-chip"
                :class="{ 'is-active': category === option.value }"
              >
                <input v-model="category" type="radio" :value="option.value" />
                <span>{{ option.label }}</span>
              </label>
            </div>
          </fieldset>

          <p v-if="statusMessage" class="status-message" :class="`is-${statusType}`" role="status">{{ statusMessage }}</p>

          <button class="button button--primary submit-button" type="submit" :disabled="!selectedFile || uploading">
            <LoaderCircle v-if="uploading" class="spin" :size="15" />
            <span>{{ uploading ? uploadButtonText : '上传并入库' }}</span>
          </button>
          <p class="field-hint">上传即完成向量化：文件会被切成若干段，逐段计算向量写入知识库；重复或过短的段落会被跳过。</p>
        </form>
      </section>

      <aside class="surface surface-pad preview-panel">
        <div class="panel-head">
          <div><p class="eyebrow">PREVIEW</p><h2>内容预览</h2></div>
          <span class="muted">{{ previewText ? `${previewText.length} 字` : '等待文件' }}</span>
        </div>
        <div v-if="previewText" class="preview-box">{{ previewText }}</div>
        <div v-else class="empty-state">{{ previewHint }}</div>

        <div v-if="lastResult" class="ingest-result">
          <p class="eyebrow">INGEST RESULT</p>
          <h2>{{ lastResult.title }}</h2>
          <div class="ingest-stats">
            <div><strong>{{ lastResult.total_chunks }}</strong><span>切片</span></div>
            <div><strong>{{ lastResult.ingested }}</strong><span>已入库</span></div>
            <div><strong>{{ lastResult.skipped }}</strong><span>跳过</span></div>
          </div>
          <ul v-if="lastResult.details.length" class="ingest-details">
            <li v-for="(line, index) in lastResult.details.slice(0, 6)" :key="index">{{ line }}</li>
          </ul>
        </div>
      </aside>
    </div>

    <section class="surface surface-pad library-panel">
      <div class="panel-head">
        <div><p class="eyebrow">MY KNOWLEDGE BASE</p><h2>我的知识库</h2></div>
        <button class="button button--quiet" type="button" :disabled="listLoading" @click="loadEntries">
          <RefreshCw :size="14" :class="{ spin: listLoading }" />刷新
        </button>
      </div>

      <div v-if="listLoading && !entries.length" class="panel-state"><LoaderCircle class="spin" :size="18" />正在读取知识库</div>
      <div v-else-if="listError" class="panel-state is-error"><CircleAlert :size="18" />{{ listError }}</div>
      <div v-else-if="!entries.length" class="panel-state">
        <FileText :size="18" />还没有上传过资料。上传之后，这里会按文档列出切好的段数。
      </div>
      <ul v-else class="entry-list">
        <li v-for="entry in entries" :key="entry.doc_id" class="entry-row">
          <div class="entry-main">
            <div class="entry-title-line">
              <h3>{{ entry.title }}</h3>
              <span class="entry-tag">{{ knowledgeCategoryLabel(entry.category) }}</span>
              <span class="entry-tag entry-tag--soft">{{ visibilityLabel(entry.visibility) }}</span>
            </div>
            <p class="muted">{{ entry.chunks }} 段 · {{ entry.total_chars }} 字 · {{ formatDate(entry.created_at) }}</p>
          </div>
          <button
            class="icon-button"
            type="button"
            :disabled="deletingDocId === entry.doc_id"
            :aria-label="`删除${entry.title}`"
            :title="`删除${entry.title}`"
            @click="removeEntry(entry)"
          >
            <Trash2 :size="16" />
          </button>
        </li>
      </ul>
    </section>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { ArrowLeft, CircleAlert, FileText, FileUp, LoaderCircle, RefreshCw, Trash2 } from 'lucide-vue-next'
import PageTitle from '@/shared/ui/PageTitle.vue'
import {
  KNOWLEDGE_ACCEPT,
  TEXT_PREVIEW_EXTENSIONS,
  knowledgeApi,
  knowledgeCategoryLabel,
  knowledgeCategoryOptions,
  visibilityLabel,
} from '@/shared/api/knowledgeApi'

const PREVIEW_CHARS = 3000

// 封面是后端的可选参数（只有视频才用得上），这一版前端不截首帧，所以不传。
// 说明字段也刻意不做：后端 upload_document 根本没有 description 参数，
// 知伴那边有个填了也不上传的输入框，别把这个坑一起搬过来。
const visibilityOptions = [
  { value: 'private', label: '仅我可见', hint: '只有你可以访问和使用这份资料' },
  { value: 'public', label: '全员可见', hint: '需要管理员权限，普通用户上传后会转为待审核' },
]

const fileInputRef = ref(null)
const selectedFile = ref(null)
const isDragging = ref(false)
const uploading = ref(false)
const materialTitle = ref('')
const visibility = ref('private')
const category = ref('knowledge_point')
const statusMessage = ref('')
const statusType = ref('success')
const previewText = ref('')
const lastResult = ref(null)
const entries = ref([])
const listLoading = ref(true)
const listError = ref('')
const deletingDocId = ref('')
const uploadedPercent = ref(0)

const unwrap = (response) => response?.data?.data ?? response?.data ?? response
const fileExtension = (file) => String(file?.name || '').split('.').pop()?.toLowerCase() || ''
const canPreviewLocally = (file) => TEXT_PREVIEW_EXTENSIONS.includes(fileExtension(file))

const fileMetaText = computed(() => {
  if (!selectedFile.value) return ''
  const size = selectedFile.value.size / 1024
  return size < 1024 ? `${size.toFixed(1)} KB` : `${(size / 1024).toFixed(2)} MB`
})

const previewHint = computed(() => {
  if (!selectedFile.value) return '选择文字文件后，这里会显示前 3000 个字符，便于你确认内容。'
  // pdf/docx 要后端解析、mp4 前端读不了 —— 与其显示乱码，不如直接说清楚。
  return `${fileExtension(selectedFile.value)} 无法在本地预览，上传后由后端解析入库。`
})

const uploadButtonText = computed(() => (
  uploadingPercent.value > 0 && uploadingPercent.value < 100
    ? `正在上传 ${uploadingPercent.value}%`
    : '正在切片并向量化…'
))

const setStatus = (message, type = 'success') => {
  statusMessage.value = message
  statusType.value = type
}

const openFilePicker = () => fileInputRef.value?.click()

const readPreview = (file) => {
  previewText.value = ''
  if (!canPreviewLocally(file)) return
  const reader = new FileReader()
  reader.onload = () => { previewText.value = String(reader.result || '').slice(0, PREVIEW_CHARS) }
  reader.readAsText(file)
}

const loadFile = (file) => {
  if (!file) return
  const extension = fileExtension(file)
  if (!KNOWLEDGE_ACCEPT.includes(`.${extension}`)) {
    setStatus(`不支持的文件格式 .${extension}，请选择 ${KNOWLEDGE_ACCEPT.replaceAll('.', '').replaceAll(',', '、')} 文件`, 'error')
    return
  }
  selectedFile.value = file
  materialTitle.value = materialTitle.value || file.name
  setStatus('')
  lastResult.value = null
  readPreview(file)
}

const handleFileChange = (event) => {
  loadFile(event.target.files?.[0])
  // 允许同一个文件被再次选中（否则重新选同名文件不触发 change）
  event.target.value = ''
}

const handleDrop = (event) => {
  isDragging.value = false
  loadFile(event.dataTransfer?.files?.[0])
}

const clearFile = () => {
  selectedFile.value = null
  previewText.value = ''
  setStatus('')
}

const submitMaterial = async () => {
  if (!selectedFile.value || uploading.value) return
  uploading.value = true
  uploadedPercent.value = 0
  setStatus('')

  const formData = new FormData()
  formData.append('file', selectedFile.value)
  formData.append('title', materialTitle.value.trim() || selectedFile.value.name)
  formData.append('visibility', visibility.value)
  formData.append('category', category.value)

  try {
    const result = unwrap(await knowledgeApi.upload(formData, (event) => {
      if (event.total) uploadedPercent.value = Math.round((event.loaded / event.total) * 100)
    }))
    if (!result || typeof result !== 'object') throw new Error('上传返回了无法识别的结果')

    const total = Number(result.total_chunks) || 0
    const ingested = Number(result.ingested) || 0
    const skipped = Number(result.skipped) || 0
    lastResult.value = {
      title: String(result.title || materialTitle.value || ''),
      total_chunks: total,
      ingested,
      skipped,
      details: Array.isArray(result.details) ? result.details.map(String) : [],
    }
    // 入库结果按段数说话：全跳过的常见原因是内容重复或单段不足 50 字。
    if (total === 0) setStatus('文件解析后没有可入库的内容，请确认文件不是空的或过短。', 'error')
    else if (ingested === 0) setStatus(`没有新内容入库：${skipped} 段因重复或过短被跳过（共 ${total} 段）。`, 'error')
    else {
      const publicHint = visibility.value === 'public' ? '；公开申请已提交，管理员通过后会出现在公共资料里' : ''
      setStatus(`已入库 ${ingested} 段${skipped > 0 ? `，${skipped} 段跳过` : ''}（共 ${total} 段）${publicHint}。`, 'success')
    }

    clearFile()
    await loadEntries()
  } catch (error) {
    setStatus(error?.response?.data?.detail || error?.response?.data?.msg || error?.message || '上传失败，请稍后重试。', 'error')
  } finally {
    uploading.value = false
    uploadedPercent.value = 0
  }
}

const formatDate = (value) => {
  if (!value) return ''
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? '' : date.toLocaleDateString('zh-CN')
}

const loadEntries = async () => {
  listLoading.value = true
  listError.value = ''
  try {
    const data = unwrap(await knowledgeApi.list({ mine: true }))
    entries.value = Array.isArray(data) ? data : []
  } catch (error) {
    listError.value = error?.response?.data?.detail || error?.message || '知识库暂时无法读取。'
  } finally {
    listLoading.value = false
  }
}

const removeEntry = async (entry) => {
  const docIds = Array.isArray(entry.doc_ids) && entry.doc_ids.length ? entry.doc_ids : [entry.doc_id]
  if (!window.confirm(`确定删除「${entry.title}」吗？这会删掉它的 ${docIds.length} 段内容，删除后不可恢复。`)) return
  deletingDocId.value = entry.doc_id
  try {
    await knowledgeApi.removeAll(docIds)
    await loadEntries()
    setStatus(`「${entry.title}」已删除。`, 'success')
  } catch (error) {
    setStatus(error?.response?.data?.detail || error?.response?.data?.msg || error?.message || '删除失败，请稍后重试。', 'error')
  } finally {
    deletingDocId.value = ''
  }
}

onMounted(loadEntries)
</script>

<style scoped>
.import-page { display: grid; gap: 18px; }
.import-layout { display: grid; grid-template-columns: minmax(0, 1.15fr) minmax(0, .85fr); gap: 18px; align-items: start; }
.upload-panel, .preview-panel, .library-panel { min-width: 0; }
.drop-zone { display: grid; justify-items: center; gap: 8px; padding: 30px 20px; border: 1px dashed var(--line); border-radius: 10px; background: #f7faf5; text-align: center; transition: border-color .2s ease, background .2s ease; }
.drop-zone.is-dragging { border-color: var(--accent-deep); background: #f1f7e8; }
.drop-zone.is-ready { border-style: solid; border-color: #c4df3d; background: #f8fbf0; }
.file-input { position: absolute; width: 1px; height: 1px; opacity: 0; }
.upload-mark { display: grid; width: 44px; height: 44px; place-items: center; border-radius: 50%; background: var(--accent); color: #1e3c34; }
.drop-zone h2 { margin: 0; color: var(--ink); font-size: 17px; overflow-wrap: anywhere; }
.drop-zone p { margin: 0; color: var(--muted); font-size: 12px; }
.upload-actions { display: flex; gap: 8px; margin-top: 6px; }
.meta-form { display: grid; gap: 16px; margin-top: 20px; }
.field { display: grid; gap: 6px; }
.field > span, .option-group legend { color: var(--muted); font-size: 12px; font-weight: 700; }
.field input { min-height: 40px; padding: 0 12px; border: 1px solid var(--line); border-radius: 5px; background: var(--paper); color: var(--ink); font-size: 13px; }
.field input:focus-visible { outline: 2px solid var(--accent-deep); outline-offset: 1px; }
.option-group { display: grid; gap: 8px; margin: 0; padding: 0; border: 0; }
.radio-option { display: grid; gap: 2px; padding: 10px 12px; border: 1px solid var(--line); border-radius: 6px; cursor: pointer; }
.radio-option input { margin-right: 6px; }
.radio-option span { color: var(--ink); font-size: 13px; font-weight: 700; }
.radio-option small { color: var(--muted); font-size: 11px; line-height: 1.6; }
.category-options { display: flex; flex-wrap: wrap; gap: 8px; }
.category-chip { padding: 7px 12px; border: 1px solid var(--line); border-radius: 99px; cursor: pointer; }
.category-chip input { position: absolute; width: 1px; height: 1px; opacity: 0; }
.category-chip span { color: var(--muted); font-size: 12px; font-weight: 700; }
.category-chip.is-active { border-color: #c4df3d; background: var(--accent); }
.category-chip.is-active span { color: #1e3c34; }
.status-message { margin: 0; padding: 10px 12px; border-radius: 6px; font-size: 12px; line-height: 1.7; }
.status-message.is-success { border: 1px solid #d7e3c9; background: #f4f8ed; color: var(--accent-deep); }
.status-message.is-error { border: 1px solid #e6cdc0; background: #fbf3ee; color: #954e38; }
.submit-button { width: 100%; gap: 8px; }
.field-hint { margin: 0; color: var(--muted); font-size: 11px; line-height: 1.7; }
.panel-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; margin-bottom: 14px; }
.panel-head h2 { margin: 0; color: var(--ink); font-size: 18px; }
.preview-box { max-height: 260px; overflow: auto; padding: 13px; border: 1px solid var(--line); border-radius: 8px; background: #f8faf5; color: var(--ink); font-size: 12px; line-height: 1.8; white-space: pre-wrap; }
.empty-state { padding: 22px 14px; border: 1px dashed var(--line); border-radius: 8px; color: var(--muted); font-size: 12px; line-height: 1.7; text-align: center; }
.ingest-result { margin-top: 18px; padding-top: 16px; border-top: 1px solid var(--line); }
.ingest-result h2 { margin: 0 0 12px; color: var(--ink); font-size: 15px; overflow-wrap: anywhere; }
.ingest-stats { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 10px; }
.ingest-stats div { display: grid; gap: 3px; padding: 10px; border: 1px solid var(--line); border-radius: 6px; background: #f7faf5; }
.ingest-stats strong { color: var(--ink); font-size: 19px; }
.ingest-stats span { color: var(--muted); font-size: 11px; }
.ingest-details { display: grid; gap: 5px; margin: 12px 0 0; padding-left: 16px; color: var(--muted); font-size: 11px; line-height: 1.7; }
.panel-state { display: flex; align-items: center; gap: 9px; padding: 18px; color: var(--muted); font-size: 12px; }
.panel-state.is-error { color: #954e38; }
.entry-list { display: grid; gap: 10px; margin: 0; padding: 0; list-style: none; }
.entry-row { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 13px 14px; border: 1px solid var(--line); border-radius: 8px; }
.entry-main { min-width: 0; }
.entry-title-line { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; }
.entry-title-line h3 { margin: 0; color: var(--ink); font-size: 14px; overflow-wrap: anywhere; }
.entry-tag { padding: 3px 7px; border-radius: 4px; background: #eef4e6; color: var(--accent-deep); font-size: 10px; font-weight: 800; }
.entry-tag--soft { background: #f1f2f4; color: var(--muted); }
.entry-main p { margin: 5px 0 0; font-size: 11px; }
.icon-button { display: grid; width: 34px; height: 34px; flex: 0 0 34px; place-items: center; border: 1px solid var(--line); border-radius: 50%; background: var(--paper); color: var(--muted); cursor: pointer; }
.icon-button:hover:not(:disabled) { border-color: #e6cdc0; color: #954e38; }
.icon-button:disabled { cursor: wait; opacity: .5; }
.spin { animation: spin 1s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
@media (max-width: 900px) {
  .import-layout { grid-template-columns: 1fr; }
}
</style>
