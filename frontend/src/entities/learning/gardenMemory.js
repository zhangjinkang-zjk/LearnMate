/**
 * 「上次看这棵树时，它有多高」的记忆 —— 只为了让学习花园**把新长的那截演给学生看**。
 *
 * 进花园时如果树只是"啪"地变成新样子，那学生看不见成长；真正有成就感的是**亲眼看见
 * 它长**。所以要有个"上次的样子"做参照，从那个高度长到当前高度。
 *
 * **这不是学习数据，是界面状态。** 它只记"这个用户上次看这棵树时它多高"，
 * 丢了顶多第一次进页不播生长动画，没有任何业务后果。服务端返回的完成度/答题结果
 * 才是唯一的真源（AGENTS §4：localStorage 只能当临时缓存）。
 *
 * 存的是**高度**而不是完成度：动画起点要的是"当前这棵树长到多高时，和上次一样高"，
 * 拿高度直接二分就能匹配上；存完成度的话还得拿当前节点数据去反推一棵旧树，多一层猜。
 */
const KEY = 'learnmate_garden_seen'
const VERSION = 1

/** 读回上次记录的各节点高度。坏了/没有/换了版本一律当空的，不抛。 */
export function loadSeenHeights() {
  try {
    const raw = JSON.parse(localStorage.getItem(KEY) || 'null')
    if (!raw || raw.v !== VERSION || typeof raw.nodes !== 'object' || raw.nodes === null) return {}
    return raw.nodes
  } catch {
    // 隐私模式、配额满、被手改坏 —— 都只是没有记忆，不该让页面挂掉
    return {}
  }
}

/** 覆盖写。写不进去（隐私模式/配额满）就算了，不抛。 */
export function saveSeenHeights(nodes) {
  try {
    localStorage.setItem(KEY, JSON.stringify({ v: VERSION, nodes }))
  } catch {
    /* 记不住就记不住，下次进来顶多不播生长动画 */
  }
}
