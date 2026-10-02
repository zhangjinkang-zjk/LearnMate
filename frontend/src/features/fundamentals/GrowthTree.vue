<!--
  一棵学习树。

  **纯展示组件**：给什么 `node` 就画什么，自己不取数、不判断该长成什么样。
  形态全由 `treeGrowth.js`（数据 → 骨架）和 `treeRender.js`（骨架 → SVG）决定，
  这两个是纯函数，所以同一棵树在任何地方画出来都一样，也能脱离浏览器测。

  每个视觉通道只承载一个意思（详见 treeGrowth.js 顶部的说明）：
    主干高度 + 分枝层数 = 做了多少     叶 = 答对率（**没测过一片叶都没有**）
    枯枝 = 哪一块薄弱                  果 = 这一章过关了

  `growth`（0~1）是**生长进度**，不是完成度：同一棵树在 growth=0.6 时画出来，
  就是它长到六成大的样子。进花园时从"上次看到的高度"演到当前，靠的就是它。
-->
<template>
  <svg
    class="growth-tree"
    :viewBox="VIEW_BOX"
    :style="{ aspectRatio: VIEW_ASPECT }"
    preserveAspectRatio="xMidYMax meet"
    :role="label ? 'img' : undefined"
    :aria-label="label || undefined"
    :aria-hidden="label ? undefined : 'true'"
  >
    <ellipse
      class="growth-tree__ground"
      cx="0"
      :cy="ground.cy"
      :rx="ground.rx"
      :ry="ground.ry"
    />
    <path
      v-for="branch in branches"
      :key="branch.key"
      class="growth-tree__branch"
      :class="[`is-depth-${branch.depth}`, { 'is-withered': branch.withered }]"
      :d="branch.d"
    />
    <path
      v-for="layer in canopy"
      :key="layer.key"
      class="growth-tree__canopy"
      :class="`is-tier-${layer.tier}`"
      :d="layer.d"
      :style="{ strokeWidth: layer.weld || 0 }"
    />
    <path
      v-if="fruit.count"
      class="growth-tree__fruit"
      :d="fruit.d"
      :opacity="reveal"
    />
  </svg>
</template>

<script setup>
import { computed } from 'vue'
import { growTree } from './treeGrowth.js'
import {
  VIEW_BOX,
  VIEW_ASPECT,
  buildBranchPaths,
  buildCanopy,
  buildCanopyPaths,
  buildFruitPath,
  buildGround,
} from './treeRender.js'

const props = defineProps({
  node: { type: Object, required: true },
  /** 全局薄弱点（`diagnosis.weak_points`）。命中本节点知识点的，那根一级枝会枯。 */
  weakPoints: { type: Array, default: () => [] },
  /** 生长进度 0~1。1 = 长到当前应有的形态。 */
  growth: { type: Number, default: 1 },
  /**
   * 果实单独一个进度：过关那一步树**高度不变**（生长进度已经是 1 了），
   * 果实跟着 growth 走的话等于永远定格在全亮，最该庆祝的一步反而没动画。
   */
  reveal: { type: Number, default: 1 },
  /**
   * 叶团的粗细。`coarse` 用在花园缩略图（一棵最宽 124px，团多了是亚像素的浪费，
   * 逐帧还要重拼 12 棵树的 path）；`fine` 用在复盘页那种大图。
   */
  detail: { type: String, default: 'coarse' },
  /** 无障碍标签。留空时整个 svg 当装饰（宿主按钮已经念过一遍了）。 */
  label: { type: String, default: '' },
})

// 骨架只随 node 变 —— 逐帧变的只有 growth，别把整棵树重算一遍。
const tree = computed(() => growTree(props.node, { weakPoints: props.weakPoints }))
const blobs = computed(() => buildCanopy(tree.value, props.detail))
const ground = computed(() => buildGround(tree.value))
const fruit = computed(() => buildFruitPath(tree.value.fruits))

const branches = computed(() => buildBranchPaths(tree.value.segments, props.growth))
const canopy = computed(() => buildCanopyPaths(blobs.value, props.growth))
</script>

<style scoped>
/*
  配色是**上一代手绘树（已删的 ForestTree）那套**（叶片渐变 #83ad6f→#5d8f57→#3f7049、
  树干 #87593c、果 #e5b25d），照搬过来只为不换视觉语言；木色在 main.css 里没有对应
  token，所以留在组件局部，不污染全局。
*/
.growth-tree {
  --tree-trunk: #87593c;
  --tree-branch: #8a6242;
  --tree-twig: #9a8a70;
  /* 枯枝：**枯木的灰褐**，不是冷灰。冷灰（原来那个 #9aa39d）在浅绿背景上像线框，
     不像一根死掉的枝。压暗一点也让它在一片绿里有分量。 */
  --tree-dead: #8d8175;
  --tree-canopy-deep: #3f7049;
  --tree-canopy-mid: #5d8f57;
  --tree-canopy-light: #88b67b;
  --tree-fruit: #e5b25d;
  display: block;
  /* 高度跟着 viewBox 的宽高比走（内联的 aspect-ratio）—— 宿主只要给宽度就行，
     不用再写一个必须和 VIEW_BOX 对得上、改一处忘一处的 aspect-ratio。 */
  width: 100%;
  height: auto;
  overflow: visible;
}

.growth-tree__ground { fill: #5d754f; opacity: .18; }

.growth-tree__branch { fill: var(--tree-branch); }
.growth-tree__branch.is-depth-0 { fill: var(--tree-trunk); }
.growth-tree__branch.is-depth-3 { fill: var(--tree-twig); }
.growth-tree__branch.is-withered { fill: var(--tree-dead); opacity: .85; }

/* 描边**必须和填充同色**：它只干一件事 —— 把相邻的叶团焊成一块
   （见 treeRender.js 里 CANOPY_WELD）。换成深色描边，一冠的碎玻璃。 */
.growth-tree__canopy { stroke-linejoin: round; }
.growth-tree__canopy.is-tier-0 { fill: var(--tree-canopy-deep); stroke: var(--tree-canopy-deep); }
.growth-tree__canopy.is-tier-1 { fill: var(--tree-canopy-mid); stroke: var(--tree-canopy-mid); }
.growth-tree__canopy.is-tier-2 { fill: var(--tree-canopy-light); stroke: var(--tree-canopy-light); }

.growth-tree__fruit { fill: var(--tree-fruit); }
</style>
