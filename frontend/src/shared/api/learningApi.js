import httpClient from './httpClient'

export const learningApi = {
  getOverview: () => httpClient.get('/learning/overview'),
  getCurrentPath: () => httpClient.get('/learning_path/current'),
  generatePath: (subject, forceRegenerate = false) => httpClient.post('/path/generate', { subject, difficulty: 'medium', node_count: 0, force_regenerate: forceRegenerate }),
  regeneratePath: (pathId) => httpClient.post('/path/regenerate', { path_id: pathId }),
  // 路径拆解和节点生成包含多次 LLM 调用，使用独立长超时，不改变普通接口的 15 秒超时。
  generatePathsFromDirection: (direction = '', goal = '', forceRegenerate = false) => httpClient.post('/path/generate-from-direction', { direction, goal, subject_limit: 4, difficulty: 'medium', node_count: 0, force_regenerate: forceRegenerate }, { timeout: 300000 }),
  getStudyStats: () => httpClient.get('/study/stats'),
  getPathStats: () => httpClient.get('/study/path-stats'),
  getMastery: () => httpClient.get('/exam/mastery'),
  getLearningGuidance: () => httpClient.get('/study/learning-guidance'),
  getExamWeekly: () => httpClient.get('/study/exam-weekly'),
  submitDiagnosis: (payload) => httpClient.post('/learning/diagnosis', payload),
  saveDecision: (payload) => httpClient.post('/learning/decisions', payload),
}
