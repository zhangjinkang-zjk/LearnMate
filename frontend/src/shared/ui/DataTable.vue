<template>
  <div class="data-table">
    <!-- 表头是纯装饰性的列名，读屏由每一行的内容自己承担，所以整行 aria-hidden。 -->
    <div v-if="columns.length" class="data-table__head" aria-hidden="true">
      <span
        v-for="(column, index) in columns"
        :key="index"
        :style="column.span > 1 ? { gridColumn: `span ${column.span}` } : undefined"
      >{{ column.label }}</span>
    </div>

    <ul class="data-table__body">
      <li
        v-for="(row, index) in rows"
        :key="rowKeyOf(row, index)"
        class="data-table__row"
        :class="{ 'data-table__row--current': isCurrentOf(row) }"
      >
        <slot :row="row" :index="index" />
      </li>
    </ul>
  </div>
</template>

<script setup>
/**
 * 一张"表头 + 若干行"的表。
 *
 * 存在的理由不是"到处都需要表格"，而是**表头和表体的列宽会走散**：这两行是两条独立的
 * CSS 规则，靠人抄成一样来对齐，改一处就整列错位；要跨列还得在表头塞一个 `display:none`
 * 的占位格子。这里把列宽模板收成一个变量、同时喂给表头和表体，跨列用 `span` 声明，
 * 那两类手工修补就没有存在的余地了。
 *
 * 行内容完全由调用方给（`<slot :row :index />`），组件不预设任何业务字段 ——
 * 它只保证"每一列落在同一条网格线上"，以及边框、圆角、当前行底纹这些共同的壳。
 */
const props = defineProps({
  // [{ label: '路径', span: 2 }, { label: '完成度' }] —— 数组长度 = 列数，
  // span = 这一列名横跨几列。label 为空字符串就是留一个空列名。
  columns: { type: Array, default: () => [] },
  rows: { type: Array, default: () => [] },
  // 行的唯一键：传字段名，或 (row, index) => key。都不给就退回下标。
  rowKey: { type: [String, Function], default: '' },
  // (row) => 布尔，标出"当前行"。
  //
  // 这里刻意**不叫 `is-current` 那种通用类名**，而是组件自己的 `data-table__row--current`：
  // 调用方那一行里还有别的"当前" —— `OverviewPage` 的 `.row__track i.is-current` 指的是
  // "路径正走到哪一站"，和"这一行是当前路径"是两件事。曾用 `is-current`，结果一个
  // 后代选择器顺着 DOM 把整行的格子全染成了当前站的颜色：两个组件对同一个类名有两种理解。
  // 状态类名一律带组件前缀。
  isCurrent: { type: Function, default: null },
})

function rowKeyOf(row, index) {
  if (typeof props.rowKey === 'function') return props.rowKey(row, index)
  if (typeof props.rowKey === 'string' && props.rowKey) return row?.[props.rowKey] ?? index
  return index
}

function isCurrentOf(row) {
  return props.isCurrent ? Boolean(props.isCurrent(row)) : false
}
</script>

<style scoped>
/* **没有外框。** 这里原来是"1px 描边 + 10px 圆角 + 白底"的一张卡，和页面上那块深绿主卡
   各自占满一整行、形状一模一样 —— 页面上于是有两个等重的盒子，读者先看到哪个都对，
   页面也就读成了"两个大矩形"。一张表不需要框来证明自己是一张表：它本来就有表头、
   有逐行的发丝分隔线，这些已经是结构。去掉框之后**这一页只剩主卡一个盒子**，
   它是唯一的重点；表格退成页面本身的内容（和标题、说明同处一层）。

   左边那 4px 的当前行色条原来贴在卡片边框内侧，现在贴在行首 —— 行不再有水平内边距
   （调用方把 `--data-table-pad` 设成 0），所以色条、列名、内容三者一起对齐到页面左边线。 */
.data-table { background: transparent; }

/* 列宽的唯一定义。表头和表体都读它，所以两者不可能走散；调用方在 .data-table 上
   设 --data-table-columns 就能改整套列宽（响应式也只改这一处）。 */
.data-table__head,
.data-table__row {
  display: grid;
  align-items: center;
  gap: var(--data-table-gap, 20px);
  padding: 0 var(--data-table-pad, 28px);
  grid-template-columns: var(--data-table-columns, minmax(0, 1fr));
}

/* 表头下面那条线画在**容器**上，不是画在每个列名上。
   画在列名上会有两个后果，两个都看得见：
   ① `align-items: center` 是按内容高度居中，而空列名（轨道那一列）没有文字、
      盒子只有 22px 内边距高，有文字的列名却有 39px —— 两个盒子底边差了 9px，
      于是那条线**在轨道那一列抬起来一截**，一根发丝线在中间走了个台阶；
   ② 列与列之间有 20px 的 grid 间距，逐列画线就会在每一道间距里断开，
      一条表头线被切成六段。
   画在容器上就是一条连续的、只有一个高度的线，而且和表体每一行的分隔线同源 ——
   表体那条本来就在 `<li>` 上，从来不分段。 */
.data-table__head { color: var(--muted); font-size: 14px; border-bottom: 1px solid var(--line); }
.data-table__head span { overflow: hidden; padding: 11px 0; text-overflow: ellipsis; white-space: nowrap; }

.data-table__body { margin: 0; padding: 0; list-style: none; }
.data-table__row { min-height: var(--data-table-row-height, 72px); border-bottom: 1px solid var(--line); }
/* 最后一行**不画线**：卡片在的时候底边由卡片的边框收口，现在没有边框了，这一行的下边界
   交给紧跟着的那条区块分隔线（页脚那条 `border-top`）—— 两者只差一个区块间距，
   再各画一条就是两条相距 20 来像素的平行发丝线，看着像画重了。一条线收两次口。 */
.data-table__row:last-child { border-bottom: 0; }
/* 「当前行」用一条左侧色条标记 —— 结构，不是装饰。放在组件里是因为它属于表格本身
   （哪一行是"现在这条"），而且行元素是组件渲染的，调用方的 scoped 样式够不着它。 */
.data-table__row--current { background: #f7faf1; box-shadow: inset 4px 0 0 var(--accent-deep); }
</style>
