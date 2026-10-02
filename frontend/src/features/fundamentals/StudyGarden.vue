<template>
  <!-- **这一页只有这一个标题。** 页面原来还有一个「学习复盘」的 `PageTitle`，
       可花园一占满整屏，两个并列的大标题就变成了互相打架的两个主语 ——
       而屏幕上明明只有树林。所以花园态下页面标题整个让位（见 FoundationTestPage），
       由这里当唯一的 h1。树是导航（点了去学 / 去做题），复盘是树点开之后的事。 -->
  <section class="forest-review" aria-labelledby="forest-review-title">
    <header class="forest-review__header">
      <div class="forest-review__title">
        <p class="eyebrow">LEARNING FOREST</p>
        <h1 id="forest-review-title">学习树林</h1>
        <span class="forest-review__count" aria-label="已完成章节数量">
          <strong>{{ completedNodes.length }}</strong> / {{ nodes.length }} 章
        </span>
      </div>
      <p v-if="activeNode" class="forest-review__status" aria-live="polite">
        <strong>{{ activeNode.title }}</strong>
        <span>{{ stageTitle }}</span>
      </p>
      <!-- 页面的"该往前走了"入口挂在这儿。花园占满整屏之后，原来 `PageTitle` 里
           那个按钮就没地方站了，但它是学生从复盘中转出去的唯一出口（见
           FoundationTestPage 里的说明），不能跟着标题一起消失。 -->
      <div class="forest-review__door"><slot name="door" /></div>
    </header>

    <div v-if="nodes.length" class="garden-scene" :style="gardenSceneStyle" role="list" aria-label="学习树林">
      <span class="garden-scene__sun" aria-hidden="true"></span>
      <span class="garden-scene__cloud garden-scene__cloud--one" aria-hidden="true"></span>
      <span class="garden-scene__cloud garden-scene__cloud--two" aria-hidden="true"></span>
      <span class="garden-scene__hill garden-scene__hill--back" aria-hidden="true"></span>
      <span class="garden-scene__hill garden-scene__hill--front" aria-hidden="true"></span>
      <span class="garden-scene__field" aria-hidden="true"></span>
      <span class="garden-scene__furrow garden-scene__furrow--one" aria-hidden="true"></span>
      <span class="garden-scene__furrow garden-scene__furrow--two" aria-hidden="true"></span>
      <span class="garden-scene__path" aria-hidden="true"></span>

      <!--
        每个章节一个 `.garden-slot`：定位和 z-index 在槽上，树是槽里的唯一一块内容。
        （槽还留着而不是把定位直接写回 `.garden-plant`，是因为窄屏那条 `left: clamp(...)`
        和 hover / active 的层级都挂在槽上，合并进按钮得重算一遍。）
      -->
      <div
        v-for="item in planted"
        :key="item.node.id"
        class="garden-slot"
        :class="{ 'is-active': isActive(item.node), 'is-locked': item.node.status === 'locked' }"
        :style="item.style"
        role="listitem"
      >
        <button
          class="garden-plant"
          type="button"
          :aria-pressed="isActive(item.node)"
          :aria-label="`${item.node.title}，${stageLabel(item.node)}`"
          :disabled="item.node.status === 'locked'"
          @click="$emit('select', item.node.id)"
        >
          <GrowthTree
            :node="item.node"
            :weak-points="weakPoints"
            :growth="growthOf(item.node)"
            :reveal="revealOf(item.node)"
            detail="coarse"
          />
          <!-- 章节名分两截：`i` 是序号、`b` 是标题。窄屏上要单独把标题藏起来
               （十几棵树挤在 500px 里，全名会互相压住），分开了才藏得掉。 -->
          <span class="garden-plant__label"><i>第 {{ item.index + 1 }} 章</i><b>{{ item.node.title }}</b></span>
          <span v-if="item.node.status === 'locked'" class="garden-plant__lock" aria-hidden="true">· · ·</span>
        </button>
      </div>

    </div>

    <div v-else class="garden-empty">
      <GrowthTree :node="SEEDLING" label="等待播种的土壤" />
      <p>学习路径生成后，这里会长出第一株幼苗。</p>
    </div>
  </section>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import GrowthTree from '@/features/fundamentals/GrowthTree.vue'
import { useGrowthTimeline } from '@/features/fundamentals/useGrowthTimeline.js'
import { growTree } from '@/features/fundamentals/treeGrowth.js'
import { growthForHeight, treeTopRatio } from '@/features/fundamentals/treeRender.js'
import { resolveNodeActions } from '@/entities/learning/nodeAction.js'
import { loadSeenHeights, saveSeenHeights } from '@/entities/learning/gardenMemory.js'

/** 没有路径时那块"等待播种的土壤"：完成度为 0 的节点，growTree 会画出一株刚破土的芽。 */
const SEEDLING = {
  id: 'empty-garden',
  status: 'unlocked',
  knowledge_tags: [],
  garden_progress: { resource_total: 0, resource_completed: 0, quiz_answered: 0, quiz_correct: 0 },
}

const props = defineProps({
  nodes: { type: Array, default: () => [] },
  activeNodeId: { type: [String, Number], default: null },
  /** 路径 id，拼进气泡的跳转 query。 */
  pathId: { type: [String, Number], default: null },
  /** 全局薄弱点（`diagnosis.weak_points`）。命中节点知识点的，那根一级枝枯。 */
  weakPoints: { type: Array, default: () => [] },
})

const emit = defineEmits(['select'])

const completedNodes = computed(() => props.nodes.filter((node) => node.status === 'completed'))
const visibleNodes = computed(() => props.nodes)
const gardenRowCount = computed(() => Math.max(1, Math.ceil(visibleNodes.value.length / 4)))
const gardenSceneStyle = computed(() => ({ '--garden-rows': gardenRowCount.value }))
const activeNode = computed(() => {
  if (props.activeNodeId === null || props.activeNodeId === undefined) return null
  return props.nodes.find((node) => String(node.id) === String(props.activeNodeId)) || null
})

const timeline = useGrowthTimeline()

// 每个节点的生长**起点**：`上次看到的高度` 反解出来的生长进度。
// 1 = 不用演（没有上次的记录，或者上次就已经长这么高了）。
const startRatios = ref({})

const nodeKey = (node) => String(node.id)

function isActive(node) {
  return nodeKey(node) === nodeKey(activeNode.value || {})
}

/**
 * 每个节点现在能做哪几件事。**一次算好存起来**，别在模板里逐棵树调 ——
 * 一屏十几棵树，模板里现算会把同一份判断跑好几十遍。
 *
 * 树上不再挂水滴（那是上一版），这份表现在只喂两处文案：顶部那句"接下来：…"，
 * 和每棵树按钮的无障碍标签。**留着它是因为这两处仍然需要"这一章下一步是什么"**
 * —— 判断规则本身在 `entities/learning/nodeAction.js`，和渲染无关，
 * 哪天要重新把动作摆回树上，把它接回模板就行。
 */
const actionsByNode = computed(() => {
  const map = {}
  for (const node of props.nodes) map[nodeKey(node)] = resolveNodeActions(node, { pathId: props.pathId })
  return map
})

function actionsOf(node) {
  return actionsByNode.value[nodeKey(node)] || []
}

/** 头部那句状态：当前章节排在头一个的下一步是什么。 */
const stageTitle = computed(() => {
  const first = actionsOf(activeNode.value || {})[0]
  if (!first) return activeNode.value ? '还没解锁' : ''
  return { read: '接下来：看资料', quiz: '接下来：做测验', review: '接下来：复盘' }[first.kind] || ''
})

/**
 * 这棵树按钮念什么。**只说动作，不重复章节名** —— 模板里已经把标题拼在前面了，
 * 再带上 `action.aria`（形如"复习：<标题>"）会念成模棱两可的两遍标题。
 */
function stageLabel(node) {
  const actions = actionsOf(node)
  if (!actions.length) return '还没解锁'
  return `可以${actions.map((item) => item.label).join('或')}`
}

/**
 * 固定哈希 → [0,1)。**每次刷新都一样** —— 截图、刷新、改一个节点的进度都不该让树换位置。
 * 树的左右站位和一点轻微抖动都靠它（`plantPosition`）。
 */
function jitter(seed) {
  let hash = 2166136261
  for (let i = 0; i < seed.length; i++) {
    hash ^= seed.charCodeAt(i)
    hash = Math.imul(hash, 16777619)
  }
  return ((hash >>> 0) % 1000) / 1000
}

function growthOf(node) {
  const from = startRatios.value[nodeKey(node)]
  if (from === undefined || from >= 1) return 1
  return from + (1 - from) * timeline.progress.value
}

/** 果实不跟生长进度走：过关那一步树高不变，跟 growth 会永远定格在全亮。 */
function revealOf(node) {
  const from = startRatios.value[nodeKey(node)]
  if (from === undefined || from >= 1) return 1
  return timeline.reveal.value
}

/**
 * 算出每棵树的生长起点。**没有记录就按成品画**：第一次见这棵树时没有"上次的样子"可比，
 * 从零抽条既没有信息量（学生不知道自己在比什么），也是十几棵树同时在重拼 path。
 */
function prepareGrowth() {
  const seen = loadSeenHeights()
  const next = {}
  let animates = false
  for (const node of props.nodes) {
    const remembered = Number(seen[nodeKey(node)]) || 0
    if (remembered <= 0) {
      next[nodeKey(node)] = 1
      continue
    }
    const tree = growTree(node, { weakPoints: props.weakPoints })
    const from = growthForHeight(tree, remembered)
    next[nodeKey(node)] = from
    if (from < 0.999) animates = true
  }
  startRatios.value = next
  // **不演的时候也得记一次**，否则"只长新增那段"永远开不了头：
  // 第一次进页没有记录 → 不播动画 → 下面那个 `watch(timeline.progress)` 也就永远不触发
  // （progress 初值就是 1，没启动过就不会变）→ 高度永远存不下去 → 下次还是没有记录。
  // 结果就是这个功能一次都不会演，而且不报错，看着像"实现了但没生效"。
  if (animates) timeline.start()
  else rememberHeights()
}

/** 演完把每棵树当前的高度记下来，下次进页才有"上次的样子"可比。 */
function rememberHeights() {
  const seen = {}
  for (const node of props.nodes) {
    seen[nodeKey(node)] = growTree(node, { weakPoints: props.weakPoints }).meta.height
  }
  saveSeenHeights(seen)
}

watch(
  () => props.nodes,
  () => prepareGrowth(),
  { immediate: true },
)

watch(timeline.progress, (value) => {
  if (value >= 1) rememberHeights()
})

/**
 * 每棵树的树顶在这块画布上的比例（见 `treeTopRatio`）。锁着的那棵树那个"· · ·"
 * 按它定位，才贴得住树顶 —— 按画布顶定位的话，小树上方会空出一大片。
 */
const treeTopByNode = computed(() => {
  const map = {}
  for (const node of props.nodes) {
    map[nodeKey(node)] = treeTopRatio(growTree(node, { weakPoints: props.weakPoints }))
  }
  return map
})

/**
 * 每棵树**摆哪儿、多大多斜、树顶在多高、章节名挂树上还是树脚下** —— 一次算好。
 *
 * 之前是模板里为了判 `label` 调一次 `plantPosition()`、`plantStyle()` 里又调一次，
 * 同一个纯函数一棵树跑两遍；两处迟早会改歪。
 */
const planted = computed(() => visibleNodes.value.map((node, index) => {
  const place = plantPosition(index, visibleNodes.value.length)
  // 越靠后的排越小。这是纵深，也是"远排的树比近排小"唯一的来源。
  const depthScale = 0.7 + ((100 - place.y) / 100) * 0.3
  // **不再按"第几档"乘一个尺寸系数。** 树的高矮现在完全由完成度决定
  // （`treeGrowth.js`），再乘一遍档位系数等于把成长讲了两遍，而且是假的那遍。
  const fitted = Math.max(0.2, place.size * depthScale)
  const top = treeTopByNode.value[nodeKey(node)] ?? 1

  return {
    node,
    index,
    style: {
      '--x': place.x,
      '--y': place.y,
      '--size': fitted,
      '--tilt': `${place.tilt}deg`,
      '--depth-order': Math.round(100 - place.y),
      '--tree-top': top,
    },
  }
}))

/*
  树的站位：**按顺序把章节摊到远、中、近三排上**，第 1 章在最远的山脊、最后一章站在你面前。

  三排的 y 拉开到快把整块地占满（`8% + y * .72%` 那条映射见 `.garden-slot`）：
  远排贴着山脊线（离底 ~60%）、中排在前面的坡上（~38%）、近排站在画面最底下的草地（~14%）。
  原来三排挤在 y 22~62（离底 22%~53%），上下各空一大片，一屏绿地里几棵小树孤零零浮在中间。

  左右范围**一排比一排窄**（远排 16~84、中排 13~89、近排 11~92）—— 既是透视
  （远处看着就是窄一点），也是地形：地平线是一条中间高两边低的弧，
  远排铺得比中排还宽的话，最左最右那两棵会站到弧线外面去。

  **每排站几棵是按总章数算的**，不是写死 4 棵一排：真实路径是 8~30 章
  （`_compute_node_count` 给的就是这个区间），30 章时一排 10 棵会自然地挤成一片树冠，
  8 章时也不会把树全堆在远中两排、让前景空着。

  章节名**一律挂在树脚下**（见 `.garden-plant__label`）：早先分两档（高的排挂树上、
  低的排挂树下）是为了给树上那些动作气泡让路，代价是同一个东西一屏里有两种高度。
  气泡撤掉之后这一档也没必要了，但"名字挂在脚下"留着 —— 它离树更近，
  读起来更像"这棵叫第几章"。
*/
const ROWS = [
  { y: 76, size: 0.58, left: 16, right: 84 }, // 远排：贴着山脊线，最小
  { y: 44, size: 0.78, left: 13, right: 89 }, // 中排：前面的坡
  { y: 8, size: 0.94, left: 11, right: 92 }, // 近排：前景草地，最大
]

/**
 * 三排各站几棵。**余数补给靠前的那几排**，不是留给最后一排 ——
 * 近排是画面里最大、最显眼的一排，宁可远排稀一点，也不能让前景中间空一个洞。
 * 12 章 → 4/4/4；8 章 → 2/3/3；30 章 → 10/10/10。
 */
function rowCounts(total) {
  const base = Math.floor(total / ROWS.length)
  const extra = total % ROWS.length
  return ROWS.map((_, row) => base + (row >= ROWS.length - extra ? 1 : 0))
}

function plantPosition(index, total) {
  const spot = ROWS[0]
  if (!total) return { x: spot.left, y: spot.y, size: spot.size, tilt: 0 }

  const counts = rowCounts(total)
  let row = 0
  let start = 0
  while (row < ROWS.length - 1 && index >= start + counts[row]) {
    start += counts[row]
    row += 1
  }
  const col = index - start
  const inRow = Math.max(1, counts[row])
  const place = ROWS[row]

  // 均分到左右边界（一排只剩一棵时就摆在正中间），再给每棵一点**固定**的抖动 ——
  // 用 `jitter()` 而不是 `Math.random()`：截图、刷新、改一个节点的进度都不该让树换位置。
  const spread = inRow > 1 ? col / (inRow - 1) : 0.5
  const x = place.left + spread * (place.right - place.left) + (jitter(`px${index}`) - 0.5) * 5
  return {
    x: Math.min(place.right + 2, Math.max(place.left - 2, x)),
    y: place.y + (jitter(`py${index}`) - 0.5) * 6,
    size: place.size * (0.93 + jitter(`ps${index}`) * 0.14),
    tilt: (jitter(`pt${index}`) - 0.5) * 2.8,
  }
}
</script>

<style scoped>
/* 高度是**父级给的**（`.foundation-test-page.is-garden` 那一环），这里只管把
   header 固定住、把剩余高度全部交给场景。`min-height: 0` 必须有 —— flex 子项默认
   `min-height: auto`，内容一高就不肯收缩，场景会顶出容器。 */
/*
  **树专用的尺度单位 `--q`，不跟页面的 `--s` 共用。**
  场景是 `flex: 1` 撑开的，屏越大它越高得越多（1366 的屏 420px，2560 的屏 1300px，3 倍），
  而 `--s` 取的是"宽高比里小的那个"、还有 1.5 的上限，在 2560 的屏上只涨到 1.4 倍。
  跟着 `--s` 走的话树只大四成、场景大了三倍 —— 一屏绿地里孤零零几棵小树。
  所以花园内部改用这个：**以视口宽高里更紧的那条为准**，下限仍是 1px。
  两个除数（1000 / 560）是量出来的：基准屏上一棵近排的树约 200px 宽，
  2560 的屏上约 300px —— 再小就只剩"几根插在地上的签子"。

  （试过容器查询 `cqh`，那才是"跟场景等比"的正解，但在浏览器里量出来是 0 ——
  `container-type: size` 挂在 flex 撑开的元素上时，块轴尺寸不参与容器查询。
  同源 iframe 复现不出来，不深挖了。）
*/
.forest-review { --q: clamp(1px, min(100vw / 1000, 100vh / 560), 2.9px); position: relative; display: flex; flex-direction: column; min-height: 0; padding: 0; }
/* 标题**浮在场景上方**而不是占一条横幅：这样绿才真的从屏幕顶铺到底。
   天空是最浅的一层，深绿的字压在上面够清楚，不需要再垫一块底色。
   `pointer-events: none` 让空白处的点击继续落到树上，只有那个门按钮自己接事件。 */
.forest-review__header { position: absolute; z-index: 130; top: 0; right: 0; left: 0; display: flex; align-items: flex-start; gap: 16px; padding: 16px 24px; pointer-events: none; }
.forest-review__title { display: flex; align-items: baseline; gap: 10px; min-width: 0; }
.forest-review__title .eyebrow { margin: 0; color: #75906c; font-size: 10px; letter-spacing: .16em; }
.forest-review h1 { margin: 0; color: #24402c; font-size: clamp(18px, 1.4vw, 24px); letter-spacing: -.01em; }
.forest-review__count { color: #5c7a5a; font-size: 12px; }
.forest-review__count strong { color: var(--accent-deep); font-size: 16px; }
.forest-review__status { display: grid; min-width: 0; flex: 1; gap: 2px; margin: 0 0 0 auto; text-align: right; }
.forest-review__status strong { overflow: hidden; color: #2c4a33; font-size: 12px; text-overflow: ellipsis; white-space: nowrap; }
.forest-review__status span { color: #6e8b6f; font-size: 11px; }
.forest-review__door { flex: 0 0 auto; pointer-events: auto; }

/* **场景吃掉整页高度**，不再按行数算一个固定高度 —— 这就是"正好撑满一屏"的来源。
   **没有边框也没有圆角**：这里不再是页面上的一张卡片，而是这一页本身。
   420px 是下限：再矮下去三排树会叠在一起。矮屏上超出的部分由页面滚动兜住
   （见 FoundationTestPage 里 `.page-container:has(.is-garden)`）。 */
.garden-scene { position: relative; flex: 1 1 auto; min-height: 420px; overflow: hidden; isolation: isolate; background: linear-gradient(180deg, #eef4eb 0%, #e8f0e4 42%, #dbe8d6 100%); }
.garden-scene::before { position: absolute; z-index: -4; inset: 0; background: radial-gradient(circle at 73% 12%, rgba(255,255,255,.42), transparent 25%), linear-gradient(165deg, transparent 44%, rgba(255,255,255,.24) 44.2%, transparent 44.6%); content: ''; opacity: .8; }
.garden-scene__sun { position: absolute; z-index: -3; top: 38px; right: 11%; width: 58px; height: 58px; border-radius: 50%; background: #efd992; box-shadow: 0 0 0 12px rgba(239,217,146,.12), 0 0 30px rgba(239,217,146,.16); opacity: .7; }
.garden-scene__cloud { position: absolute; z-index: -3; width: 86px; height: 19px; border-radius: 50%; background: #fff; opacity: .6; }
.garden-scene__cloud::before,.garden-scene__cloud::after { position: absolute; bottom: 0; border-radius: 50%; background: inherit; content: ''; }
.garden-scene__cloud::before { left: 16px; width: 32px; height: 32px; }.garden-scene__cloud::after { right: 13px; width: 42px; height: 26px; }
.garden-scene__cloud--one { top: 72px; left: 11%; }.garden-scene__cloud--two { top: 128px; right: 28%; transform: scale(.6); }
/* 地形整体抬高：地平线原来在离底 50%，一屏绿地里上空出三成是天空。
   现在田地的顶边到 64%、远排的树站在 60%，天只剩顶上一条。
   田地的顶边弧**压得很平**（`/ 7% 6%`，原来是 16%/13%）—— 弧一大，最左最右的
   远排树就跑到弧线外面去，看着像浮在空中。 */
.garden-scene__hill { position: absolute; z-index: -3; right: -8%; bottom: 42%; left: -8%; height: 32%; border-radius: 50% 50% 0 0; }
.garden-scene__hill--back { background: #c5dbbd; transform: rotate(-3deg); }.garden-scene__hill--front { bottom: 24%; height: 28%; background: #b3d0a9; transform: rotate(2deg); }
.garden-scene__field { position: absolute; z-index: -2; right: -12%; bottom: -20%; left: -12%; height: 90%; border-radius: 54% 46% 0 0 / 7% 6% 0 0; background-color: #9fbe91; background-image: radial-gradient(ellipse at 18% 38%, rgba(232,242,218,.22), transparent 36%), repeating-linear-gradient(166deg, transparent 0 34px, rgba(81,123,72,.075) 35px 37px, transparent 38px 72px); box-shadow: inset 0 18px 0 rgba(224,236,211,.25); transform: rotate(-1.2deg); }
.garden-scene__furrow { position: absolute; z-index: -1; width: 74%; height: 24%; border-top: 1px solid rgba(75,112,68,.22); border-radius: 50%; opacity: .6; pointer-events: none; }
.garden-scene__furrow--one { right: -5%; bottom: 15%; transform: rotate(-4deg); }.garden-scene__furrow--two { bottom: 2%; left: -7%; transform: rotate(3deg); }
/* 一条从地平线走到画面底边的小路。**上窄下宽**，透视才对 ——
   原来是一块 `border-radius: 50% 47% 0 0` 的高 65% 的圆顶，场景一撑到 1300px 高，
   它就变成一个杵在草地中央的巨大土色蛋，比树还抢眼。 */
.garden-scene__path { position: absolute; z-index: -1; bottom: -3%; left: 66%; width: 22%; height: 73%; background: linear-gradient(100deg, rgba(188,148,98,.45), rgba(226,203,161,.72) 50%, rgba(186,143,94,.42)); clip-path: polygon(45% 0, 55% 0, 100% 100%, 0 100%); transform: translateX(-50%) rotate(3deg); opacity: .5; }

/* 定位和 z-index 挪到槽上，树和气泡都是槽里的兄弟。 */
/* 宽度是原来的 `clamp(58px, 42px + size*92px, 124px)` 每个分量各乘 `--q`
   （`--q` 是长度，所以 `N * var(--q)` 才是 px；不能写成 `clamp(...) * var(--q)`，
   长度乘长度不合法）。`--q` 定义在 `.forest-review` 上，理由见那里。

   `bottom` 那条映射（8% + y * .72%）配 `ROWS` 里 8 / 44 / 76 的 y，
   把三排树摊在离底 14%~63% 之间 —— 下面是草地、上面是山脊，整块地都站上人。 */
.garden-slot { position: absolute; z-index: calc(1 + var(--depth-order)); bottom: calc(8% + var(--y) * .72%); left: calc(var(--x) * 1%); width: min(calc(124 * var(--q)), max(calc(58 * var(--q)), calc((42 + var(--size) * 92) * var(--q)))); transform: translateX(-50%); }
.garden-slot:hover { z-index: 120; }.garden-slot:focus-within { z-index: 121; }.garden-slot.is-active { z-index: 122; }
/* 高度不写死：`GrowthTree` 自己按 viewBox 的宽高比撑开，宿主只给宽度。 */
.garden-plant { position: relative; display: block; width: 100%; padding: 0; border: 0; background: transparent; color: var(--ink); cursor: pointer; touch-action: manipulation; transform: rotate(var(--tilt)); transform-origin: 50% 100%; transition: transform 180ms ease, filter 180ms ease; }
.garden-plant :deep(.growth-tree) { pointer-events: none; }.garden-plant:hover:not(:disabled) { filter: saturate(1.12); transform: translateY(-7px) rotate(var(--tilt)) scale(1.04); }.garden-plant:focus-visible { outline: 2px solid var(--accent-deep); outline-offset: 4px; }
.garden-slot.is-active .garden-plant { filter: saturate(1.12); }.garden-slot.is-active .garden-plant::before { position: absolute; z-index: -1; right: 6%; bottom: 4%; left: 6%; height: 22%; border: 1px dashed #507950; border-radius: 50%; background: #d4e5c9; content: ''; animation: garden-ground-pulse 1.8s ease-out infinite; }
/* 章节名**一律挂在树脚下**：名字离树更近，"这棵叫第几章"一眼就对上，
   而且同一屏里只有一种高度。（早先分两档给树上的动作气泡让路，气泡已经撤掉了。）

   `max-width` 还要跟视口挂钩：`--q` 在窄屏上被夹到 1px，光按 `--q` 算的话标签有 142px 宽，
   而手机上一棵树离屏幕边只有几十像素，章节名会被切掉半个字。 */
.garden-plant:disabled { cursor: default; opacity: .66; }.garden-plant__label { position: absolute; z-index: 4; right: 50%; bottom: calc(-26 * var(--q)); display: grid; width: max-content; max-width: min(calc(142 * var(--q)), 26vw); gap: 1px; overflow: hidden; color: #355438; font-size: calc(10 * var(--q)); font-weight: 800; line-height: 1.3; pointer-events: none; text-align: center; text-overflow: ellipsis; transform: translateX(50%); white-space: nowrap; }/* `overflow` + `text-overflow` 要落在**真正装字的那一层**上。挂在 label 上的话
   （它是个 grid 容器、字在子项里）只会硬切半个字，看不到省略号 ——
   长章节名（"大模型API调用与Prompt工程实践"）正好卡在这个宽度上。 */
.garden-plant__label b { overflow: hidden; font-weight: 800; text-overflow: ellipsis; }.garden-plant__label i { color: #6d8d65; font-size: calc(8 * var(--q)); font-style: normal; font-weight: 700; }.garden-plant:hover:not(:disabled) .garden-plant__label,.garden-slot.is-active .garden-plant__label { color: #1f5638; }

/* 锁着的树没长出来，那个"· · ·"要贴在**土面上**（树顶位置的下面一点），
   不能按画布高度的某个固定百分比放 —— 小屏上会飘在半空。 */
.garden-plant__lock { position: absolute; right: 50%; bottom: calc(var(--tree-top, 1) * 100% - 4 * var(--q)); color: #7d857d; font-size: 13px; letter-spacing: 2px; pointer-events: none; transform: translateX(50%); }
.garden-scene__hint { position: absolute; right: 17px; bottom: 13px; margin: 0; color: #537451; font-size: 10px; }.garden-scene__more { position: absolute; top: 14px; right: 15px; margin: 0; color: #5f7e5f; font-size: 11px; font-weight: 800; }

/* 空态：花园没有内边距了，这一块得自己让开边、并在整屏里居中。 */
/* 章节名**一律挂在树脚下**，不再分"高的排挂树上"。 */
.garden-empty { display: grid; width: min(760px, calc(100% - 48px)); min-height: 300px; margin: auto; grid-template-columns: 180px minmax(0, 1fr); align-items: center; gap: 20px; border: 1px solid #d8e3d5; border-radius: 7px; background: #edf4e9; padding: 15px 28px; }.garden-empty :deep(.growth-tree) { width: 190px; }.garden-empty p { max-width: 270px; color: var(--muted); font-size: 12px; line-height: 1.6; }
/* 窄屏上把最左最右那两棵**往中间收**：屏幕就这么宽，站在 11%/92% 的树连同章节名
   会被场景的 `overflow: hidden` 切掉一截。桌上的 11%/92% 是刻意的，手机上不是。 */
/* 手机上只留"第 N 章"，整名一律不显示：十几棵树挤在几百像素里，
   全名（十几个汉字）比树间距还宽，一屏看下去是一片互相压住的字。
   当前那一章的名字在顶部状态条里本来就有，其余的点开复盘页也能看到。 */
@media (max-width: 720px) { .forest-review__header { flex-wrap: wrap; gap: 10px; padding: 12px 16px; }.forest-review__status { order: 3; flex-basis: 100%; margin-left: 0; text-align: left; }.forest-review__door { order: 2; margin-left: auto; }.garden-scene__sun { top: 104px; }.garden-plant__label b { display: none; }.garden-plant__label i { font-size: calc(10 * var(--q)); color: #3d6040; }.garden-scene { min-height: max(500px, calc(320px + var(--garden-rows) * 105px)); }.garden-slot { left: clamp(16%, calc(var(--x) * 1%), 84%); width: clamp(52px, calc(30px + var(--size) * 66px), 100px); }.garden-scene__hint { display: none; }.garden-empty { width: calc(100% - 34px); grid-template-columns: 1fr; gap: 0; padding: 10px 18px 18px; text-align: center; }.garden-empty :deep(.growth-tree) { width: 160px; }.garden-empty p { margin: 0 auto; } }
@media (max-width: 430px) { .forest-review h1 { font-size: 17px; }.garden-scene { min-height: max(370px, calc(280px + var(--garden-rows) * 88px)); }.garden-slot { width: clamp(46px, calc(28px + var(--size) * 56px), 82px); }.garden-scene__sun { top: 96px; width: 46px; height: 46px; }.garden-scene__cloud { display: none; } }
@keyframes garden-ground-pulse { 0%,100% { opacity: .45; transform: scale(.88); } 50% { opacity: .9; transform: scale(1.08); } }
@media (prefers-reduced-motion: reduce) {
  .garden-slot.is-active .garden-plant::before { animation: none; }
}
</style>
