/**
 * 聊天里那三个点的显示条件。
 *
 * **为什么要有这个判据。** 五个聊天框原来都是"只要在流式就一直挂着三个点"，于是屏幕
 * 上同时出现两个"正在回复"的信号：正在长的那条助手气泡，和它下面那串点。内容都已经
 * 读到了、底下还在转，看着像卡住了 —— 学生问的就是这个（"系统正在回复，可是还有三个
 * 点是咋回事"）。五个里最先被报出来的是进阶学习的教练，画像诊断是最后补上的那个：
 * 它出题要等 9–156 秒，整段等待里问题气泡一直在长，底下那串点也就一直挂着。
 *
 * 三个点真正能表达的东西只有一件：**还没开始出字**。第一段文字落下来之后，那条不断
 * 变长的气泡本身就是进度，再多一个点在下面只是噪音。所以判据是：
 *
 * - 不在流式 → 不显示；
 * - 在流式，但最后一条助手消息已经有字 → 不显示（气泡在长呢）；
 * - 在流式，最后一条还没有字（或最后一条是学生自己的）→ 显示。
 *
 * 五种聊天框的消息形状都是 `{role, text}`，所以这一条能共用（流式的标志在各处叫法不同：
 * 基础学习那三处叫 `isStreaming`，悬浮助手和画像诊断叫 `isLoading`，判据只认"在不在流式"，
 * 不认它叫什么名字）。
 * **别再在模板里各写一遍 `v-if="isStreaming"`** —— 那正是它当初漂成五个副本的原因。
 */
export function shouldShowTyping(messages, isStreaming) {
  if (!isStreaming) return false
  const last = Array.isArray(messages) ? messages[messages.length - 1] : null
  const isAssistantWithText = Boolean(last && last.role === 'assistant' && String(last.text || '').trim())
  return !isAssistantWithText
}
