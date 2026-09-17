import httpClient from './httpClient'
import { streamJsonEvents } from './sseClient'

const unwrap = (response) => response?.data?.data ?? response?.data ?? response

// 非流式的那版：整段生成完才返回，实测要 ~50 秒，httpClient 全局 15 秒必然掐断，
// 单独放宽到这里。页面已经改走下面的流式版，这个接口留着给需要一次拿全的地方用。
const INTERVIEW_TIMEOUT_MS = 90000

export const getNextPortraitInterviewQuestion = async (payload) => {
  const response = await httpClient.post('/ai_portrait/interview/next', payload, { timeout: INTERVIEW_TIMEOUT_MS })
  return unwrap(response)
}

// 访谈下一问的流式版：题面边写边推，第一个字就是问题本身。
//
// 以前是整段返回，前端只能先垫一句本地模板、等模型那版回来再替换。模型要几十秒，
// 学生通常已经动笔，替换条件判不成立 —— 屏幕上留下的永远是那句模板，看起来就是
// "题目是写死的"（同一句还反复出现）。流式之后屏幕上的题面就是模型写的，
// 慢也只慢在第一个字之前，不再是"模型写了但轮不到它"。
export const streamNextPortraitInterviewQuestion = (payload, onEvent, options = {}) => (
  streamJsonEvents('/ai_portrait/interview/next/stream', payload, onEvent, options)
)

// 总结页那一次画像抽取（访谈 + 基础测评 → 综合画像）走的是模型的整段生成：
// 后端给它留的是 PORTRAIT_LLM_TIMEOUT_SECONDS（默认 40 秒），而 httpClient 全局
// 只有 15 秒 —— 这个模型光第一个字就要二十几到三十几秒，于是请求**必然**被浏览器
// 先掐断：后端其实跑完了、画像也落库了，只是没人接。总结页看到的就是"画像分析
// 没有完成"加一个点了也永远不会成功的"重新生成画像"按钮。
// 这里给它一个跑得完的超时，比后端预算再宽一档（后端是那个该决定何时放弃的地方，
// 它有降级路径；客户端只负责别抢在它前面）。
const PORTRAIT_TIMEOUT_MS = 90000

export const initPortraitFromDialogue = async (payload) => {
  const response = await httpClient.post('/ai_portrait/init_from_dialogue', payload, { timeout: PORTRAIT_TIMEOUT_MS })
  return unwrap(response)
}

export const readPortrait = async () => {
  const response = await httpClient.get('/ai_portrait/read_portrait')
  return unwrap(response)
}

export const readPortraitRadar = async () => {
  const response = await httpClient.get('/ai_portrait/radar')
  return unwrap(response)
}
