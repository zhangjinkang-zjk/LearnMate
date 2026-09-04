<template>
  <section class="path-picker" :class="{ 'path-picker--compact': compact }" :aria-labelledby="compact ? undefined : 'path-picker-title'">
    <div v-if="!compact" class="path-picker__heading">
      <div>
        <p class="eyebrow">学习方向拆解</p>
        <h2 id="path-picker-title">相关学习路径</h2>
        <p>同一个学习方向会拆成多个科目。先选一条路径，下面的章节和学习助手都会跟随切换。</p>
      </div>
      <span class="path-picker__count">{{ paths.length ? `${paths.length} 个科目` : '正在同步' }}</span>
    </div>

    <div v-if="loading && !paths.length" class="path-picker__state" aria-live="polite">
      <LoaderCircle class="spin" :size="17" />
      <span>正在同步相关学习路径</span>
    </div>
    <div v-else-if="!paths.length" class="path-picker__state">
      <Route :size="17" />
      <span>暂时没有可选路径，请先完成学习定向。</span>
    </div>
    <div v-else class="path-picker__list" role="list">
      <button
        v-for="(path, index) in paths"
        :key="path.path_id"
        class="path-card"
        :class="{ 'is-active': Number(path.path_id) === Number(activePathId) }"
        type="button"
        :aria-pressed="Number(path.path_id) === Number(activePathId)"
        :disabled="switching"
        @click="$emit('select', path.path_id)"
      >
        <span class="path-card__top">
          <span class="path-card__index">{{ String(index + 1).padStart(2, '0') }}</span>
          <span class="path-card__state">
            <CheckCircle2 v-if="progressFor(path).percentage >= 100" :size="13" />
            <span v-else>{{ progressFor(path).percentage }}%</span>
          </span>
        </span>
        <strong>{{ path.subject || '未命名科目' }}</strong>
        <span class="path-card__current">{{ currentLabel(path) }}</span>
        <span class="path-card__meta">
          <span>{{ progressFor(path).completed_nodes }} / {{ progressFor(path).total_nodes }} 节点</span>
          <span>{{ path.difficulty || '中等' }}</span>
        </span>
        <span class="path-card__track progress-track" aria-hidden="true">
          <span class="progress-value" :style="{ width: `${progressFor(path).percentage}%` }"></span>
        </span>
      </button>
    </div>
  </section>
</template>

<script setup>
import { CheckCircle2, LoaderCircle, Route } from 'lucide-vue-next'

defineProps({
  paths: { type: Array, default: () => [] },
  activePathId: { type: [Number, String], default: null },
  loading: { type: Boolean, default: false },
  switching: { type: Boolean, default: false },
  compact: { type: Boolean, default: false },
})

defineEmits(['select'])

function progressFor(path) {
  const value = path?.progress
  if (typeof value === 'number') {
    return { percentage: Math.round(value * 100), completed_nodes: 0, total_nodes: path.node_count || 0 }
  }
  const percentage = Number(value?.percentage ?? 0)
  return {
    percentage: Math.min(100, Math.max(0, Number.isFinite(percentage) ? Math.round(percentage) : 0)),
    completed_nodes: Number(value?.completed_nodes ?? 0),
    total_nodes: Number(value?.total_nodes ?? path.node_count ?? 0),
  }
}

function currentLabel(path) {
  const current = path?.progress?.current_node
  return current ? `当前：${current}` : (progressFor(path).percentage >= 100 ? '本路径已完成' : '尚未开始')
}
</script>

<style scoped>
.path-picker { margin-bottom: 28px; padding-bottom: 24px; border-bottom: 1px solid var(--line); }
.path-picker__heading { display: flex; align-items: flex-end; justify-content: space-between; gap: 20px; margin-bottom: 15px; }
.path-picker__heading .eyebrow { margin-bottom: 6px; }
.path-picker__heading h2 { margin: 0; color: var(--ink); font-size: 19px; }
.path-picker__heading p:last-child { max-width: 640px; margin: 7px 0 0; color: var(--muted); font-size: 12px; line-height: 1.65; }
.path-picker__count { flex: 0 0 auto; color: var(--muted); font-size: 11px; }
.path-picker__state { display: flex; min-height: 72px; align-items: center; gap: 9px; color: var(--muted); font-size: 12px; }
.path-picker__list { display: flex; overflow-x: auto; gap: 10px; padding: 2px 1px 6px; scroll-snap-type: x proximity; }
.path-card { display: grid; flex: 0 0 228px; min-width: 0; gap: 8px; padding: 14px; border: 1px solid var(--line); border-radius: 7px; background: var(--paper); color: var(--ink); text-align: left; scroll-snap-align: start; transition: border-color .16s ease, background .16s ease, transform .16s ease; }
.path-card:hover:not(:disabled) { border-color: #b8cba5; background: #fbfcf9; transform: translateY(-1px); }
.path-card:focus-visible { outline: 2px solid var(--accent-deep); outline-offset: 2px; }
.path-card.is-active { border-color: var(--accent-deep); background: #f5f9ee; box-shadow: inset 3px 0 0 var(--accent-deep); }
.path-card:disabled { cursor: wait; opacity: .7; }
.path-card__top, .path-card__meta { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.path-card__index { color: var(--accent-deep); font-size: 10px; font-weight: 900; letter-spacing: .1em; }
.path-card__state { display: inline-flex; align-items: center; gap: 4px; color: var(--accent-deep); font-size: 10px; font-weight: 800; }
.path-card strong { overflow: hidden; font-size: 14px; line-height: 1.4; text-overflow: ellipsis; white-space: nowrap; }
.path-card__current { overflow: hidden; min-height: 17px; color: var(--muted); font-size: 11px; line-height: 1.5; text-overflow: ellipsis; white-space: nowrap; }
.path-card__meta { color: var(--muted); font-size: 10px; }
.path-card__track { height: 5px; margin-top: 2px; }
.path-card__track .progress-value { display: block; }
.path-picker--compact { margin: 0; padding: 0; border-bottom: 0; }
.path-picker--compact .path-picker__state { min-height: 120px; justify-content: center; }
.path-picker--compact .path-picker__list { display: grid; overflow: visible; gap: 9px; padding: 0; scroll-snap-type: none; }
.path-picker--compact .path-card { width: 100%; min-height: 112px; }
.path-picker--compact .path-card strong,
.path-picker--compact .path-card__current { overflow: visible; text-overflow: clip; white-space: normal; }
.spin { animation: spin .8s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
@media (max-width: 620px) { .path-picker__heading { align-items: flex-start; flex-direction: column; gap: 8px; }.path-picker__list { gap: 9px; }.path-card { flex-basis: min(245px, 82vw); } }
</style>
