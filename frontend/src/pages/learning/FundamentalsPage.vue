<template>
  <div class="fundamentals-page">
    <div v-if="isPageLoading" class="page-state surface" aria-live="polite">
      <LoaderCircle class="spin" :size="28" />
      <strong>正在打开你的学习章节</strong>
      <p>同步学习路径、章节状态和主讲文档。</p>
    </div>

    <div v-else-if="pageError" class="page-state page-state--error surface">
      <CircleAlert :size="28" />
      <strong>基础学习暂时没有加载成功</strong>
      <p>{{ pageError }}</p>
      <button class="button button--quiet" type="button" @click="loadPage">重新加载</button>
    </div>

    <div v-else-if="!learningPath && !pathCatalog.length" class="page-state surface">
      <Route :size="28" />
      <strong>还没有可以学习的路径</strong>
      <p>先完成学习定向与能力诊断，系统才会按你的目标生成科目和章节。</p>
      <RouterLink class="button button--primary" to="/onboarding/direction">开始学习定向</RouterLink>
    </div>

    <template v-else>
      <div v-if="pathSwitchError" class="path-switch-error" role="status">
        <CircleAlert :size="16" />
        <span>{{ pathSwitchError }}</span>
        <button class="button button--quiet" type="button" @click="pathSwitchError = ''">关闭</button>
      </div>

      <div v-if="!learningPath" class="page-state surface">
        <Route :size="25" />
        <strong>请选择一条学习路径</strong>
        <p>打开科目抽屉，从当前学习方向下的相关科目中选择一条路径。</p>
        <button class="button button--primary" type="button" @click="openNavigationDrawer('paths')">选择学习科目</button>
      </div>

      <section v-else-if="!hasActiveLesson" class="foundation-library" aria-labelledby="foundation-library-title">
        <div class="foundation-library__layout">
          <ChapterRail
            :nodes="learningPath.nodes"
            :active-node-id="previewNode?.id"
            @select="selectPreviewNode"
          />
          <div class="foundation-library__main">
        <header class="foundation-library__header">
          <div>
            <p class="eyebrow lesson-eyebrow">FOUNDATION LEARNING</p>
            <h1 id="foundation-library-title">基础学习</h1>
            <p>先从配套资源开始，再进入对应章节的讲解与练习。</p>
          </div>
          <div class="path-progress" aria-label="当前科目学习进度">
            <div><span>{{ learningPath.goal }}</span><strong>{{ learningPath.progress }}%</strong></div>
            <div class="progress-track"><div class="progress-value" :style="{ width: `${learningPath.progress}%` }"></div></div>
            <small>已完成 {{ completedNodeCount }} / {{ learningPath.nodes.length }} 章</small>
          </div>
        </header>

        <div class="foundation-library__start-hint" role="note">
          <BookOpenText :size="16" aria-hidden="true" />
          <span><strong>建议先从主讲文档开始</strong><small>先读懂核心内容，再用 PPT、知识结构和视频辅助理解。</small></span>
        </div>
        <div v-if="resourceOverviewLoading" class="foundation-library__state surface" aria-live="polite">
          <LoaderCircle class="spin" :size="22" />
          <strong>正在整理你的学习资源</strong>
          <p>正在同步平台生成内容和配套视频。</p>
        </div>
        <div v-else-if="!resourceGroups.length" class="foundation-library__state surface">
          <BookOpenText :size="24" />
          <strong>资源正在准备中</strong>
          <p>路径已经就绪，打开任一章节后系统会生成对应的基础学习资料。</p>
          <button class="button button--primary" type="button" @click="openNodeForResource(learningPath.nodes[0])">
            准备第一章资源
            <ArrowRight :size="15" />
          </button>
        </div>
        <div v-else class="foundation-library__body">
          <section v-for="group in resourceGroups" :key="group.node.id" class="resource-group">
            <header class="resource-group__header">
              <div>
                <span class="resource-group__index">{{ String(group.index + 1).padStart(2, '0') }}</span>
                <div>
                  <p class="eyebrow">章节资源</p>
                  <h2>{{ group.node.title }}</h2>
                </div>
              </div>
              <span class="resource-group__status">{{ nodeStatusLabel(group.node.status) }}</span>
            </header>
            <div v-if="group.resources.length" class="resource-card-grid">
              <button
                v-for="resource in group.resources"
                :key="`${group.node.id}-${resource.resource_id || resource.id}`"
                class="resource-card surface"
                :class="{ 'resource-card--primary': resource.resource_type === 'document' }"
                type="button"
                @click="openFoundationResource(group.node, resource)"
              >
                <span class="resource-card__cover">
                  <img :src="resourceCoverUrl(resource)" :alt="`${resource.title || resource.topic || '学习资源'}封面`" @error="handleCoverError($event, resource)" />
                  <span class="resource-card__cover-overlay">
                    <span class="resource-card__type">{{ resourceTypeLabel(resource.resource_type) }}</span>
                    <PlayCircle v-if="resource.resource_type === 'external_video' || resource.resource_type === 'video'" :size="22" />
                    <Presentation v-else-if="resource.resource_type === 'ppt'" :size="22" />
                    <Network v-else-if="resource.resource_type === 'mindmap'" :size="22" />
                    <BookOpenText v-else :size="22" />
                  </span>
                </span>
                <span class="resource-card__content">
                  <span v-if="resource.resource_type === 'document'" class="resource-card__guide"><BookOpenText :size="13" />建议先阅读</span>
                  <strong>{{ resource.title || resource.topic || resourceLabel(resource.resource_type) }}</strong>
                  <small>{{ resourceTypeLabel(resource.resource_type) }}<span v-if="resource.source_label"> · {{ resource.source_label }}</span><span v-if="resource.duration_text"> · {{ resource.duration_text }}</span></small>
                  <span v-if="resource.description" class="resource-card__description">{{ resource.description }}</span>
                </span>
                <ArrowRight class="resource-card__arrow" :size="17" />
              </button>
            </div>
            <button v-else class="resource-group__empty surface" type="button" @click="openNodeForResource(group.node)">
              <LoaderCircle v-if="group.node.status !== 'locked'" :size="17" />
              <LockKeyhole v-else :size="17" />
              <span>{{ group.node.status === 'locked' ? '完成前置章节后解锁资源' : '打开章节并准备配套资源' }}</span>
              <ArrowRight :size="15" />
            </button>
          </section>

        </div>
          </div>
        </div>
      </section>

      <template v-else>
        <header class="lesson-context">
          <button class="button button--quiet return-resource-button" type="button" @click="openResourcePreview">
            <Eye :size="15" />
            资源预览
          </button>
          <div class="lesson-context__copy">
            <p class="eyebrow lesson-eyebrow">FOUNDATION LEARNING</p>
            <h1>{{ activeNode?.title || '选择一个章节' }}</h1>
            <p>基础学习 · {{ learningPath.goal }}<span>第 {{ activeNodeIndex + 1 }} / {{ learningPath.nodes.length }} 章</span><span>{{ activeNode?.summary || '按学习路径逐章补齐知识基础。' }}</span></p>
          </div>
          <div class="lesson-context__actions">
            <div class="path-progress" aria-label="当前科目学习进度">
              <div><span>科目进度</span><strong>{{ learningPath.progress }}%</strong></div>
              <div class="progress-track"><div class="progress-value" :style="{ width: `${learningPath.progress}%` }"></div></div>
              <small>已完成 {{ completedNodeCount }} / {{ learningPath.nodes.length }} 章</small>
            </div>
          </div>
        </header>

        <div class="learning-layout">
          <nav class="workspace-rail" aria-label="学习内容切换">
            <button
              type="button"
              title="切换学习科目"
              aria-label="切换学习科目"
              aria-controls="fundamentals-navigation-drawer"
              :aria-expanded="navigationDrawer === 'paths'"
              :class="{ 'is-active': navigationDrawer === 'paths' }"
              @click="toggleNavigationDrawer('paths')"
            >
              <Route :size="18" />
              <span>科目</span>
              <small>{{ pathCatalog.length }}</small>
            </button>
            <button
              type="button"
              title="展开章节节点"
              aria-label="展开章节节点"
              aria-controls="fundamentals-navigation-drawer"
              :aria-expanded="navigationDrawer === 'chapters'"
              :class="{ 'is-active': navigationDrawer === 'chapters' }"
              @click="toggleNavigationDrawer('chapters')"
            >
              <ListTree :size="18" />
              <span>章节</span>
              <small>{{ learningPath.nodes.length }}</small>
            </button>
            <span class="workspace-rail__divider" aria-hidden="true"></span>
            <div class="resource-tabs resource-tabs--rail" role="tablist" aria-label="章节材料视图">
              <button
                type="button"
                role="tab"
                :aria-selected="resourceView === 'document'"
                :class="{ 'is-active': resourceView === 'document' }"
                @click="showDocument"
              >
                <BookOpenText :size="16" />
                <span>主讲文档</span>
              </button>
              <button
                v-if="mindmapResource"
                type="button"
                role="tab"
                :aria-selected="resourceView === 'mindmap'"
                :class="{ 'is-active': resourceView === 'mindmap' }"
                :disabled="isMindmapLoading"
                :title="mindmapError || '查看本章知识结构'"
                @click="showMindmap"
              >
                <Network :size="16" />
                <span>{{ isMindmapLoading ? '读取中' : mindmapError ? '重试结构' : '知识结构' }}</span>
              </button>
              <button
                type="button"
                role="tab"
                :aria-selected="resourceView === 'ppt'"
                :class="{ 'is-active': resourceView === 'ppt' }"
                :disabled="isPptLoading"
                :title="pptError || '查看本章 PPT 辅助材料'"
                @click="showPpt"
              >
                <Presentation :size="16" />
                <span>{{ isPptLoading ? '读取中' : !pptResource && isResourceGenerating ? '生成中' : pptError ? '重试 PPT' : 'PPT 辅助' }}</span>
              </button>
              <button
                type="button"
                role="tab"
                :aria-selected="resourceView === 'video'"
                :class="{ 'is-active': resourceView === 'video' }"
                :title="videoError || '查看当前学习路径的视频讲解'"
                @click="showVideo"
              >
                <Video :size="16" />
                <span>{{ isVideoLoading ? '准备中' : videoError ? '重试视频' : '视频讲解' }}</span>
              </button>
            </div>
          </nav>

          <main class="lesson-main">
            <div class="resource-toolbar" aria-label="章节材料视图">
              <span class="resource-status"><span class="status-dot"></span>{{ resourceStatusLabel }}</span>
              <button
                v-if="activeResource"
                class="resource-download button button--quiet"
                type="button"
                :disabled="isResourceDownloading"
                :title="resourceDownloadError || `下载${activeResourceLabel}`"
                @click="downloadActiveResource"
              >
                <LoaderCircle v-if="isResourceDownloading" class="spin" :size="14" />
                <Download v-else :size="14" />
                {{ isResourceDownloading ? '下载中' : `下载${activeResourceLabel}` }}
              </button>
              <span v-if="resourceDownloadError" class="resource-download-error" role="status">{{ resourceDownloadError }}</span>
            </div>

            <ChapterCheck
              v-if="isChecking && activeNode"
              :key="`check-${activeNode.id}`"
              :path-id="learningPath.path_id"
              :node-id="activeNode.id"
              :session-id="activeNode.session_id || nodeDetail?.quiz_session_id || ''"
              :chapter-title="activeNode.title"
              :quiz-config="nodeDetail?.quiz_config || {}"
              @close="closeChapterCheck"
              @passed="handleChapterPassed"
              @session="handleQuizSession"
            />

            <template v-else>
              <div v-if="isResourceLoading" class="document-loading surface" aria-live="polite">
                <LoaderCircle class="spin" :size="25" />
                <strong>{{ resourceLoadingMessage }}</strong>
                <p>页面会在文档准备好后自动显示，不需要重复刷新。</p>
              </div>

              <div v-else-if="documentError" class="document-loading document-loading--error surface">
                <CircleAlert :size="25" />
                <strong>本章文档暂时不可用</strong>
                <p>{{ documentError }}</p>
                <button class="button button--quiet" type="button" @click="loadActiveNode">重试本章</button>
              </div>

              <MarkdownDocument
                v-else-if="resourceView === 'document'"
                wide
                :paginate="true"
                :show-title="false"
                :title="activeNode?.title"
                :content="documentContent"
                :tags="activeNode?.knowledge_tags || []"
                :chapter-number="activeNodeIndex + 1"
                annotatable
                :annotations="documentAnnotations"
                @create-note="createDocumentAnnotation"
                @update-note="updateDocumentAnnotation"
                @delete-note="deleteDocumentAnnotation"
                empty-message="本章文档尚未生成。"
              >
                <template #pagination-action="{ isLastPage }">
                  <button
                    v-if="isLastPage"
                    class="button button--primary document-pagination__action"
                    type="button"
                    :disabled="!documentContent || isResourceLoading"
                    @click="handlePrimaryAction"
                  >
                    {{ primaryActionLabel }}
                    <ArrowRight :size="15" />
                  </button>
                </template>
              </MarkdownDocument>

              <div v-else-if="resourceView === 'ppt' && isPptLoading" class="document-loading surface" aria-live="polite">
                <LoaderCircle class="spin" :size="25" />
                <strong>正在读取 PPT 辅助材料</strong>
                <p>主讲文档不受影响，材料读取完成后会自动显示。</p>
              </div>

              <div v-else-if="resourceView === 'ppt' && !pptResource" class="document-loading surface" aria-live="polite">
                <LoaderCircle v-if="isResourceGenerating" class="spin" :size="25" />
                <CircleAlert v-else :size="25" />
                <strong>{{ isResourceGenerating ? '正在生成 PPT 辅助材料' : 'PPT 辅助材料暂时不可用' }}</strong>
                <p>{{ isResourceGenerating ? '生成完成后会自动显示在这里。' : resourceGenerationError || '可以重新生成本章材料后再查看。' }}</p>
                <button v-if="!isResourceGenerating" class="button button--quiet" type="button" @click="loadActiveNode">重新生成</button>
              </div>

              <div v-else-if="resourceView === 'ppt' && pptError" class="document-loading document-loading--error surface">
                <CircleAlert :size="25" />
                <strong>PPT 辅助材料暂时无法打开</strong>
                <p>{{ pptError }}</p>
                <button class="button button--quiet" type="button" @click="showPpt">重新读取</button>
              </div>

              <PptEditorFrame
                v-else-if="resourceView === 'ppt' && pptResource"
                :content="pptContent"
                :title="activeNode?.title"
                :theme-id="pptResource?.ppt_theme_id || 'minimal-white'"
              />

              <div v-else-if="resourceView === 'mindmap' && isMindmapLoading" class="document-loading surface" aria-live="polite">
                <LoaderCircle class="spin" :size="25" />
                <strong>正在读取知识结构</strong>
                <p>主讲文档不受影响，结构材料读取完成后会自动显示。</p>
              </div>

              <MindmapPreview
                v-else-if="resourceView === 'mindmap'"
                :content="mindmapContent"
                :title="activeNode?.title"
              />

              <div v-else-if="resourceView === 'video' && isVideoLoading" class="document-loading surface" aria-live="polite">
                <LoaderCircle class="spin" :size="25" />
                <strong>正在准备课程视频讲解</strong>
                <p>首次生成会结合整条学习路径组织内容，请稍候。</p>
              </div>

              <div v-else-if="resourceView === 'video' && videoError" class="document-loading document-loading--error surface">
                <CircleAlert :size="25" />
                <strong>视频讲解暂时不可用</strong>
                <p>{{ videoError }}</p>
                <button class="button button--quiet" type="button" @click="showVideo">重新准备视频</button>
              </div>

              <VideoLessonFrame
                v-else-if="resourceView === 'video' && videoResource?.file_url"
                :src="videoResource.file_url"
                :title="videoResource.topic || learningPath.goal"
              />

              <VideoLessonFrame
                v-else-if="resourceView === 'external_video' && selectedExternalVideo?.embed_url"
                :src="selectedExternalVideo.embed_url"
                :title="selectedExternalVideo.title"
              />

              <section v-else-if="resourceView === 'external_video'" class="external-video-fallback surface">
                <!-- 有真封面就铺封面，没有就保留原来的图标视图。
                     不用 resourceCoverUrl()：它缺封面时会生成一张把标题画进图里的 SVG，
                     而标题在下面还会再显示一次，铺上去就成了两遍标题。 -->
                <img
                  v-if="externalVideoCover"
                  class="external-video-fallback__cover"
                  :src="externalVideoCover"
                  :alt="`${selectedExternalVideo?.title || '推荐视频'}封面`"
                  loading="lazy"
                  referrerpolicy="no-referrer"
                  @error="externalVideoCoverBroken = true"
                />
                <PlayCircle v-else :size="30" />
                <strong>{{ selectedExternalVideo?.title || '推荐视频' }}</strong>
                <p>{{ selectedExternalVideo?.description || '该来源不支持站内嵌入播放，可以跳转到原平台观看。' }}</p>
                <a v-if="selectedExternalVideo?.page_url" class="button button--primary" :href="selectedExternalVideo.page_url" target="_blank" rel="noreferrer">
                  打开原平台
                  <ArrowRight :size="15" />
                </a>
              </section>

              <footer v-if="resourceView !== 'document' && resourceView !== 'external_video'" class="chapter-footer surface">
                <button class="button button--quiet" type="button" :disabled="!previousNode" @click="previousNode && selectNode(previousNode.id)">
                  <ArrowLeft :size="15" />
                  上一章
                </button>
                <div class="chapter-footer__copy">
                  <strong>{{ chapterFooterTitle }}</strong>
                  <span>{{ documentContent ? `${estimatedReadMinutes} 分钟阅读 · ${activeNode?.knowledge_tags?.length || 0} 个知识点` : '正在准备学习材料' }}</span>
                </div>
                <RouterLink v-if="pathCompleted && !nextNode" class="button button--primary" to="/learning/advanced">
                  去做实战任务
                  <ArrowRight :size="15" />
                </RouterLink>
                <button v-else class="button button--primary" type="button" :disabled="!documentContent || isResourceLoading" @click="handlePrimaryAction">
                  {{ primaryActionLabel }}
                  <ArrowRight :size="15" />
                </button>
              </footer>
            </template>
          </main>

          <LearningAssistant
            v-if="activeNode"
            :key="activeNode.id"
            :path-id="learningPath.path_id"
            :node-id="activeNode.id"
            :chapter-title="activeNode.title"
            :chapter-content="documentContent"
            :knowledge-tags="activeNode.knowledge_tags || []"
            :resource-id="documentResource?.resource_id"
          />
        </div>
      </template>
    </template>

    <Teleport to="body">
      <Transition name="drawer-fade">
        <button
          v-if="navigationDrawer"
          class="navigation-drawer-backdrop"
          type="button"
          aria-label="关闭学习导航"
          @click="closeNavigationDrawer"
        ></button>
      </Transition>
      <Transition name="drawer-slide">
        <aside
          v-if="navigationDrawer"
          id="fundamentals-navigation-drawer"
          class="navigation-drawer"
          role="dialog"
          aria-modal="true"
          :aria-labelledby="`${navigationDrawer}-drawer-title`"
        >
          <header class="navigation-drawer__header">
            <div>
              <p class="eyebrow">{{ navigationDrawer === 'paths' ? '学习方向拆解' : learningPath?.goal }}</p>
              <h2 :id="`${navigationDrawer}-drawer-title`">{{ navigationDrawer === 'paths' ? '切换学习科目' : '选择章节' }}</h2>
              <p>{{ navigationDrawer === 'paths' ? `${pathCatalog.length} 个相关科目，选择后正文和助教会同步切换。` : `第 ${activeNodeIndex + 1} / ${learningPath?.nodes?.length || 0} 章` }}</p>
            </div>
            <button type="button" title="关闭" aria-label="关闭学习导航" @click="closeNavigationDrawer">
              <X :size="18" />
            </button>
          </header>
          <div class="navigation-drawer__body">
            <PathPicker
              v-if="navigationDrawer === 'paths'"
              compact
              :paths="pathCatalog"
              :active-path-id="learningPath?.path_id"
              :loading="isPathsLoading"
              :switching="isPathSwitching"
              @select="selectPathFromDrawer"
            />
            <ChapterRail
              v-else-if="learningPath"
              drawer
              :nodes="learningPath.nodes"
              :active-node-id="activeNodeId"
              @select="selectNodeFromDrawer"
            />
          </div>
        </aside>
      </Transition>
    </Teleport>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ArrowLeft, ArrowRight, BookOpenText, CircleAlert, Download, Eye, ListTree, LoaderCircle, LockKeyhole, Network, PlayCircle, Presentation, Route, Video, X } from 'lucide-vue-next'
import ChapterCheck from '@/features/fundamentals/ChapterCheck.vue'
import ChapterRail from '@/features/fundamentals/ChapterRail.vue'
import LearningAssistant from '@/features/fundamentals/LearningAssistant.vue'
import MarkdownDocument from '@/features/fundamentals/MarkdownDocument.vue'
import MindmapPreview from '@/features/fundamentals/MindmapPreview.vue'
import PathPicker from '@/features/fundamentals/PathPicker.vue'
import PptEditorFrame from '@/features/fundamentals/PptEditorFrame.vue'
import VideoLessonFrame from '@/features/fundamentals/VideoLessonFrame.vue'
import { fundamentalsApi } from '@/shared/api/fundamentalsApi'
import { readPortrait } from '@/shared/api/portraitApi'
import { applyWorkflowEvent, applyWorkflowProgress, finishWorkflow, resetWorkflow } from '@/entities/agent/agentWorkflowState'
import { resourceApi } from '@/shared/api/resourceApi'
import { asHttpUrl, generatedResourceCover, resourceCoverUrl } from '@/utils/resourceCover'

const route = useRoute()
const router = useRouter()
const isPageLoading = ref(true)
const pageError = ref('')
const resourceOverviewLoading = ref(false)
const externalVideoResources = ref([])
const externalVideoLoadedNodeIds = ref({})
const externalVideoLoadingNodeIds = ref({})
const selectedExternalVideo = ref(null)
// 外部视频的封面：只认服务端给的真封面（`cover_url`，B 站和博查的 images 节点都会填），
// 加载失败就退回图标视图。换一个视频要重置这个标记，否则上一个的失败会一直压着。
const externalVideoCoverBroken = ref(false)
watch(selectedExternalVideo, () => { externalVideoCoverBroken.value = false })
const externalVideoCover = computed(() =>
  externalVideoCoverBroken.value ? '' : asHttpUrl(selectedExternalVideo.value?.cover_url),
)
const previewNodeId = ref(null)
const learningPath = ref(null)
const pathCatalog = ref([])
const isPathsLoading = ref(true)
const isPathSwitching = ref(false)
const pathSwitchError = ref('')
const activeNodeId = ref(null)
const nodeDetail = ref(null)
const documentResource = ref(null)
const documentContent = ref('')
const documentAnnotations = ref([])
const pptResource = ref(null)
const pptContent = ref('')
const mindmapResource = ref(null)
const mindmapContent = ref('')
const videoResource = ref(null)
const resourceView = ref('document')
const isResourceLoading = ref(false)
const isResourceGenerating = ref(false)
const isMindmapLoading = ref(false)
const isPptLoading = ref(false)
const isVideoLoading = ref(false)
const navigationDrawer = ref(null)
const resourceLoadingMessage = ref('正在读取本章文档')
const documentError = ref('')
const mindmapError = ref('')
const pptError = ref('')
const videoError = ref('')
const resourceGenerationError = ref('')
const isResourceDownloading = ref(false)
const resourceDownloadError = ref('')
const isChecking = ref(false)
let resourceController = null
let nodeLoadVersion = 0
let openedAt = 0
let readReportPromise = null
let readingIntervalId = null
// 视频是「路径级」产物，生成要跑好几分钟。所以它是后台作业 + 轮询，而不用 nodeLoadVersion
// 守卫：切章节不该中断它（换章不影响同一条路径的视频）。只有切路径和离开页面才作废。
let videoPollToken = 0
let videoPollTimer = null
let videoPollWake = null
const VIDEO_POLL_INTERVAL_MS = 3000
const VIDEO_POLL_MAX_MS = 12 * 60 * 1000
// 作业在中途消失时，接口只会回一句"从没生成过"（idle/missing/stale）——后端重启会带走
// 内存里的作业，失败作业过了 10 分钟 TTL 也会被回收（path_video_jobs 的 _TERMINAL_TTL_SECONDS），
// 这时候失败原因早就没了。以前轮询循环里只 GET 不重发，碰上这种情况就一直空转到 12 分钟
// 上限才报"耗时过长"，学生看到的就是一直转圈。现在遇到这几种状态就重新发起一次生成，
// 但给一个重试预算：后端每次都立刻失败时不至于打成死循环。
const VIDEO_RESTART_STATUSES = ['idle', 'missing', 'stale']
const VIDEO_RESTART_LIMIT = 3
const VIDEO_RESTART_BACKOFF_MS = 5000

const activeNodeIndex = computed(() => learningPath.value?.nodes.findIndex((node) => node.id === activeNodeId.value) ?? -1)
const activeNode = computed(() => learningPath.value?.nodes[activeNodeIndex.value] || null)
const previewNode = computed(() => {
  const nodes = learningPath.value?.nodes || []
  const selected = nodes.find((node) => Number(node.id) === Number(previewNodeId.value) && node.status !== 'locked')
  return selected || chooseInitialNode(learningPath.value)
})
const hasActiveLesson = computed(() => Boolean(activeNodeId.value))
const resourceGroups = computed(() => {
  const nodes = learningPath.value?.nodes || []
  const videosByNodeId = new Map(nodes.map((node) => [Number(node.id), []]))

  externalVideoResources.value.forEach((video) => {
    const nodeId = Number(video.node_id)
    if (nodeId && videosByNodeId.has(nodeId)) videosByNodeId.get(nodeId).push(video)
  })

  return nodes
    .map((node, index) => {
      const boundResources = (node.resources || []).filter((resource) => resource?.resource_type !== 'external_video')
      const externalVideos = videosByNodeId.get(Number(node.id)) || []
      const resources = [...boundResources].sort(compareResourcesForLearning)
      externalVideos.forEach((video) => {
        if (!resources.some((resource) => Number(resource.resource_id || resource.id) === Number(video.resource_id))) {
          resources.push(video)
        }
      })
      return { node, index, resources }
    })
    .filter((group) => !previewNode.value || Number(group.node.id) === Number(previewNode.value.id))
    .filter((group) => group.resources.length || group.node.status !== 'locked')
})
const activeResource = computed(() => ({
  document: documentResource.value,
  ppt: pptResource.value,
  mindmap: mindmapResource.value,
  video: videoResource.value,
  external_video: selectedExternalVideo.value,
}[resourceView.value] || null))
const activeResourceLabel = computed(() => ({ document: '主讲文档', ppt: 'PPT', mindmap: '知识结构', video: '视频讲解', external_video: '推荐视频' }[resourceView.value] || '学习材料'))
const completedNodeCount = computed(() => learningPath.value?.nodes.filter((node) => node.status === 'completed').length || 0)
const previousNode = computed(() => {
  if (!learningPath.value || activeNodeIndex.value <= 0) return null
  return learningPath.value.nodes[activeNodeIndex.value - 1]
})
const nextNode = computed(() => {
  if (!learningPath.value || activeNodeIndex.value < 0) return null
  const candidate = learningPath.value.nodes[activeNodeIndex.value + 1]
  return candidate && candidate.status !== 'locked' ? candidate : null
})
const estimatedReadMinutes = computed(() => Math.max(3, Math.ceil(documentContent.value.replace(/\s/g, '').length / 420)))
const knowledgeContent = computed(() => extractDocumentSection(documentContent.value, ['知识点', '概念', '原理']) || '')
const exampleContent = computed(() => extractDocumentSection(documentContent.value, ['示例', '例子', '实践', 'example']) || '')
const resourceStatusLabel = computed(() => {
  if (isResourceLoading.value) return '正在准备本章'
  if (documentError.value) return '主讲文档异常'
  if (resourceGenerationError.value) return '部分辅助材料异常'
  if (isResourceGenerating.value) return '主讲文档已就绪，辅助材料生成中'
  if (documentContent.value) return '本章材料已同步'
  return '等待内容'
})
const primaryActionLabel = computed(() => {
  if (activeNode.value?.status === 'completed' && nextNode.value) return '进入下一章'
  if (activeNode.value?.status === 'completed') return '复习本章检查'
  return '完成阅读，进入检查'
})
// 整条路径都学完了：末章后面没有可进的章节是正常终态，得说清楚并指个去处，
// 否则用户停在最后一章只看到"本章已完成"，不知道是没有下一步还是加载坏了。
const pathCompleted = computed(() => {
  const nodes = learningPath.value?.nodes || []
  return nodes.length > 0 && nodes.every((node) => node.status === 'completed')
})
const chapterFooterTitle = computed(() => {
  if (activeNode.value?.status !== 'completed') return '读完正文，再用检查确认真正掌握'
  if (nextNode.value) return '本章已完成，下一章已经解锁'
  return pathCompleted.value ? '这条路径的节点都学完了' : '本章已完成'
})

function openNavigationDrawer(drawer) {
  if (!['paths', 'chapters'].includes(drawer)) return
  navigationDrawer.value = drawer
}

function closeNavigationDrawer() {
  navigationDrawer.value = null
}

function toggleNavigationDrawer(drawer) {
  navigationDrawer.value = navigationDrawer.value === drawer ? null : drawer
}

function handleGlobalKeydown(event) {
  if (event.key === 'Escape') closeNavigationDrawer()
}

function errorDetail(error, fallback) {
  return error.response?.data?.detail || error.message || fallback
}

function resourceTypeLabel(type) {
  return {
    document: '平台讲解文档',
    ppt: '平台视觉辅助',
    mindmap: '平台知识结构',
    video: '平台视频课件',
    external_video: '外部教学视频',
  }[type] || '学习资源'
}

function compareResourcesForLearning(left, right) {
  const order = { document: 0, ppt: 1, mindmap: 2, video: 3, external_video: 4 }
  return (order[left?.resource_type] ?? 99) - (order[right?.resource_type] ?? 99)
}

function resourceLabel(type) {
  return resourceTypeLabel(type).replace(/^平台|^外部/, '')
}

function nodeStatusLabel(status) {
  return { completed: '已完成', in_progress: '学习中', unlocked: '已解锁', locked: '待解锁' }[status] || '待学习'
}

function normalizedMatchText(value) {
  return String(value || '')
    .toLowerCase()
    .replace(/[\s·:：、，,。！？!?/\\_\-()（）\[\]]+/g, '')
    .replace(/(教学视频|视频教程|学习路径|基础学习|教程|教学)/g, '')
}

function videoMatchesNode(video, node) {
  const videoTopic = normalizedMatchText(video?.topic || video?.title)
  const nodeTopic = normalizedMatchText(node?.title || node?.topic)
  if (!videoTopic || !nodeTopic) return false
  return videoTopic === nodeTopic
    || (nodeTopic.length >= 4 && videoTopic.includes(nodeTopic))
    || (videoTopic.length >= 4 && nodeTopic.includes(videoTopic))
}

function parseExternalVideo(resource) {
  let payload = { ...(resource || {}) }
  if (typeof resource?.content === 'string') {
    try {
      const parsed = JSON.parse(resource.content)
      if (parsed && typeof parsed === 'object') payload = { ...parsed, ...payload }
    } catch {
      // 旧数据可能只保存了摘要文本，保留资源字段即可。
    }
  }
  return {
    ...resource,
    ...payload,
    resource_id: resource?.resource_id || resource?.id,
    title: payload.title || resource?.topic || '推荐视频',
    source_label: payload.source_label || payload.source || '外部教学视频',
    page_url: payload.page_url || resource?.file_url || resource?.url || '',
    embed_url: payload.embed_url || payload.preview_url || '',
  }
}

function videoMeta(video) {
  return [video?.author, video?.duration_text, video?.view_count_text].filter(Boolean).join(' · ')
}

async function loadNodeExternalVideos(node, force = false) {
  const pathId = Number(learningPath.value?.path_id)
  const nodeId = Number(node?.id)
  if (!pathId || !nodeId || node?.status === 'locked') return []
  if (!force && externalVideoLoadedNodeIds.value[nodeId]) {
    return externalVideoResources.value.filter((video) => Number(video.node_id) === nodeId)
  }
  if (externalVideoLoadingNodeIds.value[nodeId]) return []

  externalVideoLoadingNodeIds.value = { ...externalVideoLoadingNodeIds.value, [nodeId]: true }
  try {
    const videos = await fundamentalsApi.searchNodeExternalVideos(pathId, nodeId, 3)
    const normalized = (Array.isArray(videos) ? videos : []).map((video, index) => {
      const parsed = parseExternalVideo(video)
      return {
        ...parsed,
        node_id: nodeId,
        video_index: index,
        id: `node-${nodeId}-external-video-${index}`,
        video_meta: videoMeta(parsed),
      }
    })
    externalVideoResources.value = [
      ...externalVideoResources.value.filter((video) => Number(video.node_id) !== nodeId),
      ...normalized,
    ]
    externalVideoLoadedNodeIds.value = { ...externalVideoLoadedNodeIds.value, [nodeId]: true }
    return normalized
  } catch {
    // Recommendation failure must not prevent the chapter document from loading.
    externalVideoLoadedNodeIds.value = { ...externalVideoLoadedNodeIds.value, [nodeId]: true }
    return []
  } finally {
    const loading = { ...externalVideoLoadingNodeIds.value }
    delete loading[nodeId]
    externalVideoLoadingNodeIds.value = loading
  }
}

function handleCoverError(event, resource) {
  const image = event.currentTarget
  const fallback = generatedResourceCover(resource)
  if (!image || image.src === fallback) return
  image.onerror = null
  image.src = fallback
}

function openNodeForResource(node) {
  if (!node || node.status === 'locked') return
  void openFoundationResource(node, { resource_type: 'document' })
}

function openFoundationResource(node, resource) {
  if (!node || node.status === 'locked') return
  const resourceType = resource?.resource_type || 'document'
  const resourceId = resource?.resource_id || resource?.id || ''
  const query = {
    ...route.query,
    pathId: learningPath.value?.path_id,
    view: undefined,
    node: node.id,
    resource: resourceType,
    resourceId: undefined,
    videoIndex: undefined,
    ...(resourceType === 'external_video'
      ? { videoIndex: Number.isInteger(Number(resource?.video_index)) ? Number(resource.video_index) : 0 }
      : (resourceId ? { resourceId } : {})),
  }
  void router.push({ path: '/learning/fundamentals', query })
}

function openResourcePreview() {
  void router.push({
    path: '/learning/fundamentals',
    query: {
      ...route.query,
      view: 'resources',
      node: undefined,
      resource: undefined,
      resourceId: undefined,
      videoIndex: undefined,
    },
  })
}

function normalizeResourceId(resource) {
  return resource?.resource_id || resource?.id || null
}

function normalizeAnnotations(payload) {
  const data = payload?.data ?? payload
  const list = Array.isArray(data) ? data : data?.records || data?.list || data?.annotations || []
  return list.map((item) => ({
    ...item,
    id: item.id || item.annotation_id || item.annotationId,
    selected_text: item.selected_text || item.selectedText || '',
    note_text: item.note_text || item.note || '',
  })).filter((item) => item.id)
}

async function refreshDocumentAnnotations(resourceId = normalizeResourceId(documentResource.value)) {
  if (!resourceId) {
    documentAnnotations.value = []
    return
  }
  try {
    documentAnnotations.value = normalizeAnnotations(await resourceApi.listAnnotations(resourceId, 'generated'))
  } catch (error) {
    // 标注是辅助能力，读取失败不应让正文进入错误态。
    console.warn('[FundamentalsPage] load document annotations failed:', error)
    documentAnnotations.value = []
  }
}

async function createDocumentAnnotation(payload) {
  const resourceId = normalizeResourceId(documentResource.value)
  if (!resourceId || !payload?.selected_text) return
  try {
    await resourceApi.createAnnotation(resourceId, payload)
    await refreshDocumentAnnotations(resourceId)
  } catch (error) {
    console.warn('[FundamentalsPage] save document annotation failed:', error)
  }
}

async function updateDocumentAnnotation(annotationId, payload) {
  if (!annotationId) return
  try {
    await resourceApi.updateAnnotation(annotationId, payload)
    await refreshDocumentAnnotations()
  } catch (error) {
    console.warn('[FundamentalsPage] update document annotation failed:', error)
  }
}

async function deleteDocumentAnnotation(annotationId) {
  if (!annotationId) return
  try {
    await resourceApi.deleteAnnotation(annotationId)
    await refreshDocumentAnnotations()
  } catch (error) {
    console.warn('[FundamentalsPage] delete document annotation failed:', error)
  }
}

async function downloadActiveResource() {
  const resourceId = normalizeResourceId(activeResource.value)
  if (!resourceId || isResourceDownloading.value) return
  isResourceDownloading.value = true
  resourceDownloadError.value = ''
  try {
    const { blob, filename } = await resourceApi.download(resourceId)
    const objectUrl = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = objectUrl
    link.download = filename
    link.rel = 'noopener'
    document.body.appendChild(link)
    link.click()
    link.remove()
    window.setTimeout(() => URL.revokeObjectURL(objectUrl), 0)
  } catch (error) {
    resourceDownloadError.value = errorDetail(error, `${activeResourceLabel.value}下载失败，请稍后重试。`)
  } finally {
    isResourceDownloading.value = false
  }
}

function mindmapTreeToMarkdown(tree) {
  if (!tree || typeof tree !== 'object') return ''
  const lines = []
  const walk = (node, depth) => {
    const topic = String(node?.topic || node?.title || node?.name || '').trim()
    if (!topic) return
    lines.push(depth === 0 ? `# ${topic}` : `${'  '.repeat(depth - 1)}- ${topic}`)
    const children = Array.isArray(node.children) ? node.children : []
    children.forEach((child) => walk(child, depth + 1))
  }
  walk(tree, 0)
  return lines.join('\n')
}

function normalizeResourceContent(content, resourceType = 'document') {
  if (content && typeof content === 'object') {
    if (resourceType === 'mindmap') return content
    if (resourceType === 'ppt' && (Array.isArray(content.slides) || Array.isArray(content.pages) || Array.isArray(content.items))) return content
    if (Array.isArray(content.children)) return resourceType === 'mindmap' ? content : mindmapTreeToMarkdown(content)
    const nestedContent = content.markdown ?? content.content ?? content.document ?? content.body
    return nestedContent === undefined ? '' : normalizeResourceContent(nestedContent, resourceType)
  }
  if (typeof content !== 'string') return ''
  const trimmed = content.trim()
  if (!trimmed.startsWith('{')) return trimmed
  try {
    const parsed = JSON.parse(trimmed)
    if (resourceType === 'mindmap' || (resourceType === 'ppt' && (Array.isArray(parsed?.slides) || Array.isArray(parsed?.pages) || Array.isArray(parsed?.items)))) return parsed
    return normalizeResourceContent(parsed, resourceType) || trimmed
  } catch {
    return trimmed
  }
}

function findResource(resources, type) {
  return (resources || []).find((resource) => resource.resource_type === type) || null
}

const FUNDAMENTALS_RESOURCE_TYPES = ['document', 'ppt', 'mindmap']

function resourceSummaryFromEvent(event) {
  if (!event?.resource_type) return null
  return {
    ...event,
    id: event.resource_id || event.id || null,
    resource_id: event.resource_id || event.id || null,
    topic: event.topic || event.title || activeNode.value?.title || '',
    resource_type: event.resource_type,
  }
}

function assignResourceSummary(summary) {
  if (!summary?.resource_type) return
  if (summary.resource_type === 'document') documentResource.value = { ...documentResource.value, ...summary }
  if (summary.resource_type === 'ppt') pptResource.value = { ...pptResource.value, ...summary }
  if (summary.resource_type === 'mindmap') mindmapResource.value = { ...mindmapResource.value, ...summary }
}

function setResourceContent(type, resource, content) {
  if (type === 'document') {
    documentResource.value = { ...documentResource.value, ...resource }
    documentContent.value = normalizeResourceContent(content, 'document')
  } else if (type === 'ppt') {
    pptResource.value = { ...pptResource.value, ...resource }
    pptContent.value = normalizeResourceContent(content, 'ppt')
  } else if (type === 'mindmap') {
    mindmapResource.value = { ...mindmapResource.value, ...resource }
    mindmapContent.value = normalizeResourceContent(content, 'mindmap')
  }
}

function resourceContent(type) {
  if (type === 'document') return documentContent.value
  if (type === 'ppt') return pptContent.value
  if (type === 'mindmap') return mindmapContent.value
  return ''
}

function setResourceError(type, message) {
  if (type === 'document') documentError.value = message
  if (type === 'ppt') pptError.value = message
  if (type === 'mindmap') mindmapError.value = message
  if (type === 'video') videoError.value = message
}

async function hydrateResource(type, summary, loadVersion) {
  if (!summary || loadVersion !== nodeLoadVersion) return false
  assignResourceSummary(summary)
  const suppliedContent = summary.content
  if (suppliedContent !== undefined && suppliedContent !== null && suppliedContent !== '') {
    setResourceContent(type, summary, suppliedContent)
    return Boolean(resourceContent(type))
  }
  const resourceId = normalizeResourceId(summary)
  if (!resourceId || resourceContent(type)) return Boolean(resourceContent(type))
  try {
    const resource = await fundamentalsApi.getResource(resourceId)
    if (loadVersion !== nodeLoadVersion) return false
    setResourceContent(type, resource || summary, resource?.content)
    if (!resourceContent(type)) throw new Error(type === 'document' ? '本章文档内容为空' : '辅助材料内容为空')
    return true
  } catch (error) {
    if (loadVersion === nodeLoadVersion) setResourceError(type, errorDetail(error, '资源内容读取失败。'))
    return false
  }
}

function progressSummary(path, progress = null) {
  const nodes = Array.isArray(path?.nodes) ? path.nodes : []
  const rows = Array.isArray(progress?.nodes) ? progress.nodes : []
  const completedNodes = Number(progress?.completed_nodes ?? progress?.completed ?? nodes.filter((node) => node.status === 'completed').length)
  const totalNodes = Number(progress?.total_nodes ?? nodes.length)
  const currentRow = rows.find((row) => ['in_progress', 'unlocked'].includes(row.status))
  const currentNodeId = progress?.current_node_id ?? currentRow?.node_id ?? nodes.find((node) => ['in_progress', 'unlocked'].includes(node.status))?.id ?? null
  const currentNode = nodes.find((node) => Number(node.id) === Number(currentNodeId))
  const rawPercentage = progress?.percentage ?? path?.progress
  const fallbackPercentage = totalNodes ? completedNodes / totalNodes : 0
  const numericPercentage = Number(rawPercentage)
  const percentage = Number.isFinite(numericPercentage)
    ? (numericPercentage <= 1 ? numericPercentage * 100 : numericPercentage)
    : fallbackPercentage * 100
  return {
    percentage: Math.min(100, Math.max(0, Math.round(percentage))),
    completed_nodes: completedNodes,
    total_nodes: totalNodes,
    current_node: progress?.current_node || currentNode?.title || currentNode?.topic || '',
    current_node_id: currentNodeId,
  }
}

const SUBJECT_TERM_GROUPS = [
  { terms: ['python'], weight: 8 },
  { terms: ['rag'], weight: 8 },
  { terms: ['大模型', '语言模型'], weight: 5 },
  { terms: ['提示词', '提示工程', 'prompt'], weight: 5 },
  { terms: ['文档'], weight: 3 },
  { terms: ['向量', '嵌入', '语义'], weight: 4 },
  { terms: ['检索'], weight: 4 },
  { terms: ['知识库'], weight: 4 },
  { terms: ['架构'], weight: 3 },
  { terms: ['性能', '优化', '评估', '部署'], weight: 2 },
  { terms: ['编程', '数据处理'], weight: 3 },
  { terms: ['应用', '开发'], weight: 2 },
]

function normalizeSubject(value) {
  return String(value || '')
    .toLowerCase()
    .replace(/[\s·:：、，,。！？!?/\\_\-]+/g, '')
}

function subjectMatchScore(source, target) {
  const sourceText = normalizeSubject(source)
  const targetText = normalizeSubject(target)
  if (!sourceText || !targetText) return 0
  if (sourceText === targetText) return 1000
  let score = sourceText.includes(targetText) || targetText.includes(sourceText) ? 30 : 0
  SUBJECT_TERM_GROUPS.forEach(({ terms, weight }) => {
    const sourceHasTerm = terms.some((term) => sourceText.includes(normalizeSubject(term)))
    const targetHasTerm = terms.some((term) => targetText.includes(normalizeSubject(term)))
    if (sourceHasTerm && targetHasTerm) score += weight
  })
  const sourceBigrams = new Set(Array.from(sourceText).map((_, index) => sourceText.slice(index, index + 2)).filter((item) => item.length === 2))
  const sharedBigrams = Array.from(new Set(Array.from(targetText).map((_, index) => targetText.slice(index, index + 2)).filter((item) => item.length === 2)))
    .filter((item) => sourceBigrams.has(item)).length
  return score + Math.min(sharedBigrams, 8)
}

function selectRelatedPaths(values, relatedSubjects) {
  const selected = []
  const remaining = [...values]
  relatedSubjects.forEach((subject) => {
    let bestIndex = -1
    let bestScore = 0
    remaining.forEach((path, index) => {
      const score = subjectMatchScore(subject, path.subject)
      if (score > bestScore) {
        bestScore = score
        bestIndex = index
      }
    })
    // Do not present an unrelated historical path as a current-direction course.
    if (bestIndex >= 0 && bestScore >= 4) {
      selected.push({ ...remaining[bestIndex], related_subject: subject })
      remaining.splice(bestIndex, 1)
    }
  })
  return selected
}

function mergePathCatalog(pathList, statsPaths, currentPath = null, relatedSubjects = []) {
  const byId = new Map()
  ;(pathList || []).forEach((path) => {
    if (!path?.path_id) return
    byId.set(Number(path.path_id), { ...path, path_id: Number(path.path_id) })
  })
  ;(statsPaths || []).forEach((stat) => {
    if (!stat?.path_id) return
    const pathId = Number(stat.path_id)
    const existing = byId.get(pathId) || { path_id: pathId, subject: stat.subject || stat.goal || '' }
    byId.set(pathId, {
      ...existing,
      subject: existing.subject || stat.subject || stat.goal || '',
      difficulty: existing.difficulty || stat.difficulty,
      node_count: existing.node_count || stat.progress?.total_nodes || stat.total_nodes || 0,
      progress: stat.progress || existing.progress,
    })
  })
  if (currentPath?.path_id) {
    const pathId = Number(currentPath.path_id)
    const existing = byId.get(pathId) || { path_id: pathId }
    byId.set(pathId, {
      ...existing,
      subject: existing.subject || currentPath.goal || '',
      node_count: existing.node_count || currentPath.nodes?.length || 0,
      progress: {
        ...existing.progress,
        ...progressSummary(currentPath),
      },
    })
  }
  const values = [...byId.values()]
  if (relatedSubjects.length) {
    const subjects = relatedSubjects.map((subject) => String(subject || '').trim()).filter(Boolean)
    const relatedPaths = selectRelatedPaths(values, subjects)
    if (relatedPaths.length) return relatedPaths
  }
  return values.sort((left, right) => Number(right.path_id) - Number(left.path_id))
}

function chooseInitialNode(path, requestedNodeId = null) {
  if (!path || !Array.isArray(path.nodes)) return null
  const requestedNode = Number(requestedNodeId)
  if (requestedNode > 0) {
    const requested = path.nodes.find((node) => Number(node.id) === requestedNode && node.status !== 'locked')
    if (requested) return requested
  }
  return path.nodes.find((node) => Number(node.id) === Number(path.current_node_id))
    || path.nodes.find((node) => node.status === 'in_progress' || node.status === 'unlocked')
    || [...path.nodes].reverse().find((node) => node.status === 'completed')
    || path.nodes[0]
    || null
}

async function loadPathWorkspace(pathId) {
  const selected = await fundamentalsApi.getCurrentPath(pathId)
  if (selected && Number(selected.path_id) === Number(pathId) && Array.isArray(selected.nodes)) return selected

  // Older deployments may not support the path_id query parameter yet. Build
  // the same workspace shape from the protected path and progress endpoints.
  const [detail, progress] = await Promise.all([
    fundamentalsApi.getPath(pathId),
    fundamentalsApi.getPathProgress(pathId).catch(() => null),
  ])
  if (!detail) return null
  const progressRows = Array.isArray(progress?.nodes) ? progress.nodes : []
  const nodes = (detail.nodes || []).map((node, index) => {
    const id = node.node_id ?? node.id
    const row = progressRows.find((item) => Number(item.node_id) === Number(id))
    return {
      id,
      title: node.topic || node.title || `第 ${index + 1} 节`,
      summary: node.description || '',
      knowledge_tags: node.knowledge_tags || [],
      resource_types: node.resource_types || [],
      teaching_spec: node.teaching_spec || null,
      status: row?.status || (index === 0 ? 'unlocked' : 'locked'),
      session_id: row?.session_id || null,
      resources: [],
    }
  })
  const currentNodeId = progress?.current_node_id
    || nodes.find((node) => node.status === 'in_progress' || node.status === 'unlocked')?.id
    || null
  const completedNodes = nodes.filter((node) => node.status === 'completed').length
  return {
    path_id: detail.path_id,
    goal: detail.subject,
    stage: `${completedNodes}/${nodes.length}`,
    progress: progress?.percentage ?? Math.round(completedNodes / Math.max(nodes.length, 1) * 100),
    current_node_id: currentNodeId,
    nodes,
    next_action: currentNodeId ? { target_id: currentNodeId, type: 'read', label: '开始学习' } : null,
    diagnosis: null,
  }
}

function syncPathCatalog(path) {
  if (!path?.path_id) return
  const pathId = Number(path.path_id)
  const summary = {
    path_id: pathId,
    subject: path.goal || '',
    node_count: path.nodes?.length || 0,
    progress: progressSummary(path),
  }
  const index = pathCatalog.value.findIndex((item) => Number(item.path_id) === pathId)
  if (index < 0) pathCatalog.value = [...pathCatalog.value, summary]
  else pathCatalog.value[index] = { ...pathCatalog.value[index], ...summary }
}

async function loadPage() {
  isPageLoading.value = true
  pageError.value = ''
  pathSwitchError.value = ''
  isPathsLoading.value = true
  resourceOverviewLoading.value = true
  try {
    const [pathListResult, pathStatsResult, currentResult, portraitResult] = await Promise.allSettled([
      fundamentalsApi.listPaths(),
      fundamentalsApi.getPathStats(),
      fundamentalsApi.getCurrentPath(),
      readPortrait(),
    ])
    const pathList = pathListResult.status === 'fulfilled' && Array.isArray(pathListResult.value) ? pathListResult.value : []
    const pathStats = pathStatsResult.status === 'fulfilled' ? pathStatsResult.value : null
    let current = currentResult.status === 'fulfilled' ? currentResult.value : null
    const portrait = portraitResult.status === 'fulfilled' ? portraitResult.value : null
    externalVideoResources.value = []
    externalVideoLoadedNodeIds.value = {}
    externalVideoLoadingNodeIds.value = {}
    const relatedSubjects = Array.isArray(portrait?.traits?.learning_direction_subjects)
      ? portrait.traits.learning_direction_subjects
      : []
    pathCatalog.value = mergePathCatalog(pathList, pathStats?.paths, current, relatedSubjects)

    const requestedPathId = Number(route.query.pathId)
    const listedPathIds = new Set(pathCatalog.value.map((path) => Number(path.path_id)))
    const selectedPathId = requestedPathId > 0 && listedPathIds.has(requestedPathId)
      ? requestedPathId
      : (current?.path_id && listedPathIds.has(Number(current.path_id))
          ? current.path_id
          : pathCatalog.value[0]?.path_id)
    if (selectedPathId && (!current || Number(current.path_id) !== Number(selectedPathId))) {
      current = await loadPathWorkspace(selectedPathId)
    }
    if (!current || !Array.isArray(current.nodes) || !current.nodes.length) {
      learningPath.value = null
      activeNodeId.value = null
      return
    }
    learningPath.value = current
    syncPathCatalog(current)
    const requestedNodeId = Number(route.query.node)
    const isResourcePreview = route.query.view === 'resources'
    const initialNode = isResourcePreview ? null : chooseInitialNode(current, requestedNodeId)
    const previewNode = initialNode || chooseInitialNode(current)
    previewNodeId.value = previewNode?.id || null
    if (!initialNode && previewNode) void loadNodeExternalVideos(previewNode)
    if (selectedPathId && (Number(route.query.pathId) !== Number(selectedPathId)
      || (initialNode && Number(route.query.node) !== Number(initialNode.id)))) {
      await router.replace({
        query: {
          ...route.query,
          pathId: selectedPathId,
          ...(initialNode ? { node: initialNode.id } : { node: undefined, resource: undefined, resourceId: undefined, videoIndex: undefined }),
        },
      })
    }
    if (initialNode) {
      isPageLoading.value = false
      await selectNode(initialNode.id, false)
    }
  } catch (error) {
    pageError.value = errorDetail(error, '无法读取当前学习路径，请稍后重试。')
  } finally {
    isPathsLoading.value = false
    resourceOverviewLoading.value = false
    isPageLoading.value = false
  }
}

async function selectPath(pathId) {
  const nextPathId = Number(pathId)
  if (!nextPathId || isPathSwitching.value || Number(learningPath.value?.path_id) === nextPathId) return
  isPathSwitching.value = true
  pathSwitchError.value = ''
  await reportReadDuration(true)
  resourceController?.abort()
  // 视频是路径级的：换了路径，上一轮的轮询结果不能再往新路径上写。
  invalidateVideoPoll()
  try {
    const selected = await loadPathWorkspace(nextPathId)
    if (!selected || !Array.isArray(selected.nodes) || !selected.nodes.length) throw new Error('这条路径暂时没有可学习的章节')
    learningPath.value = selected
    videoResource.value = null
    videoError.value = ''
    activeNodeId.value = null
    selectedExternalVideo.value = null
    previewNodeId.value = chooseInitialNode(selected)?.id || null
    externalVideoResources.value = []
    externalVideoLoadedNodeIds.value = {}
    externalVideoLoadingNodeIds.value = {}
    syncPathCatalog(selected)
    await router.replace({ query: { ...route.query, pathId: nextPathId, node: undefined, resource: undefined, resourceId: undefined, videoIndex: undefined } })
  } catch (error) {
    pathSwitchError.value = errorDetail(error, '无法打开这条学习路径，请稍后重试。')
  } finally {
    isPathSwitching.value = false
  }
}

async function selectPathFromDrawer(pathId) {
  closeNavigationDrawer()
  await selectPath(pathId)
}

async function selectNodeFromDrawer(nodeId) {
  closeNavigationDrawer()
  await selectNode(nodeId)
}

async function selectPreviewNode(nodeId) {
  const node = learningPath.value?.nodes.find((item) => Number(item.id) === Number(nodeId))
  if (!node || node.status === 'locked') return
  previewNodeId.value = node.id
  await loadNodeExternalVideos(node)
}

async function selectNode(nodeId, updateUrl = true) {
  const node = learningPath.value?.nodes.find((item) => item.id === nodeId)
  if (!node || node.status === 'locked') return
  const selectedResourceType = updateUrl
    ? 'document'
    : (['document', 'ppt', 'mindmap', 'external_video'].includes(String(route.query.resource))
        ? String(route.query.resource)
        : 'document')
  // Captured before activeNodeId is reassigned below, otherwise it always matches.
  const isSameLoadedNode = activeNodeId.value != null
    && Number(activeNodeId.value) === Number(nodeId)
    && Boolean(documentContent.value)
  const requestedResourceType = selectedResourceType
  const requestedResourceReady = requestedResourceType === 'document'
    || (requestedResourceType === 'ppt' && Boolean(pptContent.value))
    || (requestedResourceType === 'mindmap' && Boolean(mindmapContent.value))
    || (requestedResourceType === 'external_video' && Boolean(selectedExternalVideo.value))
  if (activeNodeId.value && activeNodeId.value !== nodeId) await reportReadDuration(true)
  activeNodeId.value = nodeId
  resourceView.value = selectedResourceType
  selectedExternalVideo.value = null
  resourceDownloadError.value = ''
  isChecking.value = false
  if (updateUrl) await router.replace({ query: { ...route.query, node: nodeId, resource: 'document', resourceId: undefined, videoIndex: undefined } })
  // Re-selecting the chapter already on screen only needs the view state reset above.
  // Posting generate-resources again would re-run the idempotent backend path for
  // nothing. documentContent is cleared at the start of every loadActiveNode and only
  // refilled on a successful read, so it means "this chapter is already usable".
  // Keeping documentError out of the condition leaves the retry path reachable.
  if (isSameLoadedNode && requestedResourceReady && !isResourceLoading.value && !documentError.value) return
  await loadActiveNode()
}

async function loadActiveNode() {
  if (!learningPath.value || !activeNode.value) return
  const loadVersion = ++nodeLoadVersion
  resourceController?.abort()
  resourceController = new AbortController()
  isResourceLoading.value = true
  isResourceGenerating.value = true
  resourceLoadingMessage.value = '正在读取本章文档'
  documentError.value = ''
  mindmapError.value = ''
  pptError.value = ''
  videoError.value = ''
  resourceGenerationError.value = ''
  resourceDownloadError.value = ''
  nodeDetail.value = null
  documentResource.value = null
  documentContent.value = ''
  documentAnnotations.value = []
  selectedExternalVideo.value = null
  pptResource.value = null
  pptContent.value = ''
  mindmapResource.value = null
  mindmapContent.value = ''
  openedAt = 0
  const nodeVideosPromise = loadNodeExternalVideos(activeNode.value)

  let resolveDocumentReady
  let documentReadyMarked = false
  let workflowStarted = false
  const documentReady = new Promise((resolve) => { resolveDocumentReady = resolve })
  const markDocumentReady = () => {
    if (documentReadyMarked) return
    documentReadyMarked = true
    isResourceLoading.value = false
    resolveDocumentReady(true)
  }

  try {
    const detail = await fundamentalsApi.getNode(learningPath.value.path_id, activeNode.value.id)
    if (loadVersion !== nodeLoadVersion) return
    nodeDetail.value = detail
    const resources = detail?.progress?.resources || activeNode.value.resources || []
    const documentSummary = findResource(resources, 'document')
    const pptSummary = findResource(resources, 'ppt')
    const mindmapSummary = findResource(resources, 'mindmap')
    const requestedResourceType = ['ppt', 'mindmap', 'external_video'].includes(String(route.query.resource))
      ? String(route.query.resource)
      : 'document'
    resourceView.value = requestedResourceType
    assignResourceSummary(pptSummary)
    assignResourceSummary(mindmapSummary)

    if (requestedResourceType === 'external_video') {
      const resourceId = Number(route.query.resourceId)
      const nodeVideos = await nodeVideosPromise
      const videoIndex = Number(route.query.videoIndex)
      const candidate = nodeVideos[Number.isInteger(videoIndex) && videoIndex >= 0 ? videoIndex : 0]
      if (candidate) selectedExternalVideo.value = parseExternalVideo(candidate)
      if (resourceId) {
        try {
          selectedExternalVideo.value = parseExternalVideo(await resourceApi.get(resourceId))
        } catch (error) {
          videoError.value = errorDetail(error, '推荐视频暂时无法打开。')
        }
      }
      if (!selectedExternalVideo.value && !videoError.value) videoError.value = '未找到这条推荐视频。'
      isResourceLoading.value = false
      isResourceGenerating.value = false
      return
    }

    if (documentSummary) {
      resourceLoadingMessage.value = '正在读取本章文档'
      if (await hydrateResource('document', documentSummary, loadVersion)) {
        void refreshDocumentAnnotations()
        markDocumentReady()
      }
    }

    if (requestedResourceType === 'ppt' && pptSummary) {
      await hydrateResource('ppt', pptSummary, loadVersion)
    } else if (requestedResourceType === 'mindmap' && mindmapSummary) {
      await hydrateResource('mindmap', mindmapSummary, loadVersion)
    }

    // Always pass through the idempotent path-node resource endpoint.  The
    // backend decides whether to reuse a validated binding or generate a
    // missing/stale chapter; the page must not infer that from a summary row.
    resourceLoadingMessage.value = documentContent.value
      ? '主讲文档已就绪，正在准备辅助材料'
      : documentSummary ? '正在校验本章资源' : '正在调用资源生成服务'
    const requestedTypes = [...new Set([
      ...FUNDAMENTALS_RESOURCE_TYPES,
      ...(detail?.resource_types || activeNode.value.resource_types || []),
    ])]
    resetWorkflow({
      title: `${activeNode.value.title || '当前章节'} · 资源准备`,
      pathId: learningPath.value.path_id,
      nodeId: activeNode.value.id,
      resourceTypes: requestedTypes,
    })
    workflowStarted = true
    const streamPromise = fundamentalsApi.generateResources(
      learningPath.value.path_id,
      activeNode.value.id,
      (event) => {
        if (loadVersion !== nodeLoadVersion) return
        if (event?.type === 'agent_event') applyWorkflowEvent(event)
        else applyWorkflowProgress(event)
        if (event?.type === 'status') {
          resourceLoadingMessage.value = event.msg || event.message || resourceLoadingMessage.value
        }
        if (event?.type === 'resource') {
          const summary = resourceSummaryFromEvent(event)
          if (!summary) return
          assignResourceSummary(summary)
          const type = summary.resource_type
          resourceLoadingMessage.value = type === 'document'
            ? '主讲文档已准备，正在读取正文'
            : `${type === 'ppt' ? 'PPT' : '知识结构'} 已准备，正在同步`
          void hydrateResource(type, summary, loadVersion).then((loaded) => {
            if (type === 'document' && loaded) {
              void refreshDocumentAnnotations()
              markDocumentReady()
            }
          })
        }
        if (event?.type === 'error') {
          const message = event.detail || event.message || '本章资源生成失败'
          if (!documentContent.value) documentError.value = message
          else resourceGenerationError.value = message
        }
      },
      resourceController.signal,
      requestedTypes,
    )

    // The stream stays alive while PPT and mind-map resources are generated.
    // Only the primary document gates the reading view.
    void streamPromise
      .then(async () => {
        if (loadVersion !== nodeLoadVersion) return
        if (workflowStarted) finishWorkflow(false)
        isResourceGenerating.value = false
        const refreshed = await fundamentalsApi.getNode(learningPath.value.path_id, activeNode.value.id).catch(() => null)
        if (!documentContent.value && !documentError.value) {
          const refreshedDocument = findResource(refreshed?.progress?.resources, 'document')
          if (refreshedDocument && await hydrateResource('document', refreshedDocument, loadVersion)) {
            void refreshDocumentAnnotations()
            markDocumentReady()
          }
        }
        // The resource stream can finish before its final PPT event reaches the
        // browser. Re-read the persisted node bindings so a completed PPT is
        // never hidden just because that one stream event was missed.
        if (!pptContent.value) {
          const refreshedPpt = findResource(refreshed?.progress?.resources, 'ppt')
          if (refreshedPpt) await hydrateResource('ppt', refreshedPpt, loadVersion)
        }
        if (!documentContent.value && !documentError.value) documentError.value = '资源生成完成，但没有找到本章主讲文档'
        if (!documentContent.value) isResourceLoading.value = false
      })
      .catch((error) => {
        if (error?.name === 'AbortError' || loadVersion !== nodeLoadVersion) return
        if (workflowStarted) finishWorkflow(true)
        isResourceGenerating.value = false
        if (!documentContent.value) {
          documentError.value = errorDetail(error, '本章学习材料加载失败。')
          isResourceLoading.value = false
        } else {
          resourceGenerationError.value = errorDetail(error, '辅助材料生成失败，主讲文档仍可继续学习。')
        }
      })

    if (!documentReadyMarked) await Promise.race([documentReady, streamPromise])
    if (loadVersion !== nodeLoadVersion) return
    if (documentContent.value && document.visibilityState === 'visible') openedAt = Date.now()
  } catch (error) {
    if (error.name !== 'AbortError' && loadVersion === nodeLoadVersion) {
      if (workflowStarted) finishWorkflow(true)
      documentError.value = errorDetail(error, '本章学习材料加载失败。')
      isResourceLoading.value = false
      isResourceGenerating.value = false
    }
  } finally {
    if (loadVersion === nodeLoadVersion && documentContent.value) isResourceLoading.value = false
  }
}

async function showMindmap() {
  if (!mindmapResource.value || isMindmapLoading.value) return
  await reportReadDuration(true)
  resourceView.value = 'mindmap'
  resourceDownloadError.value = ''
  openedAt = 0
  if (mindmapContent.value) return
  isMindmapLoading.value = true
  mindmapError.value = ''
  try {
    const loaded = await hydrateResource('mindmap', mindmapResource.value, nodeLoadVersion)
    if (!loaded) throw new Error(mindmapError.value || '知识结构内容为空')
  } catch (error) {
    mindmapError.value = errorDetail(error, '知识结构加载失败。')
    resourceView.value = 'document'
    if (document.visibilityState === 'visible') openedAt = Date.now()
  } finally {
    isMindmapLoading.value = false
  }
}

async function showPpt() {
  if (isPptLoading.value) return
  resourceView.value = 'ppt'
  resourceDownloadError.value = ''
  openedAt = 0
  if (!pptResource.value) return
  await reportReadDuration(true)
  if (pptContent.value) return
  isPptLoading.value = true
  pptError.value = ''
  try {
    const loaded = await hydrateResource('ppt', pptResource.value, nodeLoadVersion)
    if (!loaded) throw new Error(pptError.value || 'PPT 内容为空')
  } catch (error) {
    pptError.value = errorDetail(error, 'PPT 辅助材料加载失败。')
  } finally {
    isPptLoading.value = false
  }
}

// 只清定时器不够：正在等待的那一轮轮询会永远挂着，isVideoLoading 也就永远不落。
// 所以同时把它唤醒，让循环靠 token 自己退出。
function stopVideoPoll() {
  if (videoPollTimer) {
    window.clearTimeout(videoPollTimer)
    videoPollTimer = null
  }
  if (videoPollWake) {
    videoPollWake()
    videoPollWake = null
  }
}

function waitNextVideoPoll(ms) {
  return new Promise((resolve) => {
    videoPollWake = resolve
    videoPollTimer = window.setTimeout(() => {
      videoPollTimer = null
      videoPollWake = null
      resolve()
    }, ms)
  })
}

function invalidateVideoPoll() {
  videoPollToken += 1
  stopVideoPoll()
  // isVideoLoading 属于被作废的那一轮轮询，必须在这里清掉：
  // pollPathVideo 的 finally 里那句复位带着 token 守卫（token 不等就直接 return），
  // 所以作废之后它永远不会执行 —— 而 showVideo() 开头就是
  // `if (isVideoLoading.value) { 只切视图; return }`。
  // 不清的后果是：换过一次路径之后，学生再点「视频讲解」既不发起请求也不报错，
  // 界面上一直转圈，后端日志一行都没有。
  isVideoLoading.value = false
}

// 后端把生成甩到后台作业里，POST 只回状态，产物要轮询 GET 取。
// 这样每个请求都是短的，不会再出现「前端 180 秒超时、后端还在跑」。
async function pollPathVideo() {
  const token = ++videoPollToken
  const pathId = learningPath.value?.path_id
  if (!pathId) return
  const deadline = Date.now() + VIDEO_POLL_MAX_MS
  isVideoLoading.value = true
  videoError.value = ''
  stopVideoPoll()
  let restarts = 0
  try {
    let video = await fundamentalsApi.getPathVideo(pathId)
    if (video?.status === 'failed') throw new Error(video.error || '视频生成失败，请稍后重试。')
    if (!video?.file_url && video?.status !== 'generating') {
      video = await fundamentalsApi.generatePathVideo(pathId)
      restarts += 1
      if (video?.status === 'failed') throw new Error(video.error || '视频生成失败，请稍后重试。')
    }
    while (!video?.file_url) {
      if (token !== videoPollToken) return
      if (Date.now() > deadline) throw new Error('视频生成耗时过长，请稍后重试。')
      if (VIDEO_RESTART_STATUSES.includes(video?.status)) {
        if (restarts >= VIDEO_RESTART_LIMIT) throw new Error('视频生成任务中断了，请重新点击视频讲解。')
        await waitNextVideoPoll(VIDEO_RESTART_BACKOFF_MS)
        if (token !== videoPollToken) return
        restarts += 1
        video = await fundamentalsApi.generatePathVideo(pathId)
        if (video?.status === 'failed') throw new Error(video.error || '视频生成失败，请稍后重试。')
        continue
      }
      await waitNextVideoPoll(VIDEO_POLL_INTERVAL_MS)
      if (token !== videoPollToken) return
      video = await fundamentalsApi.getPathVideo(pathId)
      if (video?.status === 'failed') throw new Error(video.error || '视频生成失败，请稍后重试。')
    }
    if (token !== videoPollToken) return
    videoResource.value = {
      ...video,
      resource_id: video.html_id || video.resource_id || video.id || null,
      resource_type: 'html',
      topic: video.topic || `${learningPath.value.goal} 视频讲解`,
    }
  } catch (error) {
    if (token !== videoPollToken) return
    videoError.value = errorDetail(error, '视频讲解准备失败，请稍后重试。')
  } finally {
    if (token === videoPollToken) isVideoLoading.value = false
  }
}

async function showVideo() {
  if (!learningPath.value) return
  if (isVideoLoading.value) {
    // 生成期间再次点击（可能刚切到别的视图）只切回视频页，不重开一轮轮询。
    resourceView.value = 'video'
    return
  }
  await reportReadDuration(true)
  resourceView.value = 'video'
  resourceDownloadError.value = ''
  openedAt = 0
  if (videoResource.value?.file_url) return
  await pollPathVideo()
}

function showDocument() {
  if (resourceView.value === 'document') return
  resourceView.value = 'document'
  resourceDownloadError.value = ''
  if (documentContent.value && document.visibilityState === 'visible' && !isChecking.value) openedAt = Date.now()
}

async function reportReadDuration(force = false) {
  const resourceId = documentResource.value?.resource_id
  if (readReportPromise) return readReportPromise
  if (!resourceId || !openedAt) return
  if (!force && (document.visibilityState !== 'visible' || resourceView.value !== 'document' || isChecking.value)) return
  const seconds = Math.max(1, Math.round((Date.now() - openedAt) / 1000))
  openedAt = 0
  readReportPromise = fundamentalsApi.markResourceRead(resourceId, seconds).catch(() => null)
  await readReportPromise
  readReportPromise = null
  if (documentResource.value?.resource_id === resourceId && resourceView.value === 'document' && !isChecking.value && document.visibilityState === 'visible') openedAt = Date.now()
}

async function openChapterCheck() {
  await reportReadDuration(true)
  resourceView.value = 'document'
  openedAt = 0

  // 阅读完成后进入独立的学习复盘页，题目测试和费曼反讲共用同一节点上下文。
  const pathId = learningPath.value?.path_id
  const nodeId = activeNode.value?.id
  if (pathId && nodeId) {
    await router.push({ path: '/learning/foundation-test', query: { pathId, node: nodeId, autoStart: '1' } })
    return
  }

  // 保留异常数据下的页内检查兜底，正常路径不会走到这里。
  isChecking.value = true
}

function closeChapterCheck() {
  isChecking.value = false
  if (documentContent.value && document.visibilityState === 'visible') openedAt = Date.now()
}

// Same reason as FoundationTestPage: a freshly generated session_id stays inside
// ChapterCheck, so reopening the panel would fall back to the stale prop and
// generate another set of questions.
function handleQuizSession(sessionId) {
  if (!sessionId) return
  if (activeNode.value) activeNode.value.session_id = sessionId
  if (nodeDetail.value) nodeDetail.value.quiz_session_id = sessionId
}

async function handlePrimaryAction() {
  if (activeNode.value?.status === 'completed' && nextNode.value) {
    await selectNode(nextNode.value.id)
    return
  }
  await openChapterCheck()
}

async function handleChapterPassed() {
  const finishedIndex = activeNodeIndex.value
  isChecking.value = false
  try {
    const currentPathId = learningPath.value?.path_id
    const refreshed = currentPathId ? await fundamentalsApi.getCurrentPath(currentPathId) : null
    if (refreshed?.nodes) {
      learningPath.value = refreshed
      syncPathCatalog(refreshed)
    }
    const nextNode = learningPath.value?.nodes[finishedIndex + 1]
    if (nextNode && nextNode.status !== 'locked') await selectNode(nextNode.id)
  } catch (error) {
    pageError.value = errorDetail(error, '章节已完成，但刷新下一章时失败。')
  }
}

function handleVisibilityChange() {
  if (document.visibilityState === 'hidden') {
    void reportReadDuration(true)
  } else if (documentContent.value && resourceView.value === 'document' && !isChecking.value) {
    openedAt = Date.now()
  }
}

watch(
  () => [route.query.pathId, route.query.node, route.query.resource, route.query.resourceId, route.query.videoIndex].join('|'),
  async () => {
    if (!learningPath.value) return
    const nodeId = Number(route.query.node)
    if (!nodeId) {
      await reportReadDuration(true)
      resourceController?.abort()
      activeNodeId.value = null
      selectedExternalVideo.value = null
      return
    }
    if (Number(activeNodeId.value) === nodeId
      && route.query.resource === resourceView.value
      && (resourceView.value !== 'external_video' || selectedExternalVideo.value?.video_index === Number(route.query.videoIndex))) return
    await selectNode(nodeId, false)
  },
)

onMounted(() => {
  document.addEventListener('visibilitychange', handleVisibilityChange)
  document.addEventListener('keydown', handleGlobalKeydown)
  readingIntervalId = window.setInterval(() => void reportReadDuration(), 30000)
  loadPage()
})
onBeforeUnmount(() => {
  resourceController?.abort()
  invalidateVideoPoll()
  document.removeEventListener('visibilitychange', handleVisibilityChange)
  document.removeEventListener('keydown', handleGlobalKeydown)
  if (readingIntervalId) window.clearInterval(readingIntervalId)
  void reportReadDuration(true)
})
</script>

<style scoped>
.fundamentals-page { display: grid; min-width: 0; height: 100%; min-height: 0; grid-template-rows: auto minmax(0, 1fr); overflow: hidden; }
.foundation-library { min-width: 0; min-height: 0; overflow: auto; padding: 6px 2px 26px; }
.foundation-library__layout { position: relative; display: block; }
.foundation-library__main { min-width: 0; }
.foundation-library__header { display: flex; align-items: flex-end; justify-content: space-between; gap: 28px; margin-bottom: 22px; padding-bottom: 18px; border-bottom: 1px solid #dfe5df; }
.foundation-library__header h1 { margin: 0; color: #1e3c34; font-size: clamp(28px, 3vw, 40px); line-height: 1.15; }
.foundation-library__header p:last-child { margin: 9px 0 0; color: var(--muted); font-size: 13px; }
.foundation-library__start-hint { display: flex; align-items: center; gap: 10px; margin: 0 0 18px; padding: 10px 13px; border-left: 3px solid var(--accent-deep); background: #f1f6eb; color: var(--accent-deep); }
.foundation-library__start-hint > svg { flex: 0 0 auto; }
.foundation-library__start-hint > span { display: grid; min-width: 0; gap: 2px; }
.foundation-library__start-hint strong { font-size: 12px; }
.foundation-library__start-hint small { color: var(--muted); font-size: 11px; line-height: 1.45; }
.foundation-library__header .path-progress { flex: 0 0 220px; }
.foundation-library__state { display: grid; min-height: 270px; place-items: center; align-content: center; gap: 9px; padding: 32px; color: var(--accent-deep); text-align: center; }
.foundation-library__state strong { color: var(--ink); font-size: 16px; }
.foundation-library__state p { max-width: 420px; margin: 0; color: var(--muted); font-size: 12px; line-height: 1.7; }
.foundation-library__state .button { display: inline-flex; align-items: center; gap: 7px; margin-top: 7px; }
.foundation-library__body { display: grid; gap: 22px; }
.resource-group { min-width: 0; }
.resource-group__header { display: flex; align-items: center; justify-content: space-between; gap: 14px; margin-bottom: 10px; }
.resource-group__header > div { display: flex; align-items: center; gap: 12px; min-width: 0; }
.resource-group__header > div > div { min-width: 0; }
.resource-group__index { display: grid; width: 38px; height: 38px; place-items: center; border: 1px solid #d8e4cc; border-radius: 11px; background: #edf5e5; color: var(--accent-deep); font-size: 11px; font-weight: 800; }
.resource-group__header .eyebrow { margin-bottom: 3px; }
.resource-group__header h2 { margin: 0; overflow: hidden; color: var(--ink); font-size: 17px; text-overflow: ellipsis; white-space: nowrap; }
.resource-group__status { flex: 0 0 auto; color: var(--muted); font-size: 11px; }
.resource-card-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 14px; }
.resource-card { position: relative; display: grid; min-width: 0; min-height: 276px; grid-template-rows: 132px minmax(0, 1fr); overflow: hidden; padding: 0; border: 1px solid #dfe6da; text-align: left; transition: border-color .18s ease, transform .18s ease, box-shadow .18s ease; }
.resource-card--primary { border-color: #b9ce99; box-shadow: 0 8px 20px rgba(63, 91, 49, .08); }
.resource-card:hover { border-color: #abc28f; box-shadow: 0 10px 22px rgba(45, 70, 40, .1); transform: translateY(-2px); }
.resource-card:focus-visible { outline: 2px solid var(--accent-deep); outline-offset: 2px; }
.resource-card__cover { position: relative; display: block; min-width: 0; overflow: hidden; background: #183d34; }
.resource-card__cover img { display: block; width: 100%; height: 100%; object-fit: cover; transition: transform .35s ease; }
.resource-card:hover .resource-card__cover img { transform: scale(1.04); }
.resource-card__cover-overlay { position: absolute; inset: 0; display: flex; align-items: flex-end; justify-content: space-between; padding: 13px 14px; background: rgba(15, 31, 25, .55); color: #fff; }
.resource-card__type { overflow: hidden; max-width: 78%; font-size: 10px; font-weight: 800; letter-spacing: .1em; text-overflow: ellipsis; white-space: nowrap; }
.resource-card__content { display: grid; min-width: 0; align-content: start; gap: 7px; padding: 15px 42px 15px 16px; }
.resource-card__guide { display: inline-flex; align-items: center; gap: 5px; color: var(--accent-deep); font-size: 10px; font-weight: 800; }
.resource-card__guide svg { flex: 0 0 auto; }
.resource-card__content strong { overflow: hidden; color: var(--ink); font-size: 13px; line-height: 1.45; text-overflow: ellipsis; white-space: nowrap; }
.resource-card__content small { color: var(--muted); font-size: 10px; }
.resource-card__description { display: -webkit-box; overflow: hidden; color: var(--muted); font-size: 11px; line-height: 1.5; -webkit-box-orient: vertical; -webkit-line-clamp: 2; }
.resource-card__arrow { position: absolute; right: 14px; bottom: 16px; color: #9baa96; transition: color .18s ease, transform .18s ease; }
.resource-card:hover .resource-card__arrow { color: var(--accent-deep); transform: translateX(2px); }
.resource-group__empty { display: flex; width: 100%; min-height: 54px; align-items: center; gap: 8px; padding: 0 14px; border: 1px dashed #cbd8c5; color: var(--muted); font-size: 12px; text-align: left; }
.resource-group__empty:hover { border-color: #9dbb8d; background: #fbfdf9; color: var(--accent-deep); }
.resource-group__empty span { flex: 1; }
.external-video-fallback { display: grid; min-height: 360px; place-items: center; align-content: center; gap: 10px; padding: 40px; color: #a45b45; text-align: center; }
.external-video-fallback__cover { width: min(100%, 620px); aspect-ratio: 16 / 9; margin-bottom: 4px; border: 1px solid var(--line); border-radius: 14px; background: var(--paper); object-fit: cover; box-shadow: 0 10px 24px rgb(32 40 36 / 8%); }
.external-video-fallback strong { color: var(--ink); font-size: 17px; }
.external-video-fallback p { max-width: 480px; margin: 0; color: var(--muted); font-size: 12px; line-height: 1.7; }
.external-video-fallback .button { display: inline-flex; align-items: center; gap: 7px; margin-top: 5px; }
.lesson-context { display: grid; grid-template-columns: auto minmax(0, 1fr) auto; align-items: start; gap: 22px; margin-bottom: 12px; padding: 0 0 16px; border-bottom: 1px solid var(--line); }
.lesson-context__copy { min-width: 0; }
.lesson-context__actions { display: flex; min-width: 0; flex: 0 0 auto; align-items: flex-end; gap: 14px; }
.return-resource-button { align-self: start; gap: 6px; min-height: 36px; white-space: nowrap; }
.lesson-context__copy .eyebrow { margin-bottom: 6px; }
.lesson-context h1 { max-width: 920px; margin: 0; color: var(--ink); font-size: clamp(22px, 2.1vw, 30px); line-height: 1.25; }
.lesson-context__copy > p:last-child { max-width: 880px; margin: 7px 0 0; color: var(--muted); font-size: 12px; line-height: 1.6; }
.lesson-context__copy > p:last-child span { margin-left: 9px; }
.lesson-context__copy > p:last-child span::before { content: "·"; margin-right: 10px; color: #a5aea7; }
.path-progress { display: grid; flex: 0 0 180px; gap: 7px; }
.path-progress > div:first-child { display: flex; align-items: baseline; justify-content: space-between; color: var(--muted); font-size: 10px; }
.path-progress strong { color: var(--accent-deep); font-size: 18px; }
.path-progress small { color: var(--muted); font-size: 10px; text-align: right; }
.learning-layout { --workspace-panel-height: min(760px, calc(100dvh - 190px)); display: grid; min-height: 0; height: var(--workspace-panel-height); grid-template-columns: 52px minmax(0, 1fr) minmax(280px, 310px); align-items: stretch; gap: 14px; overflow: hidden; }
.path-switch-error { display: flex; min-height: 42px; align-items: center; gap: 9px; margin: 0 0 12px; padding: 9px 12px; border: 1px solid #ead6c8; border-radius: 6px; background: #fff9f4; color: #965536; font-size: 11px; }
.path-switch-error > span { min-width: 0; flex: 1; }
.path-switch-error .button { min-height: 28px; padding: 0 9px; font-size: 10px; }
.workspace-rail { align-self: start; display: grid; gap: 7px; min-width: 0; padding: 5px; border: 1px solid var(--line); border-radius: 7px; background: var(--paper); }
.workspace-rail button { position: relative; display: grid; width: 40px; min-height: 57px; place-items: center; align-content: center; gap: 4px; padding: 5px 2px; border: 0; border-radius: 5px; background: transparent; color: var(--muted); transition: background .16s ease, color .16s ease; }
.workspace-rail button:hover,
.workspace-rail button.is-active { background: #e8efdf; color: var(--accent-deep); }
.workspace-rail button:focus-visible { outline: 2px solid var(--accent-deep); outline-offset: 2px; }
.workspace-rail button > span { font-size: 9px; font-weight: 800; }
.workspace-rail button > small { position: absolute; top: 4px; right: 4px; display: grid; min-width: 14px; height: 14px; place-items: center; padding: 0 3px; border-radius: 7px; background: var(--soft); color: var(--accent-deep); font-size: 8px; font-weight: 800; }
.workspace-rail__divider { width: 28px; height: 1px; margin: 3px auto; background: var(--line); }
.lesson-main { display: grid; min-width: 0; min-height: 0; grid-template-rows: auto minmax(0, 1fr) auto; gap: 12px; overflow: hidden; }
.lesson-main > .lesson-document, .lesson-main > .document-loading, .lesson-main > .ppt-editor-frame, .lesson-main > .mindmap-preview, .lesson-main > .video-lesson-frame, .lesson-main > .chapter-check { min-height: 0; height: 100%; overflow: auto; }
.learning-layout :deep(.learning-assistant) { position: static; min-height: 0; height: 100%; max-height: none; }
.resource-toolbar { display: flex; min-height: 34px; align-items: center; gap: 10px; }
.resource-tabs { display: flex; align-items: center; gap: 4px; }
.resource-tabs button { display: inline-flex; min-height: 34px; align-items: center; gap: 7px; padding: 0 10px; border: 0; border-radius: 4px; background: transparent; color: var(--muted); font-size: 11px; }
.resource-tabs button:hover:not(:disabled) { background: #e9eeea; color: var(--ink); }
.resource-tabs button.is-active { background: #e4ecdd; color: var(--accent-deep); font-weight: 800; }
.resource-tabs button:disabled { cursor: wait; opacity: .55; }
.resource-tabs--rail { display: grid; width: 100%; gap: 5px; }
.resource-tabs--rail button { display: grid; width: 40px; min-height: 57px; place-items: center; align-content: center; gap: 4px; margin: 0 auto; padding: 5px 2px; font-size: 9px; line-height: 1.25; }
.resource-tabs--rail button span { max-width: 36px; text-align: center; }
.resource-tabs--rail button.is-active { background: #e4ecdd; }
.resource-status { display: inline-flex; align-items: center; gap: 6px; margin-right: auto; color: var(--muted); font-size: 10px; }
.resource-status .status-dot { width: 6px; height: 6px; }
.resource-download { min-height: 30px; gap: 6px; padding: 0 10px; font-size: 10px; }
.resource-download-error { max-width: 220px; overflow: hidden; color: #a66442; font-size: 10px; text-overflow: ellipsis; white-space: nowrap; }
.chapter-footer { display: grid; grid-template-columns: auto minmax(0, 1fr) auto; align-items: center; gap: 18px; padding: 15px 17px; }
.chapter-footer__copy { display: grid; min-width: 0; gap: 4px; text-align: center; }
.chapter-footer__copy strong { font-size: 11px; }
.chapter-footer__copy span { color: var(--muted); font-size: 9px; }
.chapter-footer .button { gap: 7px; white-space: nowrap; }
.chapter-footer .button:disabled { cursor: not-allowed; opacity: .45; }
.navigation-drawer-backdrop { position: fixed; inset: 64px 0 0 112px; z-index: 29; border: 0; background: rgba(12, 28, 22, .28); cursor: default; }
.navigation-drawer { position: fixed; top: 64px; bottom: 0; left: 112px; z-index: 30; display: flex; width: min(420px, calc(100vw - 112px)); flex-direction: column; border-right: 1px solid var(--line); background: var(--paper); color: var(--ink); box-shadow: 18px 0 44px rgba(8, 28, 20, .18); }
.navigation-drawer__header { display: flex; flex: 0 0 auto; align-items: flex-start; justify-content: space-between; gap: 16px; padding: 24px 22px 20px; border-bottom: 1px solid var(--line); }
.navigation-drawer__header .eyebrow { max-width: 310px; margin-bottom: 7px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.navigation-drawer__header h2 { margin: 0; font-size: 21px; line-height: 1.3; }
.navigation-drawer__header p:last-child { margin: 8px 0 0; color: var(--muted); font-size: 11px; line-height: 1.6; }
.navigation-drawer__header > button { display: grid; width: 34px; height: 34px; flex: 0 0 34px; place-items: center; border: 1px solid var(--line); border-radius: 5px; background: var(--paper); color: var(--muted); }
.navigation-drawer__header > button:hover { background: #edf2ed; color: var(--ink); }
.navigation-drawer__header > button:focus-visible { outline: 2px solid var(--accent-deep); outline-offset: 2px; }
.navigation-drawer__body { min-height: 0; flex: 1 1 auto; overflow-y: auto; padding: 20px 18px 32px; scrollbar-width: thin; }
.drawer-fade-enter-active,
.drawer-fade-leave-active { transition: opacity .18s ease; }
.drawer-fade-enter-from,
.drawer-fade-leave-to { opacity: 0; }
.drawer-slide-enter-active,
.drawer-slide-leave-active { transition: transform .25s cubic-bezier(.16, 1, .3, 1), opacity .18s ease; }
.drawer-slide-enter-from,
.drawer-slide-leave-to { opacity: 0; transform: translateX(-24px); }
.page-state, .document-loading { display: grid; place-items: center; align-content: center; gap: 10px; color: var(--accent-deep); text-align: center; }
.page-state { min-height: clamp(420px, calc(100vh - 260px), 520px); padding: 42px; }
.document-loading { min-height: clamp(420px, calc(100vh - 380px), 680px); padding: 36px; }
.page-state strong, .document-loading strong { color: var(--ink); font-size: 16px; }
.page-state p, .document-loading p { max-width: 440px; margin: 0; color: var(--muted); font-size: 12px; line-height: 1.7; }
.page-state .button, .document-loading .button { margin-top: 8px; }
.page-state--error, .document-loading--error { color: #a66442; }
.spin { animation: spin .8s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
@media (max-width: 1120px) {
  .resource-card-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .learning-layout { grid-template-columns: 52px minmax(0, 1fr); }
  .learning-layout > :last-child { display: none; }
}
@media (max-width: 860px) {
  .navigation-drawer-backdrop { left: 0; }
  .navigation-drawer { left: 0; width: min(420px, 100vw); }
}
@media (max-width: 680px) {
  .foundation-library { padding: 0 0 22px; }
  .foundation-library__layout { display: grid; grid-template-columns: 1fr; gap: 18px; }
  .foundation-library__header { align-items: stretch; flex-direction: column; gap: 15px; margin-bottom: 17px; padding-bottom: 14px; }
  .foundation-library__header .path-progress { width: 100%; min-width: 0; }
  .resource-card-grid { grid-template-columns: 1fr; }
  .resource-group__header h2 { max-width: 230px; }
  .resource-card { min-height: 252px; grid-template-rows: 120px minmax(0, 1fr); }
  .lesson-context { grid-template-columns: 1fr; gap: 16px; }
  .lesson-context__actions { width: 100%; align-items: stretch; gap: 9px; }
  .return-resource-button { align-self: flex-start; }
  .path-progress { flex-basis: auto; width: min(360px, 100%); }
  .path-progress small { text-align: left; }
  .learning-layout { height: auto; grid-template-columns: 1fr; overflow: auto; }
  .learning-layout > :last-child { display: none; }
  .workspace-rail { position: static; display: flex; gap: 7px; padding: 0 0 10px; border: 0; border-bottom: 1px solid var(--line); border-radius: 0; background: transparent; }
  .workspace-rail button { display: flex; width: auto; min-width: 72px; min-height: 38px; gap: 6px; padding: 0 10px; }
  .workspace-rail button > small { position: static; min-width: 16px; }
  .workspace-rail__divider { width: 1px; height: 24px; margin: 0 2px; }
  .resource-tabs--rail { display: flex; width: auto; gap: 7px; }
  .resource-tabs--rail button { display: inline-flex; width: auto; min-width: 82px; min-height: 38px; flex-direction: row; gap: 6px; margin: 0; padding: 0 10px; font-size: 11px; }
  .resource-tabs--rail button span { max-width: none; }
  .lesson-context__copy > p:last-child { display: grid; gap: 5px; }
  .lesson-context__copy > p:last-child span { margin-left: 0; }
  .lesson-context__copy > p:last-child span::before { display: none; }
  .resource-toolbar { min-height: 14px; }
  .chapter-footer { grid-template-columns: 1fr 1fr; }
  .chapter-footer__copy { grid-column: 1 / -1; grid-row: 1; }
  .chapter-footer .button { width: 100%; }
  .navigation-drawer__header { padding: 20px 18px 17px; }
  .navigation-drawer__body { padding: 17px 14px 28px; }
}

:global(.app-content:has(.fundamentals-page)) { background: #f7f7f7; }
:global(.page-container:has(.fundamentals-page)) { width: 100%; max-width: none; height: 100%; box-sizing: border-box; margin: 0; padding: 12px 42px 20px; overflow: hidden; background: #f7f7f7; }
:global(.app-content:has(.fundamentals-page) .app-header) { border-bottom-color: #e8e8e8; background: #f7f7f7; }
.fundamentals-page .surface { border-color: rgba(63, 91, 49, .28); border-radius: 16px; box-shadow: 0 8px 24px rgba(45, 40, 92, .07); }
.lesson-context { min-height: 0; margin-bottom: 10px; padding: 0 0 10px; border: 0; border-bottom: 1px solid #dfe5df; border-radius: 0; background: transparent; }
.lesson-context__copy .lesson-eyebrow { color: var(--muted); font-size: 12px; letter-spacing: .14em; }
.lesson-context h1 { color: #1e3c34; font-size: clamp(21px, 2.2vw, 28px); }
.lesson-context__copy > p:last-child { margin-top: 5px; line-height: 1.45; }
.path-progress { min-width: 210px; gap: 5px; padding: 8px 12px; border: 1px solid #dbe5d1; border-radius: 12px; background: #f4f8ed; }
.workspace-rail { top: 82px; border-radius: 16px; padding: 7px; background: #fff; box-shadow: 0 8px 20px rgba(45, 40, 92, .05); }
.workspace-rail button, .resource-tabs--rail button { border-radius: 11px; }
.workspace-rail button.is-active, .resource-tabs--rail button.is-active { background: #e8efdf; color: var(--accent-deep); }
.resource-tabs button, .document-pagination button, .icon-button { border-radius: 11px; }
.lesson-main > .lesson-document, .lesson-main > .document-loading, .lesson-main > .chapter-footer { border-radius: 16px; }
.fundamentals-page .button { border-radius: 12px; }
.fundamentals-page .button--primary { border-color: #c4df3d; background: #b6d837; color: #1e3c34; box-shadow: 0 6px 14px rgba(63, 91, 49, .14); }
.fundamentals-page .button--primary:hover { border-color: #a9ca27; background: #a9ca27; color: #1e3c34; }
.fundamentals-page .button--quiet { border-color: #dce3dc; background: #fff; color: #3f5b31; }
.fundamentals-page .button--quiet:hover { border-color: #b9c9b2; background: #f1f6eb; }
@media (max-width: 680px) { :global(.page-container:has(.fundamentals-page)) { padding: 10px 14px 14px; }.lesson-context { align-items: flex-start; flex-direction: column; padding: 0 0 8px; }.lesson-context__copy > p:last-child { display: none; }.path-progress { width: 100%; min-width: 0; }.resource-toolbar { display: none; } }
</style>
