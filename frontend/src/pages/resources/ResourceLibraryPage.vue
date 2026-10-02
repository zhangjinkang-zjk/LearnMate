<template>
  <div class="library-page">
    <PageTitle eyebrow="RESOURCE LIBRARY" title="资料库" description="探索学习资源、查看个性化推荐，也可以管理你自己的学习资料">
      <template #actions>
        <RouterLink class="button button--quiet" to="/resources/mine"><BookOpen :size="15" />我的资源</RouterLink>
        <RouterLink class="button button--quiet" to="/resources/knowledge"><Upload :size="15" />上传知识库</RouterLink>
        <button class="button button--primary" type="button" @click="generationOpen = true"><Sparkles :size="15" />生成资料</button>
      </template>
    </PageTitle>
    <section class="resource-discovery">
      <div class="discovery-search surface">
        <div class="discovery-heading"><span class="discovery-icon"><BookOpen :size="20" /></span><div><p class="eyebrow">EXPLORE LEARNING</p><h2>探索学习资源</h2><p>查找课程、文档和实践教程，打开后即可开始学习。</p></div></div>
        <form class="external-search-form" @submit.prevent="submitExternalSearch">
          <label class="external-search-input"><Search :size="17" /><span class="sr-only">搜索学习资源</span><input v-model.trim="externalSearchTerm" type="search" placeholder="例如：Vue 3 响应式原理、Python 入门课程" /></label>
          <button class="button button--primary" type="submit" :disabled="externalSearchLoading || externalSearchTerm.length < 2"><LoaderCircle v-if="externalSearchLoading" class="spin" :size="15" /><Search v-else :size="15" />{{ externalSearchLoading ? '搜索中' : '搜索资源' }}</button>
        </form>
        <p v-if="externalSearchError" class="discovery-error">{{ externalSearchError }}</p>
      </div>
      <aside class="discovery-ai surface"><span class="ai-mark"><Sparkles :size="19" /></span><div><p class="eyebrow">LEARNMATE AI</p><h2>按你的目标生成</h2><p>把学习目标交给 AI，生成文档、练习或视频资料。</p></div><button class="button button--quiet" type="button" @click="generationOpen = true">开始生成 <ArrowRight :size="14" /></button></aside>
    </section>
    <section class="recommended-section">
      <div class="section-heading"><div><p class="eyebrow">RECOMMENDED FOR YOU</p><h2>{{ hasSearchedExternal ? '搜索结果' : '推荐资源' }}</h2><p>{{ hasSearchedExternal ? `关于「${externalSearchTerm}」的学习资源` : '根据你的学习方向精选的内容' }}</p></div><button v-if="hasSearchedExternal" class="button button--quiet" type="button" @click="clearExternalSearch">返回推荐</button></div>
      <div v-if="externalSearchLoading" class="recommendation-state surface"><LoaderCircle class="spin" :size="18" />正在查找学习资源</div>
      <div v-else-if="hasSearchedExternal && !externalResults.length" class="recommendation-state surface"><BookOpen :size="18" /><div><strong>暂时没有找到匹配资源</strong><p>换个关键词继续查找。</p></div></div>
      <div v-else class="recommendation-grid">
        <article v-for="item in (hasSearchedExternal ? externalResults : recommendedResources)" :key="item.key || item.resource_id || item.url" class="recommendation-card surface">
          <div class="recommendation-card__cover"><img v-if="resourceCoverUrl(item)" :src="resourceCoverUrl(item)" alt="" loading="lazy" referrerpolicy="no-referrer" /><span v-else class="recommendation-card__cover-empty">暂无真实封面</span></div>
          <div class="recommendation-card__content">
            <div class="recommendation-card__top"><span class="recommendation-card__icon"><BookOpen :size="17" /></span><span>{{ item.site_name || item.source_label || typeLabel(item.resource_type) }}</span></div>
            <h3>{{ item.title || item.topic }}</h3>
            <p>{{ item.snippet || item.preview || item.match_reason || '适合当前学习方向的学习资源。' }}</p>
            <a v-if="item.url" class="recommendation-link" :href="item.url" target="_blank" rel="noopener noreferrer">打开资源 <ExternalLink :size="13" /></a>
            <button v-else class="recommendation-link" type="button" @click="openPreview(item)">查看资源 <ArrowUpRight :size="13" /></button>
          </div>
        </article>
      </div>
    </section>
    <template v-if="false">
    <div class="my-resources-heading"><div><p class="eyebrow">MY RESOURCES</p><h2>我的资源</h2><p>你生成、上传和收藏的学习资料都在这里。</p></div></div>
    <section class="library-context surface">
      <div class="context-copy"><span class="context-icon"><Target :size="18" /></span><div><p class="eyebrow">PERSONALIZED FOR YOU</p><h2>{{ profile.direction || '正在生成学习方向…' }}</h2><p>{{ profile.stage || '正在生成学习阶段…' }}<span v-if="profile.goal"> · {{ profile.goal }}</span></p></div></div>
      <div class="context-stats"><div><strong>{{ filteredResources.length }}</strong><span>匹配材料</span></div><div><strong>{{ unreadCount }}</strong><span>待阅读</span></div><div><strong>{{ favoriteCount }}</strong><span>已收藏</span></div></div>
    </section>
    <Transition name="library-toast"><div v-if="notice" class="library-toast" role="status">{{ notice }}</div></Transition>
    <div class="library-toolbar"><div class="filter-tabs" role="tablist" aria-label="材料类型"><button v-for="tab in tabs" :key="tab.key" type="button" :class="{ 'is-active': activeType === tab.key }" @click="activeType = tab.key">{{ tab.label }}<span>{{ countByType(tab.key) }}</span></button></div><label class="search-box"><Search :size="16" /><span class="sr-only">搜索资料</span><input v-model.trim="searchTerm" type="search" placeholder="搜索主题、来源或标签" /></label></div>
    <div v-if="loading" class="library-state surface"><LoaderCircle class="spin" :size="20" />正在同步你的资料库</div>
    <div v-else-if="errorMessage" class="library-state library-state--error surface"><CircleAlert :size="20" /><div><strong>资料库暂时无法加载</strong><p>{{ errorMessage }}</p></div><button class="button button--quiet" type="button" @click="loadResources">重试</button></div>
    <div v-else-if="!filteredResources.length" class="library-state surface"><BookOpen :size="20" /><div><strong>还没有匹配的材料</strong><p>调整筛选条件，或让 LearnMate 根据当前目标生成一份新资料。</p></div><button class="button button--primary" type="button" @click="generationOpen = true">开始生成</button></div>
    <div v-else class="resource-list"><article v-for="resource in filteredResources" :key="resource.resource_id" class="resource-card surface" :class="{ 'is-read': resource.is_read, 'is-expanded': expandedResourceId === resource.resource_id }">
      <div class="resource-card__cover"><img v-if="resourceCoverUrl(resource)" :src="resourceCoverUrl(resource)" :alt="`${resource.topic} 封面`" loading="lazy" referrerpolicy="no-referrer" /><span v-else class="resource-card__cover-empty">暂无真实封面</span><span class="resource-card__type">{{ typeLabel(resource.resource_type) }}</span><button class="icon-button resource-card__favorite" type="button" :class="{ 'is-favorite': resource.favorited }" :aria-label="resource.favorited ? '取消收藏' : '收藏资料'" :title="resource.favorited ? '取消收藏' : '收藏资料'" @click.stop="toggleFavorite(resource)"><Star :size="16" :fill="resource.favorited ? 'currentColor' : 'none'" /></button></div>
      <div class="resource-card__body"><div class="resource-card__heading"><h2>{{ resource.topic }}</h2><span v-if="!resource.is_read" class="resource-card__unread">未读</span></div><p v-if="resource.match_reason" class="resource-reason"><span>匹配理由</span>{{ resource.match_reason }}</p><div class="resource-meta"><span v-if="difficultyLabel(resource)"><BarChart3 :size="13" />{{ difficultyLabel(resource) }}</span><span v-if="resource.source_label"><Compass :size="13" />{{ resource.source_label }}</span><span v-if="formatDate(resource.created_at)"><Clock3 :size="13" />{{ formatDate(resource.created_at) }}</span></div><div class="resource-card__actions"><button class="icon-button resource-expand-button" type="button" :aria-expanded="expandedResourceId === resource.resource_id" aria-label="展开资源详情" title="展开资源详情" @click="toggleExpanded(resource)"><ChevronDown :size="16" /></button><button class="button button--quiet open-button" type="button" @click="openPreview(resource)">打开 <ArrowUpRight :size="14" /></button></div><Transition name="resource-details"><div v-if="expandedResourceId === resource.resource_id" class="resource-details"><div v-if="resource.match_reason"><span>推荐依据</span><p>{{ resource.match_reason }}</p></div><div v-if="difficultyLabel(resource) || resource.source_label || formatDate(resource.created_at)"><span>资源信息</span><p>{{ [difficultyLabel(resource), resource.source_label, formatDate(resource.created_at)].filter(Boolean).join(' · ') }}</p></div><div v-if="resource.knowledge_tags?.length"><span>关联知识点</span><div class="resource-tags"><span v-for="tag in resource.knowledge_tags" :key="tag">{{ tag }}</span></div></div></div></Transition></div>
    </article></div>
    </template>
    <div v-if="previewResource" class="preview-backdrop" @click.self="previewResource = null"><section class="preview-modal surface" role="dialog" aria-modal="true" aria-labelledby="preview-title"><button class="preview-close icon-button" type="button" aria-label="关闭预览" @click="previewResource = null"><X :size="17" /></button><p class="eyebrow">{{ typeLabel(previewResource.resource_type) }}<span v-if="difficultyLabel(previewResource)"> · {{ difficultyLabel(previewResource) }}</span></p><h2 id="preview-title">{{ previewResource.topic }}</h2><p v-if="previewResource.source_label || previewResource.match_reason" class="preview-source">{{ previewResource.source_label }}<span v-if="previewResource.source_label && previewResource.match_reason"> · </span>{{ previewResource.match_reason }}</p><div class="preview-content">{{ formatResourcePreview(previewResource) || '这份材料还没有可预览的摘要，打开学习工作区查看完整内容。' }}</div><div class="preview-footer"><button class="button button--quiet" type="button" @click="previewResource = null">稍后阅读</button><button class="button button--primary" type="button" @click="markAndClose(previewResource)">标记为已读</button></div></section></div>
    <ResourceGenerationDialog v-model="generationOpen" @saved="handleGeneratedResources" @backgroundSettled="handleBackgroundSettled" @discarded="handleDiscardedResources" />
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { ArrowRight, ArrowUpRight, BarChart3, BookOpen, ChevronDown, CircleAlert, Clock3, Code2, Compass, ExternalLink, FileText, ListChecks, LoaderCircle, PlayCircle, Search, Sparkles, Star, Target, Upload, X } from 'lucide-vue-next'
import PageTitle from '@/shared/ui/PageTitle.vue'
import { learningApi } from '@/shared/api/learningApi'
import { resourceApi } from '@/shared/api/resourceApi'
import ResourceGenerationDialog from '@/features/resources/ResourceGenerationDialog.vue'
import { resourceCoverUrl } from '@/utils/resourceCover'
import { formatResourcePreview } from '@/utils/resourcePreview'
import mdnCover from '@/shared/assets/resource-covers/mdn-web-docs.jpg'
import freeCodeCampCover from '@/shared/assets/resource-covers/freecodecamp.jpg'
import runoobCover from '@/shared/assets/resource-covers/runoob.jpg'

const unwrap = (response) => response?.data?.data ?? response?.data ?? []
const loading = ref(true); const errorMessage = ref(''); const resources = ref([]); const publicResources = ref([]); const activeType = ref('all'); const searchTerm = ref(''); const previewResource = ref(null); const expandedResourceId = ref(null); const generationOpen = ref(false); const notice = ref(''); const externalSearchTerm = ref(''); const externalResults = ref([]); const externalSearchLoading = ref(false); const externalSearchError = ref(''); const hasSearchedExternal = ref(false); let noticeTimer = null
const profile = reactive({ direction: '', goal: '', stage: '' })
const tabs = [{ key: 'all', label: '全部' }, { key: 'document', label: '文档' }, { key: 'video', label: '视频' }, { key: 'code', label: '代码模板' }, { key: 'exercise', label: '练习题' }]
const curatedRecommendations = [
  { key: 'mdn', title: 'MDN Web Docs', site_name: 'MDN', resource_type: 'document', cover_url: mdnCover, snippet: '权威的 Web 平台、JavaScript 和 CSS 文档，适合随时查阅。', url: 'https://developer.mozilla.org/zh-CN/' },
  { key: 'freecodecamp', title: 'freeCodeCamp', site_name: 'freeCodeCamp', resource_type: 'exercise', cover_url: freeCodeCampCover, snippet: '从基础到项目实践的免费编程课程与练习。', url: 'https://www.freecodecamp.org/learn/' },
  { key: 'runoob', title: '菜鸟教程', site_name: '菜鸟教程', resource_type: 'reading', cover_url: runoobCover, snippet: '覆盖多种编程语言和开发工具的中文入门教程。', url: 'https://www.runoob.com/' },
]
const typeLabel = (type) => ({ document: '文档', reading: '阅读材料', video: '视频', external_video: '视频', code: '代码模板', template: '代码模板', exercise: '练习题', case: '案例' }[type] || '学习材料')
const difficultyLabel = (resource) => resource.difficulty || resource.level || ''
const normalize = (item, { requireId = true } = {}) => {
  const resourceId = item?.resource_id ?? item?.id
  const topic = String(item?.topic || item?.title || '').trim()
  if ((!resourceId && requireId) || !topic) return null
  return { ...item, resource_id: resourceId || item.key || item.url || topic, topic, match_reason: item.match_reason || item.reason || '', source_label: item.source_label || item.source || '', is_read: Boolean(item.is_read), favorited: Boolean(item.favorited) }
}
const filteredResources = computed(() => resources.value.filter((item) => { const typeMatch = activeType.value === 'all' || item.resource_type === activeType.value || (activeType.value === 'video' && item.resource_type === 'external_video') || (activeType.value === 'code' && item.resource_type === 'template'); const needle = searchTerm.value.toLowerCase(); return typeMatch && (!needle || [item.topic, item.match_reason, item.source_label, typeLabel(item.resource_type)].join(' ').toLowerCase().includes(needle)) }))
const recommendedResources = computed(() => publicResources.value.length ? publicResources.value : curatedRecommendations)
const countByType = (type) => type === 'all' ? resources.value.length : resources.value.filter((item) => item.resource_type === type || (type === 'video' && item.resource_type === 'external_video') || (type === 'code' && item.resource_type === 'template')).length
const unreadCount = computed(() => resources.value.filter((item) => !item.is_read).length); const favoriteCount = computed(() => resources.value.filter((item) => item.favorited).length)
async function loadResources() {
  loading.value = true
  errorMessage.value = ''
  Object.assign(profile, { direction: '', goal: '', stage: '' })
  try {
    const [resourceResult, overviewResult, publicResult] = await Promise.allSettled([resourceApi.list(), learningApi.getOverview(), resourceApi.list('public')])
    if (resourceResult.status === 'rejected') throw resourceResult.reason
    resources.value = (Array.isArray(resourceResult.value) ? resourceResult.value : []).map(normalize).filter(Boolean)
    publicResources.value = publicResult.status === 'fulfilled' ? (Array.isArray(publicResult.value) ? publicResult.value : []).map((item) => normalize(item, { requireId: false })).filter(Boolean) : []
    if (overviewResult.status === 'fulfilled') {
      const overview = unwrap(overviewResult.value) || {}
      Object.assign(profile, { direction: overview.profile?.direction || overview.subjects?.[0]?.name || '', goal: overview.profile?.goal || overview.goals?.[0]?.title || '', stage: overview.diagnosis?.stage || '' })
    }
  } catch (error) {
    resources.value = []
    publicResources.value = []
    errorMessage.value = error?.response?.data?.detail || error?.message || '请稍后重试'
  } finally {
    loading.value = false
  }
}
function normalizeExternal(item) {
  const url = String(item?.url || '').trim()
  const title = String(item?.title || item?.name || '').trim()
  if (!/^https?:\/\//i.test(url) || !title) return null
  const resourceType = /(?:youtube\.com|youtu\.be|bilibili\.com)/i.test(url) ? 'video' : 'reading'
  return { ...item, key: url, url, title, resource_type: item.resource_type || resourceType, snippet: String(item.snippet || item.summary || '').trim() }
}
async function submitExternalSearch() {
  const query = externalSearchTerm.value.trim()
  if (query.length < 2 || externalSearchLoading.value) return
  externalSearchLoading.value = true
  externalSearchError.value = ''
  hasSearchedExternal.value = true
  try {
    const result = await resourceApi.searchExternal(query)
    externalResults.value = (Array.isArray(result) ? result : []).map(normalizeExternal).filter(Boolean)
  } catch (error) {
    externalResults.value = []
    externalSearchError.value = error?.response?.data?.detail || '搜索服务暂时不可用，请稍后重试。'
  } finally {
    externalSearchLoading.value = false
  }
}
function clearExternalSearch() { hasSearchedExternal.value = false; externalResults.value = []; externalSearchError.value = '' }
async function markRead(resource) { if (resource.is_read) return; const previous = resource.is_read; resource.is_read = true; try { await resourceApi.markRead(resource.resource_id) } catch { resource.is_read = previous } }
function showNotice(message) { notice.value = message; window.clearTimeout(noticeTimer); noticeTimer = window.setTimeout(() => { notice.value = '' }, 2200) }
async function handleGeneratedResources() { showNotice('资料已保存到资料库'); await loadResources() }
// 丢弃后必须重新拉取：资源是真被删了，不刷新的话列表上还留着已被删除的条目
async function handleDiscardedResources() { showNotice('已丢弃本次生成的资料'); await loadResources() }
// 弹窗被关掉后任务仍在后台跑，跑完/失败时靠这个事件告诉用户
async function handleBackgroundSettled(payload) {
  if (payload?.ok) { showNotice('资料已在后台生成完成，已放入资料库'); await loadResources() }
  else showNotice(payload?.message || '后台生成未能完成，请稍后重试')
}
function toggleExpanded(resource) { expandedResourceId.value = expandedResourceId.value === resource.resource_id ? null : resource.resource_id }
async function toggleFavorite(resource) {
  const previous = resource.favorited
  resource.favorited = !previous
  showNotice(resource.favorited ? '已加入收藏' : '已取消收藏')
  try {
    await resourceApi.favorite(resource.resource_id)
  } catch {
    resource.favorited = previous
    showNotice('收藏操作失败，请稍后重试')
  }
}
function openPreview(resource) { previewResource.value = resource; markRead(resource) }; function markAndClose(resource) { markRead(resource); previewResource.value = null }
function formatDate(value) { if (!value) return ''; const date = new Date(value); return Number.isNaN(date.getTime()) ? '' : date.toLocaleDateString('zh-CN', { month: 'numeric', day: 'numeric' }) + ' 更新' }
onMounted(loadResources)
onBeforeUnmount(() => window.clearTimeout(noticeTimer))
</script>

<style scoped>
.resource-discovery { display: grid; grid-template-columns: minmax(0, 1.5fr) minmax(260px, .8fr); gap: 14px; margin-bottom: 26px; }
.discovery-search, .discovery-ai { min-width: 0; padding: 20px; }
.discovery-search { background: #f7f6fb; border-color: transparent; }
.discovery-heading { display: flex; align-items: flex-start; gap: 12px; }
.discovery-heading h2, .discovery-ai h2 { margin: 0; font-size: 19px; line-height: 1.35; }
.discovery-heading p:last-child, .discovery-ai p:last-of-type { margin: 5px 0 0; color: var(--muted); font-size: 12px; line-height: 1.55; }
.discovery-icon, .ai-mark { display: grid; width: 40px; height: 40px; flex: 0 0 40px; place-items: center; border-radius: 11px; background: #1e3c34; color: #e2f452; }
.external-search-form { display: flex; gap: 9px; margin-top: 18px; }
.external-search-input { display: flex; flex: 1; align-items: center; gap: 8px; min-width: 0; min-height: 42px; padding: 0 13px; border: 1px solid var(--line); border-radius: 8px; background: #fff; color: var(--muted); }
.external-search-input:focus-within { border-color: var(--accent-deep); box-shadow: 0 0 0 3px rgba(182, 216, 55, .16); }
.external-search-input input { width: 100%; min-width: 0; border: 0; outline: 0; background: transparent; color: var(--ink); font-size: 12px; }
.external-search-form .button { min-height: 42px; white-space: nowrap; }
.external-search-form .button:disabled { cursor: not-allowed; opacity: .55; }
.discovery-error { margin: 9px 0 0; color: #a55342; font-size: 11px; }
.discovery-ai { display: grid; align-content: start; gap: 14px; background: rgba(250, 255, 196, .35); border-color: transparent; }
.discovery-ai .button { justify-self: start; gap: 6px; }
.recommended-section { margin-bottom: 28px; }
.section-heading { display: flex; align-items: flex-end; justify-content: space-between; gap: 16px; margin-bottom: 13px; }
.section-heading h2, .my-resources-heading h2 { margin: 0; font-size: 21px; line-height: 1.35; }
.section-heading p:last-child, .my-resources-heading p:last-child { margin: 4px 0 0; color: var(--muted); font-size: 12px; }
.recommendation-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 11px; }
.recommendation-card { display: flex; min-width: 0; min-height: 274px; flex-direction: column; overflow: hidden; padding: 0; transition: border-color .2s ease, box-shadow .2s ease, transform .2s ease; }
.recommendation-card:hover { border-color: #a8ba9e; box-shadow: 0 8px 22px rgba(45,70,40,.08); transform: translateY(-1px); }
.recommendation-card__cover { height: 150px; overflow: hidden; border-bottom: 1px solid var(--line); background: #1e3c34; }
.recommendation-card__cover img { display: block; width: 100%; height: 100%; object-fit: cover; }
.recommendation-card__cover-empty { display: grid; width: 100%; height: 100%; place-items: center; color: rgba(255,255,255,.78); font-size: 11px; }
.recommendation-card__content { display: flex; min-height: 0; flex: 1; flex-direction: column; padding: 11px 16px 13px; }
.recommendation-card__top { display: flex; align-items: center; gap: 7px; color: var(--muted); font-size: 10px; }
.recommendation-card__icon { display: grid; width: 29px; height: 29px; place-items: center; border-radius: 8px; background: #1e3c34; color: #e2f452; }
.recommendation-card h3 { overflow: hidden; margin: 8px 0 0; color: var(--ink); font-size: 14px; text-overflow: ellipsis; white-space: nowrap; }
.recommendation-card p { display: -webkit-box; overflow: hidden; margin: 5px 0 0; color: var(--muted); font-size: 11px; line-height: 1.5; -webkit-box-orient: vertical; -webkit-line-clamp: 2; }
.recommendation-link { display: inline-flex; align-items: center; gap: 5px; width: max-content; max-width: 100%; padding: 0; margin-top: auto; border: 0; background: transparent; color: var(--accent-deep); font-size: 11px; font-weight: 800; text-decoration: none; }
.recommendation-link:hover { color: var(--ink); }
.recommendation-state { display: flex; align-items: center; gap: 11px; min-height: 72px; padding: 16px; color: var(--muted); font-size: 12px; }
.recommendation-state strong { color: var(--ink); }
.recommendation-state p { margin: 4px 0 0; font-size: 11px; }
.recommendation-state .button { margin-left: auto; gap: 5px; white-space: nowrap; }
.my-resources-heading { display: flex; align-items: flex-end; justify-content: space-between; margin: 4px 0 13px; }
.library-page { min-width: 0; }.library-page :deep(.page-heading) { margin-bottom: 24px; }.library-page :deep(.page-heading h1) { font-size: 30px; }.library-page :deep(.page-heading p) { max-width: 590px; }.library-context { display: flex; align-items: center; justify-content: space-between; gap: 24px; padding: 20px 22px; margin-bottom: 18px; background: rgba(250,255,196,.2); border-color: transparent; }.context-copy { display: flex; align-items: center; gap: 13px; min-width: 0; }.context-icon { display: grid; width: 40px; height: 40px; flex: 0 0 40px; place-items: center; border-radius: 50%; background: #fff; color: var(--accent-deep); }.context-copy h2 { margin: 0; font-size: 18px; }.context-copy p:last-child { margin: 4px 0 0; color: var(--muted); font-size: 12px; }.context-stats { display: flex; gap: 28px; }.context-stats div { display: grid; gap: 2px; text-align: right; }.context-stats strong { color: var(--accent-deep); font-size: 22px; }.context-stats span { color: var(--muted); font-size: 11px; }.library-toolbar { display: flex; align-items: center; justify-content: space-between; gap: 16px; margin-bottom: 15px; }.filter-tabs { display: flex; gap: 4px; overflow-x: auto; }.filter-tabs button { display: inline-flex; align-items: center; gap: 7px; min-height: 34px; padding: 0 11px; border: 0; border-radius: 4px; background: transparent; color: var(--muted); font-size: 12px; white-space: nowrap; }.filter-tabs button:hover { background: var(--soft); color: var(--ink); }.filter-tabs button.is-active { background: var(--ink); color: #fff; }.filter-tabs button span { opacity: .65; font-size: 10px; }.search-box { display: flex; align-items: center; gap: 8px; width: min(255px, 100%); min-height: 35px; padding: 0 11px; border: 1px solid var(--line); border-radius: 5px; color: var(--muted); }.search-box input { width: 100%; min-width: 0; border: 0; outline: 0; color: var(--ink); font-size: 12px; }.resource-list { display: grid; gap: 10px; }.resource-row { display: grid; grid-template-columns: 46px minmax(0,1fr) auto; align-items: center; gap: 15px; padding: 16px 18px; transition: border-color .2s ease, box-shadow .2s ease, transform .2s ease; }.resource-row:hover { border-color: #a8ba9e; box-shadow: 0 8px 22px rgba(45,70,40,.08); transform: translateY(-1px); }.resource-row.is-read { background: #fcfdfb; }.resource-mark { display: grid; width: 42px; height: 42px; place-items: center; border-radius: 10px; color: var(--accent-deep); background: #e9f0e3; }.mark-video { color: #514c8c; background: #eeeef9; }.mark-code { color: #79602b; background: #f8efd7; }.mark-exercise { color: #8a4c43; background: #f8e8e5; }.resource-main { min-width: 0; }.resource-title-line { display: flex; align-items: center; gap: 9px; min-width: 0; }.resource-title-line h2 { overflow: hidden; margin: 0; font-size: 16px; text-overflow: ellipsis; white-space: nowrap; }.type-label { flex: 0 0 auto; padding: 3px 7px; border-radius: 3px; background: var(--soft); color: var(--muted); font-size: 10px; }.resource-reason { overflow: hidden; margin: 7px 0 9px; color: var(--muted); font-size: 12px; text-overflow: ellipsis; white-space: nowrap; }.resource-reason span { margin-right: 7px; color: var(--accent-deep); font-size: 10px; font-weight: 800; }.resource-meta { display: flex; flex-wrap: wrap; gap: 14px; color: var(--muted); font-size: 11px; }.resource-meta span { display: inline-flex; align-items: center; gap: 5px; }.resource-actions { display: flex; align-items: center; gap: 9px; }.icon-button { display: grid; width: 34px; height: 34px; place-items: center; border: 1px solid transparent; border-radius: 50%; background: transparent; color: var(--muted); }.icon-button:hover, .icon-button.is-favorite { border-color: #d9e1d5; background: #f2f6ef; color: var(--accent-deep); }.open-button { gap: 5px; min-height: 34px; padding: 0 10px; font-size: 11px; }.library-state { display: flex; align-items: center; gap: 12px; padding: 24px; color: var(--muted); font-size: 13px; }.library-state strong { color: var(--ink); }.library-state p { margin: 4px 0 0; font-size: 12px; }.library-state--error { color: #9a4a43; }.library-state .button { margin-left: auto; }.spin { animation: spin 1s linear infinite; } .preview-backdrop { position: fixed; inset: 0; z-index: 50; display: grid; place-items: center; padding: 20px; background: rgba(25,38,31,.45); }.preview-modal { position: relative; width: min(620px, 100%); padding: 28px; box-shadow: 0 22px 60px rgba(13,28,20,.22); }.preview-close { position: absolute; top: 16px; right: 16px; }.preview-modal h2 { margin: 0; padding-right: 25px; font-size: 22px; }.preview-source { margin: 9px 0 20px; color: var(--muted); font-size: 12px; }.preview-content { max-height: 300px; overflow: auto; padding: 17px; border: 1px solid var(--line); background: #fafcf9; color: var(--ink); font-size: 13px; line-height: 1.75; white-space: pre-wrap; }.preview-footer { display: flex; justify-content: flex-end; gap: 9px; margin-top: 20px; }@keyframes spin { to { transform: rotate(360deg); } }
@media (max-width: 700px) { .library-context { align-items: flex-start; flex-direction: column; }.context-stats { width: 100%; justify-content: space-between; gap: 12px; }.context-stats div { text-align: left; }.library-toolbar { align-items: stretch; flex-direction: column-reverse; }.search-box { width: 100%; }.resource-row { grid-template-columns: 40px minmax(0,1fr); gap: 12px; }.resource-mark { width: 38px; height: 38px; }.resource-actions { grid-column: 2; justify-content: flex-end; }.resource-title-line { align-items: flex-start; flex-direction: column; gap: 5px; }.resource-title-line h2 { white-space: normal; }.resource-reason { white-space: normal; }.library-page :deep(.page-heading h1) { font-size: 25px; } }
@media (max-width: 820px) { .resource-discovery { grid-template-columns: 1fr; }.recommendation-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
@media (max-width: 540px) { .external-search-form { align-items: stretch; flex-direction: column; }.external-search-form .button { width: 100%; }.recommendation-grid { grid-template-columns: 1fr; }.discovery-search, .discovery-ai { padding: 16px; }.section-heading { align-items: flex-start; flex-direction: column; gap: 9px; }.recommendation-state { align-items: flex-start; flex-wrap: wrap; }.recommendation-state .button { width: 100%; margin-left: 29px; } }
.library-page .surface,
.library-page .search-box,
.library-page .filter-tabs button,
.library-page .type-label,
.library-page .resource-mark,
.library-page .preview-content,
.library-page .button { border-radius: 12px; }
.library-page .button--primary,
.library-page .filter-tabs button.is-active { border-color: #e2f452; background: #e2f452; color: #1e3c34; }
.library-page .button--primary:hover,
.library-page .filter-tabs button.is-active:hover { border-color: #d5f242; background: #d5f242; color: #1e3c34; }
.library-page .button--quiet { border-radius: 12px; }
.library-page :deep(.button--primary) { border-color: #e2f452; border-radius: 12px; background: #e2f452; color: #1e3c34; }
.library-page :deep(.button--primary:hover) { border-color: #d5f242; background: #d5f242; color: #1e3c34; }
.library-generate-button { min-height: 56px; padding: 0 24px; font-size: 16px; font-weight: 800; }
.library-page .filter-tabs button.is-active,
.library-page :deep(.filter-tabs button.is-active) { border-color: #e2f452 !important; border-radius: 12px; background: #e2f452 !important; color: #1e3c34 !important; }
.resource-list .resource-row:nth-child(odd) { background: #fff; }
.resource-list .resource-row:nth-child(even) { background: #f7f6fb; }
.resource-list .resource-row:nth-child(even):hover { background: #f1f0f8; }
.library-page .resource-mark,
.library-page .mark-video,
.library-page .mark-code,
.library-page .mark-exercise { background: #1e3c34 !important; color: #e2f452 !important; }
:global(.page-container:has(.library-page)) { min-height: calc(100vh - 64px); background: #f7f7f7; }
:global(.app-content:has(.library-page)) { background: #f7f7f7; }
:global(.app-content:has(.library-page) .app-header) { border-bottom-color: #e8e8e8; background: #f7f7f7; }
.resource-row.is-expanded { border-color: #a8ba9e; }
.resource-expand-button svg { transition: transform .2s ease; }
.resource-row.is-expanded .resource-expand-button svg { transform: rotate(180deg); }
.resource-details { display: grid; grid-column: 1 / -1; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 16px; padding: 14px 0 1px 61px; border-top: 1px solid rgba(63, 91, 49, .13); }
.resource-details > div { min-width: 0; }
.resource-details > div > span { color: var(--muted); font-size: 10px; }
.resource-details p { margin: 5px 0 0; color: var(--ink); font-size: 11px; line-height: 1.55; }
.resource-tags { display: flex; flex-wrap: wrap; gap: 5px; margin-top: 6px; }
.resource-tags span { padding: 3px 7px; border-radius: 4px; background: var(--soft); color: var(--accent-deep); font-size: 10px; }
.resource-details-enter-active, .resource-details-leave-active { overflow: hidden; transition: opacity .2s ease, max-height .24s ease; }
.resource-details-enter-from, .resource-details-leave-to { max-height: 0; opacity: 0; }
.resource-details-enter-to, .resource-details-leave-from { max-height: 220px; opacity: 1; }
.library-toast { position: fixed; top: 78px; left: 50%; z-index: 20; padding: 9px 13px; border: 1px solid #d7e3c9; border-radius: 8px; background: #f3f8ea; box-shadow: 0 8px 20px rgba(45, 70, 40, .12); color: var(--accent-deep); font-size: 12px; transform: translateX(-50%); }
.library-toast-enter-active, .library-toast-leave-active { transition: opacity .18s ease, transform .18s ease; }
.library-toast-enter-from, .library-toast-leave-to { opacity: 0; transform: translate(-50%, -6px); }
@media (max-width: 700px) { .resource-details { grid-template-columns: 1fr; gap: 10px; padding: 13px 0 1px 52px; } }

/* Personal resources use the cover as the primary scan target. */
.resource-list { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 16px; }
.resource-card { display: flex; min-width: 0; flex-direction: column; overflow: hidden; padding: 0; transition: border-color .2s ease, box-shadow .2s ease, transform .2s ease; }
.resource-card:hover, .resource-card.is-expanded { border-color: #a8ba9e; box-shadow: 0 10px 25px rgba(45,70,40,.1); transform: translateY(-2px); }
.resource-card.is-read { background: #fcfdfb; }
.resource-card__cover { position: relative; aspect-ratio: 2.2 / 1; overflow: hidden; background: #e8efe5; }
.resource-card__cover::after { position: absolute; inset: 0; pointer-events: none; content: ''; background: linear-gradient(180deg, rgba(20,35,28,.12), transparent 42%, rgba(20,35,28,.16)); }
.resource-card__cover img { display: block; width: 100%; height: 100%; object-fit: cover; transition: transform .3s ease; }
.resource-card__cover-empty { display: grid; width: 100%; height: 100%; place-items: center; color: var(--muted); font-size: 11px; }
.resource-card:hover .resource-card__cover img { transform: scale(1.025); }
.resource-card__type { position: absolute; z-index: 1; top: 12px; left: 13px; padding: 4px 8px; border-radius: 999px; background: rgba(255,255,255,.9); color: var(--accent-deep); font-size: 10px; font-weight: 800; letter-spacing: .02em; }
.resource-card__favorite { position: absolute; z-index: 1; top: 8px; right: 9px; border-color: rgba(255,255,255,.55); background: rgba(255,255,255,.88); }
.resource-card__favorite:hover, .resource-card__favorite.is-favorite { border-color: #d9e1d5; background: #f2f6ef; color: var(--accent-deep); }
.resource-card__body { display: flex; min-width: 0; flex: 1; flex-direction: column; padding: 15px 16px 14px; }
.resource-card__heading { display: flex; align-items: flex-start; justify-content: space-between; gap: 8px; min-width: 0; }
.resource-card__heading h2 { display: -webkit-box; overflow: hidden; margin: 0; color: var(--ink); font-size: 17px; line-height: 1.35; -webkit-box-orient: vertical; -webkit-line-clamp: 2; }
.resource-card__unread { flex: 0 0 auto; padding: 3px 6px; border-radius: 999px; background: #edf5e5; color: var(--accent-deep); font-size: 10px; white-space: nowrap; }
.resource-card .resource-reason { display: -webkit-box; margin: 9px 0 10px; line-height: 1.5; white-space: normal; -webkit-box-orient: vertical; -webkit-line-clamp: 2; }
.resource-card .resource-meta { min-height: 19px; gap: 9px 12px; }
.resource-card__actions { display: flex; align-items: center; justify-content: flex-end; gap: 7px; margin-top: auto; padding-top: 14px; }
.resource-card__actions .resource-expand-button { margin-right: auto; }
.resource-card .resource-details { grid-template-columns: 1fr; gap: 10px; padding: 13px 0 0; margin-top: 13px; }
.resource-card .resource-details p { overflow: hidden; display: -webkit-box; -webkit-box-orient: vertical; -webkit-line-clamp: 3; }
@media (max-width: 960px) { .resource-list { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
@media (max-width: 540px) { .resource-list { grid-template-columns: 1fr; gap: 13px; }.resource-card__cover { aspect-ratio: 2.35 / 1; }.resource-card__body { padding: 14px; } }
</style>
