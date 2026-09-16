import httpClient from './httpClient'

export const learningApi = {
  getOverview: () => httpClient.get('/study/overview'),
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
  // 诊断走 diagnosisApi（/learning/diagnosis/start|answer|…/stream）。
  // 这里曾有一个 POST /learning/diagnosis，但后端只注册了子路径，调用必 404。
}
