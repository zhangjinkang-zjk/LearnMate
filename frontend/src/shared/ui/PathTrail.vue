<template>
  <div ref="host" class="path-trail" :style="{ height: `${height}px` }">
    <svg
      v-if="width > 0 && stops.length"
      class="path-trail__svg"
      :width="width"
      :height="height"
      :viewBox="`0 0 ${width} ${height}`"
      role="img"
      :aria-label="label"
    >
      <!-- 底线：整条路径的虚线，从头画到尾，从不缺席 —— 站点之间因此永远有线连着，
           不会出现"这个点和下一个点之间什么都没有"的断口。走过的部分盖在它上面。 -->
      <line
        v-if="restLine"
        class="trail__rest"
        :x1="restLine.x1" :x2="restLine.x2" :y1="centerY" :y2="centerY"
      />
      <!-- 走过的部分：**一段一段地画，不是从头一刀切到某个点。** 见下方 `walkedRuns`。 -->
      <line
        v-for="run in walkedRuns"
        :key="`run-${run.x1}`"
        class="trail__walked"
        :x1="run.x1" :x2="run.x2" :y1="centerY" :y2="centerY"
        :style="{ '--trail-length': `${run.x2 - run.x1}` }"
      />

      <g
        v-for="point in stops"
        :key="point.index"
        class="trail__stop"
        :class="[`trail__stop--${point.kind}`, { 'trail__stop--hovered': hovered === point.index, 'trail__stop--focus': focused === point.index }]"
        :style="{ '--stop-delay': `${Math.min(point.index, 24) * 22}ms` }"
      >
        <circle v-if="point.kind === 'current'" class="trail__halo" :cx="point.x" :cy="centerY" :r="radius * 2.1" />
        <circle
          class="trail__dot"
          :cx="point.x"
          :cy="centerY"
          :r="point.kind === 'current' ? radius * 1.25 : radius"
        />
      </g>
    </svg>

    <!-- 站点本体是真正的 <button>，浮在图形上：这样键盘能 Tab 到、读屏能念、
         hover 有 title 提示，而且焦点环交给浏览器画，不用在 SVG 里手搓。 -->
    <div v-if="stops.length" class="path-trail__stops">
      <button
        v-for="point in stops"
        :key="point.index"
        class="path-trail__stop-hit"
        :class="{ 'path-trail__stop-hit--locked': point.kind === 'locked' }"
        :style="{ left: `${point.x}px` }"
        type="button"
        :disabled="point.kind === 'locked'"
        :title="stopTitle(point)"
        @mouseenter="highlight(point, 'hovered', true)"
        @mouseleave="highlight(point, 'hovered', false)"
        @focus="highlight(point, 'focused', true)"
        @blur="highlight(point, 'focused', false)"
        @click="select(point)"
      >
        <span class="sr-only">{{ stopTitle(point) }}</span>
      </button>
    </div>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'

/**
 * 一条学习路径画成的路线图。
 *
 * 存在的理由：这一页原来的"轨道"是 13 个等宽 `div` 拼的彩条 —— 那是个进度条，
 * 不是路径。学习路径产品里，路径本身就是最该被画出来的东西：哪几站走过了、
 * 现在站在哪、前面还剩几站，一条线全说完，比任何数字都快。
 *
 * 宽度是量出来的（ResizeObserver）而不是用 viewBox 缩放的：`<circle>` 在非等比
 * 缩放下会变成椭圆，等比缩放又会让窄屏上的圆点小到看不见。
 *
 * 组件不认识路由：点某一站只往外抛 `select`，跳去哪由页面决定。
 */
const props = defineProps({
  // [{ id, title, status }]，后端 `paths[].nodes` 原样传进来
  nodes: { type: Array, default: () => [] },
  // 读屏用的一句话，例如「大语言模型原理与微调的学习进度」
  label: { type: String, default: '' },
})

const emit = defineEmits(['select'])

const host = ref(null)
const width = ref(0)
const hovered = ref(null)
const focused = ref(null)
const height = 40
const centerY = height / 2

// **所有"已完成"站点的半径一样大**。以前是按节点数分档（13 站给 7.5、18 站给 6），
// 结果是同一页上"已完成"的点在四条路径里画成三种大小 —— 同一个状态在不同行长得不同
// 是纯粹的噪声，读者只会以为它俩不是一回事。
// 只在站点密到会连成一条实心带时才整体缩小，那是排版下限，不是分档。
const radius = computed(() => (props.nodes.length > 40 ? 4.5 : 7))

// 后端的四种状态 → 四种画法。**四个都要分开画**，两两合并都会让读者读错：
//   completed   → done       实心深绿
//   in_progress → current    实心柠檬绿 + 光环（"你正站在这一站"）
//   unlocked    → available  空心 + 柠檬绿环（"这一站能点了，还没开始"）
//   locked      → locked     空心 + 灰环
//
// 以前 `unlocked` 和 `in_progress` 都画成 `current`，于是**一条路径上有几个未开始的
// 节点，就亮几个柠檬绿"当前站"**。实测 Transformer 那条路径上同时亮着两个，而右边
// 「当前节点」那一列只写着一个节点名 —— 同一行自己跟自己打架。
const KIND_BY_STATUS = { completed: 'done', in_progress: 'current', unlocked: 'available' }
const STATUS_LABEL = { completed: '已完成', in_progress: '正在这里', unlocked: '可开始', locked: '未解锁' }

const kindOf = (status) => KIND_BY_STATUS[status] || 'locked'
const labelOf = (status) => STATUS_LABEL[status] || '未解锁'

const points = computed(() => {
  const count = props.nodes.length
  if (count < 2 || width.value <= 0) return []
  // 两端各留一个半径，首尾两站才不会贴着边框被切掉。
  const inset = radius.value + 3
  const span = Math.max(0, width.value - inset * 2)
  return props.nodes.map((node, index) => {
    const status = String(node?.status || '')
    return {
      index,
      node,
      status,
      kind: kindOf(status),
      x: inset + (span * index) / (count - 1),
    }
  })
})

/**
 * **"正在这里"全局只有一个。**
 *
 * 后端取当前节点用的是 `path/service.py` 里那句"路径上第一个 in_progress / unlocked
 * 的节点"，学习方向表右边「当前节点」那一列显示的也是它。路线图必须和后端同源 ——
 * 否则同一行会给出两个互相矛盾的答案。
 *
 * 于是：第一个 in_progress/unlocked 升格为 `current`，其余 `in_progress` 降为
 * `available`（`unlocked` 本来就是）。它们仍然可点。
 */
const stops = computed(() => {
  const list = points.value
  const currentIndex = list.findIndex((point) => point.kind === 'current' || point.kind === 'available')
  if (currentIndex < 0) return list
  return list.map((point, index) => {
    if (index === currentIndex) return { ...point, kind: 'current' }
    if (point.kind === 'current') return { ...point, kind: 'available' }
    return point
  })
})

const stopTitle = (point) => {
  const name = String(point.node?.title || '').trim()
  const position = `第 ${point.index + 1} / ${stops.value.length} 站`
  return [position, name, labelOf(point.status)].filter(Boolean).join(' · ')
}

// 未解锁的站点点了没有去处 —— 后端也不让进，所以直接不给点。
const canSelect = (point) => point.kind !== 'locked' && Boolean(point.node?.id)

function select(point) {
  if (!canSelect(point)) return
  emit('select', point.node)
}

/**
 * 指针反馈只发给**能点的站**。
 *
 * 未解锁的站是唯一不该亮的点，可它偏偏最容易被点亮：鼠标只是扫过，那条灰环就变成柠檬
 * 绿环（hover 规则是通配的，`--locked` 没有自己的例外），屏幕上唯一的"能点"信号被点亮在
 * 一个点不动的站上 —— 读者只能以为它可进。实测就是这么误报的。
 *
 * `disabled` 的 `<button>` 到底会不会派发 mouseenter，各浏览器并不一致，所以不依赖它：
 * 事件即使来了，这里也直接丢弃。
 */
function highlight(point, key, isOn) {
  if (isOn && !canSelect(point)) return
  const target = key === 'hovered' ? hovered : focused
  target.value = isOn ? point.index : null
}

/**
 * 走过的实线 = **连续的"已完成"站点，每一段单独画一条**。
 *
 * 这里原来是"从第一站一刀切到当前站"。它默认完成顺序和路径顺序一致，而**这个前提是
 * 假的**：`path/service.py` 建节点时写着 `status = "unlocked" if (i == 0 or not has_prereqs)
 * else "locked"` —— 路径中段没有前置的节点一出生就是"可学"，学生可以先做第 12 站再回头
 * 做第 11 站。实测那条 Transformer 路径的序列就是「已完成 ×10 → 未解锁 ×5 → 可开始 ×2 →
 * 未解锁 ×1」，那条一刀切的实线于是**从 5 个没做过的空心站点身上碾了过去**，
 * 而右侧同一行写的是 56%。
 *
 * 改成分段之后，绿线只落在真正走过去的那几站之间；中间没走的那些，虚线照旧穿过去，
 * 谁也不冒充谁。
 */
const walkedRuns = computed(() => {
  const runs = []
  let open = null
  for (const point of stops.value) {
    if (point.kind === 'done') {
      if (open) open.x2 = point.x
      else open = { x1: point.x, x2: point.x }
      continue
    }
    if (open) {
      runs.push(open)
      open = null
    }
  }
  if (open) runs.push(open)
  // 单站构成的"段"画不出线（x1 === x2），丢掉；它自己那颗圆点已经说明问题了。
  return runs.filter((run) => run.x2 > run.x1)
})

// 虚线底线：整条路径从头到尾。它只负责"站点之间有线连着"，不表示走过没走过。
const restLine = computed(() => {
  const list = stops.value
  if (list.length < 2) return null
  const start = list[0].x
  const end = list[list.length - 1].x
  return end > start ? { x1: start, x2: end } : null
})

onMounted(() => {
  if (!host.value) return
  const observer = new ResizeObserver(([entry]) => {
    width.value = Math.round(entry.contentRect.width)
  })
  observer.observe(host.value)
  width.value = Math.round(host.value.getBoundingClientRect().width)
  onBeforeUnmount(() => observer.disconnect())
})
</script>

<style scoped>
.path-trail { position: relative; width: 100%; min-width: 0; }
.path-trail__svg { display: block; overflow: visible; pointer-events: none; }

.trail__rest { stroke: #d7e0d4; stroke-width: 3; stroke-dasharray: 4 7; stroke-linecap: round; }
/* 走过的部分：实线，进场时从起点"画"出来。
   **颜色写在 CSS 里（`var(--accent-deep)`），没有渐变。** 这里原来用
   `stroke="url(#渐变)"`，那支渐变既有两个毛病、又是个纯装饰：
   ① 末端那支是 `#94b32c` —— **不在调色板里**（只有 `--accent-deep` / `--accent`
      两支绿），于是屏幕上同时出现四种绿，读者只能问"为什么深绿浅绿都有"；
   ② 渐变让线尾的颜色跟着"当前站停在哪"变，**同样是"走过的路"，四条行颜色
      各不相同** —— 和之前"同一个状态画成两种大小"是同一类错误。
   现在走过的路一律深绿，和"已完成"的圆点同一个色，连成一条链；
   柠檬绿只留给"当前站"那一个圆点。 */
.trail__walked { stroke: var(--accent-deep); stroke-width: 3.5; stroke-linecap: round; animation: trail-draw .9s cubic-bezier(.4, 0, .2, 1) both; }
@keyframes trail-draw {
  from { stroke-dasharray: var(--trail-length); stroke-dashoffset: var(--trail-length); }
  to { stroke-dasharray: var(--trail-length); stroke-dashoffset: 0; }
}

.trail__dot { fill: #ffffff; stroke: #ffffff; stroke-width: 3; }
.trail__stop--done .trail__dot { fill: var(--accent-deep); stroke: var(--accent-deep); }
/* 可开始：空心 + 柠檬绿环。它和"锁定"（灰环）都还没做，但一个能点一个不能 ——
   在点开之前就该看出来。 */
.trail__stop--available .trail__dot { fill: #ffffff; stroke: var(--accent); stroke-width: 2.5; }
/* 未解锁：空心 + 灰环。**它是唯一不参与指针反馈的状态**，所以这条的选择器多带一个
   `.trail__stop` 把权重提到 (0,3,0) —— 下面那条 hover 通配规则（(0,2,0)）本来会把灰环
   染成柠檬绿，而柠檬绿环在这一页的语义就是"这里能点"。脚本里已经挡了一道
   （见 `highlight()`），CSS 这道是不让它在样式层再漏回来。 */
.trail__stop.trail__stop--locked .trail__dot { fill: #ffffff; stroke: #cfd9cb; stroke-width: 3; }
.trail__stop--current .trail__dot { fill: var(--accent); stroke: #ffffff; stroke-width: 3.5; }
/* 指针停在哪一站，那一站就套上柠檬绿的环 —— 哪几站能点，鼠标扫过去就看得出来。
   不用 transform 放大：入场动画带 `fill-mode: both`，动画结束后它一直占着
   transform，悬停的 scale 会被压掉。改描边没这个问题。 */
.trail__stop--hovered .trail__dot,
.trail__stop--focus .trail__dot { stroke: var(--accent); stroke-width: 4.5; }
.trail__stop--hovered.trail__stop--current .trail__dot,
.trail__stop--focus.trail__stop--current .trail__dot { stroke: #ffffff; stroke-width: 4.5; }
.trail__stop--hovered .trail__halo,
.trail__stop--focus .trail__halo { opacity: .34; }

.trail__halo { fill: var(--accent); opacity: .18; transform-box: fill-box; transform-origin: center; animation: trail-breathe 2.4s ease-in-out infinite; }
@keyframes trail-breathe {
  0%, 100% { transform: scale(.82); opacity: .12; }
  50% { transform: scale(1.12); opacity: .26; }
}

/* 站点逐个亮起，接在"画线"后面 —— 整页只有这一次入场动效，不散着加。 */
.trail__stop { animation: trail-stop-in .34s ease-out both; animation-delay: var(--stop-delay); }
@keyframes trail-stop-in {
  from { opacity: 0; transform: translateY(-3px); }
  to { opacity: 1; transform: none; }
}

/* 点击热区：只负责命中，本身不可见。宽 30px 覆盖住圆点，比鼠标精确瞄准一个
   7px 的圆点现实得多。 */
.path-trail__stops { position: absolute; inset: 0; }
.path-trail__stop-hit {
  position: absolute;
  top: 0;
  width: 30px;
  height: 100%;
  padding: 0;
  border: 0;
  background: transparent;
  cursor: pointer;
  transform: translateX(-50%);
}
.path-trail__stop-hit--locked { cursor: default; }
.path-trail__stop-hit:focus-visible { outline: 2px solid var(--accent-deep); outline-offset: 1px; border-radius: 4px; }

@media (prefers-reduced-motion: reduce) {
  .trail__walked, .trail__stop { animation: none; }
  .trail__halo { animation: none; opacity: .2; }
}
</style>
