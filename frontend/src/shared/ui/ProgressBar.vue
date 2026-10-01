<template>
  <div
    class="progress-bar"
    :class="[`progress-bar--${size}`, `progress-bar--track-${track}`, { 'is-indeterminate': indeterminate }]"
    role="progressbar"
    :aria-valuenow="indeterminate ? undefined : percent"
    :aria-valuemin="indeterminate ? undefined : 0"
    :aria-valuemax="indeterminate ? undefined : 100"
    :aria-label="label || undefined"
  >
    <span
      class="progress-bar__fill"
      :class="`progress-bar__fill--${tone}`"
      :style="indeterminate ? undefined : { width: `${percent}%` }"
    ></span>
  </div>
</template>

<script setup>
import { computed } from 'vue'

/**
 * 一条确定或不确定的进度条。
 *
 * 存在的理由：`.progress-track` / `.progress-value` 这两个类早就在 `shared/styles/main.css`
 * 里了，但全站有 6 处把这对类连同 `:style="{ width: ... }"` 一起抄了一遍
 * （ChapterCheck / ChapterRail / PathPicker / FundamentalsPage ×2 / StageCard），
 * 另有 ResourceGenerationDialog 和 FoundationTestPage 各自又造了一个新的。
 * 每抄一次就多一次"宽度算错 / 忘了 clamp / 传进来的是 0.85 还是 85"的机会。
 *
 * 传值有两种写法，各自只有一种含义，不猜：
 * - `:value="85"`（默认 max=100）—— 已经是一个百分比；
 * - `:value="3" :max="8"` —— 原始计数，组件自己算比例。
 * `max <= 0` 或值非数字时一律画成 0，不画成满格（"没有分母"不等于"全部完成"）。
 */
const props = defineProps({
  value: { type: Number, default: 0 },
  max: { type: Number, default: 100 },
  // sm / md / lg —— 4 / 7 / 12 像素高，对应"页脚细线 / 正文 / 需要看见"三档。
  size: { type: String, default: 'md' },
  // deep 是深绿（默认，和 --accent-deep 一致），accent 是柠檬绿。
  tone: { type: String, default: 'deep' },
  // light = 浅色底上的槽（默认），on-dark = 深色面板上的槽。深色底上再用浅灰槽
  // 会亮得像一条白杠，抢过填充本身。
  track: { type: String, default: 'light' },
  // 不知道进度时用：一条来回走的动画，而不是画一条假的 0%。
  indeterminate: { type: Boolean, default: false },
  // 进度条本身不写文字，但读屏需要一个名字。
  label: { type: String, default: '' },
})

const percent = computed(() => {
  const max = Number(props.max)
  const value = Number(props.value)
  if (!Number.isFinite(max) || max <= 0) return 0
  if (!Number.isFinite(value) || value <= 0) return 0
  return Math.min(100, Math.round((value / max) * 100))
})
</script>

<style scoped>
.progress-bar { width: 100%; overflow: hidden; border-radius: 99px; }
.progress-bar--track-light { background: #e9eee8; }
.progress-bar--track-on-dark { background: rgba(255, 255, 255, .16); }
.progress-bar--sm { height: 4px; }
.progress-bar--md { height: 7px; }
.progress-bar--lg { height: 12px; }

.progress-bar__fill { display: block; height: 100%; border-radius: inherit; transition: width .35s ease; }
.progress-bar__fill--deep { background: var(--accent-deep); }
.progress-bar__fill--accent { background: var(--accent); }

.progress-bar.is-indeterminate .progress-bar__fill { width: 35%; animation: progress-bar-sweep 1.1s ease-in-out infinite; }
@keyframes progress-bar-sweep {
  from { transform: translateX(-100%); }
  to { transform: translateX(320%); }
}

@media (prefers-reduced-motion: reduce) {
  .progress-bar__fill { transition: none; }
  .progress-bar.is-indeterminate .progress-bar__fill { width: 100%; animation: none; opacity: .55; }
}
</style>
