<template>
  <div class="task-bar">
    <span class="task-bar__kind">{{ task.kind_label || '实践任务' }}</span>
    <span class="task-bar__difficulty">{{ task.difficulty_label || '标准' }}</span>
    <h2 class="task-bar__title" :title="task.title">{{ task.title }}</h2>

    <span v-if="taskSource === 'pending'" class="task-bar__status task-bar__status--pending">
      <LoaderCircle class="spin" :size="12" />正在生成
    </span>
    <button
      v-else-if="taskSource === 'fallback'"
      class="task-bar__status task-bar__status--fallback"
      type="button"
      @click="emit('regenerate')"
    >
      <CircleAlert :size="12" />临时入口 · 重新生成
    </button>

    <div class="task-bar__switch">
      <button
        class="button button--quiet task-bar__switch-button"
        type="button"
        :aria-expanded="open"
        :disabled="!options.length"
        @click="open = !open"
      >
        <Repeat2 :size="13" />换一个
        <span v-if="options.length" class="task-bar__count">{{ options.length }}</span>
      </button>
      <!-- 点外面就收起来。这里不用 focusout：下拉里的按钮一被点就会先触发失焦，收得比点击快 -->
      <div v-if="open" class="task-bar__backdrop" @click="open = false"></div>
      <ul v-if="open" class="task-bar__menu" role="menu">
        <li v-for="item in options" :key="item.id">
          <button type="button" role="menuitem" class="task-bar__menu-item" @click="choose(item.id)">
            <span class="task-bar__menu-top"><strong>{{ item.kind_label || '实践任务' }}</strong><small>{{ item.difficulty_label || '标准' }}</small></span>
            <span class="task-bar__menu-title">{{ item.title }}</span>
          </button>
        </li>
      </ul>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { CircleAlert, LoaderCircle, Repeat2 } from 'lucide-vue-next'

const props = defineProps({
  task: { type: Object, required: true },
  taskSource: { type: String, default: '' },
  options: { type: Array, default: () => [] },
})
const emit = defineEmits(['select', 'regenerate'])

const open = ref(false)

function choose(taskId) {
  open.value = false
  emit('select', taskId)
}
</script>

<style scoped>
.task-bar { display: flex; min-width: 0; align-items: center; gap: 10px; padding: 9px 14px; border: 1px solid rgba(63, 91, 49, .28); border-radius: 12px; background: var(--paper); box-shadow: 0 8px 24px rgba(45, 40, 92, .07); }
.task-bar__kind { flex: 0 0 auto; color: var(--accent-deep); font-size: 11px; font-weight: 800; }
.task-bar__difficulty { flex: 0 0 auto; padding: 3px 8px; border: 1px solid #d5e2c8; border-radius: 99px; background: #f3f8ea; color: var(--accent-deep); font-size: 10px; font-weight: 800; }
.task-bar__title { min-width: 0; flex: 1; margin: 0; overflow: hidden; color: var(--ink); font-size: 14px; line-height: 1.4; text-overflow: ellipsis; white-space: nowrap; }
.task-bar__status { display: inline-flex; flex: 0 0 auto; align-items: center; gap: 5px; padding: 4px 9px; border: 1px solid #dbe7d2; border-radius: 99px; background: #fff; color: #536057; font-size: 11px; }
.task-bar__status--pending { border-color: #cfdfc2; background: #f4f8ed; color: var(--accent-deep); }
.task-bar__status--fallback { border-color: #e6d6b8; background: #fffdf6; color: #7a5c1e; cursor: pointer; }
.task-bar__switch { position: relative; flex: 0 0 auto; }
.task-bar__switch-button { gap: 6px; padding: 6px 11px; font-size: 12px; }
.task-bar__count { padding: 1px 6px; border-radius: 99px; background: #e8f2de; color: var(--accent-deep); font-size: 10px; font-weight: 800; }
.task-bar__backdrop { position: fixed; inset: 0; z-index: 20; }
.task-bar__menu { position: absolute; z-index: 21; top: calc(100% + 6px); right: 0; display: grid; width: min(330px, 78vw); gap: 6px; margin: 0; padding: 8px; border: 1px solid var(--line); border-radius: 12px; background: var(--paper); box-shadow: 0 14px 34px rgba(31, 49, 40, .16); list-style: none; }
.task-bar__menu-item { display: grid; width: 100%; min-width: 0; gap: 3px; padding: 9px 10px; border: 0; border-radius: 8px; background: transparent; color: var(--ink); text-align: left; cursor: pointer; }
.task-bar__menu-item:hover { background: #f1f6eb; }
.task-bar__menu-top { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.task-bar__menu-top strong { color: var(--accent-deep); font-size: 10px; }
.task-bar__menu-top small { color: var(--muted); font-size: 10px; }
.task-bar__menu-title { overflow-wrap: anywhere; font-size: 12px; font-weight: 700; line-height: 1.45; }
.spin { animation: spin 1s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
</style>
