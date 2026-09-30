/**
 * 聊天输入框的发送键。
 *
 * **为什么要有这个文件。** 五个 composer 原来各写各的：开场对话（`LearnmateChatView`）
 * 用的是单行 `<input>`，在表单里**普通回车就能发**；另外四个用的是 `<textarea>`，只绑了
 * `@keydown.ctrl.enter`，普通回车是换行。于是同一个应用里同时存在两套发送键 —— 学生在
 * 开场里养成的习惯，进到课堂 / 浮层助手就变成"按回车没反应"。
 *
 * 现在统一成聊天应用通行的那一套：**Enter 发送，Shift + Enter 换行**。
 * Ctrl / Cmd + Enter 保留（老习惯，另外粘长文本时不想发出去也用它）。
 *
 * 这四个调用点长得一模一样，所以抽出来；**别再在模板里手写 `@keydown.enter`** ——
 * 下面那个输入法判断漏一处，中文用户就会觉得"打字打到一半自己发出去了"。
 */

/**
 * 这次回车该不该当成"发送"。
 *
 * 三个判断都不能省：
 *
 * 1. **输入法组合期间不算发送。** 用拼音打字时，回车是"确认候选词"，不是发送 —— 少了
 *    这一条，每确认一个词就把半句话发出去。Chromium / Firefox 在组合期间派发的 keydown
 *    会把 `isComposing` 置为真，老实现只给 `keyCode === 229`，两个都查。
 * 2. **`shiftKey` 让路**，交给浏览器插入换行。
 * 3. **`altKey` 让路** —— Alt + Enter 在各平台另有含义，不去抢。
 *
 * Ctrl / Cmd 不作限制：它和普通回车的效果一样（都发送），拦掉反而要让调用方写两遍。
 */
export function shouldSendOnKeydown(event) {
  if (!event || event.key !== 'Enter') return false
  if (event.isComposing || event.keyCode === 229) return false
  if (event.shiftKey || event.altKey) return false
  return true
}
