<template>
  <div class="overview-page">
    <div v-if="loading" class="notice">正在同步学习状态…</div>

    <div v-else-if="errorMessage" class="notice">
      <p class="notice__title">暂时无法读取学习概览</p>
      <p>{{ errorMessage }}</p>
      <button class="button button--quiet" type="button" @click="loadOverview">重试</button>
    </div>

    <template v-else>
      <p class="context">
        <span class="context__kicker">学习方向</span>
        <b>{{ profile.direction || '还没有设定' }}</b>
        <template v-if="profile.goal">
          <span class="context__sep">·</span>
          <span class="context__kicker">目标</span>
          <b>{{ profile.goal }}</b>
        </template>
      </p>

      <!-- 主卡和走势图**并排**，不再各占一条通栏。
           通栏的问题不在高度，在形状：两块一样宽、一样左对齐的圆角大矩形上下摞着，
           页面就成了"两个盒子"。并排之后这一行有两种宽度，下面的路径表才是唯一一块通栏。 -->
      <div class="top">
      <!-- 这一页唯一的主行动，也是唯一一块深色面板 —— 深绿是首页定下来的主表面色
           （#1e3c34 + 柠檬绿按钮），内页用它是"沿用"而不是另起一套。

           **布局：左「这一章是什么」 / 右上「去哪」 / 下面一条「讲什么 · 做到哪了」。**
           按钮原来在最底下一行靠右，中间那条 1600px 宽的空带把卡片撑到 300px 高却什么都没说；
           提到标题右侧之后，卡片矮了近三分之一，而内容一件没少。

           深色面上的颜色只有三个：`#f2f7ec`（主）· `#a9bdb0`（次）· `var(--accent)`（**只给这颗
           按钮**）。原来这一块同时有四处柠檬绿在喊 —— 小标、三颗药丸的描边和字、测验值、按钮
           —— 同一块面里四处高饱和，读起来发酸，还分不出主次。 -->
      <section class="focus" aria-labelledby="focus-title">
        <div class="focus__head">
          <p class="focus__lead">{{ focusLead }}</p>
          <h1 id="focus-title" class="focus__title">{{ focusTitle }}</h1>
          <p class="focus__where">{{ focusWhere }}</p>
          <!-- 「为什么是它」。后端 `recommendation.reason` 一直在返回里，页面一个字没用 ——
               主卡于是只有结论、没有理由，学生只能默认"系统说的"。这句理由的每一条分支都在
               `_build_recommendation_reason` 里对着可核实的证据写（薄弱点的正确率、路径进度），
               不是"AI 智能推荐"。只用 `reason`，不用 `criteria`：那句"能够解释…并通过节点测验"
               是把已经写在按钮上的事又说了一遍。 -->
          <p v-if="focusReason" class="focus__reason">{{ focusReason }}</p>
        </div>

        <RouterLink v-if="actionTarget" class="button button--primary focus__cta" :to="actionTarget">{{ actionLabel }}</RouterLink>
        <button v-else class="button button--quiet focus__cta" type="button" @click="loadOverview">重新检查</button>

        <!-- 知识点曾经是三颗描边药丸。描边在界面上是"能点"的信号，而它们不可点 —— 读者
             会去点。改成一行普通文字，用中文的顿号连接：既不再冒充按钮，也不必靠中圆点
             这种"通用元信息"排版（那是模板脸）。 -->
        <p v-if="knowledgeTags.length" class="focus__topics">
          <span class="focus__topics-lead">这一章讲</span>
          <span class="focus__topics-list">{{ knowledgeTags.join('、') }}</span>
        </p>

        <div class="focus__do">
          <!-- 测验这一行**不带进度条**：只有一组测验，一条 4px 的空轨既不能比也不能量，
               只是把「待做 1 组」这五个字又说了一遍。状态由文字承担。 -->
          <p v-if="quizItem" class="focus__quiz">
            <span class="focus__quiz-label">本章测验</span>
            <b class="focus__quiz-value">{{ quizItem.value }}</b>
          </p>
          <RouterLink v-if="reviewTarget" class="focus__aside" :to="reviewTarget">这章有 {{ weakCount }} 个知识点该复习</RouterLink>
        </div>
      </section>

      <!-- 走势图**不从属于主卡，也不和「本周」「进阶学习」并排**。它原来挂在页脚那三栏里，
           和另外两项等宽等权，读起来就是"第三条数据"—— 但它回答的是另一个问题
           （我最近在往前走还是在停），不是同一句话的第三个数。
           放在主卡旁边之后它自成一块，宽度也归它自己。 -->
      <section class="trend" aria-labelledby="trend-title">
        <div class="trend__head">
          <h2 id="trend-title" class="trend__title">{{ trendTitle }}</h2>
          <p v-if="trendTotal" class="trend__total">{{ trendTotal }}</p>
        </div>
        <TrendBars v-if="trendTotal" :weeks="activity.weekTrend" />
        <!-- 一个还没学过的人看到的只能是这句话。别写成"正在生成…"：它不是待办，
             是有了学习记录之后才会有的东西。六根 0 高的空柱比这句话更让人以为坏了。 -->
        <p v-else class="trend__quiet">还没有学习记录。开始之后，这里会按周显示你有几天在学习。</p>
      </section>
      </div>

      <!-- 四条路径是一张表，不是四张卡：它们本来就是同一批字段横着比，
          摊成卡片只会得到四个等权的盒子，扫不出"哪条快学完了"。 -->
      <section class="paths" aria-labelledby="paths-title">
        <!-- 这一行是**总账**：跨路径的节点总数、已学完数、总体正确率。三样都是"全部加起来"
             的数，别处没有第二个地方能回答，所以收在它们描述的那张表头上 —— 原来它们散在
             页脚那条统计行里，和"本周读了多久"这种周内数字混在一起读。 -->
        <div class="paths__head">
          <h2 id="paths-title" class="paths__title">我的学习方向</h2>
          <p v-if="paths.length" class="paths__note">
            <span>{{ paths.length }} 条路径 · 共 {{ totalNodes }} 个节点</span>
            <span class="paths__note-lead">已学完 {{ completedNodesTotal }} 个</span>
            <span>{{ accuracyText }}</span>
          </p>
        </div>

        <DataTable
          v-if="paths.length"
          :style="{ '--data-table-columns': pathColumnTemplate }"
          :columns="pathColumns"
          :rows="paths"
          row-key="id"
          :is-current="(row) => row.is_current"
        >
          <template #default="{ row, index }">
            <span class="row__no">{{ index + 1 }}</span>
            <span class="row__name" :title="row.name">{{ row.name }}</span>
            <!-- 路径的形状：**每个节点一个等宽方格**，横着铺满这一列。
                 哪几站走过了、现在站在哪、前面还剩几站，一横条看完。
                 读屏当一个图形读（见 `trackLabel`），不逐格念。 -->
            <span class="row__track" role="img" :aria-label="trackLabel(row)">
              <i v-for="cell in trackCells(row)" :key="cell.key" :class="`is-${cell.kind}`"></i>
            </span>
            <span class="row__pct">{{ row.progress }}%</span>
            <span v-if="!isNarrow" class="row__now" :title="row.current_node ? row.current_node.title : '已学完'">
              {{ row.current_node ? row.current_node.title : '已学完' }}
            </span>
            <span class="row__when" :title="row.last_active_date || '这条路径没有留下时间戳'">{{ lastActiveText(row) }}</span>
            <span class="row__count">{{ row.completed_nodes }} / {{ row.total_nodes }}</span>
          </template>
        </DataTable>
        <p v-else class="paths__empty">{{ pathsEmptyCopy }}</p>
      </section>

      <!-- 进阶学习的剧透。这一页原来只在"整条路径学完"时那个按钮上出现过「进阶学习」
           四个字，学生看不出它是什么；而它**其实不设门槛**（`AdvancedLearningPage.vue` 里
           写着：一个基础节点都没做完也能拿自己的项目去问教练，旧的封锁页已删），
           所以这里要说明白它是什么、并且**现在就能进**，而不是等哪天点到才发现。 -->
      <!-- 页脚：**两个去处 + 一周的账，共用一条带**。
           它们原来是上下两条独立的全宽行 —— 一条 105px 的横幅只为放一句话，
           底下再跟一行 24px 的统计，中间还隔着 32px 的空隙。三个都是"小内容"，
           各自占满一整行是浪费：并排就装得下。

           **原来只有两块，左边那块空得很明显**：标题和按钮占掉 400px 之后，中间
           剩 800px 没有任何东西，一块 1000px 宽的盒子里排着一行字。补上「资料库」
           之后每一块的宽度都在 500px 上下，块内不再有大段空白，两块**去处**（进阶学习、
           资料库）也并在一起，和右边那笔"这一周干了什么"的账分开读。 -->
      <footer class="foot">
        <!-- **整块可点，块里没有按钮。** 两块各留一颗 `button--quiet` 的时候，读者要先
             判断"这颗按钮和三行文字是什么关系"，而它本来就是"这块地方可以去"——
             把标题做成链接、再用 `::after` 把它铺满整块，点击区域和它要表达的区域
             就对上了。链接的文字仍然只是「进阶学习」四个字，读屏读出来的也是它，
             不是整段说明。 -->
        <section class="entry" aria-labelledby="advanced-title">
          <div class="entry__head">
            <h2 id="advanced-title" class="entry__title">
              <RouterLink class="entry__link" :to="{ name: 'advancedLearning' }">进阶学习</RouterLink>
            </h2>
            <span class="entry__tag">应用实践</span>
          </div>
          <p class="entry__body">
            <b>每通过 10 个基础节点，系统自动下发一批实践任务</b>，此后每满 10 个更换一批。没有任务时，也可以带着自己的项目直接请教教练。
          </p>
        </section>

        <!-- 资料库。**先说是干什么用的，再给数。** 原来这块只有一行「共 41 份，已读 10 份」——
             三个数说得都对，但它们只回答了"有多少"，没回答"我为什么要打开它"。资料在
             这个产品里的位置是**复习材料**：`path/service.py` 里节点能否通过只看测验成绩
             （`node_read_count` 不参与任何判定），所以资料从头到尾都是可查可回看的辅助，
             不是一道要读完的关卡。这句话把这个位置说清楚，数字退到第二句。
             说「已读 N 份」不说「进度 N%」—— 给个百分比就成了门禁（和当初删掉的
             「资料 1 / 4 份」同因）。 -->
        <section class="entry" aria-labelledby="library-title">
          <div class="entry__head">
            <h2 id="library-title" class="entry__title">
              <RouterLink class="entry__link" :to="{ name: 'resourceLibrary' }">资料库</RouterLink>
            </h2>
          </div>
          <p class="entry__body">
            <b>每个节点的讲解、脑图与练习都收在这里，复习时按知识点回看。</b>{{ libraryText }}
          </p>
        </section>

        <!-- 右半边是**本周**：标题 + 一排七格 + 三个数 + 一扇通向个人画像的门。

             它原来和另外两块一样，是一块"读一读"的静态区；现在**整块可点，去个人画像** ——
             和左边两块的机制完全相同：标题里那颗链接用 `::after` 铺满整块，块里不再有
             第二颗按钮。三块长得一样，点法也一样。

             **「本周」两个字后跟一句只给读屏的「：看个人画像」。** 光把 `::after` 铺开
             是不够的：那样读屏读出来是一个名叫「本周」的链接，点进去却是画像页 ——
             名实不符。可见文字仍然只有「本周」（块里不出现按钮样的东西），但这个名字
             既含住了可见的「本周」，又把去处说出来了。

             **那三个数是这一周的账，和标题同一个范围**（`questions_this_week` /
             `quizzes_passed_this_week` / `read_seconds_this_week`）。它们和主卡上那个
             「本章测验 已通过」**不是同一件事** —— 主卡说的是"当前这个节点的测验做没做完"
             （节点级、不限本周）。口径不同的两个数摆在同一屏上，读者只会读成
             "通过了"和"还没过测验"两句互相否认的话，所以主卡那一行的标签从「测验」改成了
             「本章测验」，把范围写在字面上。 -->
        <section class="week" aria-labelledby="week-title">
          <!-- **三行，各占一行**：标题 / 七格 / 三个数。标题原来和七格挤在一行（"本周 ···○"），
               七格挨着标题看起来像标题的附属；分开之后这一块读起来是"本周 → 每天 → 总计"，
               从上往下一条线。它和 `.entry__title` 同为 18px，三块的标题因此落在同一条水平线上。 -->
          <h2 id="week-title" class="week__title">
            <RouterLink class="week__link" :to="{ name: 'profile' }">本周<span class="sr-only">：看个人画像</span></RouterLink>
          </h2>
          <ol class="week__days" aria-label="本周每天是否有学习记录">
            <li
              v-for="day in activity.weeklyDays"
              :key="day.date"
              class="week__day"
              :class="{ 'is-active': day.active, 'is-today': day.is_today }"
              :title="dayTitle(day)"
            >
              <span class="week__dot" aria-hidden="true"></span>
              <span class="week__label">{{ weekdayLabel(day.date) }}</span>
            </li>
          </ol>
          <!-- 本周一次都没来时，那排格子只会全是灰的 —— 一句"上次是 X"才说得清现状。
               来过时就不说了：来了几天格子上看得见。 -->
          <p v-if="!activity.activeDaysThisWeek" class="week__quiet">{{ activityText }}</p>
          <p class="week__facts">
            <span>{{ questionsText }}</span>
            <span>{{ quizText }}</span>
            <span>{{ readText }}</span>
          </p>
        </section>
      </footer>
    </template>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { learningApi } from '@/shared/api/learningApi'
import DataTable from '@/shared/ui/DataTable.vue'
import TrendBars from '@/shared/ui/TrendBars.vue'
const loading = ref(true)
const errorMessage = ref('')
const profile = reactive({ direction: '', goal: '' })
const paths = ref([])
const path = reactive({ id: null, completed: false, total: 0, completedNodes: 0 })
const diagnosis = reactive({ answered: 0 })
const recommendation = reactive({ action: '', reason: '', targetId: null, target: null })
const activity = reactive({
  activeDaysThisWeek: 0,
  readSecondsThisWeek: 0,
  questionsThisWeek: 0,
  quizzesPassedThisWeek: 0,
  weeklyDays: [],
  weekTrend: [],
  lastActiveDate: null,
  windowDays: 0,
})
const summary = reactive({ correctRate: null })
// 资料库那一块的三个数。后端把 `get_stats` 已经算好的那份原样透出来（`resources`），
// 页面此前一个字没读过。
const library = reactive({ total: 0, readCount: 0, collectedCount: 0 })
const weakPoints = ref([])

const unwrap = (response) => response?.data?.data ?? response?.data ?? null
const toInt = (value) => {
  const numeric = Number(value)
  return Number.isFinite(numeric) && numeric > 0 ? Math.round(numeric) : 0
}

// ── 主行动 ──────────────────────────────────────────────────
// 「接着上次」指的不是"队列里下一个没做完的节点"，而是**你离开时手上那件事**：
// 还剩几份资料、测验做没做完。所以按钮写什么和点去哪，由同一个状态算出来 ——
// 这两个以前是分家的（文字取后端的 action_label，落点写死基础讲解），
// 于是出现"按钮说开始测验、点进去是阅读页"。
const remainingResources = computed(() => Math.max(
  0,
  toInt(recommendation.target?.resources) - toInt(recommendation.target?.resources_done),
))
const remainingQuiz = computed(() => (toInt(recommendation.target?.quiz_total) > toInt(recommendation.target?.quiz_answered) ? 1 : 0))

const focusLead = computed(() => (path.completed ? '这条路径' : '接着上次'))

const focusTitle = computed(() => {
  if (path.completed) return '整条路径已经学完'
  return recommendation.target?.title || recommendation.action || '学习路径生成中'
})

const focusWhere = computed(() => {
  if (path.completed) return '可进入进阶学习，用实践任务巩固已学内容'
  if (!recommendation.targetId) return '学习路径生成中，尚无可用节点'
  const current = paths.value.find((item) => item.is_current)
  if (!current) return ''
  return `${current.name}，第 ${current.completed_nodes + 1} / ${toInt(current.total_nodes) || path.total} 个节点`
})

// 主卡上的「为什么是它」。整条路径学完、或还没有可学节点时不显示 —— 那时后端给的理由
// 说的是"路径上的下一个待学节点"，而这个节点并不存在。
const focusReason = computed(() => {
  if (path.completed || !recommendation.targetId) return ''
  return recommendation.reason || ''
})

// 这一栏只回答一个问题：**还差什么才能往下走**。答案只有一项 —— 测验。
//
// 这一章确实还有"资料"，但它是**可选材料**：`path/service.py` 里节点完成的判定只有一句
// `passed = score >= threshold * 100`，过了就 `node_status = "completed"` 并解锁下一节点；
// `node_read_count` **从头到尾不参与任何判定**，读了不推进，不读也不拦。
// 所以「资料 1 / 4 份」加一条进度条，是把"读完 4 份"说成一道门禁 —— 产品没有这个意思。
//
// 试过退一步：只报总数「资料 4 份」、不给分母不给条。**结果它和测验那行长得一模一样**
// （都是"标签 + 值"），测验进度为 0 时那条空轨又看起来只是条分隔线 —— 读者仍然会把它
// 当成一条要求。要么是要求（假的），要么是噪声，没有第三种。所以整行删掉。
//
// **曾经还有第三行「任务 n / m 个」，也已删除。** 它不是系统里的一个概念，是把上面两类加起来：
//   `task_total = 资料数 + (有测验 ? 1 : 0)`，`task_completed = 已读资料数 + (测验全答完 ? 1 : 0)`。
// 所以「任务 2 / 5」就是「资料 1 / 4」+「测验 1 / 1」，一个学生做不了、也找不到的第三件事。
// （`garden_progress` 里那对 `completed_tasks` / `total_tasks` **仍然活着** ——
//  `StudyGarden.vue` / `TreeReviewScene.vue` 拿它挑树的生长阶段。是这里不该把它当成
//   一件"要做的事"展示出来，不是那个字段没用。）
const quizItem = computed(() => {
  if (!recommendation.target || path.completed) return null
  const target = recommendation.target
  const total = toInt(target.quiz_total)
  if (!total) return null
  const answered = toInt(target.quiz_answered)
  // 只给一个字符串。**不再返回 `done`** —— 它以前只用来给"已通过"上柠檬绿，而那支绿
  // 现在只属于主按钮；状态本身"已通过 / 待做 1 组"这几个字已经说完了。
  return { value: answered >= total ? '已通过' : `待做 ${total - answered} 组` }
})

// 这一章实际要学的知识点名。**只渲染名字** —— 后端 `knowledge_points` 那个计数
// 是同一批标签的长度，页面上不重复说一遍"共 N 个知识点"。
const knowledgeTags = computed(() => {
  const tags = recommendation.target?.knowledge_tags
  if (!Array.isArray(tags)) return []
  return tags.filter((tag) => typeof tag === 'string' && tag.trim()).slice(0, 6)
})

// 三句话都写**要做的动作**，不写"接着…"：卡片最上面那行小字已经是「接着上次」，
// 按钮再写一次"接着"就是同一句话说两遍，而且"读"只说对了三种情况里的一种 ——
// 资料读完只剩测验时点进去是测验页，写"读"是错的。
const actionLabel = computed(() => {
  if (path.completed) return '进入进阶学习'
  if (!recommendation.targetId) return ''
  if (remainingResources.value) return '继续学习'
  if (remainingQuiz.value) return '做本章测验'
  return '开始学习'
})

const actionTarget = computed(() => {
  if (path.completed) return { name: 'advancedLearning' }
  if (!recommendation.targetId) return null
  const query = { node: recommendation.targetId }
  if (path.id) query.pathId = path.id
  // 资料读完、只剩测验时才去测验页 —— 和按钮上的字是同一个判断。
  if (!remainingResources.value && remainingQuiz.value) return { name: 'foundationTest', query }
  return { name: 'fundamentals', query }
})

// ── 学习方向表 ──────────────────────────────────────────────
// 窄一点的桌面放不下「当前节点」那一列（路径名会先被挤没）。列名、列宽、单元格
// 三样必须一起变，所以都从这一个 computed 出来 —— 分开放就会再次走散。
//
// 「上次学习」两档都有，掉的是「当前节点」：前者是固定宽度的短词，后者是长度不定的
// 节点标题 —— 挤的时候先让标题走。而"这条路径我多久没碰了"正是这张表最该一眼看出来的事。
const narrow = ref(false)
const narrowQuery = typeof window !== 'undefined' ? window.matchMedia('(max-width: 1500px)') : null
const syncNarrow = () => { narrow.value = Boolean(narrowQuery?.matches) }

// 中间那个空列名对应轨道那一列 —— 它自己会说话，不需要表头。
const pathColumns = computed(() => (narrow.value
  ? [{ label: '路径', span: 2 }, { label: '' }, { label: '完成度' }, { label: '上次学习' }, { label: '进度' }]
  : [{ label: '路径', span: 2 }, { label: '' }, { label: '完成度' }, { label: '当前节点' }, { label: '上次学习' }, { label: '进度' }]))
const isNarrow = computed(() => narrow.value)
const pathColumnTemplate = computed(() => (narrow.value
  ? '30px minmax(0, 1.4fr) minmax(150px, 1.8fr) 62px 104px 84px'
  : '30px minmax(0, 1.1fr) minmax(240px, 2.6fr) 68px minmax(0, 1fr) 104px 88px'))

// 全部路径的节点总数与已学完数。表里每一行各自给了 N / M，但**整体到哪了**页面别处没说 ——
// 这是唯一一个跨路径的总账。节点属于且只属于一条路径，跨路径相加不会重复计数。
const totalNodes = computed(() => paths.value.reduce((sum, item) => sum + toInt(item.total_nodes), 0))
const completedNodesTotal = computed(() => paths.value.reduce((sum, item) => sum + toInt(item.completed_nodes), 0))
const pathsEmptyCopy = computed(() => (path.id ? '暂无其他路径' : '学习路径生成中，完成后将按顺序列出各科目'))

// ── 本周 ────────────────────────────────────────────────────
// 「本周」而不是「近 7 天」：滚动窗口的起点每天都在动，没人会对齐它。日历周是学生
// 自己记账用的单位。
//
// 这句话**只在本周一次没来时出现**（模板上的 `v-if="!activity.activeDaysThisWeek"`）。
// 本周来过时不用说话：来了几天，上面那排格子自己看得见 —— 再写一句"本周来了 3 天"
// 是把格子已经说过的事说一遍。所以这里不再有"来了 N 天"那个分支。
// `lastActiveDate` 为空不是"没来过"，是"窗口内没来过"（后端只回溯 30 天），
// 所以那句话要把窗口说出来，不能写成"从没来过"。
const activityText = computed(() => {
  if (!activity.lastActiveDate) return '30 天内没来过'
  const last = relativeDay(activity.lastActiveDate)
  // 「上次是今天」在中文里不成立 —— 本周一次没来、而最近一次是今天，这组合到不了这里。
  return last ? `上次是${last}` : '还没来过'
})

// 三个数都**不再自带「本周」**：它们上面就是「本周」这个标题，一句话里说三遍是噪声。
// 区块已经用 `aria-labelledby` 指向那个标题，读屏软件读到的仍然是"本周，答了 12 题"。
const questionsText = computed(() => (activity.questionsThisWeek > 0
  ? `答了 ${activity.questionsThisWeek} 题`
  : '还没答题'))
// 「通过」数的是**节点测验**（`node_quiz` 事件里 `metadata.passed` 为真的次数），
// 不含交卷和诊断 —— 那些不是"过了一关"。别写成"测验 N 次"：那是做了几次，不是过了几次。
//
// **只有这一项自带「本周」，另外两项不带。** 因为它和主卡上那颗「本章测验 已通过」
// 撞的是同一件事的两个范围：主卡问的是"当前这个节点做没做完"（节点级、不限周），
// 这里问的是"本周过没过"（周级）。两句都对，可「还没过测验」摆在那里读起来是一句
// 关于**全部历史**的断言 —— 和主卡当场互相否认。上面那个「本周」标题离着两行，
// 挡不住这种读法；把范围写进这句话里才挡得住。
// 另外两项（答了几题、读了多久）没有这个冲突，不必跟着重复"本周"。
const quizText = computed(() => (activity.quizzesPassedThisWeek > 0
  ? `本周通过 ${activity.quizzesPassedThisWeek} 个测验`
  : '本周还没过测验'))
// 说「读了」不说「学习了」：系统里**只有阅读有真实计时**（基础讲解页在文档可见时每 30 秒
// 上报增量），测验、课堂、对话都没记时。写成"学习了 X 小时"，只做测验不读资料的人会显示
// 0，和同一行的"本周来了 N 天"当场打架。宁可范围写小，不能不实。
const readText = computed(() => (activity.readSecondsThisWeek >= 60
  ? `读了 ${formatDuration(activity.readSecondsThisWeek)}`
  : '没读资料'))

// ── 资料库 ──────────────────────────────────────────────────
// 说「共 N 份，已读 M 份」，**不给百分比、不给分母当门禁**：资料是学完一章自动产出的，
// 没有"应该读完"这回事。写成「已读 12 / 36」就变成了一张待办清单 —— 和当初从主卡删掉的
// 「资料 1 / 4 份」犯的是同一个错。
// 一份都没有时**返回空串而不是报 0**：这块地方现在通篇在说"这里有什么、为什么值得点"，
// 「0 份」在这样一句话旁边不是中性信息，是"你还什么都没有"。新账号的落点是资料库页面
// 自己的空状态，那里才是该说"学完一个节点后会有"的地方。
const libraryText = computed(() => {
  if (!library.total) return ''
  const read = `共 ${library.total} 份，已读 ${library.readCount} 份`
  return library.collectedCount > 0 ? `${read}，收藏 ${library.collectedCount} 份` : read
})

// ── 走势 ────────────────────────────────────────────────────
// 周数从数据里现算，不写死"最近 6 周"：后端 `_TREND_WEEKS` 一改，标题会跟着变，
// 而写死的标题会开始撒谎，且没人会发现。
const trendWeeks = computed(() => activity.weekTrend.length)
const trendTitle = computed(() => (trendWeeks.value ? `最近 ${trendWeeks.value} 周学习天数` : '学习天数'))
// 柱顶已经印着每周的天数了，这里只给一个整体印象。**平均值而不是总和**：总和要读者自己
// 拿"一共 23 天"去除以周数才知道节奏，而节奏正是这张图要回答的事。
// 值为 0 时返回空串，模板据此把图整个换成一句说明 —— 六根 0 高的空柱看着像加载失败。
const trendTotal = computed(() => {
  if (!trendWeeks.value) return ''
  const days = activity.weekTrend.reduce((sum, week) => sum + toInt(week?.active_days), 0)
  if (!days) return ''
  const average = days / trendWeeks.value
  // 差 0.05 以内就当整数说：「平均每周 5 天」比「平均每周 5.0 天」像人话。
  const text = Math.abs(average - Math.round(average)) < 0.05 ? String(Math.round(average)) : average.toFixed(1)
  return `平均每周 ${text} 天`
})
// 正确率后面带上题数：58% 是 3 道题还是 50 道题得来的，可信度差着量级。
const accuracyText = computed(() => {
  if (summary.correctRate === null) return '暂无答题记录'
  const rate = `答题正确率 ${Math.round(summary.correctRate * 100)}%`
  return diagnosis.answered > 0 ? `${rate}（${diagnosis.answered} 题）` : rate
})

// 复习入口只在后端给出了可跳转的章节时才出现，不在页面上编一个。
const reviewTarget = computed(() => {
  const point = weakPoints.value[0]
  if (!point?.path_id || !point?.node_id) return null
  return { name: 'foundationTest', query: { pathId: point.path_id, node: point.node_id } }
})
const weakCount = computed(() => weakPoints.value.length)

// ── 路径方格 ────────────────────────────────────────────────
// 后端四种节点状态 → 四种颜色的格子。**四种都留着，不把「可开始」并进「正在这里」。**
// 并过一版：`unlocked` 和 `in_progress` 都画成柠檬绿"当前站"，于是**一条路径上有几个
// 未开始的节点，就亮几个柠檬绿的当前站** —— 实测 Transformer 那条同时亮着两个，而右边
// 「当前节点」那一列只写着一个标题，同一行自己跟自己打架。
const TRACK_KIND = { completed: 'done', in_progress: 'current', unlocked: 'available' }

/**
 * 一行的格子序列：`[{ key, kind }]`。
 *
 * **"正在这里"全行只剩一个。** `in_progress` 是"打开过、没做完"—— 节点一被点开就写这个
 * 状态（`helpers.py` 绑定资源时），而路径中段没有前置的节点一出生就是 `unlocked`，
 * 所以同一条路径上挂着一串 `in_progress` 是常态，后端自己也按复数在数
 * （`path/service.py` 里 `in_progress = sum(...)`）。照状态直接上色的话，这一行会亮起
 * 好几个柠檬绿实心格，而右边「当前节点」只写着一个名字 —— 屏幕上同时有两个"你现在在这"。
 *
 * 规则和后端取当前节点的那句（`path/service.py`：按 order_index 第一个
 * `unlocked`/`in_progress`）**同源**：第一个非"已完成"的格子升格为实心柠檬绿，
 * 其余原本要画成实心的降为空心环（"能学，但不是这一站"）。
 */
function trackCells(row) {
  const nodes = Array.isArray(row?.nodes) ? row.nodes : []
  const kinds = nodes.map((node) => TRACK_KIND[String(node?.status ?? '')] || 'locked')
  const at = kinds.findIndex((kind) => kind === 'current' || kind === 'available')
  return nodes.map((node, i) => ({
    key: node?.id ?? i,
    kind: i === at ? 'current' : at >= 0 && kinds[i] === 'current' ? 'available' : kinds[i],
  }))
}

const TRACK_WORD = { done: '已完成', current: '正在学', available: '可开始', locked: '未解锁' }

// 整条轨道当一个图形念，**不逐格念**：最多 23 个格子，读屏一格一格报出来是一串噪声，
// 而且右边「完成度」「进度」两列已经把总数说过了；这里补的是那两列没有的分布。
// 数的是 `trackCells` 出来的结果，不是原始状态 —— 念出来的分布必须和画出来的一致。
function trackLabel(row) {
  const counts = {}
  for (const cell of trackCells(row)) counts[cell.kind] = (counts[cell.kind] || 0) + 1
  const parts = ['done', 'current', 'available', 'locked']
    .filter((kind) => counts[kind])
    .map((kind) => `${TRACK_WORD[kind]} ${counts[kind]} 个`)
  return `${row?.name || '路径'}：${parts.join('，') || '还没有节点'}`
}

function formatDuration(seconds) {
  const minutes = Math.round(seconds / 60)
  if (minutes < 60) return `${minutes} 分钟`
  return `${Math.floor(minutes / 60)} 小时 ${minutes % 60} 分`
}

// ── 本周七格 ────────────────────────────────────────────────
// 星期几**从日期算**，不用数组下标 —— 后端给的就是周一开头，但下标一旦对上了一个错的
// 约定就会整排错位，而日期是自证的。解析按 UTC 走，和 `relativeDay` 同一个理由：
// 库里是 naive 时间，按本地时区解析会整体偏一天。
const WEEKDAY_NAMES = ['一', '二', '三', '四', '五', '六', '日']
function weekdayLabel(value) {
  const parts = /^(\d{4})-(\d{2})-(\d{2})$/.exec(String(value || ''))
  if (!parts) return ''
  const weekday = new Date(Date.UTC(Number(parts[1]), Number(parts[2]) - 1, Number(parts[3]))).getUTCDay()
  return WEEKDAY_NAMES[(weekday + 6) % 7]
}

function dayTitle(day) {
  const label = `${Number(String(day.date).slice(5, 7))} 月 ${Number(String(day.date).slice(8, 10))} 日`
  const state = day.active ? '有学习记录' : '没有学习记录'
  return `${label}（周${weekdayLabel(day.date)}）${day.is_today ? ' · 今天' : ''} ${state}`
}

// 每条路径「上次学到哪天」。后端给日期不给时间戳，所以这里也只做日期运算。
//
// 日期为空时**不能一律说"还没开始"**：`regenerate_path` 承接已完成主题用的是批量
// `.update(node_status="completed")`，它不写 `completed_at` —— 那条路径会有十几个已完成
// 节点、却一个时间戳都没有（实测的 机器学习 那条就是 10 / 23）。对它说"还没开始"是一句
// 直接和左边 43% 打架的假话。所以：有完成节点但没时间戳 → 承认"暂无记录"；
// 一个节点都没动过才是"还没开始"。
function lastActiveText(row) {
  const value = row?.last_active_date
  if (value) return relativeDay(value) || '暂无记录'
  return toInt(row?.completed_nodes) > 0 ? '暂无记录' : '还没开始'
}

// 后端回的是**日期**不是时间戳（库里存的是 naive 时间，当时间戳解析会整体偏一个时区），
// 所以这里也只按日期相减，不做时刻运算。
function relativeDay(value) {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(String(value || ''))
  if (!match) return ''
  const then = Date.UTC(Number(match[1]), Number(match[2]) - 1, Number(match[3]))
  const now = new Date()
  const today = Date.UTC(now.getFullYear(), now.getMonth(), now.getDate())
  // 服务端按 UTC 归日、浏览器按本地日，UTC+8 的凌晨相减会出现 0 甚至 -1，两种都当"今天"。
  const days = Math.round((today - then) / 86400000)
  if (days <= 0) return '今天'
  if (days === 1) return '昨天'
  return `${days} 天前`
}

function resetActivity() {
  Object.assign(activity, {
    activeDaysThisWeek: 0,
    readSecondsThisWeek: 0,
    questionsThisWeek: 0,
    quizzesPassedThisWeek: 0,
    weeklyDays: [],
    lastActiveDate: null,
    windowDays: 0,
  })
}

function resetState() {
  Object.assign(profile, { direction: '', goal: '' })
  Object.assign(path, { id: null, completed: false, total: 0, completedNodes: 0 })
  Object.assign(diagnosis, { answered: 0 })
  Object.assign(recommendation, { action: '', reason: '', targetId: null, target: null })
  resetActivity()
  Object.assign(summary, { correctRate: null })
  paths.value = []
  weakPoints.value = []
}

async function loadOverview() {
  loading.value = true
  errorMessage.value = ''
  resetState()
  try {
    const overview = unwrap(await learningApi.getOverview()) || {}
    const profileData = overview.profile || {}
    const pathData = overview.path || {}
    const advice = overview.recommendation || {}
    const activityData = overview.activity || {}
    const summaryData = overview.summary || {}
    Object.assign(profile, { direction: profileData.direction || '', goal: profileData.goal || '' })
    Object.assign(path, {
      id: pathData.id || null,
      completed: pathData.completed === true,
      total: toInt(pathData.total_nodes),
      completedNodes: toInt(pathData.completed_nodes),
    })
    Object.assign(diagnosis, { answered: toInt((overview.diagnosis || {}).answered) })
    Object.assign(recommendation, {
      action: advice.action || '',
      reason: advice.reason || '',
      targetId: advice.target_id ?? null,
      // `target` / `paths` 是后端的增量字段：旧进程没有它们也要能跑，
      // 缺了就退回只用 `action` + `target_id` 的旧形状。
      target: advice.target && typeof advice.target === 'object' ? advice.target : null,
    })
    Object.assign(activity, {
      activeDaysThisWeek: toInt(activityData.active_days_this_week),
      readSecondsThisWeek: toInt(activityData.read_seconds_this_week),
      questionsThisWeek: toInt(activityData.questions_this_week),
      quizzesPassedThisWeek: toInt(activityData.quizzes_passed_this_week),
      // 七格**原样收下**，缺字段就是空数组、那排格子不渲染 —— 不在前端补一份假日历。
      weeklyDays: Array.isArray(activityData.weekly_days) ? activityData.weekly_days : [],
      // 同上：后端按时间从早到晚排好，前端只判它是不是数组，不重排也不补空周。
      weekTrend: Array.isArray(activityData.week_trend) ? activityData.week_trend : [],
      lastActiveDate: activityData.last_active_date || null,
      windowDays: toInt(activityData.window_days),
    })
    const resourceData = overview.resources && typeof overview.resources === 'object' ? overview.resources : {}
    Object.assign(library, {
      total: toInt(resourceData.total),
      readCount: toInt(resourceData.read_count),
      collectedCount: toInt(resourceData.collected_count),
    })
    const rate = summaryData.correct_rate
    summary.correctRate = rate === null || rate === undefined || !Number.isFinite(Number(rate)) ? null : Number(rate)
    paths.value = Array.isArray(overview.paths) ? overview.paths.slice(0, 6) : []
    weakPoints.value = Array.isArray(overview.blind_spots) ? overview.blind_spots : []
  } catch (error) {
    errorMessage.value = error?.response?.data?.detail || error?.message || '请稍后重试'
  } finally {
    loading.value = false
  }
}
onMounted(() => {
  syncNarrow()
  narrowQuery?.addEventListener('change', syncNarrow)
  loadOverview()
})
onBeforeUnmount(() => narrowQuery?.removeEventListener('change', syncNarrow))
</script>

<style scoped>
/* ── 字号阶梯：12 / 14 / 16 / 18 / 22 / 40，只有这六档 ──
   这一页原来有 13/15/16/17/18/20/22 七档挤在 1.7 倍的范围里 —— 15 和 16 在屏幕上分不出来，
   18/20/22 三档却在做着三件不同的事，于是"哪块更重要"根本读不出来。层级是靠**拉开档位**
   建立的，不是靠多给几档。这套档位对齐 Material Design 3 的 role ramp（Display / Headline /
   Title / Body / Label），按本项目 2.5K 观看距离整体放大了一档：
     40 = display（主卡唯一标题，走 clamp，这里不参与）
     22 = headline（区块标题：我的学习方向）
     18 = title   （行名、完成度、横幅标题、章节数值、主按钮）
     16 = body    （说明文字、当前节点、进度、统计行）
     14 = label   （表头、行号、kicker、章节标签）
     12 = label-sm（药丸）
   **新加字号前先看它落在哪一档**，不要引入第七档。（两个媒体查询里的 32/26 是窄屏下
   display 那一档的覆盖值，不属于正文阶梯。） */

/* 一屏一版：高度由 .page-container 那一格给定（父级是 grid 的 minmax(0,1fr)）。
   字号按 2.5K 的观看距离整体放大了一档 —— 1080p 的 14px 拿到 2560 宽上太小。
   内容宽度封顶 1760：2560 的屏上把一行铺满，主卡会变成一条 2400px 宽的绿带 ——
   那不是"撑满"，那是没设计。桌面应用在大屏上都是内容居中 + 两侧留边。 */
/* `safe center` 不是可有可无的：内容比容器高一点点时（1440×900 实测差 30 来像素），
   光写 `center` 会往上下两头同时溢出，上面那行"学习方向"被裁掉且滚不回去。 */
/* 高度预算：整页必须落在 1440p 屏**扣掉浏览器自身那 100 多像素**之后的高度里，
   所以要留出 200px 以上的余量，不能卡着 1384 排。下面这些 clamp 的上限都是按
   "笔记本上也不出滚动条"定的，不是按 1440p 最大化定的。 */
/* 行高 56px 是**这一页高度的主要调节阀**。四行各减 12px 就是 48px，正好换来走势图
   那一栏的高度（见 `.trend`），而路径表本身该给的信息一个没少：一行的内容里最高的
   是 40px 的路线，56 让它上下各留 8px，仍然是"一行一条路径"的疏密。 */
/* `--data-table-pad: 0`：表没有外框了（见 `DataTable.vue`），内容要和上面的区块标题
   对齐到同一条左边线，再留 28px 内边距就会整张表缩进去一截。 */
.overview-page { --ink: #46504a; --data-table-row-height: 56px; --data-table-pad: 0px; display: grid; align-content: start; gap: clamp(10px, 1.4vh, 16px); width: 100%; max-width: 1760px; height: 100%; margin: 0 auto; overflow: hidden; }

/* 主卡 + 走势图。**这一行是整页唯一一处不等宽的排布**，也是它存在的理由：两块通栏大矩形
   摞起来会读成"两个盒子"，拆成一宽一窄就把主次说清楚了 —— 左边是"现在做什么"（主），
   右边是"我最近怎么样"（辅）。

   0.55 这个比例是照**柱子**定的，不是照感觉：走势图那一栏减去内边距要有 540px 左右，
   六根柱子才会是 51px 宽、间隔 40px 那种正常的柱状图；再宽就变成六块色板漂在空地上。
   阈值 1420 也不是随手写的：再窄下去主卡里的标题 + 按钮就放不到一行了。 */
.top { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 0.55fr); gap: 0 40px; align-items: center; }

.context { display: flex; align-items: baseline; gap: 8px; margin: 0; color: var(--ink); font-size: 14px; white-space: nowrap; }
.context__kicker { color: var(--muted); font-size: 12px; }
.context__sep { color: var(--line); }
.context b { overflow: hidden; font-weight: 500; text-overflow: ellipsis; }
/* 这一行右端原来挂着一颗「点击查看学习画像」。删掉有两个理由：一是它的去处现在由页脚
   那块「个人画像」承担，同一页上不该有两个入口通向同一页；二是它挂不住 —— 这行是
   `white-space: nowrap` 的一句长话（方向 + 目标），目标写得长时那颗链接会被挤到
   右侧头像底下，实测就是叠在一起。 */

/* ── 主行动：全页唯一一块深色 ── */
/* 深绿 #1e3c34 + 柠檬绿是首页已经定下的主表面色，内页沿用同一套。
   浅色的"淡绿卡片"在 2560 的屏上几乎和白底分不出前后景，所以主卡必须是实心的。

   **格子是 [左 1fr | 右 auto] × 三行：**
     row1  这一章是什么（小标 / 标题 / 副行）   ←→   去哪（按钮）
     row2  ── 这一章讲 …… ────────────────────（整行）
     row3  ── 测验 …… 复习入口 ───────────────（整行，带发丝线）

   按钮原来在最底下一行靠右，于是标题右侧到按钮之间横着一条 1600px 宽、两层楼高的空带 ——
   卡片因此长到 300px，而那一段什么都没说。把按钮提到标题右边的同一行之后，卡片矮了近三分之一。

   深色面上的字色只有三个，**多一个都不加**：
     #f2f7ec  主（标题、知识点名、测验值、可点的复习入口）
     #a9bdb0  次（小标、副行、「这一章讲」「测验」两个标签）
     var(--accent)  **只给这一颗按钮** —— 它在这一页是"主行动"的颜色，别处用都会把它稀释掉。
   之前这一块同时有四处柠檬绿（小标、三颗药丸的描边和字、测验值、按钮），四处高饱和在一个
   面上喊，读起来发酸还分不出主次。 */
.focus { display: grid; grid-template-columns: minmax(0, 1fr) auto; align-items: center; gap: 8px 28px; border-radius: 10px; background: #1e3c34; padding: clamp(14px, 1.5vh, 20px) clamp(24px, 2.2vw, 40px); }
.focus__head { display: grid; gap: 4px; min-width: 0; }
.focus__lead { margin: 0; color: #a9bdb0; font-size: 12px; font-weight: 600; letter-spacing: .06em; }
/* 40 是这一页字号阶梯里的 display 那一档。原来是 clamp(38px, 2.7vw, 60px) —— 在 2.5K 屏上
   顶上 60px，那已经是官网首屏的号，不是工作台的。 */
.focus__title { margin: 0; color: #f2f7ec; font-size: 32px; font-weight: 600; letter-spacing: -.01em; line-height: 1.12; }
.focus__where { margin: 0; color: #a9bdb0; font-size: 14px; }
/* 「为什么是它」比 `where` 低一档：它是对上面那句话的补充说明，不是又一条标题。
   同一块面上靠字号拉开层次，不再多引进一种颜色。 */
.focus__reason { margin: 2px 0 0; max-width: 92ch; color: #a9bdb0; font-size: 12px; line-height: 1.5; }

/* 这一章讲什么 —— 卡片上唯一的"内容"，其余全是状态。 */
.focus__topics { display: flex; flex-wrap: wrap; align-items: baseline; gap: 8px; margin: 0; grid-column: 1 / -1; }
.focus__topics-lead { color: #a9bdb0; font-size: 12px; }
.focus__topics-list { color: #f2f7ec; font-size: 14px; font-weight: 500; }

/* 最后一行：测验（左）· 复习入口（右）。一条发丝线把它和上面分开 ——
   上面答"这一章是什么"，这一行答"你做到哪了"。 */
.focus__do { display: flex; flex-wrap: wrap; align-items: baseline; gap: 8px 24px; grid-column: 1 / -1; padding-top: 10px; border-top: 1px solid rgba(255, 255, 255, .16); }
.focus__quiz { display: flex; align-items: baseline; gap: 10px; margin: 0; }
.focus__quiz-label { color: #a9bdb0; font-size: 14px; }
.focus__quiz-value { color: #f2f7ec; font-size: 16px; font-weight: 600; font-variant-numeric: tabular-nums; }
.focus__cta { grid-column: 2; grid-row: 1; min-height: 42px; padding: 0 28px; color: #334139; font-size: 14px; font-weight: 600; text-decoration: none; white-space: nowrap; }
/* 复习入口推到右端，和左端的测验值分列两头。它是次要入口，用下划线表明可点、不抢柠檬绿。 */
.focus__aside { margin-left: auto; color: #a9bdb0; font-size: 14px; font-weight: 500; text-decoration: underline; text-underline-offset: 3px; }
.focus__aside:hover { color: #f2f7ec; }

/* ── 学习方向表 ── */
.paths { display: grid; gap: 10px; }
.paths__head { display: flex; align-items: baseline; gap: 14px; }
.paths__title { margin: 0; color: var(--ink); font-size: 20px; font-weight: 600; }
/* 总账一行：跨路径的节点数、已学完数、总体正确率。用间距分组，不用中圆点 ——
   中圆点把三个不相干的数连成一句，读起来像元信息栏。 */
.paths__note { display: flex; flex-wrap: wrap; align-items: baseline; gap: 6px 20px; margin: 0; color: var(--muted); font-size: 14px; }
.paths__note-lead { color: var(--ink); font-weight: 500; }
.paths :deep(.data-table__head) { font-size: 12px; }
.paths :deep(.data-table__head span) { padding: 8px 0; }

/* 列宽走 --data-table-columns（在模板里由 pathColumnTemplate 绑定），表头和表体读同一个值。 */
.row__no { color: var(--muted); font-size: 14px; font-variant-numeric: tabular-nums; }
.row__name { overflow: hidden; color: var(--ink); font-size: 16px; font-weight: 500; text-overflow: ellipsis; white-space: nowrap; }
/* 这里原来有一条 `.row.is-current .row__name { color: var(--accent-deep) }`，从来没生效过：
   `DataTable` 给当前行加的是 `data-table__row--current`，不是 `row is-current`。
   删掉而不是改对 —— 当前行已经有左侧 4px 色条 + 整行浅绿底纹（组件自带），
   再把路径名也染绿就是同一件事说三遍。（组件那两处样式在 `DataTable.vue` 里，够不着也不该够。） */

/* 路径的形状：**一条等宽、等长、等高的细条，节点只体现在缝的密度上**。

   上一版是"一个节点一个 16px 方格、每格平分列宽"（`flex: 1 1 0` + `gap: 4px`）。
   它有个看着就不对、但说不上哪不对的毛病：**格子的大小跟着节点数走**。13 个节点那行
   每格 48px，23 个节点那行每格 23px —— 四行并排，两行像粗条纹、两行像细梳子，
   同一张表里出现四种纹理。**读者要比的本来就是这四行**，而这里比不了。

   这不是审美问题，是有定论的：单位图（unit chart）一旦各行格子数不同，读者就没法比较
   长度、只能去数格子 —— Stephen Few《Unit Charts Are For Kids》专门批这一类，
   它举的例子正是"左边一格、右边五格"，并指出这种排布会"呈现出根本不存在的模式"；
   同一页里同一单位的图形要用同一个刻度也是数据可视化里成文的规则（CDC 那条是说
   成组展示必须同分母）。所以**不能**靠"给每格定死 16px"来解决 —— 那只是把
   "格子大小不齐"换成"条子长短不齐"，比较照样做不了。

   定下来的形状：四行都是同一条 10px 高、铺满整列的圆头条，**外轮廓完全一致**；
   节点的分界退化成缝的颜色（`gap: 1px` 露出的行底色），一个节点一缝。
   于是"我走了多少"由**填充的长度**回答（四行同一个刻度，能比），
   "这条路径有多少站、我在第几站"由**缝的密度和柠檬绿那一段的位置**回答。

   `height: 10px` 不是随手定的：它得比 16px 的方格矮（方格那种厚度会把注意力从
   "填充到哪"抢到"格子多大"上），又得容得下 1px 的缝和可开始那圈 1.5px 的环。 */
.row__track { display: flex; gap: 1px; height: 10px; overflow: hidden; border-radius: 99px; }
/* 底色 = 未解锁。**这一段必须能看见**：看不见就等于"路径只有 10 个节点"，
   而真相是后面还有 13 个没解锁。 */
.row__track i { flex: 1 1 0; min-width: 2px; background: #e2e9e0; }
.row__track i.is-done { background: var(--accent-deep); }
/* 「正在这里」全行只有一个（见 `trackCells`）。 */
.row__track i.is-current { background: var(--accent); }
/* 可开始：柠檬绿环 + 比灰底略亮的心。它和"未解锁"都还没做，但一个能学一个不能，
   在点开之前就该看出来 —— 这也是它不并进"正在这里"的原因。
   底色不写 `transparent`：当前行有 `#f7faf1` 的浅绿底纹，透明的心会跟着变绿，
   和"可开始"该有的"空心"读起来不是一回事。 */
.row__track i.is-available { background: #f4f8ef; box-shadow: inset 0 0 0 1.5px var(--accent); }

.row__pct { color: var(--ink); font-size: 16px; font-weight: 600; font-variant-numeric: tabular-nums; }
.row__now { overflow: hidden; color: var(--muted); font-size: 14px; text-overflow: ellipsis; white-space: nowrap; }
/* 「上次学习」写成相对日（今天 / 3 天前）。它答的是"这条路径我多久没碰了"，
   绝对日期还得让人自己减一遍。 */
.row__when { color: var(--muted); font-size: 14px; white-space: nowrap; }
.row__count { color: var(--ink); font-size: 14px; font-weight: 500; font-variant-numeric: tabular-nums; text-align: right; }
.paths__empty { margin: 0; color: var(--muted); font-size: 14px; line-height: 1.6; }

/* ── 页脚：进阶学习 ＋ 资料库 ＋ 本周，共用一条带 ── */
/* 三块都是"小内容"，各自占一条全宽行的话光行距就要 150px 上下。并排之后一条带装下。

   **三块等宽**（各 1fr）：现在每块内部都没有按钮了，宽度不再由"标题 + 按钮"决定，
   而由那块地方本身决定 —— 等宽读起来是"三个并列的去处/台账"，不等宽反而会让人以为
   宽的那块更重要。 */
/* `padding-top` 挪到每一块自己身上，条带上不再留 —— 悬停那层底色因此从分隔线开始往下铺，
   而不是从线下面 16px 处凭空起一条边。 */
.foot { display: grid; gap: 0 0; border-top: 1px solid var(--line); grid-template-columns: repeat(3, minmax(0, 1fr)); }
/* 三个 `__head` 统一到 36px 高，标题的基线才落在同一条线上 —— 本周那排七格自己只有
   28px，不拉齐的话「本周」会比另外两个标题低一截。 */
.entry { position: relative; display: grid; align-content: start; gap: 8px; min-width: 0; padding: 12px 28px 0 0; }
/* 第二块左侧也要留：那道竖线画在它的 `padding-left` 左边，不留就贴着上一块的字。 */
.entry + .entry { padding-left: 28px; border-left: 1px solid var(--line); }
.entry__head { display: flex; align-items: center; gap: 10px; min-height: 30px; }
.entry__title { margin: 0; color: var(--ink); font-size: 16px; font-weight: 600; letter-spacing: 0; }
.entry__tag { padding: 3px 11px; border: 1px solid #cfdcbb; border-radius: 99px; color: var(--accent-deep); font-size: 12px; font-weight: 500; line-height: 1.6; }
/* 标题里的链接**长得不像链接**（不换色、不加下划线）：它的可点区域是整块，
   把四个字染成绿的反而在说"只有这四个字能点"。可点的信号交给整块的 hover 底色。 */
.entry__link { color: inherit; text-decoration: none; }
/* 把链接铺满整块 —— 这是"整块可点"的标准做法：可访问名仍然只是标题那四个字
   （读屏读的是"进阶学习，链接"），而不是把下面整段说明都念成链接名。 */
.entry__link::after { content: ''; position: absolute; inset: 0; }
/* 悬停/聚焦的信号用 `#f7faf1` —— 路径表里"当前这条路径"用的就是同一个浅绿底，
   一处"你现在在这里"，一处"这一块能点"，都是"这一块和别处不同"。 */
.entry:hover, .entry:focus-within { background: #f7faf1; }
.entry:hover .entry__title, .entry:focus-within .entry__title { color: var(--accent-deep); }
/* 键盘走查要看得见焦点在哪。`focus-visible` 而不是 `focus`：鼠标点完不留一圈框。 */
.entry__link:focus-visible { outline: 2px solid var(--accent-deep); outline-offset: 3px; border-radius: 4px; }
/* 那句"什么时候会有任务"是这一块唯一一条**规则**（不是形容词），所以它加粗 ——
   其余两句是说明。整段都用灰字的话，"学完 10 个节点就有了"这条最关键的信息会沉下去。 */
.entry__body { margin: 0; color: var(--muted); font-size: 14px; line-height: 1.55; }
.entry__body b { color: var(--ink); font-weight: 500; }

/* 第三块：**本周**。竖线和内边距代替网格间距 —— 线画在 `padding-left` 的左边，
   没有这段空隙线会贴着左边的字。

   它和三块里另外两块一样宽、一样有标题和正文，所以也**整块可点**，去个人画像
   —— 机制和 `.entry__link` 逐字相同（标题里的链接铺满整块，块里没有第二颗按钮）。
   底色和内边距和 `.entry:hover` 是同一套，可点与不可点在鼠标扫过时看得出来。

   **这一块的内容整体右移了一段**（`padding-left` 从 40 加到 80）。它比另外两块窄得多
   （标题 + 一排七格，正文只有一行，最宽的一行 310 出头），贴在分隔线上就把它那一列的
   右半边整个空着；右移之后，内容左边到分隔线的距离和右边到块边缘的距离大致相等，
   这两块空白才不会一边倒。**仍然左对齐** —— 移的是这一整块内容的位置，不是行内对齐，
   所以标题和下面那行数还是同一条左边缘；**块本身一点没小**，改的只是内容从哪儿起。

   试过两个极端，都不对：贴左（40）右半边空一大片；`justify-items: end` 靠右则越过了
   头，读者会先去找"这一列的标题在哪"。

   两个量过的参照，改这一个数的时候对着挑：
     **40** —— 贴着自己的分隔线，和左边两块的 36/40 同一条规矩；这个值下内容的左边缘
              正好落在 **1206**，就是上面表格「当前节点」那一列的左边缘。
     **100** —— 这一块 513px 宽、内容最宽的一行（那三个数）约 312px，
              `(513 − 312) / 2 ≈ 100`，左右空白等宽，内容在这一列里居中。
   现在取中间偏左的 72：既不贴线，也不居中。

   `gap: 14px` 而不是另外两块的 10px：这一块是三行（标题 / 七格 / 三个数），行与行
   各自起止，间距小了会读成一段；左边两块是"标题 + 一段正文"，两行之间本来就该挨着。 */
.week { position: relative; display: grid; align-content: start; gap: 10px; border-left: 1px solid var(--line); padding: 12px 0 0 56px; min-width: 0; }
.week:hover, .week:focus-within { background: #f7faf1; }
.week:hover .week__title, .week:focus-within .week__title { color: var(--accent-deep); }

/* `min-height: 36px` + 居中**不是为了这排字好看，是为了和左边两块对齐**：
   `.entry__head` 是 36px 高的居中对齐盒，里面的标题因此往下偏了 5.5px；这一块现在没有
   那个盒子了（标题独占一行），把同样的 36px 直接给标题，三块的标题才落在同一条水平线上。 */
.week__title { display: flex; align-items: center; min-height: 30px; margin: 0; color: var(--ink); font-size: 16px; font-weight: 600; letter-spacing: 0; white-space: nowrap; }

/* 七格。**一格一天，包括没来的那些** —— 灰色的格子就是这一项要说的信息。
   活跃的整颗填实，没来的只剩一个浅环；今天那一格的星期字加重，不用再加一圈框。 */
.week__days { display: flex; gap: 4px; margin: 0; padding: 0; list-style: none; }
.week__day { display: grid; justify-items: center; gap: 4px; width: 26px; }
.week__dot { width: 12px; height: 12px; border: 1px solid #cfd9cb; border-radius: 50%; background: var(--paper); }
.week__day.is-active .week__dot { border-color: var(--accent-deep); background: var(--accent-deep); }
.week__label { color: var(--muted); font-size: 12px; line-height: 1; }
.week__day.is-today .week__label { color: var(--ink); font-weight: 600; }

/* 本周一次都没来时的那句"上次是 X 天前"。别的时候不出现 —— 来了几天，上面那排格子看得见。 */
.week__quiet { margin: 0; color: var(--muted); font-size: 14px; }

/* 一件事一行，不是一整句：每条独立成立、单位自带。 */
.week__facts { display: flex; flex-wrap: wrap; gap: 5px 16px; margin: 0; color: var(--muted); font-size: 14px; }

/* 铺满整块的那一层，和 `.entry__link` 是同一套写法。**可见文字只有「本周」** ——
   块里不出现任何像按钮的东西，三块因此长得一样；去处由后面那句 `sr-only`
   补进链接名里（见模板注释）。 */
.week__link { color: inherit; text-decoration: none; }
.week__link::after { content: ''; position: absolute; inset: 0; }
.week__link:focus-visible { outline: 2px solid var(--accent-deep); outline-offset: 3px; border-radius: 4px; }

/* **走势**。这一页此前所有图形讲的都是"现在到哪了"（路线、进度条、七格），
   没有一处回答"我最近是在往上走还是在往下掉"。

   `align-self: center`：它旁边的主卡高（标题 + 那条说明 + 底部一行），这一块矮一截，
   顶对齐会在右栏底下留一片空白，居中读成"和主卡对齐"而不是"掉了一截"。 */
.trend { display: grid; align-content: center; align-self: center; gap: 8px; min-width: 0; }
/* 标题和总量**挤在一行**：这一块的高度给不出第三行，而"最近 6 周学习天数"和"平均每周 4 天"
   本来就是一句话的两半（一个是窗口，一个是结论）。
   用 grid 而不是 flex：单行 flex 容器没有"行高"可以居中，`align-content` 会被忽略；
   grid 才能把这唯一一行在 30px 里居中，再用 `align-items: baseline` 让 14px 的总量
   贴住 18px 标题的基线，而不是两者的中心对齐（那样小字会浮在中间）。 */
.trend__head { display: grid; grid-template-columns: minmax(0, 1fr) auto; align-items: baseline; align-content: center; gap: 16px; min-height: 30px; }
.trend__title { margin: 0; color: var(--ink); font-size: 16px; font-weight: 600; letter-spacing: 0; }
/* 标题可以折行（窄屏那一栏只有 300px 出头），总量不行 —— 它是个短数字，折了就更短，
   看起来像被截断。 */
.trend__total { margin: 0; color: var(--muted); font-size: 14px; white-space: nowrap; }
/* 一组测验都没做过时这里只有一句话。和 `.week__quiet` 一样是**替换**而不是占位 ——
   空图配一个坐标轴会让人以为数据加载失败。 */
.trend__quiet { margin: 0; color: var(--muted); font-size: 14px; line-height: 1.7; }

.notice { color: var(--muted); font-size: 14px; line-height: 1.7; }
.notice__title { margin: 0 0 6px; color: var(--ink); font-size: 18px; font-weight: 600; }
.trend :deep(.bars__value.is-current), .trend :deep(.bars__label.is-current) { font-weight: 600; }
.notice .button { margin-top: 12px; }

/* 装得下就没有滚动条，装不下就老老实实滚 —— 不能 overflow: hidden 把内容裁掉。 */
:global(.page-container:has(.overview-page)) { box-sizing: border-box; height: 100%; overflow: hidden; }

/* 主卡 + 走势图什么时候并成一栏：**1420**，比页脚那条 1180 高得多。
   两边门槛不同是因为挤的东西不同：页脚是两块小内容，1180 还排得下；而这一行左边是
   40px 的大标题加按钮、右边是六根柱子，窄到 1400 上下「标题 + 按钮」就先放不到一行了。 */
@media (max-width: 1420px) {
  .top { grid-template-columns: minmax(0, 1fr); gap: 20px; }
  /* 叠成一栏之后右栏不再是"旁边那块"，居中会让它离主卡忽远忽近 —— 顶对齐就是紧跟其后。
     同时给它一道顶部发丝线，因为它上下都是白的，没有别的东西说明这是新的一块。 */
  .trend { align-self: stretch; align-content: start; padding-top: 16px; border-top: 1px solid var(--line); }
}

/* 页脚什么时候并成一栏：1180 以下并排的七格和那段说明会挤成一团。 */
@media (max-width: 1180px) {
  .foot { grid-template-columns: minmax(0, 1fr); gap: 18px; }
  /* 叠成一栏之后那些竖线都没了，给竖线让出来的内边距也要一并收掉 —— 留着它，
     后面几块的字会比第一块缩进去几十像素，几段对不齐。 */
  .entry { padding-right: 0; }
  .entry + .entry { padding-left: 0; border-left: 0; border-top: 1px solid var(--line); padding-top: 16px; }
  /* 叠成一栏之后那 80px 的右移就不成立了 —— 右边不再是页面右边缘，而是这一栏自己的
     右边界，留着它只会让这一块和上面两块的左边缘错开一截。回到 0。 */
  .week { border-left: 0; padding-left: 0; border-top: 1px solid var(--line); padding-top: 16px; }
  /* 主卡并成一栏：按钮回落到正常流，跟在标题块下面，不再占第二列。 */
  .focus { grid-template-columns: minmax(0, 1fr); }
  .focus__cta { grid-column: 1; grid-row: auto; justify-self: start; }
  .focus__title { font-size: 32px; }
}

/* 窄屏不硬塞：一屏一版只在桌面上成立，这里放开高度、允许纵向滚动。 */
@media (max-width: 1100px) {
  .overview-page { height: auto; align-content: start; gap: 18px; }
  .focus__title { font-size: 26px; }
  .focus__cta { min-height: 48px; }
  /* 行高和内边距都不在这里重设：桌面端已经收到 72px / 0，窄屏再写一遍是个空操作。
     窄屏真正要收紧的是列间距 —— 六列挤在一起时，先让空隙变窄，而不是让字变小。 */
  .overview-page { --data-table-gap: 12px; }
  :global(.page-container:has(.overview-page)) { height: auto; overflow: visible; }
}

@media (min-width: 1101px) and (max-height: 900px) {
  .overview-page { height: auto; overflow: visible; }
  :global(.page-container:has(.overview-page)) { height: auto; overflow-y: auto; }
}
</style>
