<template>
  <div class="advanced-page">
    <!-- 这一页不给视觉标题。以前用的是 PageTitle（大标题 + ADVANCED PRACTICE 眉标 + 描述），
         整套约 100px；而"你在进阶学习"这件事，上方面包屑和左侧导航已经各说了一遍。
         全屏工作区里这三行等于从编辑器身上割走一块，所以只留读屏能读到的那份。 -->
    <h1 class="sr-only">应用实践 · 进阶学习</h1>

    <!-- 这两个全屏分支只在**还没有任务**时出现。以前是 `v-if="loading"`，于是点
         「重新同步」也会命中 —— 而 CodeWorkspace 就住在下面的 <template v-else> 里，
         它会被整个卸载，学生正在写的文件跟着一起没。刷新不该把工作区拆掉。 -->
    <section v-if="loading && !task" class="surface surface-pad state-panel" aria-live="polite"><LoaderCircle class="spin" :size="20" /><div><strong>正在整理实践任务</strong><p>系统正在读取你的学习目标、路径进度和能力诊断。</p></div></section>
    <section v-else-if="errorMessage && !task" class="surface surface-pad state-panel state-panel--error"><CircleAlert :size="20" /><div><strong>暂时无法读取实践任务</strong><p>{{ errorMessage }}</p></div><button class="button button--quiet" type="button" @click="loadTask({ refresh: true })">重试</button></section>
    <!-- 这里的分支只在**连一条路径都没有**时才走到：完成 0 个基础节点也有工作区可用
         （见 loadTask 末尾那个兜底），所以以前那个"先完成基础学习，再进入实践"的封锁页
         已经不存在了 —— 它拦的是入口，而学生可能只是想拿自己的项目来问教练。
         剩下这个状态是路径缺失，文案得说清缺的是**路径**，不是"你还不够格"。 -->
    <section v-else-if="!task" class="surface surface-pad empty-panel"><p class="eyebrow">进阶学习</p><h2>{{ learningStatus === 'path_required' ? '先建立学习路径，再进入实践' : '还没有可开始的实践任务' }}</h2><p v-if="learningStatus === 'path_required'">进阶学习要挂在一条学习路径上 —— 先完成基础学习，系统会为你生成路径和节点。</p><p v-else>这条路径上还没有能用作依据的节点。稍后再同步一次，或先完成一个基础节点。</p><RouterLink class="button button--primary" to="/learning/fundamentals">继续基础学习</RouterLink></section>

    <template v-else>
      <!-- 整页只有这一行页头：任务信息 + 两个动作。任务情境、推荐依据、节点/里程碑这些
           要么属于学习概览，要么在对话里已经说过 —— 搬进 IDE 只是把旧页面的篇幅也搬过来，
           占掉真正干活的地方。 -->
      <div class="advanced-top">
        <TaskBar
          :task="task"
          :task-source="taskSource"
          :options="optionalTasks"
          @select="selectTaskById"
          @regenerate="loadTask({ refresh: true })"
        />
        <button class="button button--quiet advanced-top__sync" type="button" :disabled="loading" @click="loadTask({ refresh: true })">
          <RefreshCw :size="14" :class="{ spin: loading }" />{{ loading ? '同步中' : '重新同步' }}
        </button>
      </div>

      <!-- 已经有任务时刷新失败，错误挂在这里，而不是把整页换成错误页 ——
           换页会把下面学生正在写的工作区一起卸载掉。 -->
      <p v-if="syncError" class="advanced-sync-error" role="status">
        <CircleAlert :size="14" />{{ syncError }}
      </p>

      <div ref="layoutRef" class="ide-layout" :class="{ 'is-dragging': isDragging }" :style="layoutStyle">
        <CodeWorkspace ref="workspaceRef" class="ide-workspace" :draft-key="workspaceDraftKey" />

        <!-- 分隔条：拖动改两侧宽度，双击回到一半。键盘也能调（左右方向键）。
             有了它就不必把 50/50 写死 —— 写代码时把编辑区拉大，讨论时把对话拉大。 -->
        <div
          class="ide-splitter"
          role="separator"
          aria-orientation="vertical"
          aria-label="拖动调整代码区和对话区的宽度"
          :aria-valuenow="Math.round(splitPercent)"
          :aria-valuemin="SPLIT_MIN"
          :aria-valuemax="SPLIT_MAX"
          tabindex="0"
          @pointerdown="startSplitDrag"
          @keydown="onSplitKey"
          @dblclick="resetSplit"
        >
          <span class="ide-splitter__grip" aria-hidden="true"></span>
        </div>

        <div class="ide-practice">
          <PracticeDialogue
            v-if="hasWorkspace && !sessionEnded"
            :key="task.id"
            compact
            :path-id="selectedWorkspace.pathId"
            :node-id="selectedWorkspace.nodeId"
            :task="task"
            :chapter-content="chapterContent"
            :resource-id="resourceId"
            :workspace-reader="readWorkspaceSnapshot"
            @end="endPractice"
          />
          <section v-else-if="!hasWorkspace" class="surface surface-pad state-panel state-panel--error"><CircleAlert :size="20" /><div><strong>实践任务缺少关联节点</strong><p>请重新同步任务后再开始巩固。</p></div><button class="button button--quiet" type="button" @click="loadTask({ refresh: true })">重新同步</button></section>

          <section v-else class="surface surface-pad session-ended">
            <span class="session-ended__mark">✓</span>
            <p class="eyebrow">本次巩固已暂存</p>
            <h2>对话过程已经保存</h2>
            <p>这不是提交成果。会话还在，可以随时接着往下想。</p>
            <div v-if="summaryLoading" class="session-summary session-summary--loading" role="status"><LoaderCircle class="spin" :size="14" /><span>正在根据这次的过程记录整理小结…</span></div>
            <div v-else-if="summaryText" class="session-summary"><p class="eyebrow">这次的过程小结</p><div class="session-summary__body" v-html="renderMarkdown(summaryText)"></div></div>
            <div class="session-ended__actions"><button class="button button--primary" type="button" @click="sessionEnded = false">继续本次巩固</button></div>
          </section>
        </div>
      </div>
    </template>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { CircleAlert, LoaderCircle, RefreshCw } from 'lucide-vue-next'
import { useRoute } from 'vue-router'
import PracticeDialogue from '@/features/advanced/PracticeDialogue.vue'
import TaskBar from '@/features/advanced/TaskBar.vue'
import CodeWorkspace from '@/features/advanced/workspace/CodeWorkspace.vue'
import { draftKeyFor } from '@/shared/storage/workspaceDraftStore'
import { clearCurrentPage, setCurrentPage } from '@/entities/learning/currentPageContext'
import { advancedLearningApi } from '@/shared/api/advancedLearningApi'
import { fundamentalsApi } from '@/shared/api/fundamentalsApi'
import { renderMarkdown } from '@/shared/lib/markdown'

const route = useRoute()
const loading = ref(true)
const errorMessage = ref('')
// 已经有任务时的刷新失败。和 errorMessage 分开，是因为两者后果不同：
// 前者只挂一条提示，后者要把整页换成错误页（那会卸载工作区）。
const syncError = ref('')
const learningStatus = ref('')
// agent = 智能体生成的；pending = 还在后台生成，展示的是临时入口；
// fallback = 智能体这次失败了，展示的仍是临时入口（下次进页面会自动重试）
const taskSource = ref('')
const task = ref(null)
const tasks = ref([])
const sessionEnded = ref(false)

// 代码区和对话区的宽度比（左侧占的百分比）。两块内容轻重会来回变 —— 写代码时要编辑区，
// 讨论时要对话 —— 所以不给固定比例，交给用户拖，选择按比例记住。
const SPLIT_STORAGE_KEY = 'learnmate_advanced_split'
const SPLIT_MIN = 25
const SPLIT_MAX = 75
const SPLIT_STEP = 2
const SPLIT_STEP_LARGE = 8
const layoutRef = ref(null)
const splitPercent = ref(readStoredSplit())
const isDragging = ref(false)
const summaryText = ref('')
const summaryLoading = ref(false)
let summaryController = null
const chapterContent = ref('')
const resourceId = ref(null)
const workspaceRef = ref(null)
const unwrap = (response) => response?.data?.data ?? response?.data ?? null

function getTaskWorkspace(value) {
  const workspace = value?.workspace || {}
  return {
    pathId: workspace.path_id ?? workspace.pathId ?? value?.path_id ?? value?.pathId ?? null,
    nodeId: workspace.node_id ?? workspace.nodeId ?? value?.node_id ?? value?.nodeId ?? null,
  }
}

const selectedWorkspace = computed(() => getTaskWorkspace(task.value))
const hasWorkspace = computed(() => selectedWorkspace.value.pathId !== null && selectedWorkspace.value.nodeId !== null)

// ── 「无任务」：学生不挑任务，带着自己的项目来，聊什么由他说了算 ──────────────
//
// 这是**一个显式的模式，不是"任务字段为空"**。教练那边是按任务办事的（会问"要交付什么"
// "验收标准是什么"），任务块凭空消失它只会换个说法接着问，或者自己编一个任务出来 ——
// 缺席在提示词里是个不可靠的信号。所以这份任务带 `mode: 'free'`，服务端照着它明说
// "这次没有任务"（见 practice_service.FREE_TASK_MODE）。
const FREE_TASK_ID = '__free__'

// 锚点：这次自由对话挂在哪个 (路径, 节点) 上。会话账本按 (user, task_key, path, node)
// 分区，所以必须有个真实节点 —— 但它只是个分区键，不出现在学生眼前的任何地方，
// 选当前这个即可。
//
// **它必须能"定下来"。** 锚点要是永远从 tasks.value 现算，一次轮询就能把它掀掉：
// 状态不是 ready 时 tasks 会被整个清空（见 loadTask），于是 `__free__` 查不到、
// 学生几秒内就被踢回推荐任务，连工作区一起卸载。所以进「无任务」那一刻抓一份快照。
const freeAnchor = ref(null)

// 服务端 path 载荷里的锚点。**没有任务卡时唯一的锚点来源** —— 那时候 selectedWorkspace
// 是空的（它读的是 task.value），而一个基础节点都没完成的学生正是这种情况：
// 后端不发任务，页面靠这个锚点落进「无任务」，IDE 和教练照样能用。
const serverPathAnchor = ref(null)

function currentWorkspaceAnchor() {
  const current = selectedWorkspace.value
  return current.pathId !== null && current.nodeId !== null ? { ...current } : null
}

// 没抓过快照时依次退回"当前任务的工作区"、"服务端给的当前路径节点" —— 前者是常规路径，
// 后者是没任务卡时的兜底。都没有才返回 null（那种情况下建不出自由会话，页面显示空状态）。
const resolvedFreeAnchor = computed(
  () => freeAnchor.value || currentWorkspaceAnchor() || serverPathAnchor.value,
)

const freeTask = computed(() => {
  const anchor = resolvedFreeAnchor.value
  if (!anchor) return null
  return {
    id: FREE_TASK_ID,
    mode: 'free',
    kind_label: '无任务',
    difficulty_label: '自由',
    title: '拿你自己的项目来聊',
    // 四段任务说明全空是有意的：`TaskBar` 的 hasDetails 会因此为假，「任务说明」
    // 开关整个不出现 —— 一个没有任务的任务说明，比没有更让人困惑。
    brief: '',
    problem: '',
    focus: '',
    criteria: [],
    deliverables: [],
    constraints: [],
    workspace: { path_id: anchor.pathId, node_id: anchor.nodeId },
  }
})

// 上限 3：后端一个里程碑只给三个任务（迁移练习 / 案例诊断 / 项目实训），
// 去掉当前选中的那个之后最多剩两个备选。
// 「无任务」接在最后当兜底选项；已经在这个模式里时不再出现（点它等于原地不动，
// 只会让人以为菜单坏了）。
const optionalTasks = computed(() => {
  const alternatives = tasks.value.filter((item) => !item.is_recommended).slice(0, 3)
  const free = freeTask.value
  return free && task.value?.id !== FREE_TASK_ID ? [...alternatives, free] : alternatives
})
// 工作区草稿的归属。按学习路径而不是 task_id / node_id —— 理由见 draftKeyFor：
// 工作区本来就跨任务卡和节点共享，按更细的粒度分会变成行为变更，而节点粒度的 key
// 还会因为 prop 在挂载后变化而把旧文件写进新草稿里。
const workspaceDraftKey = computed(() => draftKeyFor(selectedWorkspace.value.pathId))

// 把"我在哪一页"报给跨界面助手（罗伯特）—— 它挂在 App.vue 上，拿不到这里的 task。
// **只报标识**：任务名、节点名由服务端按 id 重查（见 schemas/chat.py 的信任规则）。
// 任务还没加载出来（或节点缺失）时只报页面名，后端认不出定位就不渲染那一块。
watch(
  [() => task.value?.id, () => selectedWorkspace.value.nodeId],
  () => setCurrentPage('advanced', {
    nodeId: selectedWorkspace.value.nodeId,
    taskId: task.value?.id || '',
  }),
  { immediate: true },
)
onBeforeUnmount(() => clearCurrentPage('advanced'))

// 对话要能看见工作区，可数据在 CodeWorkspace 里。这里往下传的是个**身份稳定**的读取
// 函数，而不是一份快照：
//   - 正文随每次击键变（见 CodeWorkspace.onEditorInput），做成响应式 prop 会让对话
//     组件每敲一个字符重渲染一次，而快照只在"按下发送那一刻"才有意义；
//   - 发送时现取才是诚实的语义 —— 教练看到的是学生按下发送时的那份代码。
// 所以它必须在页面里定义一次。**别改成模板里的内联箭头** —— 那样 prop 身份每渲染
// 都变，等于把每次重渲染又还回来了。
function readWorkspaceSnapshot() {
  return workspaceRef.value?.readSnapshot?.() ?? { available: false }
}

// 智能体生成现在跑在后台（见后端 service/advanced/task_jobs.py），首次请求会先返回
// 一份确定性任务并标记 task_source='pending'。所以这里要轮询到它落定为止 ——
// 否则用户永远停在临时入口上，正是"页面像写死的"那个观感的来源。
const POLL_INTERVAL_MS = 3000
// 40 × 3s = 2 分钟，覆盖后端生成作业的 120s 预算：轮询窗口比生成预算短的话，
// 用户会在结果落地前就停在"生成中"，只能手动刷新。
const POLL_MAX_TRIES = 40
let pollTimer = 0
let pollTries = 0

function clearPoll() {
  if (pollTimer) { window.clearTimeout(pollTimer); pollTimer = 0 }
}

function schedulePoll() {
  clearPoll()
  if (taskSource.value !== 'pending') return
  if (pollTries >= POLL_MAX_TRIES) return
  pollTimer = window.setTimeout(() => {
    pollTries += 1
    // silent：轮询不能把整页切成"正在整理实践任务"，否则每 3 秒闪一次
    loadTask({ silent: true })
  }, POLL_INTERVAL_MS)
}

// refresh：**只有用户手点的按钮才传 true**。它让服务端绕过兜底重试冷却、强制重跑一次
// 生成作业 —— 没有它，「重新同步」和兜底卡片上那句「重新生成」都是空转的：库里是一行
// 刚写下的 fallback 时，冷却期内的每次请求都返回同一份兜底，点一百次也没反应。
async function loadTask(options = {}) {
  const silent = options.silent === true
  if (!silent) {
    pollTries = 0
    clearPoll()
    loading.value = true
  }
  errorMessage.value = ''
  if (!silent) syncError.value = ''
  try {
    const result = unwrap(await advancedLearningApi.getCurrentTask(options.refresh === true))
    learningStatus.value = result?.status || ''
    taskSource.value = result?.task_source || ''
    // 没有任务卡时唯一的锚点来源（见 serverPathAnchor）。它由服务端算，客户端只读。
    serverPathAnchor.value = result?.path?.id && result?.path?.current_node_id
      ? { pathId: result.path.id, nodeId: result.path.current_node_id }
      : null
    const source = Array.isArray(result?.tasks) && result.tasks.length ? result.tasks : (result?.task ? [result.task] : [])
    tasks.value = result?.status === 'ready' ? source : []
    // 轮询时保留用户当前选中的任务，否则每 3 秒把他弹回推荐项。
    // 「无任务」额外算一种：它不在服务端列表里，重查一遍也**找不回来**（它不是任何一条
    // 任务），所以连手动「重新同步」都留着它 —— 否则点一下就被悄悄换回推荐任务。
    //
    // 这一条也覆盖"自动落进无任务之后任务卡才出现"：学生学完第一个节点，任务卡就位了，
    // 但**不把他拽过去**。他可能正在跟教练聊自己的项目，而 PracticeDialogue 是按 task.id
    // 挂 key 的 —— 换任务 = 重挂 = 那段对话当场消失。想换是点一下「换一个」的事，
    // 自动换却会把正在做的事弄没。
    const keepSelected = silent || task.value?.id === FREE_TASK_ID
    const selectedId = keepSelected ? task.value?.id : null
    task.value = resolveTaskById(selectedId)
      || tasks.value.find((item) => String(item.id) === String(route.query.taskId))
      || tasks.value.find((item) => item.status === 'active')
      || tasks.value[0]
      // 服务端一张任务卡都没发（一个基础节点都还没完成），落进「无任务」而不是空状态：
      // 工作区和教练本来就该立刻能用，学生是来问自己的项目的。锚点取服务端的当前节点。
      || freeTask.value
      || null
  } catch (error) {
    if (!silent) {
      const detail = error.response?.data?.detail || error.message || '请检查后端服务后重新同步。'
      // 已经有任务时只挂一条提示，不换整页 —— 换页会把工作区一起卸载（见模板里的注释）。
      if (task.value) syncError.value = detail
      else errorMessage.value = detail
    }
  } finally {
    if (!silent) loading.value = false
  }
  schedulePoll()
}

// 按 id 找任务，认得出「无任务」这个不在服务端列表里的伪任务。
// 轮询和点击都走这里，免得两处的解析规则长歪 —— 少一处判断，就少一次"轮询把学生
// 踢出无任务"这种只在特定时机才现形的错。
function resolveTaskById(taskId) {
  if (!taskId) return null
  if (String(taskId) === FREE_TASK_ID) return freeTask.value
  return tasks.value.find((item) => String(item.id) === String(taskId)) || null
}

// 换任务时把上一次的"已暂存"状态清掉 —— 那个小结属于上一个任务，挂在新任务上会张冠李戴。
// PracticeDialogue 按 task.id 挂 key，会跟着重挂并对新任务开一个会话。
function selectTaskById(taskId) {
  const next = resolveTaskById(taskId)
  if (!next) return
  // 进「无任务」时把锚点定下来（见 freeAnchor 的注释）。放在赋值 task 之前 ——
  // 赋值之后再取，拿到的是伪任务自己的工作区，等于把锚点绕回它自己，轮询一来照样崩。
  if (String(taskId) === FREE_TASK_ID) freeAnchor.value = currentWorkspaceAnchor() || freeAnchor.value
  task.value = next
  sessionEnded.value = false
}

function clampSplit(value) {
  if (!Number.isFinite(value)) return 50
  return Math.min(SPLIT_MAX, Math.max(SPLIT_MIN, value))
}

// 只记比例、不记像素：窗口大小变了，比例仍然是用户想要的那个"左多还是右多"。
function readStoredSplit() {
  try {
    const raw = window.localStorage.getItem(SPLIT_STORAGE_KEY)
    return raw === null ? 50 : clampSplit(Number(raw))
  } catch {
    // 隐私模式等场景下 localStorage 会直接抛异常，退回默认比例即可
    return 50
  }
}

function persistSplit() {
  try {
    window.localStorage.setItem(SPLIT_STORAGE_KEY, String(Math.round(splitPercent.value)))
  } catch {
    // 存不下只是下次进来回到默认比例，不影响本次拖动
  }
}

// 拖动用指针捕获，不挂在 window 上：指针移出分隔条（甚至移出窗口）事件仍然回到它，
// 而且组件卸载时监听随之消失，不用另外清理。整段拖拽过程按容器宽度换算百分比，
// 所以中途改窗口大小也不会跑偏。
function startSplitDrag(event) {
  const container = layoutRef.value
  if (!container || event.button !== 0) return
  const rect = container.getBoundingClientRect()
  if (!rect.width) return
  const handle = event.currentTarget
  isDragging.value = true
  handle.setPointerCapture?.(event.pointerId)

  const onMove = (moveEvent) => {
    splitPercent.value = clampSplit(((moveEvent.clientX - rect.left) / rect.width) * 100)
  }
  const onEnd = () => {
    isDragging.value = false
    handle.releasePointerCapture?.(event.pointerId)
    handle.removeEventListener('pointermove', onMove)
    handle.removeEventListener('pointerup', onEnd)
    handle.removeEventListener('pointercancel', onEnd)
    persistSplit()
  }

  handle.addEventListener('pointermove', onMove)
  handle.addEventListener('pointerup', onEnd)
  handle.addEventListener('pointercancel', onEnd)
}

function onSplitKey(event) {
  const step = event.shiftKey ? SPLIT_STEP_LARGE : SPLIT_STEP
  if (event.key === 'ArrowLeft') splitPercent.value = clampSplit(splitPercent.value - step)
  else if (event.key === 'ArrowRight') splitPercent.value = clampSplit(splitPercent.value + step)
  else if (event.key === 'Home') splitPercent.value = 50
  else return
  event.preventDefault()
  persistSplit()
}

function resetSplit() {
  splitPercent.value = 50
  persistSplit()
}

const layoutStyle = computed(() => ({ '--ide-split': `${splitPercent.value}%` }))

function normalizeContent(value) {
  if (typeof value === 'string') return value
  if (value && typeof value === 'object') return String(value.markdown || value.content || value.text || '')
  return ''
}

async function loadNodeContext() {
  chapterContent.value = ''
  resourceId.value = null
  if (!hasWorkspace.value) return
  try {
    const detail = await fundamentalsApi.getNode(selectedWorkspace.value.pathId, selectedWorkspace.value.nodeId)
    const resources = detail?.progress?.resources || detail?.resources || []
    const documentResource = resources.find((resource) => resource.resource_type === 'document')
    resourceId.value = documentResource?.resource_id || documentResource?.id || null
    // 有 resource_id 时不再把整篇正文拉到客户端：服务端会按本次提问自己挑相关段落
    // （见 classroom_chat._build_classroom_path_context）。以前这里把整篇主讲材料取回来，
    // 只为在客户端截 1200 字塞进 segment.script —— 白拉一趟，而且那份比服务端挑出来的
    // 3600 字相关段落更差。同一份教材喂两遍是纯浪费。
    // 只有服务端确实拿不到的时候（没有 resource_id），客户端这份才是唯一来源。
    if (!resourceId.value) chapterContent.value = normalizeContent(documentResource?.content)
  } catch {
    chapterContent.value = ''
  }
}

// 右栏一上来就是对话，没有"开始"这一步。对话需要节点正文当上下文（教练的提示词会用到），
// 所以任务一定就先把它取回来；取不到也不挡对话，只是上下文为空。
watch(() => task.value?.id, () => { loadNodeContext() })

// 暂存后请服务端按**它自己记的**会话记录写一份过程小结：消息、阶段、评价都在库里，
// 不用前端再描述一遍"我刚才学了什么"（那样总结就成了给自己打分）。
// 失败就什么都不显示 —— 编一段"你已经掌握了…"比不显示更糟（同本文件里程碑默认值那条注释）。
async function endPractice(sessionId = '') {
  sessionEnded.value = true
  summaryText.value = ''
  summaryController?.abort()
  summaryController = null
  if (!sessionId || !hasWorkspace.value) return
  summaryLoading.value = true
  summaryController = new AbortController()
  try {
    await fundamentalsApi.streamAssistantReply({
      path_id: Number(selectedWorkspace.value.pathId),
      node_id: Number(selectedWorkspace.value.nodeId),
      resource_id: resourceId.value ? Number(resourceId.value) : null,
      practice_session_id: String(sessionId),
      scenario: 'practice_summary',
      text: '',
      segment: { id: `practice-summary-${task.value?.id || ''}`, type: 'practice_summary', title: task.value?.title || '' },
    }, (event) => {
      if (event?.error) throw new Error(event.error)
      if ((event?.type === 'chunk' || event?.type === 'content') && event.content) {
        summaryText.value += String(event.content)
      }
    }, summaryController.signal)
  } catch (error) {
    if (error.name !== 'AbortError') summaryText.value = ''
  } finally {
    summaryLoading.value = false
    summaryController = null
  }
}

onMounted(() => { loadTask() })

// 轮询是 setTimeout 链，组件卸载后必须停掉，否则切页之后还在后台拉接口
onBeforeUnmount(() => {
  clearPoll()
  summaryController?.abort()
  summaryController = null
})
</script>

<style scoped>
/* IDE 要占满可视区：页面容器改成固定高度 + 不滚动，滚动交给内部各自的面板。
   原来这里是 overflow-y: auto，编辑器会被撑成一条长纸。内边距也收紧了 —— 这一页的
   主角是下面两块面板，四周多留的每一像素都是从编辑器和对话里拿走的。 */
:global(.page-container:has(.advanced-page)) { display: flex; height: calc(100vh - 64px); box-sizing: border-box; min-width: 0; flex-direction: column; margin: 0; padding: 14px 20px 16px; overflow: hidden; }
:global(.app-content:has(.advanced-page)), :global(.page-container:has(.advanced-page)) { background: #f7f7f7; }
:global(.app-content:has(.advanced-page) .app-header) { border-bottom-color: #e8e8e8; background: #f7f7f7; }

.advanced-page { display: flex; min-width: 0; min-height: 0; flex: 1; flex-direction: column; }
.advanced-top { display: flex; flex: 0 0 auto; align-items: center; gap: 10px; margin-bottom: 10px; }
/* 任务条吃掉横向余量，同步按钮按内容宽。min-width: 0 是给标题省略号留的余地。 */
.advanced-top > :first-child { min-width: 0; flex: 1; }
.advanced-top__sync { flex: 0 0 auto; padding: 6px 11px; font-size: 12px; }
/* 刷新失败时的一行提示。刻意做得很薄：工作区才是主角，错误只是"这次没同步上"。 */
.advanced-sync-error { display: flex; flex: 0 0 auto; align-items: center; gap: 7px; margin: 0 0 10px; padding: 7px 11px; border: 1px solid rgba(149, 78, 56, .32); border-radius: 10px; background: rgba(149, 78, 56, .06); color: #954e38; font-size: 12px; line-height: 1.6; }
.advanced-page h2 { color: #1e3c34; }
.advanced-page .surface { border-radius: 14px; border-color: rgba(63, 91, 49, .28); box-shadow: 0 8px 24px rgba(45, 40, 92, .07); }
.advanced-page .button { border-radius: 12px; gap: 8px; }
.advanced-page .button--primary { border-color: #c4df3d; background: #b6d837; color: #1e3c34; box-shadow: 0 6px 14px rgba(63, 91, 49, .14); }
.advanced-page .button--primary:hover { border-color: #a9ca27; background: #a9ca27; color: #1e3c34; }
.advanced-page .button--quiet { border-color: #dce3dc; background: #fff; color: #3f5b31; }
.advanced-page .button--quiet:hover { border-color: #b9c9b2; background: #f1f6eb; }
.advanced-page .button:disabled { cursor: wait; opacity: .55; }

.state-panel { display: flex; align-items: center; gap: 14px; min-height: 96px; color: var(--accent-deep); }
.state-panel > div { min-width: 0; flex: 1; }
.state-panel p, .empty-panel p { margin: 5px 0 0; color: var(--muted); font-size: 13px; line-height: 1.7; }
.state-panel--error { color: #954e38; }
.spin { animation: spin 1s linear infinite; }
.empty-panel { max-width: 720px; }
.empty-panel h2 { margin: 0; font-size: 22px; }
.empty-panel > p:not(.eyebrow) { margin-bottom: 20px; }

/* 代码区宽度由 --ide-split 决定（用户拖出来的），对话区吃掉剩下的。
   两块都包 minmax(0, …)：不包的话 Monaco 的画布和对话里的长代码块会把轨道顶开，
   比例就失真了（这个坑在只有两列 1fr 的时候不明显，换成百分比就很明显）。 */
.ide-layout { display: grid; min-width: 0; min-height: 0; flex: 1; grid-template-columns: minmax(0, var(--ide-split, 50%)) 14px minmax(0, 1fr); }
.ide-layout.is-dragging { cursor: col-resize; user-select: none; }
.ide-workspace { min-width: 0; min-height: 0; }
.ide-practice { min-height: 0; }
.ide-practice > * { height: 100%; }

/* 分隔条：平时只是一条 1px 的线，指针移上去（或拖动中）才亮出来。热区给 14px，
   照线本身做的话根本点不中；touch-action: none 是让触屏拖动不被滚动抢走。 */
.ide-splitter { position: relative; display: grid; place-items: center; cursor: col-resize; touch-action: none; }
.ide-splitter::before { content: ''; position: absolute; top: 0; bottom: 0; left: 50%; width: 1px; transform: translateX(-50%); background: var(--line); }
.ide-splitter:focus-visible { outline: none; }
.ide-splitter__grip { position: relative; width: 4px; height: 40px; border-radius: 99px; transition: background .16s ease; }
.ide-splitter:hover .ide-splitter__grip,
.ide-splitter:focus-visible .ide-splitter__grip,
.ide-layout.is-dragging .ide-splitter__grip { background: var(--accent); }

.session-ended { display: grid; place-content: center; justify-items: center; gap: 9px; overflow-y: auto; padding: 22px; text-align: center; }
.session-ended__mark { display: grid; width: 46px; height: 46px; place-items: center; border-radius: 50%; background: #e8f2de; color: var(--accent-deep); font-size: 21px; }
.session-ended h2 { margin: 0; font-size: 19px; }
.session-ended > p:not(.eyebrow) { max-width: 420px; margin: 0; color: var(--muted); font-size: 12px; line-height: 1.7; }
.session-ended__actions { display: flex; flex-wrap: wrap; gap: 9px; margin-top: 10px; }
.session-summary { width: 100%; margin-top: 6px; padding: 13px 15px; border: 1px solid #dbe7d2; border-radius: 10px; background: #f8fbf3; text-align: left; }
.session-summary--loading { display: flex; align-items: center; justify-content: center; gap: 7px; color: var(--accent-deep); font-size: 12px; }
.session-summary .eyebrow { margin-bottom: 7px; }
.session-summary__body { color: #536057; font-size: 12px; line-height: 1.75; overflow-wrap: anywhere; }
.session-summary__body :deep(p) { margin: 0 0 8px; }
.session-summary__body :deep(p:last-child) { margin-bottom: 0; }
.session-summary__body :deep(ul), .session-summary__body :deep(ol) { margin: 6px 0 0; padding-left: 20px; }

@keyframes spin { to { transform: rotate(360deg); } }

/* 窄屏不再并排：让页面重新可滚动，两块上下堆叠。IDE 在手机上本来就退化成预览。 */
@media (max-width: 1120px) {
  :global(.page-container:has(.advanced-page)) { height: auto; min-height: 0; overflow: visible; padding: 22px 18px 40px; }
  /* 堆叠之后没有"两列"可分了，分隔条必须撤掉 —— 留着会在中间空出一行 */
  .ide-layout { grid-template-columns: minmax(0, 1fr); }
  .ide-splitter { display: none; }
  .ide-workspace { height: clamp(420px, 60vh, 640px); }
  .ide-practice > * { height: auto; min-height: 420px; }
  /* 对话这一块得单独提一级：它自己的 .practice-dialogue.is-compact 写着 height:100%; min-height:0
     （按"右栏撑满"写的），而这里父级高度由内容决定 —— 100% 退化成内容高度，里面的
     minmax(0,1fr) 再把消息区算成 0，整块只剩 64px。既然堆叠了，就和工作区一样给个确定高度。 */
  .ide-practice :deep(.practice-dialogue.is-compact) { height: clamp(420px, 60vh, 640px); }
}

/* 再窄就把任务条和同步按钮分成两行。挤在一行时这一条的 min-content 约 474px
   （标题虽然能省略，但任务条内部的类别/难度/切换都不可压缩），480px 的手机上会把整页
   撑到 562px，而 .app-content 是 overflow: hidden —— 多出来的部分是被直接切掉的。
   这个断点写在宽的后面，避免以后往上面那个块里加 .advanced-top 规则时被顶掉。 */
@media (max-width: 760px) {
  .advanced-top { flex-wrap: wrap; }
  .advanced-top > :first-child { flex: 1 1 100%; }
}
</style>
