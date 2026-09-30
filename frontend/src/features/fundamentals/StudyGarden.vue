<template>
  <section class="study-garden surface" aria-labelledby="study-garden-title">
    <div class="study-garden__header">
      <div>
        <p class="eyebrow">LEARNING GARDEN</p>
        <h2 id="study-garden-title">把完成的章节种成一座小树林</h2>
        <p class="study-garden__description">每完成一个章节就种下一株树苗，章节完成度越高，树苗越茂盛。</p>
      </div>
      <div class="study-garden__summary" aria-label="学习花园进度">
        <strong>{{ completedCount }}<span>/{{ nodes.length }}</span></strong>
        <small>章节已长成</small>
      </div>
    </div>

    <div v-if="nodes.length" class="study-garden__plot" role="list" aria-label="学习章节花园">
      <button
        v-for="(node, index) in visibleNodes"
        :key="node.id || index"
        class="plant-card"
        :class="{ 'is-active': String(node.id) === String(activeNodeId), 'is-complete': node.status === 'completed', 'is-locked': node.status === 'locked' }"
        type="button"
        :disabled="node.status === 'locked'"
        role="listitem"
        :aria-label="`${node.title || `章节 ${index + 1}`}，${stageLabel(node)}`"
        @click="$emit('select', node.id)"
      >
        <span class="plant-card__number">{{ String(index + 1).padStart(2, '0') }}</span>
        <svg class="plant-card__visual" viewBox="0 0 120 140" role="img" :aria-label="stageLabel(node)">
          <path class="plant-card__ground" d="M18 123C35 119 84 119 103 123" />
          <g class="plant-card__plant" :style="{ '--plant-scale': `${plantScale(node)}` }">
            <path class="plant-card__stem" d="M60 118V72" />
            <path v-if="plantScale(node) > 0.45" class="plant-card__branch" d="M60 93L42 79M60 84L78 69M60 104L79 91" />
            <ellipse v-if="plantScale(node) > 0.08" class="plant-card__leaf plant-card__leaf--left" cx="43" cy="78" rx="13" ry="7" transform="rotate(-28 43 78)" />
            <ellipse v-if="plantScale(node) > 0.2" class="plant-card__leaf plant-card__leaf--right" cx="78" cy="68" rx="14" ry="7" transform="rotate(-22 78 68)" />
            <ellipse v-if="plantScale(node) > 0.52" class="plant-card__leaf plant-card__leaf--left" cx="42" cy="96" rx="14" ry="8" transform="rotate(18 42 96)" />
            <ellipse v-if="plantScale(node) > 0.68" class="plant-card__leaf plant-card__leaf--right" cx="80" cy="91" rx="15" ry="8" transform="rotate(-18 80 91)" />
            <circle v-if="plantScale(node) > 0.78" class="plant-card__crown" cx="60" cy="57" r="25" />
            <circle v-if="plantScale(node) > 0.9" class="plant-card__crown plant-card__crown--small" cx="41" cy="67" r="14" />
            <circle v-if="plantScale(node) > 0.94" class="plant-card__crown plant-card__crown--small" cx="80" cy="65" r="15" />
            <path v-if="plantScale(node) < 0.08" class="plant-card__seed" d="M60 120C51 115 52 106 60 103C68 106 69 115 60 120Z" />
          </g>
        </svg>
        <span class="plant-card__stage">{{ stageLabel(node) }}</span>
        <strong class="plant-card__title" :title="node.title">{{ node.title || `学习章节 ${index + 1}` }}</strong>
        <span class="plant-card__hint">{{ statusHint(node) }}</span>
      </button>
    </div>
    <div v-else class="study-garden__empty">完成第一章学习后，这里会出现你的第一株树苗。</div>

    <div class="study-garden__legend" aria-label="植物成长阶段">
      <span><i class="legend-dot legend-dot--seed"></i>未开始</span>
      <span><i class="legend-dot legend-dot--sprout"></i>学习中</span>
      <span><i class="legend-dot legend-dot--tree"></i>已完成</span>
    </div>
  </section>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  nodes: { type: Array, default: () => [] },
  activeNodeId: { type: [String, Number], default: null },
})

defineEmits(['select'])

const visibleNodes = computed(() => props.nodes.slice(0, 12))
const completedCount = computed(() => props.nodes.filter((node) => node.status === 'completed').length)

function plantScale(node) {
  if (node.status === 'completed') return 1
  if (node.status === 'locked') return 0
  if (node.resources_viewed) return 0.62
  if (node.status === 'in_progress') return 0.35
  return 0.12
}

function stageLabel(node) {
  if (node.status === 'completed') return '已完成 · 小树'
  if (node.status === 'in_progress' && node.resources_viewed) return '学习中 · 茂盛树苗'
  if (node.status === 'in_progress') return '学习中 · 树苗'
  if (node.status === 'unlocked') return '已解锁 · 萌芽'
  return '待解锁 · 种子'
}

function statusHint(node) {
  if (node.status === 'completed') return '本章已完成'
  if (node.resources_viewed) return '继续完成章节复盘'
  if (node.status === 'unlocked') return '开始学习'
  return '完成前置章节后解锁'
}
</script>

<style scoped>
.study-garden { padding: 22px; overflow: hidden; }
.study-garden__header { display: flex; align-items: flex-start; justify-content: space-between; gap: 18px; margin-bottom: 18px; }
.study-garden h2 { margin: 0; font-size: 19px; line-height: 1.35; }
.study-garden__description { max-width: 520px; margin: 6px 0 0; color: var(--muted); font-size: 12px; line-height: 1.6; }
.study-garden__summary { flex: 0 0 auto; padding-left: 18px; border-left: 1px solid var(--line); text-align: right; }
.study-garden__summary strong { display: block; color: var(--accent-deep); font-size: 26px; line-height: 1; }
.study-garden__summary strong span { color: var(--muted); font-size: 14px; font-weight: 500; }
.study-garden__summary small { display: block; margin-top: 6px; color: var(--muted); font-size: 10px; }
.study-garden__plot { display: grid; grid-template-columns: repeat(6, minmax(92px, 1fr)); gap: 10px; align-items: end; min-height: 250px; padding: 16px 4px 0; border-bottom: 1px solid var(--line); background: linear-gradient(to bottom, transparent 72%, rgba(53, 91, 63, .035) 72%); }
.plant-card { position: relative; display: flex; min-width: 0; flex-direction: column; align-items: center; padding: 7px 5px 13px; border: 1px solid transparent; border-radius: 7px; background: transparent; color: var(--ink); cursor: pointer; transition: border-color .2s ease, background .2s ease, transform .2s ease; }
.plant-card:hover { border-color: var(--line); background: rgba(255, 255, 255, .62); transform: translateY(-3px); }
.plant-card:focus-visible { outline: 2px solid var(--accent-deep); outline-offset: 2px; }
.plant-card.is-active { border-color: var(--accent-deep); background: rgba(224, 234, 221, .48); }
.plant-card.is-locked { cursor: default; opacity: .58; }
.plant-card__number { align-self: flex-start; color: var(--muted); font-size: 9px; font-weight: 800; letter-spacing: .08em; }
.plant-card__visual { display: block; width: 100%; height: 128px; overflow: visible; }
.plant-card__ground { fill: none; stroke: #bdcbb8; stroke-width: 2; stroke-linecap: round; }
.plant-card__plant { transform: translateY(calc(18px * (1 - var(--plant-scale)))) scale(calc(.58 + var(--plant-scale) * .42)); transform-origin: 60px 120px; transition: transform .55s cubic-bezier(.2, .8, .2, 1); }
.plant-card__stem, .plant-card__branch { fill: none; stroke: #55725a; stroke-linecap: round; stroke-width: 4; }
.plant-card__branch { stroke-width: 3; }
.plant-card__leaf { fill: #829c76; stroke: #55725a; stroke-width: 1.5; }
.plant-card__leaf--right { fill: #9aae83; }
.plant-card__crown { fill: #6e956a; stroke: #55725a; stroke-width: 1.5; }
.plant-card__crown--small { fill: #86a879; }
.plant-card__seed { fill: #b58c5c; stroke: #806442; stroke-width: 1.5; }
.plant-card__stage { min-height: 14px; color: var(--accent-deep); font-size: 10px; font-weight: 800; }
.plant-card__title { width: 100%; margin-top: 5px; overflow: hidden; font-size: 11px; line-height: 1.35; text-align: center; text-overflow: ellipsis; white-space: nowrap; }
.plant-card__hint { width: 100%; margin-top: 3px; overflow: hidden; color: var(--muted); font-size: 9px; text-align: center; text-overflow: ellipsis; white-space: nowrap; }
.study-garden__empty { min-height: 170px; display: grid; place-items: center; color: var(--muted); font-size: 12px; }
.study-garden__legend { display: flex; flex-wrap: wrap; gap: 14px; margin-top: 14px; color: var(--muted); font-size: 10px; }
.study-garden__legend span { display: inline-flex; align-items: center; gap: 5px; }
.legend-dot { display: inline-block; width: 8px; height: 8px; border-radius: 50%; }
.legend-dot--seed { background: #b58c5c; }.legend-dot--sprout { background: #9aae83; }.legend-dot--tree { background: #55725a; }
@media (max-width: 920px) { .study-garden__plot { grid-template-columns: repeat(4, minmax(92px, 1fr)); } }
@media (max-width: 620px) { .study-garden { padding: 17px; }.study-garden__header { gap: 12px; }.study-garden h2 { font-size: 17px; }.study-garden__summary { padding-left: 12px; }.study-garden__plot { grid-template-columns: repeat(3, minmax(80px, 1fr)); gap: 6px; min-height: 0; padding-top: 10px; }.plant-card__visual { height: 112px; }.plant-card__hint { display: none; } }
</style>
