import httpClient from './httpClient'

const unwrap = (response) => response?.data?.data ?? response?.data ?? response

// 这一问单独放宽超时：httpClient 全局是 15 秒，而访谈下一问实测要 ~50 秒
// （模型本身慢，不是提示词长），沿用全局值会让请求必然被 axios 掐断、
// 后端生成的那一版永远拿不到。页面本身不等它（先显示本地兜底题），
// 这里只是给它一个能跑完的机会。后端 INTERVIEW_LLM_TIMEOUT_SECONDS 是 75。
const INTERVIEW_TIMEOUT_MS = 90000

export const getNextPortraitInterviewQuestion = async (payload) => {
  const response = await httpClient.post('/ai_portrait/interview/next', payload, { timeout: INTERVIEW_TIMEOUT_MS })
  return unwrap(response)
}

export const initPortraitFromDialogue = async (payload) => {
  const response = await httpClient.post('/ai_portrait/init_from_dialogue', payload)
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
