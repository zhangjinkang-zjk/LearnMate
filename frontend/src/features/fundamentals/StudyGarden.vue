<template>
  <section class="forest-review surface" aria-labelledby="forest-review-title">
    <header class="forest-review__header">
      <div>
        <p class="eyebrow">LEARNING FOREST</p>
        <h2 id="forest-review-title">学习树林</h2>
      </div>
      <p v-if="activeNode" class="forest-review__status" aria-live="polite">
        <strong>{{ activeNode.title }}</strong>
        <span>{{ stageTitle }}</span>
      </p>
      <div class="forest-review__count" aria-label="已完成章节数量">
        <strong>{{ completedNodes.length }}</strong><span>/ {{ nodes.length }}</span>
      </div>
    </header>

    <div v-if="nodes.length" class="garden-scene" role="list" aria-label="学习树林">
      <span class="garden-scene__sun" aria-hidden="true"></span>
      <span class="garden-scene__cloud garden-scene__cloud--one" aria-hidden="true"></span>
      <span class="garden-scene__cloud garden-scene__cloud--two" aria-hidden="true"></span>
      <span class="garden-scene__hill garden-scene__hill--back" aria-hidden="true"></span>
      <span class="garden-scene__hill garden-scene__hill--front" aria-hidden="true"></span>
      <span class="garden-scene__path" aria-hidden="true"></span>

      <button
        v-for="(node, index) in visibleNodes"
        :key="node.id"
        class="garden-plant"
        :class="[
          `is-stage-${nodeStage(node)}`,
          {
            'is-active': String(node.id) === String(activeNode?.id),
            'is-locked': node.status === 'locked',
            'has-label-above': plantPositions[index].label === 'above',
          },
        ]"
        :style="plantStyle(index, node)"
        type="button"
        role="listitem"
        :aria-pressed="String(node.id) === String(activeNode?.id)"
        :aria-label="`${node.title}，${nodeStageLabel(node)}`"
        :disabled="node.status === 'locked'"
        @click="$emit('select', node.id)"
      >
        <ForestTree :key="`${node.id}-${nodeStage(node)}`" :stage="nodeStage(node)" :variant="treeVariant(node, index)" :label="''" />
        <span class="garden-plant__label"><i>第 {{ index + 1 }} 章</i>{{ node.title }}</span>
        <span v-if="node.status === 'locked'" class="garden-plant__lock" aria-hidden="true">· · ·</span>
      </button>

      <p v-if="hiddenNodeCount" class="garden-scene__more">+ {{ hiddenNodeCount }} 个节点</p>
    </div>

    <div v-else class="garden-empty">
      <ForestTree :stage="0" label="等待播种的土壤" />
      <p>学习路径生成后，这里会长出第一株幼苗。</p>
    </div>
  </section>
</template>

<script setup>
import { computed } from 'vue'
import ForestTree from '@/features/fundamentals/ForestTree.vue'

const plantPositions = [
  { x: 10, row: 0, size: 0.9, label: 'below' }, { x: 24, row: 2, size: 0.72, label: 'above' }, { x: 39, row: 0, size: 1.04, label: 'below' },
  { x: 55, row: 3, size: 0.8, label: 'above' }, { x: 70, row: 1, size: 1.12, label: 'below' }, { x: 88, row: 3, size: 0.76, label: 'above' },
  { x: 17, row: 5, size: 1.02, label: 'above' }, { x: 33, row: 6, size: 0.82, label: 'above' }, { x: 49, row: 5, size: 0.92, label: 'above' },
  { x: 64, row: 7, size: 0.72, label: 'above' }, { x: 78, row: 5, size: 1.05, label: 'above' }, { x: 91, row: 7, size: 0.72, label: 'above' },
]

const props = defineProps({
  nodes: { type: Array, default: () => [] },
  activeNodeId: { type: [String, Number], default: null },
})

defineEmits(['select'])

const completedNodes = computed(() => props.nodes.filter((node) => node.status === 'completed'))
const visibleNodes = computed(() => props.nodes.slice(0, plantPositions.length))
const hiddenNodeCount = computed(() => Math.max(0, props.nodes.length - visibleNodes.value.length))
const activeNode = computed(() => {
  if (props.activeNodeId === null || props.activeNodeId === undefined) return null
  return props.nodes.find((node) => String(node.id) === String(props.activeNodeId)) || null
})
const stageTitle = computed(() => nodeStageLabel(activeNode.value || {}))

function nodeStage(node) {
  if (node.status === 'completed') return 4
  const progress = node.garden_progress
  if (progress?.total_tasks > 0) {
    if (progress.completed_tasks <= 0) return 1
    if (progress.quiz_answered > 0 || progress.completed_tasks >= progress.total_tasks) return 3
    return 2
  }
  if (node.resources_viewed || node.status === 'in_progress') return 2
  if (node.status === 'unlocked') return 1
  return 0
}

function nodeStageLabel(node) {
  return ['等待播种', '刚种下的小苗', '幼苗正在抽芽', '树苗等待复盘完成', '这棵树已经长成'][nodeStage(node)]
}

function plantStyle(index, node) {
  const position = plantPositions[index]
  const stage = nodeStage(node)
  const size = Math.max(0.28, position.size * [0.28, 0.38, 0.64, 1.02, 1.5][stage])
  return { '--x': position.x, '--row': position.row, '--size': size }
}

function treeVariant(node, offset) {
  const id = Number(node?.id) || offset
  return ['round', 'pine', 'willow'][Math.abs(id + offset) % 3]
}
</script>

<style scoped>
.forest-review { padding: 24px; }
.forest-review__header { display: flex; align-items: center; gap: 18px; margin-bottom: 16px; }
.forest-review h2 { margin: 0; color: var(--ink); font-size: 20px; }
.forest-review__status { display: grid; min-width: 0; flex: 1; gap: 3px; margin: 0 0 0 auto; text-align: right; }
.forest-review__status strong { overflow: hidden; color: var(--ink); font-size: 12px; text-overflow: ellipsis; white-space: nowrap; }
.forest-review__status span { color: #6e8b6f; font-size: 11px; }
.forest-review__count { flex: 0 0 auto; color: var(--muted); font-size: 13px; }
.forest-review__count strong { color: var(--accent-deep); font-size: 28px; line-height: 1; }
.forest-review__count span { margin-left: 3px; }

.garden-scene { position: relative; min-height: 460px; overflow: hidden; isolation: isolate; border: 1px solid #d8e3d5; border-radius: 7px; background: #edf4e9; }
.garden-scene::before { position: absolute; z-index: -4; inset: 0; background-image: linear-gradient(#ffffff55 1px, transparent 1px), linear-gradient(90deg, #ffffff55 1px, transparent 1px); background-size: 28px 28px; content: ''; opacity: .36; }
.garden-scene__sun { position: absolute; z-index: -3; top: 36px; right: 10%; width: 72px; height: 72px; border-radius: 50%; background: #f1d78b; opacity: .64; }
.garden-scene__cloud { position: absolute; z-index: -3; width: 86px; height: 19px; border-radius: 50%; background: #fff; opacity: .6; }
.garden-scene__cloud::before,.garden-scene__cloud::after { position: absolute; bottom: 0; border-radius: 50%; background: inherit; content: ''; }
.garden-scene__cloud::before { left: 16px; width: 32px; height: 32px; }.garden-scene__cloud::after { right: 13px; width: 42px; height: 26px; }
.garden-scene__cloud--one { top: 72px; left: 11%; }.garden-scene__cloud--two { top: 128px; right: 28%; transform: scale(.6); }
.garden-scene__hill { position: absolute; z-index: -2; right: -8%; bottom: 19%; left: -8%; height: 46%; border-radius: 50% 50% 0 0; }
.garden-scene__hill--back { background: #c8dfc1; transform: rotate(-3deg); }.garden-scene__hill--front { bottom: -20%; height: 56%; background: #a8cb9f; transform: rotate(2deg); }
.garden-scene__path { position: absolute; z-index: -1; bottom: -18%; left: 44%; width: 22%; height: 63%; border: 2px solid #cbad7d; border-radius: 50% 50% 0 0; background: #ddc391; transform: rotate(9deg); opacity: .55; }

.garden-plant { position: absolute; z-index: 1; bottom: calc(9% + var(--row) * 4.8%); left: calc(var(--x) * 1%); display: block; width: clamp(32px, calc(28px + var(--size) * 78px), 154px); aspect-ratio: 180 / 235; padding: 0; border: 0; background: transparent; color: var(--ink); cursor: pointer; transform: translateX(-50%); transition: transform 180ms ease, filter 180ms ease; }
.garden-plant :deep(.forest-tree) { height: 100%; }.garden-plant:hover:not(:disabled) { z-index: 3; filter: saturate(1.12); transform: translateX(-50%) translateY(-7px) scale(1.04); }.garden-plant:focus-visible { z-index: 4; outline: 2px solid var(--accent-deep); outline-offset: 4px; }
.garden-plant.is-active { z-index: 3; filter: saturate(1.12); }.garden-plant.is-active::before { position: absolute; z-index: -1; right: 6%; bottom: 4%; left: 6%; height: 22%; border: 1px dashed #507950; border-radius: 50%; background: #d4e5c9; content: ''; animation: garden-ground-pulse 1.8s ease-out infinite; }
.garden-plant:disabled { cursor: default; opacity: .66; }.garden-plant__label { position: absolute; z-index: 4; right: 50%; bottom: -33px; display: grid; width: max-content; max-width: 142px; gap: 1px; overflow: hidden; color: #355438; font-size: 10px; font-weight: 800; line-height: 1.3; text-align: center; text-overflow: ellipsis; transform: translateX(50%); white-space: nowrap; }.garden-plant__label i { color: #6d8d65; font-size: 8px; font-style: normal; font-weight: 700; }.garden-plant:hover:not(:disabled) .garden-plant__label,.garden-plant.is-active .garden-plant__label { color: #1f5638; }.garden-plant.has-label-above .garden-plant__label { bottom: calc(100% + 7px); }
.garden-plant__lock { position: absolute; top: 43%; right: 50%; color: #7d857d; font-size: 13px; letter-spacing: 2px; transform: translateX(50%); }
.garden-scene__hint { position: absolute; right: 17px; bottom: 13px; margin: 0; color: #537451; font-size: 10px; }.garden-scene__more { position: absolute; top: 14px; right: 15px; margin: 0; color: #5f7e5f; font-size: 11px; font-weight: 800; }

.garden-empty { display: grid; min-height: 300px; grid-template-columns: 180px minmax(0, 1fr); align-items: center; gap: 20px; border: 1px solid #d8e3d5; border-radius: 7px; background: #edf4e9; padding: 15px 28px; }.garden-empty :deep(.forest-tree) { height: 210px; }.garden-empty p { max-width: 270px; color: var(--muted); font-size: 12px; line-height: 1.6; }
@media (max-width: 720px) { .forest-review { padding: 17px; }.forest-review__header { gap: 11px; flex-wrap: wrap; }.forest-review__status { order: 3; flex-basis: 100%; margin-left: 0; text-align: left; }.garden-scene { min-height: 420px; }.garden-scene__hint { display: none; }.garden-plant:nth-of-type(n + 12) { display: none; }.garden-empty { grid-template-columns: 1fr; gap: 0; padding: 10px 18px 18px; text-align: center; }.garden-empty :deep(.forest-tree) { height: 175px; }.garden-empty p { margin: 0 auto; } }
@media (max-width: 430px) { .garden-scene { min-height: 370px; }.garden-plant { width: clamp(44px, calc(30px + var(--size) * 46px), 82px); }.garden-scene__sun { top: 26px; width: 52px; height: 52px; }.garden-scene__cloud { display: none; } }
@keyframes garden-ground-pulse { 0%,100% { opacity: .45; transform: scale(.88); } 50% { opacity: .9; transform: scale(1.08); } }
@media (prefers-reduced-motion: reduce) { .garden-plant.is-active::before { animation: none; } }
</style>
