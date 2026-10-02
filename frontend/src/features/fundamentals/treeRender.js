/**
 * 把 `treeGrowth.js` 吐出的三维骨架**画成 SVG** —— 纯函数，不碰 DOM、不碰 three.js。
 *
 * 分成这一层是为了同一个渲染逻辑能给两个地方用：Vue 组件（实时逐帧）和演示页
 * （预先把帧烤好）。也方便单独测。
 *
 * ## 两条硬约束
 *
 * 1. **viewBox 必须所有树共用，不能用每棵树自己的包围盒。**
 *    各自适配的话，刚种下的小苗会被放大到和长成的树一样大 —— 树不是在长，只是被
 *    重新缩放了，"成长"整个消失。所以这里是**一个固定的世界坐标框**，大小树都画进去。
 *    （这个坑踩过两次：一次在对比页，一次在设计时。）
 *
 * 2. **叶片只按桶改透明度，不逐帧重算几何。**
 *    一片叶子的位置永远不变，变的只是"出现了没有"。全树上限 420 片叶，逐帧拼字符串
 *    会制造大量垃圾；按出现时刻分 5 桶、每桶一条 path，逐帧只改 opacity 就够了。
 *    枝干不一样：`growth` 在段内部推进时那一段要**画一半**，所以枝干必须逐帧重算 `d`。
 */
import { segmentVisibility } from './treeGrowth.js'

// 斜投影：把 z 摊到 x 和 y 上，做出一个 3/4 视角的纵深。
// 压成纯二维的话，树就是一排平面扇，而且换渲染层的路也堵死了。
const PROJECT_XZ = 0.32
const PROJECT_YZ = 0.12

// 所有树共用的世界坐标框，底部对齐 y=0（树根）。实测（40 个 id × 9 档完成度扫一遍，
// 含叶团外沿）最极端的一棵占 2.25 宽 × 2.11 高，框留约 4% 余量。
//
// **框要紧**：框比树大多少，树在容器里就小多少。之前那个框是 2.90×3.35（改主干比例
// 之前量的），树只填了 76% 的宽、57% 的高，花园里一排小树苗就是那来的。
export const VIEW_BOX = '-1.18 -2.21 2.43 2.21'

/** 框的宽高比。宿主容器要按它定 aspect-ratio，树才填得满。 */
export const VIEW_ASPECT = 2.43 / 2.21

/** 画布高度（世界单位）。**必须和 `VIEW_BOX` 的第 4 个数一致** —— 见 `treeTopRatio`。 */
export const VIEW_BOX_HEIGHT = 2.21

/**
 * 这棵树在画布上**实际画出来多高**（0~1，从画布底边算起）。
 *
 * 画布是**固定大小**的（照最极端的那棵树留的量），而树高随完成度变 —— 一棵只读了两份
 * 资料的树只占画布的下半截，上面全是空的。任何要"贴着树顶"放的东西（锁着那棵树的
 * "· · ·"）都必须按这个比例定位：按画布顶放的话，它会飘在树上方一百多像素的地方，
 * 大屏上看着就是**和树脱开了**。
 *
 * 枝头之外还要算树冠：团块的半径会往外胀一圈，只取 `meta.height` 会偏矮。
 */
export function treeTopRatio(tree, detail = 'coarse') {
  let top = 0
  for (const segment of tree.segments) {
    top = Math.max(top, segment.b[1] + segment.b[2] * PROJECT_YZ + segment.r1)
  }
  for (const blob of buildCanopy(tree, detail)) {
    // 1.2：九边形的半径抖动最多到 1.18 倍，取 1.2 盖住。
    top = Math.max(top, blob.center[1] + blob.center[2] * PROJECT_YZ + blob.radius * 1.2)
  }
  // 下限 0.05：一株刚破土的芽也得留出放章节名的位置。
  return Math.min(1, Math.max(0.05, top / VIEW_BOX_HEIGHT))
}

/** 树冠按高度分几档明暗。三档（暗/中/亮）是"低多边形实心团块"那一派的通行做法 ——
 *  冠底压暗、冠顶提亮，模拟顶光，树冠才有体积，不然就是一片平的绿。 */
export const CANOPY_TIERS = 3

/** 一个叶团画成几边形。9 边配上下面的半径抖动，边缘是碎的 —— 正圆看着像气球。 */
const BLOB_SIDES = 9

/** 树冠上色：整团冠画三遍，每往上走一层就上抬、收缩这么多（比例，不是绝对值）。 */
const LAYER_RISE = 0.10
const LAYER_SHRINK = 0.05

/**
 * **焊缝宽度**（占树冠高度的比例）。
 *
 * 用和填充同色的描边把每个团胀大一圈：相邻的团边缘一叠，凹口就补上了，整块冠连成一片；
 * 因为描边和填充同色，**不会出现内部轮廓线**（换成深色描边试过，一冠的碎玻璃）。
 * 不加这道工序，冠就是几个圆球摞在一起，像一棵菜花。
 */
const CANOPY_WELD = 0.05

// 两位小数够了：viewBox 只有 2.9 宽，0.01 世界单位 ≈ 画面的 0.34%，肉眼看不出。
// 三位的话 12 棵树的 path 数据要多出两成，纯属浪费。
const round = (value) => Math.round(value * 100) / 100

/** 世界坐标 → SVG 坐标（y 取负，因为 SVG 的 y 轴向下）。 */
export function project(point) {
  return [point[0] + point[2] * PROJECT_XZ, -(point[1] + point[2] * PROJECT_YZ)]
}

/** 细枝的最小半径。见 `treeGrowth.js` 里"故意画粗"那段 —— 缩略图里没这条底线，细枝就没了。 */
const MIN_BRANCH_RADIUS = 0.008

/**
 * 枝干：**画成带锥度的实心带**，不是等宽线条。
 *
 * 原先按 depth 分组、整组一条 `stroke` + 一个平均 `stroke-width`，于是主干被抹成一根
 * 等粗的柱子（半径从 0.15 收到 0.07，全被平均掉了）—— 看着像猴面包树，不像树。
 * 现在把同一根枝的段**串成一条链**，逐点算切线的垂线、左右各偏一个半径，围成一个多边形，
 * 半径从根到梢线性收细，锥度就出来了。逐帧重算：可见度落在 (0,1) 之间时，链的末点要
 * 插值到段中间，半径也跟着插值 —— 那才是"长了一半"该有的样子。
 *
 * 同一个 `depth` 的链拼进同一条 path（低多边形不做内部描边，重叠处自然融合）。
 */
export function buildBranchPaths(segments, growth) {
  const chains = new Map()
  for (const segment of segments) {
    // 老数据没有 `path` 时退回按 depth 串 —— 至少还能画出来，不会整棵树消失。
    const key = segment.path ?? `d${segment.depth}`
    let chain = chains.get(key)
    if (!chain) { chain = []; chains.set(key, chain) }
    chain.push(segment)
  }

  const groups = new Map()
  for (const chain of chains.values()) {
    const points = [] // [x, y, radius]，屏幕坐标
    for (let i = 0; i < chain.length; i++) {
      const segment = chain[i]
      const visible = segmentVisibility(segment, growth)
      if (visible <= 0) break
      if (i === 0) points.push([...project(segment.a), segment.r0])
      const end = visible >= 1
        ? segment.b
        : [
          segment.a[0] + (segment.b[0] - segment.a[0]) * visible,
          segment.a[1] + (segment.b[1] - segment.a[1]) * visible,
          segment.a[2] + (segment.b[2] - segment.a[2]) * visible,
        ]
      points.push([...project(end), segment.r0 + (segment.r1 - segment.r0) * visible])
    }
    if (points.length < 2) continue // 只冒出个头，还画不出带

    const head = chain[0]
    const key = `${head.depth}-${head.withered ? 'dead' : 'live'}`
    let group = groups.get(key)
    if (!group) {
      group = { key, depth: head.depth, withered: head.withered, d: '', count: 0 }
      groups.set(key, group)
    }
    group.d += ribbon(points)
    group.count += 1
  }
  return [...groups.values()].sort((a, b) => a.depth - b.depth)
}

/** 一条中心线 + 逐点半径 → 闭合的锥形带。切线用前后点之差，端点上退化成单侧方向。 */
function ribbon(points) {
  const left = []
  const right = []
  for (let i = 0; i < points.length; i++) {
    const before = points[Math.max(0, i - 1)]
    const after = points[Math.min(points.length - 1, i + 1)]
    let tx = after[0] - before[0]
    let ty = after[1] - before[1]
    const span = Math.hypot(tx, ty) || 1
    tx /= span
    ty /= span
    const radius = Math.max(points[i][2], MIN_BRANCH_RADIUS)
    left.push([points[i][0] - ty * radius, points[i][1] + tx * radius])
    right.push([points[i][0] + ty * radius, points[i][1] - tx * radius])
  }
  let d = `M${round(left[0][0])} ${round(left[0][1])}`
  for (let i = 1; i < left.length; i++) d += `L${round(left[i][0])} ${round(left[i][1])}`
  for (let i = right.length - 1; i >= 0; i--) d += `L${round(right[i][0])} ${round(right[i][1])}`
  return d + 'Z'
}

/**
 * **把叶子聚成叶团。**
 *
 * 低多边形树冠要的是"一坨一坨的体"，不是一片片散叶 —— 640 片小菱形散开会读成噪点，
 * 一团一团的实心块才读成一棵树（对比页/参考板里好看的树全是这个做法）。
 * 所以这里不逐片画，而是**按枝把叶子聚成团块**，每团画成一个带抖动的九边形。
 *
 * 聚团的粒度取"二级枝"（`path` 形如 `r.2.1`）：再细就碎成一大堆小球，再粗就糊成一整坨。
 *
 * 团块**仍然是从叶子算出来的**，所以"叶 = 成绩"这条语义没丢：答对率低 → 叶少 →
 * 团块又小又少；答对率高 → 团块饱满。
 */
export function buildCanopy(tree, detail = 'fine') {
  const { leaves, tips } = tree
  if (!leaves.length) return []

  // 聚团的粗细**要跟着画出来的尺寸走**。花园里一棵树最宽 124px，198 个团每个才 1.5px，
  // 白算；而且逐帧要重拼 12 棵树的 path 字符串（每帧几百 KB），60fps 撑不住。
  // 反过来，复盘页那种 400px 的大图，团少了就露馅（见下面 fine 那段）。
  //   fine   = 一个挂叶点一团（4 片叶），大图用
  //   coarse = 一根挂叶枝一团，缩略图用 —— 团大、数量少一个量级
  const coarse = detail === 'coarse'

  const groups = new Map()
  for (const leaf of leaves) {
    const tip = tips[leaf.site]
    if (!tip) continue
    // fine 的粒度 = **一个挂叶点**（4 片叶挤在一起，本来就是一小撮）。
    // 踩过的两级：按二级枝聚 → 整棵树只有 8 团、每团半径 0.35，9 边形的边在树冠上
    // 有 100px 长，看着是一堆多边形板子；按三级枝聚 → 17 团，仍然是一块块平板。
    // 树冠要读成叶，就得是**一嘟噜小球密密地叠**，一个球才 15px 上下 —— 密到互相咬住，
    // 轮廓自然就碎了。团多了元素数不变（同档还是拼成一条 path）。
    const key = coarse ? tip.path : String(leaf.site)
    let group = groups.get(key)
    if (!group) { group = []; groups.set(key, group) }
    group.push(leaf)
  }

  const blobs = []
  for (const [key, group] of groups) {
    const center = [0, 0, 0]
    for (const leaf of group) {
      center[0] += leaf.at[0]
      center[1] += leaf.at[1]
      center[2] += leaf.at[2]
    }
    center[0] /= group.length
    center[1] /= group.length
    center[2] /= group.length

    const distances = group
      .map((leaf) => Math.hypot(leaf.at[0] - center[0], leaf.at[1] - center[1], leaf.at[2] - center[2]))
      .sort((a, b) => a - b)
    // 取 75 分位而不是最大距离：最大距离被**离群的一片叶**撑着，团会虚胖一圈。
    const spread = distances[Math.floor((distances.length - 1) * 0.75)]

    // 半径的抖动**一次算好**：每帧重算的话团块边缘会一直抽搐。
    const shape = []
    for (let i = 0; i < BLOB_SIDES; i++) shape.push(0.74 + hash01(key, i) * 0.44)

    blobs.push({
      key,
      center,
      // 要放大到超过叶子的散布范围，让相邻的团互相咬住、连成一整块树冠。
      // 收着画（系数 < 1）的话每团是个独立的球，一眼看过去是"几颗绿球挂在枝上"。
      // 调这个数就是调树冠的松紧。
      radius: spread * 1.6 + 0.055,
      shape,
      t0: Math.min(...group.map((leaf) => leaf.t)),
      t1: Math.max(...group.map((leaf) => leaf.t)),
      count: group.length,
    })
  }

  return blobs
}

/**
 * 每帧：按 `growth` 重算树冠的 `d`。
 *
 * **明暗不是按团块分的，是按"整团冠画几遍"分的。**
 * 踩过两版：按团块的高度分档 → 树冠变成一片深绿浅绿的迷彩块，分界线还是折线；
 * 每个团自己画暗底亮面 → 满树浅绿麻点。两版都不成，因为**明暗该描述的是"光从哪来"，
 * 不是"这块叶子多高"**。现在整团冠连着画 `CANOPY_TIERS` 遍，一遍比一遍往上抬、往里收：
 * 最底下一遍露出来的就成了暗边，往上依次被盖住 —— 光从上面打下来，整个冠是一个体积。
 *
 * `count` 仍然是团块数（每层一样），调用方靠它判断该不该画这一层。
 */
export function buildCanopyPaths(blobs, growth) {
  const layers = []
  for (let i = 0; i < CANOPY_TIERS; i++) layers.push({ key: `canopy-${i}`, tier: i, d: '', count: 0 })
  if (!blobs.length) return layers

  // 上抬量按**树冠自己的高度**取比例，不用绝对数：小苗的冠只有大树的十分之一高，
  // 用固定的世界坐标偏移，小树会被"抬飞"。
  let lowest = Infinity
  let highest = -Infinity
  for (const blob of blobs) {
    lowest = Math.min(lowest, blob.center[1] - blob.radius)
    highest = Math.max(highest, blob.center[1] + blob.radius)
  }
  const span = Math.max(highest - lowest, 1e-6)
  for (const layer of layers) layer.weld = round(span * CANOPY_WELD)

  for (const blob of blobs) {
    const window = Math.max(blob.t1 - blob.t0, 1e-6)
    const visible = Math.min(1, Math.max(0, (growth - blob.t0) / window))
    if (visible <= 0) continue
    // 半径随时间涨大比"淡入"像生长得多
    const grow = 0.25 + 0.75 * visible
    const [cx, cy] = project(blob.center)
    for (let layer = 0; layer < CANOPY_TIERS; layer++) {
      const entry = layers[layer]
      const radius = blob.radius * grow * (1 - LAYER_SHRINK * layer)
      const lift = span * LAYER_RISE * layer
      for (let i = 0; i < BLOB_SIDES; i++) {
        const angle = (i / BLOB_SIDES) * Math.PI * 2
        const r = radius * blob.shape[i]
        // 纵向压扁一点：树冠的团是横宽的，正圆看着像气球
        entry.d += `${i ? 'L' : 'M'}${round(cx + Math.cos(angle) * r)} ${round(cy - lift + Math.sin(angle) * r * 0.82)}`
      }
      entry.d += 'Z'
      entry.count += 1
    }
  }
  return layers
}

/** 地上一圈影。参考板里好看的树都有个"站得住"的底 —— 悬空的树看着像贴纸。 */
export function buildGround(tree) {
  return {
    cy: round(project([0, 0, 0])[1]),
    rx: round(Math.max(tree.meta.radius, 0.35) * 0.78),
    ry: round(Math.max(tree.meta.radius, 0.35) * 0.16),
  }
}

/** 确定性哈希 → [0,1)。用来给团块边缘做固定的抖动。 */
function hash01(text, index) {
  const source = `${text}#${index}`
  let hash = 2166136261
  for (let i = 0; i < source.length; i++) {
    hash ^= source.charCodeAt(i)
    hash = Math.imul(hash, 16777619)
  }
  return ((hash >>> 0) % 1000) / 1000
}

/** 果实：过完关才有，出现得比叶还晚。同样不逐帧重算。 */
export function buildFruitPath(fruits) {
  let d = ''
  let count = 0
  for (const fruit of fruits) {
    const [cx, cy] = project(fruit.at)
    const r = fruit.size
    // 六边形，和叶子的菱形区分开
    const points = []
    for (let i = 0; i < 6; i++) {
      const angle = (i / 6) * Math.PI * 2 + 0.4
      points.push(`${round(cx + Math.cos(angle) * r)} ${round(cy + Math.sin(angle) * r)}`)
    }
    d += `M${points.join('L')}Z`
    count += 1
  }
  return { d, count, from: fruits.length ? Math.min(...fruits.map((f) => f.t)) : 1 }
}

/** 果实整组的透明度：最后一颗结出来时才全亮。 */
export function fruitVisibility(fruitLayer, growth) {
  return Math.min(1, Math.max(0, (growth - fruitLayer.from + 0.08) / 0.12))
}

/**
 * 这棵树在 `growth` 时有多高（世界坐标）。**对 growth 单调不减** —— 靠这条性质做二分。
 */
export function heightAt(tree, growth) {
  let top = 0
  for (const segment of tree.segments) {
    const visible = segmentVisibility(segment, growth)
    if (visible <= 0) continue
    top = Math.max(top, segment.a[1] + (segment.b[1] - segment.a[1]) * visible)
  }
  for (const leaf of tree.leaves) {
    if (leaf.t <= growth) top = Math.max(top, leaf.at[1])
  }
  for (const fruit of tree.fruits) {
    if (fruit.t <= growth) top = Math.max(top, fruit.at[1])
  }
  return top
}

/**
 * 反解：当前这棵树要长到 `growth` 等于多少时，才有 `targetHeight` 那么高。
 *
 * 用途是"**只长新增的那截**"：进页时拿上次看到的高度当靶子，二分出起点，动画就从那儿
 * 跑到 1 —— 于是树一进来就是上次那么大，然后新长的那部分当场抽出来。
 * 拿高度而不是完成度当靶子，是因为两边完成度对应的**骨架不是同一棵**（形状会随完成度
 * 微调），只有高度是可比的量。
 */
export function growthForHeight(tree, targetHeight) {
  if (!(targetHeight > 0)) return 0
  if (heightAt(tree, 1) <= targetHeight) return 1
  let low = 0
  let high = 1
  for (let i = 0; i < 20; i++) {
    const mid = (low + high) / 2
    if (heightAt(tree, mid) < targetHeight) low = mid
    else high = mid
  }
  return high
}
