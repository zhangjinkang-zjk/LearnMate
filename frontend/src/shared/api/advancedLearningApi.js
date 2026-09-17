import httpClient from './httpClient'

export const advancedLearningApi = {
  // 智能体生成跑在后台：这个接口立刻返回（首次会带 task_source='pending'），
  // 页面按 generation_status 轮询到结果落定为止，所以不需要长超时。
  getCurrentTask: () => httpClient.get('/learning/advanced/current', { timeout: 15000 }),
  openPracticeSession: (payload) => httpClient.post('/learning/advanced/practice/sessions', payload),
  getPracticeSession: (sessionId) => httpClient.get(`/learning/advanced/practice/sessions/${sessionId}`),
  savePracticeSession: (sessionId, payload) => httpClient.patch(`/learning/advanced/practice/sessions/${sessionId}`, payload),
  endPracticeSession: (sessionId) => httpClient.post(`/learning/advanced/practice/sessions/${sessionId}/end`),
  submitPracticeSession: (sessionId, payload) => httpClient.post(`/learning/advanced/practice/sessions/${sessionId}/submit`, payload),
}
