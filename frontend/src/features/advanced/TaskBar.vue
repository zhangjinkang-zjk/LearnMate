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

    <!-- 任务说明的开关。**这个按钮不是装饰**：教练会拿验收标准和需要交付来提问
         （"交付物形态是什么"），而那些字段以前在整个界面上一个字都不显示 —— 学生
         无处可查，只能瞎猜，然后被反复追问同一个问题。 -->
    <button
      v-if="hasDetails"
      class="button button--quiet task-bar__toggle"
      type="button"
      :aria-expanded="detailsOpen"
      @click="toggleDetails"
    >
      <ClipboardList :size="13" />任务说明
      <ChevronDown class="task-bar__chevron" :class="{ 'is-open': detailsOpen }" :size="13" />
    </button>

    <div class="task-bar__switch">
      <button
        class="button button--quiet task-bar__switch-button"
        type="button"
        :aria-expanded="open"
        :disabled="!options.length"
        @click="toggleMenu"
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

    <!-- **必须浮层，不能内联展开。** 这一段最长能到几屏，以前是 flex-basis:100% 挤在
         文档流里，一展开就把下面的编辑器整体推下去 —— 而这一页的主体就是编辑器，
         学生点"任务说明"是想**边看边写**，不是想看它把工作区顶开。
         浮层常有的两个代价在这里都不成立：它盖住的那块本来就不用透出去，位置也就
         固定在任务条正下方，不需要跟着滚动走。点外面收起，和"换一个"共用一套遮罩。 -->
    <div v-if="detailsOpen && hasDetails" class="task-bar__backdrop" @click="detailsOpen = false"></div>
    <section v-if="detailsOpen && hasDetails" class="task-bar__details">
      <div v-if="briefText" class="task-bar__field">
        <span class="task-bar__field-label">任务情境</span>
        <p>{{ briefText }}</p>
      </div>
      <div v-if="problemText" class="task-bar__field">
        <span class="task-bar__field-label">要解决的问题</span>
        <p>{{ problemText }}</p>
      </div>
      <div v-if="focusText" class="task-bar__field">
        <span class="task-bar__field-label">能力重点</span>
        <p>{{ focusText }}</p>
      </div>
      <div v-if="deliverables.length" class="task-bar__field">
        <span class="task-bar__field-label">需要交付</span>
        <ul>
          <li v-for="(item, index) in deliverables" :key="index">{{ item }}</li>
        </ul>
      </div>
      <div v-if="criteria.length" class="task-bar__field">
        <span class="task-bar__field-label">验收标准</span>
        <ul>
          <li v-for="(item, index) in criteria" :key="index">{{ item }}</li>
        </ul>
      </div>
    </section>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'
import { ChevronDown, CircleAlert, ClipboardList, LoaderCircle, Repeat2 } from 'lucide-vue-next'

const props = defineProps({
  task: { type: Object, required: true },
  taskSource: { type: String, default: '' },
  options: { type: Array, default: () => [] },
})
const emit = defineEmits(['select', 'regenerate'])

const open = ref(false)
// **默认收起。** 这一页是全屏工作区，展开的任务说明会盖住它 ——
// 试过默认展开，代价是编辑器少一大截，不值得。按钮本身就在那儿，找得到的。
const detailsOpen = ref(false)

// 两个浮层互斥：两块内容各自都有遮罩，同时开着会多出一层看不出区别的"点一下没反应"
// （点中的是下面那层遮罩，关的是另一个）。开一个就关另一个，行为才是确定的。
function toggleDetails() {
  detailsOpen.value = !detailsOpen.value
  if (detailsOpen.value) open.value = false
}

function toggleMenu() {
  open.value = !open.value
  if (open.value) detailsOpen.value = false
}

// 任务说明的四段都来自服务端任务负载（router 整体透传）。任何一段缺失就不渲染它，
// 全缺时连开关都不出现 —— 空荡荡的"任务说明"比没有更让人困惑。
function text(value) {
  return String(value || '').trim()
}

// 交付物在服务端是**对象**数组（`{id, label, completed}`，见
// advanced/service.py 的 item["deliverables"]），不是字符串数组 ——
// 直接 String() 会渲染成一排 `[object Object]`。验收标准是纯字符串，
// 但同样过这个函数，免得以后形状变了再炸一次。
function label(value) {
  if (value && typeof value === 'object') return text(value.label || value.title || value.name)
  return text(value)
}

function labelList(value) {
  return Array.isArray(value) ? value.map(label).filter(Boolean) : []
}

const briefText = computed(() => text(props.task.brief))
const problemText = computed(() => text(props.task.problem))
const focusText = computed(() => text(props.task.focus))
const deliverables = computed(() => labelList(props.task.deliverables))
const criteria = computed(() => labelList(props.task.criteria))
const hasDetails = computed(() => Boolean(
  briefText.value || problemText.value || focusText.value
  || deliverables.value.length || criteria.value.length,
))

function choose(taskId) {
  open.value = false
  emit('select', taskId)
}
</script>

<style scoped>
/* `position: relative` 是任务说明浮层的定位基准。flex-wrap 现在只剩窄屏那条规则在用
   （标题整行换行），浮层已经不参与排版了。 */
.task-bar { position: relative; display: flex; min-width: 0; flex-wrap: wrap; align-items: center; gap: 10px; padding: 9px 14px; border: 1px solid rgba(63, 91, 49, .28); border-radius: 12px; background: var(--paper); box-shadow: 0 8px 24px rgba(45, 40, 92, .07); }
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
.task-bar__toggle { flex: 0 0 auto; gap: 5px; padding: 6px 11px; font-size: 12px; }
.task-bar__toggle:hover { border-color: #9dbb8d; color: var(--accent-deep); }
.task-bar__toggle:focus-visible { outline: 2px solid var(--accent-deep); outline-offset: 2px; }
.task-bar__chevron { transition: transform .2s ease; }
.task-bar__chevron.is-open { transform: rotate(180deg); }
/* 浮在下面那排之上，**不占流**：展开它，工作区一像素都不动。
   `max-height` 用 vh 而不是 px 为主 —— 窄屏上 320px 可能比编辑器还高，而这里的原则是
   "说明永远不能比它说明的东西还占地方"。超出就自己滚动（overscroll-behavior 挡住
   滚动穿透到下面的编辑器）。 */
.task-bar__details {
  position: absolute;
  z-index: 21;
  top: calc(100% + 6px);
  right: 0;
  left: 0;
  display: grid;
  gap: 10px;
  max-height: min(50vh, 420px);
  padding: 13px 15px;
  border: 1px solid var(--line);
  border-radius: 12px;
  background: var(--paper);
  box-shadow: 0 14px 34px rgba(31, 49, 40, .16);
  overflow-y: auto;
  overscroll-behavior: contain;
}
.task-bar__field { display: grid; gap: 4px; }
.task-bar__field-label { color: var(--accent-deep); font-size: 10px; font-weight: 800; letter-spacing: .04em; }
.task-bar__field p { margin: 0; color: var(--ink); font-size: 12px; line-height: 1.7; overflow-wrap: anywhere; }
.task-bar__field ul { display: grid; gap: 4px; margin: 0; padding-left: 17px; color: var(--ink); font-size: 12px; line-height: 1.7; }
.task-bar__field li { overflow-wrap: anywhere; }
.spin { animation: spin 1s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
/* 窄屏下标题本来就该换行，别跟着挤在一条线上 */
@media (max-width: 760px) {
  .task-bar__title { flex: 1 1 100%; order: 3; white-space: normal; }
  .task-bar__toggle { margin-left: auto; }
}
</style>
