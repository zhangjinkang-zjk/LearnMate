/**
 * 把**一节的学习数据**算成一棵树的骨架。
 *
 * 这是纯函数：不碰 DOM、不碰 three.js、不碰接口。所以它可测，也能被两种渲染层共用
 * —— 现在用 SVG 画，之后换成 three.js 只换渲染层，这棵树怎么长一个字都不用改。
 *
 * 出台的消息（返回值）
 *   segments  枝干。每段带 `depth` 和 `t0/t1`（它在整棵树的生长时间轴上的那段窗口）。
 *   leaves    叶片。`size` 是**世界坐标里的半径**（和枝干的 r0/r1 同一套单位），
 *             渲染层直接乘缩放；`t` 是出现时刻。
 *   fruits    果实。只有 `status === 'completed'` 且有测验结果时才结。
 *             叶是"考了多少分"，果是"这一章过了" —— 两个通道，别合并。
 *   tips      枝头（叶子长在哪）。渲染层一般不用看，调试时有用。
 *   meta      这次算出来的中间量。渲染层用它决定文案，**不要**重新算一遍 —— 两处算必然漂。
 *
 * 生长动画怎么来：整棵树只认一个参数 `growth ∈ [0,1]`。渲染时把 `growth` 和每段的
 * `[t0,t1]` 一比，落在窗口里的才画出来。于是主干先冒出来、再一级枝、二级枝，最后铺叶子
 * —— 是**连续长出来**的，不是切五张图。
 *
 * 为什么坐标是三维的：现在 SVG 只取 x/y，z 用来做纵深（越靠后越小越暗）。等换成
 * three.js，同一份骨架直接就是几何。**不要**为了省事把它压成二维，那等于把换渲染层的路
 * 提前堵死。
 *
 * ── 和旧的"五档"比，变的是三件事 ──────────────────────────────────────────
 *
 * 旧实现（`StudyGarden.vue` 的 `nodeStage`）：五档整数，`[0.24, 0.31, 0.46, 0.64, 0.82]`
 * 五个尺寸乘数。三处硬伤：
 *
 *   1. 档和档之间是**跳**的。判据是「有没有完成记录」（`completed_tasks > 0`），
 *      所以读了 1/20 份和 19/20 份的树**一模一样大**。学生啃了一天，树没动。
 *   2. `quiz_correct` 后端算了、前端**一处都没用**。全对和全错长得一样，
 *      直到最后一档「测验通过」才一次性翻脸。
 *   3. 没有"哪块没学会"。薄弱点在这棵树上不存在。
 *
 * 新实现把这三条都换掉：完成度是实数 → 决定**能长几层**（带概率的连续量）；
 * 答对率 → 决定**叶子多少、枝多壮**；薄弱知识点 → **枯枝**（只长干，不挂叶）。
 */

// 递归层数上限。**别往上加**：一层一层是乘出来的，4 层已经能长到上百段，
// 再深一档在集显上就掉帧了（tree-js 的建议也是 levels < 5）。
const MAX_DEPTH = 4
const TRUNK_SEGMENTS = 6
// 单棵树的叶子总数上限。**这是全局预算，不是每枝头的量** —— 按枝头乘会爆
// （枝头有三四十个，乘起来三千多片，SVG 直接跪）。答对率在这个总数里分。
const LEAF_BUDGET = 640
// 有成绩的树最少挂多少比例的叶（见 `vigor`）。留个底是为了让"考了但全错"和
// "根本没考"画出两棵不同的树 —— 后者才该是一片叶都没有的那棵。
const LEAF_FLOOR = 0.22
// 单棵树的段数上限。到顶就不再分枝 —— 宁可少长几根，也不能让一棵病态数据
// （比如知识点几十个）把整片森林拖垮。
const SEGMENT_BUDGET = 320
// 一级分枝数上限。再多就不是"这棵树的枝"，是一丛草了。
const MAX_PRIMARY_BRANCHES = 5
// 骨架长势的下限（见 `growTree` 里 `grown` 那段）。0.28 ≈ 一层完整的分枝：
// 一章完全没动过也是棵有枝的小苗，而不是一根插在地上的签子。
const MIN_GROWTH = 0.28
// 一棵树最多结几颗果。果是"这一章拿下了"的标记，不是分数 —— 数量少才有分量。
const FRUIT_MAX = 6
// 每片叶绕它的挂点最多散开多远（世界坐标）。
// **不能是 0** —— 挂在同一根枝上的叶子如果全叠在一个点上，一整片树冠就退化成
// 一串"浆果"，看上去只有十几颗而不是几百片。叶子的**位置**必须散开，方向只决定
// 它朝哪边长，那个不解决叠在一起的问题。（这个坑踩过：420 片叶看着像 99 颗莓。）
const LEAF_JITTER = 0.085
// 生长时间轴的分界：前 62% 抽枝，后 38% 铺叶。见文件末尾归一化那一段的注释。
const GRAFT_END = 0.62

const clamp = (value, low, high) => Math.min(high, Math.max(low, value))
const num = (value) => (Number.isFinite(Number(value)) ? Number(value) : 0)
/** FNV-1a。用来给"每条枝"派一个只由**它自己在树里的位置**决定的种子。
 *
 *  **不能用一条共享的随机流。** 共享流是按生成顺序消耗的：完成度一变，"哪几根枝
 *  是短枝"就变，消耗的随机数个数跟着变，下游所有随机量整体错位 —— 于是完成度从
 *  1/8 到 2/8，树干上每根枝的角度都换了位置。那不是"长大"，是"重新洗牌"，
 *  "只长新增那段"的动画会变成整棵树乱抖。
 *  按位置派种子之后，一根枝的角度和分枝数**永远不变**，随完成度变的只有"短枝还是
 *  长枝"这个由阈值决定的东西 —— 而阈值单调，所以树是**稳定地长大**。 */
function hashSeed(text) {
  let hash = 2166136261
  for (let i = 0; i < text.length; i++) {
    hash ^= text.charCodeAt(i)
    hash = Math.imul(hash, 16777619)
  }
  return hash >>> 0
}

const add = (a, b) => [a[0] + b[0], a[1] + b[1], a[2] + b[2]]
const scaled = (v, k) => [v[0] * k, v[1] * k, v[2] * k]
const spread = (a, b) => Math.hypot(b[0] - a[0], b[1] - a[1], b[2] - a[2])

/** 确定性伪随机（mulberry32）。**必须确定性**：同一份数据刷新两次得是同一棵树，
 *  否则学生每刷一次页面树就变个样，"这是我的那棵树"这句话就立不住了。 */
function makeRandom(seed) {
  let state = (seed >>> 0) || 1
  return () => {
    state = (state + 0x6d2b79f5) >>> 0
    let t = state
    t = Math.imul(t ^ (t >>> 15), t | 1)
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61)
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}

const cross = (a, b) => [
  a[1] * b[2] - a[2] * b[1],
  a[2] * b[0] - a[0] * b[2],
  a[0] * b[1] - a[1] * b[0],
]
const normalize = (v) => {
  const length = Math.hypot(v[0], v[1], v[2]) || 1
  return [v[0] / length, v[1] / length, v[2] / length]
}

/**
 * 枝条往外张的**尺度**。两套，差别只有一件事：**这棵树挂不挂叶。**
 *
 * 有叶的时候，叶团会把轮廓补成一个圆 —— 冠幅 ≈ 树高是对的，撑得开反而好看。
 * 没测过试的章节一片叶都不挂（"叶 = 成绩"那条铁律），露出来的就是骨架本身，
 * 于是同一套张开角度在两棵树上的读法完全不同：有叶的是"树冠"，没叶的是"树枝"。
 * 所以剪影按"有没有叶"分 —— 冬天落了叶的树本来就和夏天不是同一个轮廓。
 *
 * ── 光秃那套的 `primary` 为什么是 0.92，而不是"收窄" ──────────────────────
 * 先试过反方向：把张开角度**收紧**（0.54、`maxTilt` 0.90），想让它别摊成扫帚。
 * 结果是"电线杆" —— 账面上的 冠/高 是降了（1.03 → 0.91），屏幕上却是几根并排
 * 竖着的签子，底下坐一截粗圆锥。原因在投影：
 *
 * `treeRender.project` 是 `[x + z*0.32, -(y + z*0.12)]` —— **x 不缩，z 按 0.32 摊到 x**。
 * 朝向 x 的枝原样保留张开角，朝向 ±z 的枝（正对 / 背对观察者）横向只剩三成，
 * 画出来几乎是竖直的。也就是说**投影之后能看见的"张开"本来就只有三维账面上的一半出头**，
 * 再按账面把角度收紧，等于把剩下那一半也收掉。
 *
 * 所以 `primary` 要按**投影之后**想要的角度反推着给：屏幕上想要 25°，三维就得给 55° 上下。
 * `attachFalloff` 负责把这份张开按挂点分配（越靠下的枝越平），`maxTilt` 要跟着放宽，
 * 否则钳位会把张开的枝又掰回竖直。张开之后每根枝的竖直分量变小、树会变矮，
 * `childLength` 再把长度补一点回来 —— 两棵树的**相对大小**见 `LEAN_BARE`。
 *
 * `maxTilt` 单独调几乎没用（量过：1.08 → 0.82 只把 冠/高 从 1.03 压到 0.94，
 * 因为绝大多数枝根本够不到那个上限），真正管事的是每一级的 `pitch`。
 */
const LEAN_LEAFY = {
  maxTilt: 1.08,
  primary: 0.58,
  primarySpread: 0.16,
  // 越靠下的枝越平。系数越大，下缘张得越开、上缘越收拢 —— 塔形的来源。
  attachFalloff: 0.32,
  child: 0.20,
  childSpread: 0.28,
  // 下一级枝占上一级的比例。张开得越大，竖直方向能长到的高度越少，
  // 所以这两项和 `pitch` 是一对**配平**的量：见 `LEAN_BARE` 那段。
  childLength: 0.66,
  childLengthSpread: 0.18,
  // 主干：**矮而粗**。底下是一大坨实心树冠，底座细了就成棒棒糖。
  trunk: { radius: { base: 0.100, growth: 0.050 }, length: { base: 0.30, growth: 0.28 } },
}
const LEAN_BARE = {
  maxTilt: 1.05,
  primary: 0.92,
  primarySpread: 0.20,
  attachFalloff: 0.55,
  child: 0.34,
  childSpread: 0.30,
  // 一级枝收得比有叶那套**慢**。张开角度大 -> 每根枝的竖直分量小 -> 树自然矮，
  // 而这正是想要的（见下面"整体小一圈"）。收得慢一点，竖直方向的损失能回来一些，
  // 光秃的树才不会缩成一根针。
  childLength: 0.86,
  childLengthSpread: 0.16,
  // **整体比有叶那套小一圈**（主干长度约 0.73 倍，整棵树的枝长都是从它派生出来的，
  // 所以这一个数就是整棵树的缩放）。
  //
  // 这是产品规则：**叶 = 你已经验证过了**，所以"挂叶的树苗"必须比"光秃的树枝"更大更实。
  // 两个状态画成一样大（甚至光秃的更大）时，一屏看过去是枯枝在抢戏，学生读到的
  // "我做得挺多，但全是死的"。改之前光秃的 6/6 是 193x160px，挂叶的只有 113x137px ——
  // 后者是**奖励**，凭什么比前者小。
  //
  // 主干又矮又细也是同一个方向：没有树冠挡着，主干整根露在外面，一截实心棕色圆柱
  // 占掉树高三分之一、宽出一条胳膊，读出来是"树桩上插了几根枝"，不是树。
  trunk: { radius: { base: 0.034, growth: 0.022 }, length: { base: 0.175, growth: 0.158 } },
}

/**
 * 从 `dir` 张开一根枝：离它 `pitch` 弧度，方位角 `azimuth`。
 *
 * **不能只做"绕 Y 轴转"** —— 主干方向就是 `[0,1,0]`，绕 Y 轴转它等于没转，
 * 于是所有一级枝还是笔直朝上，再往下递归同样如此，整棵树退化成一根竖线。
 * （这个坑踩过：数值检查全过，只有字符画里才看出来所有枝挤在同一列。）
 * 所以这里先按 `dir` 现搭一组正交基，再往**垂直于它**的方向张开 —— 对任意
 * 父方向都成立，竖直的也不例外。
 */
function tilted(dir, azimuth, pitch, maxTilt = LEAN_LEAFY.maxTilt) {
  // 参考轴不能和 dir 平行，否则叉乘退化成零向量。
  const ref = Math.abs(dir[1]) < 0.9 ? [0, 1, 0] : [1, 0, 0]
  const u = normalize(cross(ref, dir))
  const v = cross(dir, u)
  const cosP = Math.cos(pitch)
  const sinP = Math.sin(pitch)
  const cosA = Math.cos(azimuth)
  const sinA = Math.sin(azimuth)

  const out = normalize([
    dir[0] * cosP + (u[0] * cosA + v[0] * sinA) * sinP,
    dir[1] * cosP + (u[1] * cosA + v[1] * sinA) * sinP,
    dir[2] * cosP + (u[2] * cosA + v[2] * sinA) * sinP,
  ])

  // 夹住与竖直方向的夹角，方位角保留 —— 枝照旧朝那个方向伸，只是不许趴下去。
  // 下限也是一样的道理：夹太松会有枝直接朝下（树冠变垂柳），还可能钻到地面以下。
  const tilt = Math.acos(clamp(out[1], -1, 1))
  if (tilt <= maxTilt) return out
  const horizontal = Math.hypot(out[0], out[2]) || 1
  const ring = Math.sin(maxTilt)
  return [out[0] / horizontal * ring, Math.cos(maxTilt), out[2] / horizontal * ring]
}

/**
 * 算一棵树。
 *
 * @param {object} node  路径节点（后端 `get_current_path` 给的那份）
 * @param {object} [options]
 * @param {Array}  [options.weakPoints] 薄弱点，元素带 `tag`。命中的知识点长成**枯枝**
 * @returns {{segments: Array, leaves: Array, tips: Array, meta: object}}
 */
export function growTree(node, options = {}) {
  const weakPoints = Array.isArray(options.weakPoints) ? options.weakPoints : []

  const progress = node?.garden_progress || {}
  const totalTasks = num(progress.total_tasks)
  const doneTasks = num(progress.completed_tasks)
  const answered = num(progress.quiz_answered)
  const correct = num(progress.quiz_correct)

  // 完成度：有任务清单就按清单算；没有（老数据 / 还没排资源）退回"看过没有"。
  const completion = totalTasks > 0
    ? clamp(doneTasks / totalTasks, 0, 1)
    : (node?.resources_viewed ? 0.25 : (node?.status === 'completed' ? 1 : 0))

  // **答对率单独拿出来**：没考过时它是 null，不是 0。「还没考」和「考了全错」是两件事，
  // 不能混成同一个 0 —— 前者是"还没验证"，后者是"验证了没通过"。
  // 两者在 `meta.hasQuizResult` 上可区分，文案该说"还没测验"还是"测验都没对"就看它。
  const accuracy = answered > 0 ? clamp(correct / answered, 0, 1) : null
  // **没有"完成但生疏"这一档，是查过之后砍掉的，别再补回来。**
  // 后端 `backend/src/service/path/service.py:1741-1746`：已完成的节点重测没过，
  // 只写一行日志，**不回退 `node_status`**，`quiz_passed` 也保持 True。所以服务端
  // 根本发不出"生疏"这个信号。拿 `quiz_correct/quiz_answered` 偏低去近似也不行 ——
  // 一次过、4/5 及格的节点和"重做砸了"的节点，这个比值是一样的。
  // 现有两个通道已经把"这块不牢"说清楚了：叶稀 = 答对率低，枯枝 = 命中薄弱点。
  // 叶的浓密度。**只影响挂多少叶，不影响树长多大** —— 尺寸归完成度管，
  // 因为完成度只增不减、答对率不是（见下面枝长那段）。
  //
  // **有成绩时给一个不能到 0 的下限。** 完全按 `accuracy` 线性给的话，5 题全错 ->
  // 0 片叶 -> 这棵树和"根本没测过"**长得分毫不差**。可"一片叶都没有"这个形态是
  // 专门留给"还没验证过"的（配着"做题"那颗水滴），两个状态画成同一张图，那个信号就废了，
  // 而且学生考完试回来看见树一动不动，读到的信息是"我刚才那趟白去了"。
  // 0.22 大约是一百多片叶 —— 稀，但不是没有；"叶稀 = 答得差"这条通道照样成立。
  const vigor = accuracy === null ? completion * 0.6 : LEAF_FLOOR + (1 - LEAF_FLOOR) * accuracy

  const tags = Array.isArray(node?.knowledge_tags) ? node.knowledge_tags.filter(Boolean) : []
  const weakTags = new Set(weakPoints.map((point) => String(point?.tag ?? '')).filter(Boolean))
  // **薄弱的知识点排在前面。** 一级枝是从下往上依次认领知识点的（attach 随 i 递增），
  // 排前面 = 挂在更低的枝上。不排的话，一个薄弱点可能正好落在树顶那根上 ——
  // 整棵树的**树冠**枯掉、底下留一根绿枝，一个知识点的亏看着像整棵树死了。
  // 排过之后枯枝永远是从下往上数的那几根，树冠留着。
  const branchTags = [...tags].sort(
    (a, b) => Number(weakTags.has(String(b))) - Number(weakTags.has(String(a))),
  )

  const seedBase = `${num(node?.id)}|${tags.length}`
  // 每棵树整把枝的**朝向**：只由 id 决定，所以同一棵树每次画都一样，
  // 但不同的树各朝各的，不会一屏全是同一个斜向（见下面 azimuth 那段）。
  const fanRotation = makeRandom(hashSeed(`${seedBase}|fan`))() * Math.PI * 2
  // 叶子和果实各自一条独立的流：它们和树的结构无关，只要稳定就行。
  const leafRandom = makeRandom(hashSeed(`${seedBase}|leaf`))
  const fruitRandom = makeRandom(hashSeed(`${seedBase}|fruit`))
  const segments = []
  const tips = []

  // 完成度 → **骨架的长势**：`grown = 0` 是一根光杆，`grown = 1` 是长满。
  //
  // **这里不是 `completion` 本身，抬了一个下限。** 纯线性映射的话，一章没动过的树
  // `depthBudget = 0` —— 一根枝都不分，就是一截三十厘米的签子插在地上。一屏十几棵里
  // 混着几根签子，整片林子看着像秃了一半，而且那根签子读不出"树"这个形状。
  // 抬到 0.28 之后最少也有一整层分枝：是棵小苗，不是断棍。
  //
  // 每一项任务仍然看得见：`0.72 / 任务数` 一台阶，八项任务的话每项 9% 的长势，
  // 高度和分枝层数都跟着动 —— "每完成一个任务树必须有变化"这条没破。
  const grown = MIN_GROWTH + (1 - MIN_GROWTH) * completion

  // 剪影按"这棵树挂不挂叶"分两套（理由见 `LEAN_LEAFY` 上面那段）。
  // 判据用的是 `accuracy === null`：**没有测验结果就不挂叶**，和下面 `leaves` 那段同一个开关。
  const lean = accuracy === null ? LEAN_BARE : LEAN_LEAFY

  // **能长几层，是实数不是整数。** `grown=0.5` 就是 2.0 层：前两层一定长满，
  // 第三层每根枝掷一次硬币。所以 0.4 和 0.6 的树**长得不一样**，而旧实现会给出同一棵。
  const depthBudget = grown * MAX_DEPTH
  // 这棵树**实际能达到的最深层**。深度 d 的枝能长出子枝的条件是 d < depthBudget，
  // 所以最深层 = floor(depthBudget) + 1。**叶只长在"最外两级"上**，判据要用它，
  // 不能用手边的 `terminal` —— 那个随完成度变，高完成度时中层枝也算"非末梢"，
  // 结果主干中段和一级枝上也长出叶团（出过这个 bug：树干底下一坨深绿）。
  const deepest = Math.min(MAX_DEPTH, Math.max(1, Math.floor(depthBudget - 1e-9) + 1))

  /** 长一根枝：沿 `dir` 切 `count` 段，半径从 `radius` 线性收到 `radius * taper`，
   *  生长窗口铺在 [t0,t1] 上。长到梢就把枝头记进 `tips`（叶子后面统一分配到这些点上）。 */
  function growBranch({ origin, dir, length, radius, depth, t0, t1, withered, taper, path }) {
    // 这条枝**自己的**随机流，种子只由它在树里的位置决定（见 hashSeed 的说明）。
    // 所以它消耗多少随机数都不影响别的枝 —— 完成度变了，树不会重新洗牌。
    const random = makeRandom(hashSeed(`${seedBase}|${path}`))
    const count = depth === 0 ? TRUNK_SEGMENTS : 2 + Math.round(random())
    const tipRadius = radius * taper
    const span = (t1 - t0) / count
    // 枝上任意位置（f=0 根部，f=1 梢）：一级枝要沿主干**分散**着挂，就得能取中间点。
    const pointAt = (f) => add(origin, scaled(dir, length * f))
    let cursor = origin

    for (let i = 0; i < count; i++) {
      if (segments.length >= SEGMENT_BUDGET) return
      const next = add(cursor, scaled(dir, length / count))
      segments.push({
        a: cursor,
        b: next,
        depth,
        r0: radius + (tipRadius - radius) * (i / count),
        r1: radius + (tipRadius - radius) * ((i + 1) / count),
        t0: t0 + i * span,
        t1: t0 + (i + 1) * span,
        withered,
        // 渲染层要靠它把同一根枝的段串成一条链，才画得出**带锥度的**枝
        // （一段一段各画各的，就只能给整根枝一个平均线宽，主干会变成等粗的柱子）。
        path,
      })
      cursor = next
    }

    // 这一层还能不能再往下分：`depthBudget - depth` 落在 (0,1) 时，就是"还差几分之一
    // 层"的边角 —— 长出来的那几根才是这一档的差别所在。
    const room = depthBudget - depth
    const terminal = depth >= MAX_DEPTH || room <= 0
    // **叶子铺在"最外两级"枝上**，不是只挂最末梢那三个点。
    // 只挂梢头的话树冠是一层薄壳，里面的枝全露着 —— 看着是副骨架，不是一棵枝繁叶茂的树。
    // 枯枝的挂点**照样记进来**（它和活枝走的是同一条分叉路径，见下面），只是等会儿
    // 分叶时跳过：不记的话它那份会被别的枝分掉，总数一点不少，"这块没学会"就看不出亏。
    // `weight` 用位置 f 本身：梢头分到的叶子比枝根多，树冠外沿才厚。
    if (depth >= deepest - 1) {
      for (const f of (terminal ? [0.3, 0.55, 0.8, 1] : [0.55, 1])) {
        // `path` 一路带下来：渲染层靠它把叶子**按枝聚成团块**（低多边形树冠要的是
        // 一坨一坨的体，不是一片片散叶）。没有它就只能按坐标猜，聚出来的团会跨枝。
        tips.push({ at: pointAt(f), dir, depth, t1: t0 + (t1 - t0) * f, withered, weight: f, path })
      }
    }
    if (terminal) return

    // 一级分枝数 = 这一节的知识点数；再往下就按随机 2~3 根。
    const children = depth === 0
      ? clamp(tags.length || 3, 2, MAX_PRIMARY_BRANCHES)
      : (random() < 0.65 ? 2 : 3)

    for (let i = 0; i < children; i++) {
      // **一级枝沿主干分散着挂**，不是全从顶端一个点冒出来 —— 全从顶端出来就是一把
      // 扫帚。（这个坑踩过：字符画里一眼就看出来。）
      // 挂点**取整到段边界**：真实树的枝是从"节"上长出来的，而且这样每根枝的起点
      // 一定落在某一段的终点上 —— 整棵树是连通的，这个性质可以拿来做断言。
      const attach = depth === 0
        ? Math.round((0.4 + 0.6 * (i / Math.max(1, children - 1))) * count) / count
        : 1
      // 方位角用**黄金角**铺开，而不是均分：均分会把枝摊成一个平面扇，
      // 黄金角在任意根数下都散得开、不重样。
      //
      // 但整把扇子还要**按棵随机转一个角度**（`fanRotation`）。不转的话每棵树的五根
      // 一级枝都朝着同样的五个方位，再经过 3/4 投影，所有树的斜向就一模一样 ——
      // 一屏十二棵看过去像同一棵树复制粘贴，而且集体朝同一边斜。
      const azimuth = fanRotation + i * 2.399963 + random() * 0.35
      // 越靠下的枝越平，越往上越收拢 —— 真实树就是这样的。张开多少见 `lean`。
      const pitch = depth === 0
        ? (lean.primary - lean.attachFalloff * attach) + random() * lean.primarySpread
        : lean.child + random() * lean.childSpread
      const childDir = tilted(dir, azimuth, pitch, lean.maxTilt)

      // 不够一整层时，这一根要么按正常长度往下长、要么只长一截短的作结。
      // **用短枝比"干脆不长"更像树** —— 不长的话叶子没枝托着，会悬在空中；
      // 而且概率正好 = `room`，完成度越高能长满的枝越多，是连续的。
      const stub = room < 1 && random() > room

      // 每个一级枝认领一个知识点；这个知识点在薄弱点里 → 这根枝是枯的。
      // 用 `branchTags`（薄弱点排在前面）而不是 `tags`，理由见上面那段。
      const tag = depth === 0 ? branchTags[i % Math.max(branchTags.length, 1)] : null
      growBranch({
        origin: pointAt(attach),
        dir: childDir,
        // **长度只看完成度，不看答对率。**
        // 答对率乘进长度的话，学生做完测验答得差，树会**缩回去** —— 刚干完活反而变小，
        // 那是最糟的反馈，而且"从上次长到现在"的动画会直接失去起点（当前树比上次还矮，
        // 二分反解取到 1，等于没动画）。完成度只增不减，所以尺寸也只会增不会减。
        // 答对率交给叶子（见下面 leaves 那段），只影响"挂多少"，不影响"长多大"。
        length: stub
          ? length * 0.38
          : length * (lean.childLength + random() * lean.childLengthSpread),
        // 每级收到上一级梢头的 0.70。真实树的细枝约占树高 0.3%，画出来在缩略图里
        // 是亚像素的、等于不存在；风格化的树得把细枝**故意画粗**才看得见，
        // 尤其是"读完没测"那棵只有骨架的树 —— 枝看不见，那棵树就什么都不剩了。
        radius: tipRadius * 0.70,
        depth: depth + 1,
        // 子枝的窗口从"父枝长到它那个位置"的时刻开始：先有父枝，才有子枝。
        t0: t0 + (t1 - t0) * attach,
        t1: clamp(t1 + 0.16, 0, 1),
        // **枯是整条子树的事，不是那一根的事。** 枯枝照样往下分叉、照样长到该有的长度，
        // 只是整条子树都不挂叶、并且染成木灰色。早退（`if (withered) return`）的话枯枝
        // 只是根残桩，最高的那根一级枝一枯，树高直接从 1.72 掉到 1.16、树冠整个没了 ——
        // 一个 5/5 全对的已完成章节看着像棵死树，而且违反"答得差不该让树缩回去"。
        withered: withered || (depth === 0 && tag ? weakTags.has(String(tag)) : false),
        taper: 0.75,
        path: `${path}.${i}`,
      })
    }
  }

  growBranch({
    origin: [0, 0, 0],
    dir: [0, 1, 0],
    // 主干随长势长高 —— 光秃秃的小苗和半大的树先在这儿分开。
    // 同样**不乘 vigor**（理由见下面子枝那段）：答得差不该让树缩回去。
    // 高度的大头交给分枝 —— 冠本来就该是树的七成。主干的增量也一并收小
    // （0.28 而不是 0.40），多出来的那部分长势让**分枝去长**，形变更明显。
    // 长短粗细两套，见 `lean.trunk`（光秃那套矮一截、细一圈）。
    length: lean.trunk.length.base + grown * lean.trunk.length.growth,
    // 收得比子枝狠（taper 0.45 vs 0.7）：底下粗、往上迅速收细，才有小树的底座感，
    // 不然就是根等粗的柱子。粗度不乘 vigor —— 理由同长度。
    radius: lean.trunk.radius.base + grown * lean.trunk.radius.growth,
    depth: 0,
    t0: 0,
    t1: 0.3,
    withered: false,
    taper: 0.45,
    path: 'r',
  })

  // 叶子：**总数是先定死的**（`LEAF_BUDGET * vigor`），再平摊到每个枝头。
  // 反过来做（每枝头 N 片）数量就跟着枝头数乘出去，控不住，答对率的差别也会被淹没。
  const leaves = []
  if (accuracy !== null && tips.length) {
    const total = Math.round(LEAF_BUDGET * vigor)
    const perTip = total / tips.length
    let assigned = 0
    tips.forEach((tip, site) => {
      const upto = Math.round((site + 1) * perTip)
      // 枯枝的那份**直接丢掉，不摊给别人** —— 否则"这块没学会"只是把叶子挪了个位置，
      // 整棵树一点亏都不吃。`t` 先只存枝头的先后顺序，归一化时再摊开。
      if (!tip.withered) {
        for (let i = assigned; i < upto; i++) {
          // 位置绕挂点散开（见 LEAF_JITTER）—— 这是"树冠"和"浆果串"的分界。
          const scatter = (0.25 + leafRandom() * 0.75) * LEAF_JITTER
          leaves.push({
            at: add(tip.at, scaled(tilted(tip.dir, leafRandom() * Math.PI * 2, leafRandom() * 1.45), scatter)),
            dir: tilted(tip.dir, leafRandom() * Math.PI * 2, 0.5 + leafRandom() * 0.5),
            // **世界坐标里的半径**，和 `segments` 的 r0/r1 同一套单位 —— 渲染层
            // 直接乘缩放就行。别退回"0.7~1.3 的倍率"：那样渲染层得自己猜一个系数，
            // 猜错就是满屏巨型色块（这个坑踩过）。
            size: (0.030 + leafRandom() * 0.020) * (0.85 + vigor * 0.3),
            t: tip.t1,
            // 挂在哪根枝上（tips 的下标）—— 渲染层按这个聚团
            site,
          })
        }
      }
      assigned = upto
    })
  }

  // **时间轴分两段：枝占 [0, GRAFT_END]，叶占 [GRAFT_END, 1]。**
  // 不分段的话枝叶的 t 挨得太近，归一化后一起被压到 0.85 以后，两百多片叶子在最后
  // 几帧"炸"出来 —— 那是弹出来，不是长出来。分开之后先抽枝、后铺叶。
  const maxBranchT = Math.max(0.0001, ...segments.map((segment) => segment.t1))
  const maxTipT = Math.max(0.0001, ...tips.map((tip) => tip.t1))
  for (const segment of segments) {
    segment.t0 = (segment.t0 / maxBranchT) * GRAFT_END
    segment.t1 = (segment.t1 / maxBranchT) * GRAFT_END
  }
  for (const leaf of leaves) {
    // 深的枝头后铺，但顺序只占两成权重 —— 一棵树的枝头经常是**同一深度**的
    // （完成度整好卡在某档），那时顺序项是个常数，权重给多了叶子就退回"一起冒出来"。
    // 八成交给抖动，叶子才会在整段窗口里陆续铺开。
    leaf.t = GRAFT_END + (1 - GRAFT_END) * clamp(0.2 * (leaf.t / maxTipT) + 0.8 * leafRandom(), 0, 1)
  }

  // 果实：**"这一章拿下了"的标记**，和叶子是两个通道，不能合并。
  //   叶多而没果 = 考得不错但还没过（或者根本没测完）
  //   果 = status 已经是 completed
  // 所以它只看 status，不看 completion。数量随答对率 —— 满分才结满。
  // 没有测验结果（accuracy === null）就不结果：连分都没有，凭什么说拿下了。
  const fruits = []
  if (node?.status === 'completed' && accuracy !== null && tips.length) {
    const sites = tips.filter((tip) => !tip.withered)
    const want = clamp(Math.round(FRUIT_MAX * accuracy), 0, sites.length)
    for (let i = 0; i < want; i++) {
      // 沿枝头均匀挑几个，不要全挤在一处
      fruits.push({
        at: sites[Math.floor(((i + 0.5) / want) * sites.length)].at,
        size: 0.036 + fruitRandom() * 0.014,
        // 果在叶之后才结，所以直接给 [0.9, 1]，不参与上面那套归一化
        t: 0.9 + fruitRandom() * 0.1,
      })
    }
  }

  const totalLength = segments.reduce((sum, segment) => sum + spread(segment.a, segment.b), 0)
  return {
    segments,
    leaves,
    fruits,
    tips,
    meta: {
      completion,
      accuracy,
      hasQuizResult: accuracy !== null,
      vigor,
      depthBudget,
      maxDepth: segments.reduce((deepest, segment) => Math.max(deepest, segment.depth), 0),
      tagCount: tags.length,
      witheredBranches: segments.filter((segment) => segment.withered).length,
      segmentCount: segments.length,
      leafCount: leaves.length,
      fruitCount: fruits.length,
      isCompleted: node?.status === 'completed',
      totalLength,
      // 渲染层用这两个把树等比缩放进画布 —— 树高和冠幅都随完成度变，
      // 不归一化，完成度高的树就会顶出框。
      height: segments.reduce((tallest, segment) => Math.max(tallest, segment.b[1]), 0),
      radius: segments.reduce((widest, segment) => Math.max(widest, Math.hypot(segment.b[0], segment.b[2])), 0),
    },
  }
}

/** 渲染层用：`growth` 从 0 走到 1 时，这一段该不该出现、出现了多少（0~1）。 */
export function segmentVisibility(segment, growth) {
  const span = segment.t1 - segment.t0
  if (span <= 0) return growth >= segment.t1 ? 1 : 0
  return clamp((growth - segment.t0) / span, 0, 1)
}
