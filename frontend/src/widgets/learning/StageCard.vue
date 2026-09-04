<template>
  <article class="surface surface-pad stage-card"><div class="stage-card-top"><span class="stage-index">{{ index }}</span><span class="stage-state" :class="`stage-state--${state}`">{{ stateLabel }}</span></div><h3>{{ title }}</h3><p>{{ description }}</p><div v-if="progress !== undefined" class="stage-progress"><div class="progress-track"><div class="progress-value" :style="{ width: `${progress}%` }"></div></div><span>{{ progress }}%</span></div><RouterLink v-if="to" class="stage-link" :to="to">进入模块 <span>→</span></RouterLink></article>
</template>

<script setup>
import { computed } from 'vue'
const props = defineProps({ index: { type: [String, Number], required: true }, title: { type: String, required: true }, description: { type: String, required: true }, progress: { type: Number, default: undefined }, state: { type: String, default: 'locked' }, to: { type: String, default: '' } })
const stateLabel = computed(() => ({ done: '已完成', active: '进行中', locked: '待解锁' })[props.state] || props.state)
</script>

<style scoped>
.stage-card { display: grid; gap: 13px; }
.stage-card-top { display: flex; justify-content: space-between; align-items: center; }
.stage-index { display: grid; width: 28px; height: 28px; place-items: center; border-radius: 50%; background: var(--soft); color: var(--accent-deep); font-size: 12px; font-weight: 800; }
.stage-state { font-size: 11px; color: var(--muted); }.stage-state--active { color: var(--accent-deep); font-weight: 800; }.stage-state--done { color: #5a8d61; }
.stage-card h3 { margin: 0; font-size: 17px; }.stage-card p { min-height: 42px; margin: 0; color: var(--muted); font-size: 13px; line-height: 1.65; }
.stage-progress { display: flex; align-items: center; gap: 9px; }.stage-progress .progress-track { flex: 1; }.stage-progress span { color: var(--muted); font-size: 11px; }
.stage-link { color: var(--accent-deep); font-size: 12px; font-weight: 800; text-decoration: none; }.stage-link span { margin-left: 5px; }
</style>
