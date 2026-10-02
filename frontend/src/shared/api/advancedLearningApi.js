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
  // 把官方文档抓下来，返回一组可以直接落盘的文件（正文在 data.files[].markdown）。
  //
  // `frameworks` 是注册表里的标识（服务端展开成挑好的那几页），`urls` 是教练自己找的
  // 官方文档页地址 —— 表里没有的技术走后者。
  //
  // **这个接口是慢的**：服务端要并发抓最多 12 页官网正文，单页上限 8 秒。用默认超时会
  // 在抓到一半时断开，而断开的表现和"没有这些文档"一模一样 —— 学生会以为读不到，
  // 其实只是超时。所以这里显式放宽。
  fetchReferenceDocs: (frameworks, urls = []) => httpClient.post(
    '/learning/advanced/reference-docs',
    { frameworks, urls },
    { timeout: 60000 },
  ),
}
