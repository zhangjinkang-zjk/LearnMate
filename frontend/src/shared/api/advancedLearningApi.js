import httpClient from './httpClient'

export const advancedLearningApi = {
  // 智能体生成跑在后台：这个接口立刻返回（首次会带 task_source='pending'），
  // 页面按 generation_status 轮询到结果落定为止，所以不需要长超时。
  // refresh=true 只给**用户手点**的按钮用（重新同步 / 重新生成）：服务端会绕过兜底
  // 重试冷却，强制重跑一次生成作业。自动轮询绝不能带 —— 每 3 秒一发会白烧调用。
  getCurrentTask: (refresh = false) => httpClient.get('/learning/advanced/current', {
    params: refresh ? { refresh: true } : undefined,
    timeout: 15000,
  }),
  openPracticeSession: (payload) => httpClient.post('/learning/advanced/practice/sessions', payload),
  getPracticeSession: (sessionId) => httpClient.get(`/learning/advanced/practice/sessions/${sessionId}`),
  savePracticeSession: (sessionId, payload) => httpClient.patch(`/learning/advanced/practice/sessions/${sessionId}`, payload),
  endPracticeSession: (sessionId) => httpClient.post(`/learning/advanced/practice/sessions/${sessionId}/end`),
}
