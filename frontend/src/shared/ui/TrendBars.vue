<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'

/**
 * 一周一根柱子的「学习天数」走势图。数据来自 `activity.week_trend`
 * （后端按日历周分好桶、从早到晚），每项 `{ week_start: '2026-08-10', active_days: 3 }`。
 *
 * **画的是天数，不是题数。** 天数只要那天动过就算（读资料、做节点测验、课堂提问都算），
 * 值域固定 0-7；题数会把"只读资料不刷题"的人画成一片空白，那是在说他没学。
 * 柱子顶上印着当周的天数，所以纵轴没有刻度也不会读错。
 *
 * **宽度是量出来的（ResizeObserver），不是用 viewBox 缩放的。** 非等比缩放下 `<text>` 会被
 * 横向拉扁，等比缩放又会让窄屏上的字小到看不清。量出真实像素后，柱宽、间距、字号都是确定的，
 * 和下面的星期标签也才对得上（标签那一行是等宽 flex 格，中心落在 `(i + 0.5) / n` 上，
 * 和柱子同一个算式 —— 见 `.bars__labels`）。
 *
 * **不用图表库**：这里只有 6 个矩形、一条基线和 6 个数字。引一包运行时进来，它的默认主题
 * 和这一页的 `--ink / --accent-deep` 语汇也对不上，照样得重写一遍 theme。
 */
const props = defineProps({
  weeks: { type: Array, default: () => [] },
})

// 一根柱子最多能长到多高。**这一页的高度调节阀**：路径表那一行减 4px，这里就能长 4px。
const PLOT_HEIGHT = 130
// 柱顶到 SVG 顶边留给"这根柱子是几天"那个数字的高度。柱子的 0 点是下面的基线，
// 长到顶也只会碰到这条留白的下沿，数字不会被裁掉。
const VALUE_SPACE = 16
// 一周最多 7 天。**固定值域**，不按最大值归一化 —— 否则"这周 2 天"在一段都很闲的时间里
// 会画得和"这周 7 天"一样高。
const MAX_DAYS = 7
// 柱宽上限。柱子再多也只到这个宽度，剩下的宽度留成间距，别让 6 根柱子撑成 6 个色块。
const BAR_MAX = 56
const BAR_HEIGHT = PLOT_HEIGHT - VALUE_SPACE

const host = ref(null)
const width = ref(0)

const toDays = (value) => {
  const numeric = Number(value)
  if (!Number.isFinite(numeric) || numeric <= 0) return 0
  return Math.min(MAX_DAYS, Math.round(numeric))
}

const bars = computed(() => {
  const count = props.weeks.length
  if (!count || !width.value) return []
  const slot = width.value / count
  const barWidth = Math.max(6, Math.min(BAR_MAX, slot * 0.56))
  return props.weeks.map((week, index) => {
    const days = toDays(week?.active_days)
    const center = slot * (index + 0.5)
    const barHeight = (days / MAX_DAYS) * BAR_HEIGHT
    const barTop = PLOT_HEIGHT - barHeight
    return {
      key: week?.week_start ?? index,
      days,
      x: center - barWidth / 2,
      barWidth,
      barTop,
      barHeight,
      center,
      isCurrent: index === count - 1,
    }
  })
})

// 横轴只用相对说法（本周 / 上周 / N 周前），不用 `8/10` 那种日期：这张图要回答的是
// "我这几周是在往上走还是在往下掉"，周次比日历日期更贴这个问题，也短得多。
function weekLabel(index) {
  const offset = props.weeks.length - 1 - index
  if (offset <= 0) return '本周'
  if (offset === 1) return '上周'
  return `${offset} 周前`
}

// 图里的数不能只靠柱高传达 —— 屏幕阅读器读不出柱子。整串铺在 aria-label 上。
const chartLabel = computed(() => {
  const parts = props.weeks.map((week, index) => {
    const days = toDays(week?.active_days)
    return days === 0 ? `${weekLabel(index)}没有学习` : `${weekLabel(index)}学了 ${days} 天`
  })
  return `每周学习天数：${parts.join('，')}`
})

onMounted(() => {
  if (!host.value) return
  const observer = new ResizeObserver(([entry]) => {
    width.value = Math.round(entry.contentRect.width)
  })
  observer.observe(host.value)
  width.value = Math.round(host.value.getBoundingClientRect().width)
  onBeforeUnmount(() => observer.disconnect())
})
</script>

<template>
  <div ref="host" class="bars">
    <svg class="bars__plot" :width="width" :height="PLOT_HEIGHT" role="img" :aria-label="chartLabel">
      <!-- 基线。某周一天都没来时那根柱子是 0 高、什么都不画，只有这条线能说明"这里确实有一周" ——
           没有它，空周和"数据缺失"在图上长得一样。 -->
      <line class="bars__axis" x1="0" :x2="width" :y1="PLOT_HEIGHT" :y2="PLOT_HEIGHT" />
      <g v-for="bar in bars" :key="bar.key">
        <rect class="bars__bar" :x="bar.x" :y="bar.barTop" :width="bar.barWidth" :height="bar.barHeight" />
        <!-- 天数是数出来的，不是比出来的：柱子之间差一天只差 11px 高，光看高度分不出 4 和 5。
             所以数字印在柱顶，柱高只负责给"这几周的整体形状"。 -->
        <text
          class="bars__value"
          :class="{ 'is-current': bar.isCurrent }"
          :x="bar.center"
          :y="bar.barTop - 5"
          text-anchor="middle"
        >{{ bar.days }}</text>
      </g>
    </svg>
    <ol class="bars__labels">
      <li
        v-for="(week, index) in weeks"
        :key="week?.week_start ?? index"
        class="bars__label"
        :class="{ 'is-current': index === weeks.length - 1 }"
      >{{ weekLabel(index) }}</li>
    </ol>
  </div>
</template>

<style scoped>
/* 宽度上限：页脚在 1180 以下会叠成一栏，那时这一栏有 900 多像素宽，六根柱子会各自
   漂在一片空白里。封顶之后柱子继续按比例长，只是不再跟着容器无限拉开。 */
.bars { display: grid; gap: 4px; max-width: 640px; }
/* `display: block` 去掉 svg 的行内基线间隙 —— 留着它，柱子底下会多出一条缝。 */
.bars__plot { display: block; }
/* 基线用 `--line`（页面里所有分隔线的颜色），它是坐标系不是数据。 */
.bars__axis { stroke: var(--line); stroke-width: 1; }
.bars__bar { fill: var(--accent-deep); }
.bars__value { fill: var(--muted); font-size: 12px; font-variant-numeric: tabular-nums; }
/* 本周那个数用墨色加重，和下面「本周」那个词同步 —— 一列上下的两处加重指向同一天。 */
.bars__value.is-current { fill: var(--ink); font-weight: 800; }

/* 每一格等宽、各自居中，所以标签的中心必然落在柱子中心上（两者都是 (i + 0.5) / n）。 */
.bars__labels { display: flex; margin: 0; padding: 0; list-style: none; }
.bars__label { flex: 1; min-width: 0; color: var(--muted); font-size: 12px; line-height: 1.2; text-align: center; white-space: nowrap; }
.bars__label.is-current { color: var(--ink); font-weight: 800; }
</style>
