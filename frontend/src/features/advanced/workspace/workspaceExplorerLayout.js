/**
 * 文件面板（IDE 左边那栏）的宽度规则。
 *
 * 只有纯函数，不碰 localStorage、不碰 DOM —— 和 `workspaceDraft.js` / `workspaceSnapshot.js`
 * 同一个路子：读写留在组件里，算数留在这里，于是这条规则能被单独验。
 */

/**
 * 宽度用**像素**记，和右边那条分隔条（对话区）用比例不一样。
 *
 * 这不是不一致，是两码事：右边分的是两块**同等地位**的内容（写代码 / 讨论），窗口变宽
 * 时各让一点才合理；文件面板是个**固定宽度的工具**，窗口从 1400 变到 2000 没人希望
 * 文件树跟着变胖、编辑器反被挤窄。VS Code 同款。
 */
export const EXPLORER_WIDTH_KEY = 'learnmate_advanced_explorer_width'
export const EXPLORER_DEFAULT_WIDTH = 210
export const EXPLORER_MIN_WIDTH = 150
export const EXPLORER_MAX_WIDTH = 480
/** 再宽也不能把编辑器吃掉：最多占这一块的一半。 */
export const EXPLORER_MAX_RATIO = 0.5
export const EXPLORER_STEP = 12
export const EXPLORER_STEP_LARGE = 40

/**
 * 把宽度夹进合法区间。
 *
 * `containerWidth` 传 0（或不传）表示"还不知道容器多宽"—— 读存档时就是这样，这时只按
 * 绝对上限卡。拿到真实宽度之后**必须再夹一次**：只卡 480 是不够的，右边那条分隔条拖到
 * 25% 时工作区只剩几百像素，480 会把编辑器压成一条缝。
 *
 * 容器特别窄（不到 300px）时上限会低于下限 150，所以先 `Math.max(MIN, ...)` 兜一下，
 * 让"下限赢"，宽度永远不会变成负数或 0。
 */
export function clampExplorerWidth(value, containerWidth = 0) {
  if (!Number.isFinite(value)) return EXPLORER_DEFAULT_WIDTH
  const max = containerWidth > 0
    ? Math.min(EXPLORER_MAX_WIDTH, Math.max(EXPLORER_MIN_WIDTH, containerWidth * EXPLORER_MAX_RATIO))
    : EXPLORER_MAX_WIDTH
  return Math.min(max, Math.max(EXPLORER_MIN_WIDTH, value))
}
