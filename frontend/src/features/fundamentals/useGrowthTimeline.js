/**
 * 一条 `requestAnimationFrame` 驱动一屏所有的树。
 *
 * **为什么不是每棵树一个 rAF**：花园里十几棵树要一起抽条，十几条独立循环各自算各自的
 * 时间、各自触发各自的响应式更新，掉帧时它们还会互相追。一条循环、一个共享的进度值，
 * 所有树都从它派生，天然同步，也只有一个地方要管停。
 *
 * 进花园时树不是"啪"地变成新样子，而是**从上次看到的高度长到当前高度** —— 有落差才有
 * 成就感。落差由调用方算（二分当前骨架，找到和上次一样高的那个生长进度当起点），
 * 这里只负责把 0→1 走完。
 */
import { onBeforeUnmount, ref } from 'vue'

const DURATION = 1500

/** 用户在系统里关了动效就不要再动。这是无障碍，不是性能开关。 */
function prefersReducedMotion() {
  if (typeof window === 'undefined' || !window.matchMedia) return false
  return window.matchMedia('(prefers-reduced-motion: reduce)').matches
}

export function useGrowthTimeline(duration = DURATION) {
  // 默认 1（= 已经长完）：`start()` 之前先把树画成成品，别让页面一进来是十几根光杆。
  const progress = ref(1)
  const reveal = ref(1)
  let frame = 0
  let startedAt = 0

  function stop() {
    if (frame) cancelAnimationFrame(frame)
    frame = 0
  }

  function start() {
    stop()
    if (prefersReducedMotion()) {
      progress.value = 1
      reveal.value = 1
      return
    }
    startedAt = performance.now()
    progress.value = 0
    reveal.value = 0
    const step = () => {
      const k = Math.min(1, (performance.now() - startedAt) / duration)
      // 三次缓出：起步快、收尾稳，像"抽条"而不是匀速平移
      progress.value = 1 - (1 - k) ** 3
      // 果实押后到六成之后才冒头，跟生长错开，两个变化才都看得见
      reveal.value = Math.min(1, Math.max(0, (k - 0.6) / 0.4))
      frame = k < 1 ? requestAnimationFrame(step) : 0
    }
    frame = requestAnimationFrame(step)
  }

  onBeforeUnmount(stop)
  return { progress, reveal, start, stop }
}

export default useGrowthTimeline
