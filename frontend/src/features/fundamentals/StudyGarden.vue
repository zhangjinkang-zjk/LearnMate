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

      <button
        v-for="(node, index) in visibleNodes"
        :key="node.id"
        class="garden-plant"
        :class="[
          `is-stage-${nodeStage(node)}`,
          {
            'is-active': String(node.id) === String(activeNode?.id),
            'is-locked': node.status === 'locked',
            'has-label-above': plantPosition(index, visibleNodes.length).label === 'above',
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

const sizeOffsets = [0.96, 1.02, 0.98, 1.04, 0.97, 1.03]

const props = defineProps({
  nodes: { type: Array, default: () => [] },
  activeNodeId: { type: [String, Number], default: null },
})

defineEmits(['select'])

const completedNodes = computed(() => props.nodes.filter((node) => node.status === 'completed'))
const visibleNodes = computed(() => props.nodes)
const gardenRowCount = computed(() => Math.max(1, Math.ceil(visibleNodes.value.length / 4)))
const gardenSceneStyle = computed(() => ({ '--garden-rows': gardenRowCount.value }))
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
  const position = plantPosition(index, visibleNodes.value.length)
  const stage = nodeStage(node)
  const depthScale = 0.7 + ((100 - position.y) / 100) * 0.3
  const size = Math.max(0.2, position.size * depthScale * [0.24, 0.31, 0.46, 0.64, 0.82][stage])
  return {
    '--x': position.x,
    '--y': position.y,
    '--size': size,
    '--tilt': `${position.tilt}deg`,
    '--depth-order': Math.round(100 - position.y),
  }
}

function plantPosition(index, total) {
  const point = FIELD_POINTS[index]
  if (point) return point

  // Keep long paths organic without letting later chapters stack on top of one another.
  const x = 9 + ((index * 37) % 82)
  const y = 13 + ((index * 23) % 52)
  return {
    x,
    y,
    size: sizeOffsets[index % sizeOffsets.length] * 0.92,
    tilt: index % 2 ? 1.2 : -0.9,
    label: y < 57 ? 'above' : 'below',
  }
}

function treeVariant(node, offset) {
  const id = Number(node?.id) || offset
  return ['round', 'pine', 'willow'][Math.abs(id + offset) % 3]
}

const FIELD_POINTS = [
  // The chapter sequence travels from the distant ridge toward the foreground.
  { x: 13, y: 57, size: 0.68, tilt: -1.1, label: 'above' },
  { x: 36, y: 62, size: 0.76, tilt: 1.3, label: 'above' },
  { x: 61, y: 55, size: 0.64, tilt: -0.8, label: 'above' },
  { x: 85, y: 60, size: 0.72, tilt: 1.1, label: 'above' },
  { x: 20, y: 40, size: 0.74, tilt: 0.8, label: 'above' },
  { x: 45, y: 46, size: 0.82, tilt: -1.4, label: 'above' },
  { x: 69, y: 38, size: 0.7, tilt: 1.2, label: 'above' },
  { x: 91, y: 44, size: 0.76, tilt: -0.7, label: 'above' },
  { x: 12, y: 24, size: 0.78, tilt: 1.2, label: 'above' },
  { x: 37, y: 30, size: 0.86, tilt: -1.1, label: 'above' },
  { x: 62, y: 22, size: 0.74, tilt: 0.9, label: 'above' },
  { x: 84, y: 28, size: 0.82, tilt: -1.3, label: 'above' },
]
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

.garden-scene { position: relative; min-height: max(560px, calc(350px + var(--garden-rows) * 112px)); overflow: hidden; isolation: isolate; border: 1px solid #d8e3d5; border-radius: 7px; background: linear-gradient(180deg, #eef4eb 0%, #e8f0e4 42%, #dbe8d6 100%); }
.garden-scene::before { position: absolute; z-index: -4; inset: 0; background: radial-gradient(circle at 73% 12%, rgba(255,255,255,.42), transparent 25%), linear-gradient(165deg, transparent 44%, rgba(255,255,255,.24) 44.2%, transparent 44.6%); content: ''; opacity: .8; }
.garden-scene__sun { position: absolute; z-index: -3; top: 38px; right: 11%; width: 58px; height: 58px; border-radius: 50%; background: #efd992; box-shadow: 0 0 0 12px rgba(239,217,146,.12), 0 0 30px rgba(239,217,146,.16); opacity: .7; }
.garden-scene__cloud { position: absolute; z-index: -3; width: 86px; height: 19px; border-radius: 50%; background: #fff; opacity: .6; }
.garden-scene__cloud::before,.garden-scene__cloud::after { position: absolute; bottom: 0; border-radius: 50%; background: inherit; content: ''; }
.garden-scene__cloud::before { left: 16px; width: 32px; height: 32px; }.garden-scene__cloud::after { right: 13px; width: 42px; height: 26px; }
.garden-scene__cloud--one { top: 72px; left: 11%; }.garden-scene__cloud--two { top: 128px; right: 28%; transform: scale(.6); }
.garden-scene__hill { position: absolute; z-index: -3; right: -8%; bottom: 28%; left: -8%; height: 29%; border-radius: 50% 50% 0 0; }
.garden-scene__hill--back { background: #c5dbbd; transform: rotate(-3deg); }.garden-scene__hill--front { bottom: 17%; height: 22%; background: #b3d0a9; transform: rotate(2deg); }
.garden-scene__field { position: absolute; z-index: -2; right: -12%; bottom: -18%; left: -12%; height: 68%; border-radius: 54% 46% 0 0 / 16% 13% 0 0; background-color: #9fbe91; background-image: radial-gradient(ellipse at 18% 38%, rgba(232,242,218,.22), transparent 36%), repeating-linear-gradient(166deg, transparent 0 34px, rgba(81,123,72,.075) 35px 37px, transparent 38px 72px); box-shadow: inset 0 18px 0 rgba(224,236,211,.25); transform: rotate(-1.2deg); }
.garden-scene__furrow { position: absolute; z-index: -1; width: 74%; height: 24%; border-top: 1px solid rgba(75,112,68,.22); border-radius: 50%; opacity: .6; pointer-events: none; }
.garden-scene__furrow--one { right: -5%; bottom: 15%; transform: rotate(-4deg); }.garden-scene__furrow--two { bottom: 2%; left: -7%; transform: rotate(3deg); }
.garden-scene__path { position: absolute; z-index: -1; bottom: -23%; left: 48%; width: 15%; height: 65%; border: 1px solid rgba(176,139,92,.55); border-radius: 50% 47% 0 0; background: linear-gradient(105deg, rgba(188,148,98,.62), rgba(218,191,145,.78) 48%, rgba(186,143,94,.52)); box-shadow: inset 5px 0 0 rgba(250,235,192,.18); transform: rotate(8deg); opacity: .74; }

.garden-plant { position: absolute; z-index: calc(1 + var(--depth-order)); bottom: calc(5% + var(--y) * .78%); left: calc(var(--x) * 1%); display: block; width: clamp(58px, calc(42px + var(--size) * 92px), 124px); aspect-ratio: 180 / 220; padding: 0; border: 0; background: transparent; color: var(--ink); cursor: pointer; touch-action: manipulation; transform: translateX(-50%) rotate(var(--tilt)); transform-origin: 50% 100%; transition: transform 180ms ease, filter 180ms ease; }
.garden-plant :deep(.forest-tree) { height: 100%; pointer-events: none; }.garden-plant:hover:not(:disabled) { z-index: 120; filter: saturate(1.12); transform: translateX(-50%) translateY(-7px) rotate(var(--tilt)) scale(1.04); }.garden-plant:focus-visible { z-index: 121; outline: 2px solid var(--accent-deep); outline-offset: 4px; }
.garden-plant.is-active { z-index: 122; filter: saturate(1.12); }.garden-plant.is-active::before { position: absolute; z-index: -1; right: 6%; bottom: 4%; left: 6%; height: 22%; border: 1px dashed #507950; border-radius: 50%; background: #d4e5c9; content: ''; animation: garden-ground-pulse 1.8s ease-out infinite; }
.garden-plant:disabled { cursor: default; opacity: .66; }.garden-plant__label { position: absolute; z-index: 4; right: 50%; bottom: -33px; display: grid; width: max-content; max-width: 142px; gap: 1px; overflow: hidden; color: #355438; font-size: 10px; font-weight: 800; line-height: 1.3; pointer-events: none; text-align: center; text-overflow: ellipsis; transform: translateX(50%); white-space: nowrap; }.garden-plant__label i { color: #6d8d65; font-size: 8px; font-style: normal; font-weight: 700; }.garden-plant:hover:not(:disabled) .garden-plant__label,.garden-plant.is-active .garden-plant__label { color: #1f5638; }.garden-plant.has-label-above .garden-plant__label { bottom: calc(100% + 7px); }
.garden-plant__lock { position: absolute; top: 43%; right: 50%; color: #7d857d; font-size: 13px; letter-spacing: 2px; pointer-events: none; transform: translateX(50%); }
.garden-scene__hint { position: absolute; right: 17px; bottom: 13px; margin: 0; color: #537451; font-size: 10px; }.garden-scene__more { position: absolute; top: 14px; right: 15px; margin: 0; color: #5f7e5f; font-size: 11px; font-weight: 800; }

.garden-empty { display: grid; min-height: 300px; grid-template-columns: 180px minmax(0, 1fr); align-items: center; gap: 20px; border: 1px solid #d8e3d5; border-radius: 7px; background: #edf4e9; padding: 15px 28px; }.garden-empty :deep(.forest-tree) { height: 210px; }.garden-empty p { max-width: 270px; color: var(--muted); font-size: 12px; line-height: 1.6; }
@media (max-width: 720px) { .forest-review { padding: 17px; }.forest-review__header { gap: 11px; flex-wrap: wrap; }.forest-review__status { order: 3; flex-basis: 100%; margin-left: 0; text-align: left; }.garden-scene { min-height: max(500px, calc(320px + var(--garden-rows) * 105px)); }.garden-plant { width: clamp(52px, calc(30px + var(--size) * 66px), 100px); }.garden-scene__hint { display: none; }.garden-empty { grid-template-columns: 1fr; gap: 0; padding: 10px 18px 18px; text-align: center; }.garden-empty :deep(.forest-tree) { height: 175px; }.garden-empty p { margin: 0 auto; } }
@media (max-width: 430px) { .garden-scene { min-height: max(370px, calc(280px + var(--garden-rows) * 88px)); }.garden-plant { width: clamp(46px, calc(28px + var(--size) * 56px), 82px); }.garden-scene__sun { top: 26px; width: 46px; height: 46px; }.garden-scene__cloud { display: none; } }
@keyframes garden-ground-pulse { 0%,100% { opacity: .45; transform: scale(.88); } 50% { opacity: .9; transform: scale(1.08); } }
@media (prefers-reduced-motion: reduce) { .garden-plant.is-active::before { animation: none; } }
</style>
