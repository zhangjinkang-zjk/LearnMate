<template>
  <aside class="chapter-rail" :class="{ 'chapter-rail--drawer': drawer }" aria-label="本科目章节">
    <div class="chapter-rail__heading">
      <p class="eyebrow">本科目章节</p>
      <span>{{ completedCount }} / {{ nodes.length }}</span>
    </div>

    <div class="chapter-rail__progress progress-track" aria-hidden="true">
      <div class="progress-value" :style="{ width: `${progress}%` }"></div>
    </div>

    <select class="chapter-select" :value="activeNodeId" aria-label="选择章节" @change="selectFromMenu">
      <option v-for="(node, index) in nodes" :key="node.id" :value="node.id" :disabled="node.status === 'locked'">
        {{ index + 1 }}. {{ node.title }}{{ node.status === 'locked' ? '（待解锁）' : '' }}
      </option>
    </select>

    <ol class="chapter-list list-reset">
      <li v-for="(node, index) in nodes" :key="node.id">
        <button
          class="chapter-item"
          :class="{ 'is-active': node.id === activeNodeId, 'is-locked': node.status === 'locked' }"
          type="button"
          :disabled="node.status === 'locked'"
          :aria-current="node.id === activeNodeId ? 'step' : undefined"
          @click="$emit('select', node.id)"
        >
          <span class="chapter-item__marker" aria-hidden="true">
            <CircleCheck v-if="node.status === 'completed'" :size="17" />
            <LockKeyhole v-else-if="node.status === 'locked'" :size="15" />
            <BookOpen v-else-if="node.id === activeNodeId" :size="16" />
            <span v-else>{{ String(index + 1).padStart(2, '0') }}</span>
          </span>
          <span class="chapter-item__copy">
            <strong>{{ node.title }}</strong>
            <small>{{ statusLabel(node.status) }}</small>
          </span>
        </button>
      </li>
    </ol>
  </aside>
</template>

<script setup>
import { computed } from 'vue'
import { BookOpen, CircleCheck, LockKeyhole } from 'lucide-vue-next'

const props = defineProps({
  nodes: { type: Array, default: () => [] },
  activeNodeId: { type: [Number, String], default: null },
  drawer: { type: Boolean, default: false },
})

const emit = defineEmits(['select'])
const completedCount = computed(() => props.nodes.filter((node) => node.status === 'completed').length)
const progress = computed(() => props.nodes.length ? Math.round(completedCount.value / props.nodes.length * 100) : 0)

function statusLabel(status) {
  return ({
    completed: '已完成',
    in_progress: '正在学习',
    unlocked: '可以开始',
    locked: '完成前章后解锁',
  })[status] || '尚未开始'
}

function selectFromMenu(event) {
  const rawValue = event.target.value
  const node = props.nodes.find((item) => String(item.id) === rawValue)
  if (node && node.status !== 'locked') emit('select', node.id)
}
</script>

<style scoped>
.chapter-rail { min-width: 0; padding: 4px 17px 24px 0; border-right: 1px solid var(--line); }
.chapter-rail__heading { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; }
.chapter-rail__heading .eyebrow { margin: 0; }
.chapter-rail__heading > span { color: var(--muted); font-size: 11px; }
.chapter-rail__progress { height: 4px; margin: 14px 0 20px; }
.chapter-list { display: grid; gap: 4px; }
.chapter-item { display: grid; grid-template-columns: 28px minmax(0, 1fr); width: 100%; min-height: 62px; align-items: center; gap: 8px; padding: 9px 8px; border: 0; border-radius: 6px; background: transparent; color: var(--ink); text-align: left; transition: background .16s ease, color .16s ease; }
.chapter-item:hover:not(:disabled) { background: #edf2ed; }
.chapter-item:focus-visible { outline: 2px solid var(--accent-deep); outline-offset: 2px; }
.chapter-item.is-active { background: #e8efdf; color: #2f4d35; }
.chapter-item.is-locked { cursor: not-allowed; color: #9da69f; }
.chapter-item__marker { display: grid; width: 26px; height: 26px; place-items: center; color: var(--accent-deep); font-size: 9px; font-weight: 900; }
.chapter-item.is-locked .chapter-item__marker { color: #a7afa9; }
.chapter-item__copy { display: grid; min-width: 0; gap: 5px; }
.chapter-item__copy strong { overflow: hidden; font-size: 12px; line-height: 1.45; text-overflow: ellipsis; }
.chapter-item__copy small { color: var(--muted); font-size: 10px; }
.chapter-select { display: none; width: 100%; min-height: 42px; padding: 0 36px 0 12px; border: 1px solid var(--line); border-radius: 5px; background: var(--paper); color: var(--ink); outline: none; }
@media (max-width: 1280px) {
  .chapter-rail { padding: 0; border-right: 0; }
  .chapter-list, .chapter-rail__progress { display: none; }
  .chapter-rail__heading { margin-bottom: 10px; }
  .chapter-select { display: block; }
}
.chapter-rail--drawer { padding: 0; border-right: 0; }
.chapter-rail--drawer .chapter-rail__heading { margin-bottom: 0; }
.chapter-rail--drawer .chapter-rail__progress { display: block; }
.chapter-rail--drawer .chapter-select { display: none; }
.chapter-rail--drawer .chapter-list { display: grid; }
.chapter-rail--drawer .chapter-item { min-height: 58px; padding: 8px 10px; }
</style>
