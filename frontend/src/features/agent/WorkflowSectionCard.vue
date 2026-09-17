<template>
  <article :data-section-key="section.key" class="ws-card" :class="[`is-${cardStatus}`, { 'is-open': isOpen }]">
    <button class="ws-card__head" type="button" :aria-expanded="isOpen" @click="toggle">
      <div class="ws-card__title">
        <strong>{{ section.label }}</strong>
        <small>{{ headline }}</small>
      </div>
      <div class="ws-card__badges">
        <em v-if="section.score !== null" class="ws-card__score">{{ section.score }} 分</em>
        <span class="ws-card__status" :class="`is-${cardStatus}`">{{ statusText }}</span>
        <ChevronDown :size="14" class="ws-card__chevron" />
      </div>
    </button>

    <dl class="ws-card__rows">
      <div class="ws-row" :class="`is-${section.genStatus}`">
        <dt>生成</dt>
        <dd>{{ section.genMessage }}</dd>
      </div>
      <div class="ws-row" :class="`is-${section.reviewStatus}`">
        <dt>审核</dt>
        <dd>{{ section.reviewMessage }}</dd>
      </div>
    </dl>

    <template v-if="isOpen">
      <section v-if="timeline.length" class="ws-card__block">
        <p class="ws-card__block-title">
          <span>过程</span>
          <small>{{ timeline.length }} 步</small>
        </p>
        <ol class="ws-timeline">
          <li v-for="(item, index) in timeline" :key="index">
            <time>{{ item.time }}</time>
            <span :class="`is-${item.status}`">{{ item.message }}</span>
          </li>
        </ol>
      </section>

      <section v-if="section.content" class="ws-card__block">
        <p class="ws-card__block-title">
          <span>正文</span>
          <small>{{ contentNote }}</small>
        </p>
        <pre ref="contentEl" class="ws-content">{{ section.content }}<i v-if="section.streaming" class="ws-caret" aria-hidden="true"></i></pre>
      </section>
    </template>
  </article>
</template>

<script setup>
import { computed, nextTick, ref, watch } from 'vue'
import { ChevronDown } from 'lucide-vue-next'

const props = defineProps({
  section: { type: Object, required: true },
})

const ACTIVE_STATUSES = new Set(['running', 'reviewing', 'retrying', 'saving'])
const STATUS_TEXT = {
  running: '生成中',
  reviewing: '审核中',
  retrying: '重写中',
  saving: '保存中',
  done: '已完成',
  failed: '失败',
}

// 卡片状态是"生成"和"审核"两个维度的合成。顺序有讲究：
// 失败优先（任意一维失败就是这张卡有问题），然后是谁正在动，最后才轮到完成。
// 只生成完、审核还没开始的章节报 pending —— 那确实是"等待审核"，不是"进行中"。
const cardStatus = computed(() => {
  const { genStatus, reviewStatus } = props.section
  if (genStatus === 'failed' || reviewStatus === 'failed') return 'failed'
  if (ACTIVE_STATUSES.has(reviewStatus)) return reviewStatus
  if (ACTIVE_STATUSES.has(genStatus)) return genStatus
  if (reviewStatus === 'done') return 'done'
  return 'pending'
})

const statusText = computed(() => {
  if (cardStatus.value === 'pending') {
    return props.section.genStatus === 'done' ? '待审核' : '等待中'
  }
  return STATUS_TEXT[cardStatus.value] || '等待中'
})

// 折叠语义：进行中或异常自动展开，跑完自动折成一行 —— 15 章全展开会变成一条长不见底的列表，
// 而已经完成的内容此刻并不需要占着屏幕。手动点过折叠箭头的卡片就交给用户，不再自动摆布。
const userToggled = ref(false)
const userOpen = ref(false)
const isOpen = computed(() => (userToggled.value ? userOpen.value : cardStatus.value !== 'done'))

function toggle() {
  const next = !isOpen.value
  userToggled.value = true
  userOpen.value = next
}

const headline = computed(() => props.section.title || props.section.genMessage)

function formatTime(at) {
  const date = new Date(at)
  const pad = (value) => String(value).padStart(2, '0')
  return `${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`
}

const timeline = computed(() => props.section.timeline.map((item) => ({
  ...item,
  time: formatTime(item.at),
})))

const contentNote = computed(() => {
  // 页码只在 PPT 上有意义；文档的 section 是"节"，没有页。
  const page = props.section.resourceType === 'ppt' && props.section.slideIdx >= 0
    ? `第 ${props.section.slideIdx + 1} 页`
    : ''
  if (props.section.streaming) return page ? `${page} · 正在写入…` : '正在写入…'
  return page ? `${page} · ${props.section.content.length} 字` : `${props.section.content.length} 字`
})

// 正文是逐字追加的，超过可视高度后必须跟着滚，否则用户盯着的是最早那几行，
// 而"正在写"的部分在底下看不见 —— 那样打字效果就白做了。
const contentEl = ref(null)
watch(() => props.section.content, async () => {
  if (!props.section.streaming) return
  await nextTick()
  const el = contentEl.value
  if (el) el.scrollTop = el.scrollHeight
})
</script>

<style scoped>
.ws-card { display: grid; gap: 9px; padding: 11px 13px; border: 1px solid var(--line); border-radius: 7px; background: var(--paper); }
.ws-card.is-running, .ws-card.is-reviewing, .ws-card.is-retrying, .ws-card.is-saving { border-color: #a9bf91; background: #f7faf3; }
.ws-card.is-failed { border-color: #e1bba9; background: #fff9f4; }
.ws-card__head { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; width: 100%; padding: 0; border: 0; background: none; text-align: left; cursor: pointer; }
.ws-card__title { min-width: 0; }
.ws-card__title strong { display: block; color: var(--ink); font-size: 12px; }
.ws-card__title small { display: block; margin-top: 3px; overflow: hidden; color: var(--muted); font-size: 11px; text-overflow: ellipsis; white-space: nowrap; }
.ws-card__badges { display: flex; flex: 0 0 auto; align-items: center; gap: 6px; }
.ws-card__score { padding: 2px 7px; border-radius: 3px; background: #eef3ea; color: var(--accent-deep); font-size: 10px; font-style: normal; font-variant-numeric: tabular-nums; }
.ws-card__status { padding: 2px 8px; border-radius: 3px; background: #edf2ed; color: var(--muted); font-size: 10px; white-space: nowrap; }
.ws-card__status.is-running, .ws-card__status.is-reviewing, .ws-card__status.is-retrying, .ws-card__status.is-saving { background: var(--accent); color: var(--accent-deep); }
.ws-card__status.is-done { background: var(--accent-deep); color: #fff; }
.ws-card__status.is-failed { background: #b96e4d; color: #fff; }
.ws-card__chevron { color: var(--muted); transition: transform .18s ease; }
.ws-card.is-open .ws-card__chevron { transform: rotate(180deg); }
.ws-card__rows { display: grid; gap: 4px; margin: 0; }
.ws-row { display: grid; grid-template-columns: 30px minmax(0, 1fr); align-items: baseline; gap: 8px; }
.ws-row dt { color: var(--muted); font-size: 10px; }
.ws-row dd { margin: 0; overflow: hidden; color: var(--ink); font-size: 11px; line-height: 1.5; text-overflow: ellipsis; white-space: nowrap; }
.ws-row.is-running dd, .ws-row.is-reviewing dd, .ws-row.is-retrying dd, .ws-row.is-saving dd { color: var(--accent-deep); }
.ws-row.is-failed dd { color: #a65d43; }
.ws-card__block { display: grid; gap: 6px; padding-top: 9px; border-top: 1px solid var(--line); }
.ws-card__block-title { display: flex; align-items: baseline; justify-content: space-between; gap: 10px; margin: 0; color: var(--muted); font-size: 10px; font-weight: 700; }
.ws-card__block-title small { font-weight: 500; }
.ws-timeline { display: grid; gap: 4px; margin: 0; padding: 0; list-style: none; }
.ws-timeline li { display: grid; grid-template-columns: 52px minmax(0, 1fr); align-items: baseline; gap: 8px; }
.ws-timeline time { color: var(--muted); font-size: 9px; font-variant-numeric: tabular-nums; }
.ws-timeline span { color: var(--muted); font-size: 10px; line-height: 1.5; }
.ws-timeline span.is-running, .ws-timeline span.is-reviewing, .ws-timeline span.is-retrying, .ws-timeline span.is-saving { color: var(--accent-deep); }
.ws-timeline span.is-failed { color: #a65d43; }
.ws-content { max-height: 132px; margin: 0; overflow-y: auto; padding: 9px 10px; border-radius: 4px; background: var(--soft); color: var(--muted); font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 10px; line-height: 1.65; white-space: pre-wrap; word-break: break-word; }
.ws-caret { display: inline-block; width: 5px; height: 11px; margin-left: 2px; background: var(--accent-deep); vertical-align: text-bottom; animation: wsCaretBlink .9s steps(2, start) infinite; }
@keyframes wsCaretBlink { 0%, 100% { opacity: 1; } 50% { opacity: 0; } }
@media (prefers-reduced-motion: reduce) { .ws-caret, .ws-card__chevron { transition: none; animation: none; } }
</style>
