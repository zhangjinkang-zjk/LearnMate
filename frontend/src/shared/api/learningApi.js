import httpClient from './httpClient'

export const learningApi = {
  getOverview: () => httpClient.get('/learning/overview'),
  getCurrentPath: () => httpClient.get('/learning_path/current'),
  getStudyStats: () => httpClient.get('/study/stats'),
  getPathStats: () => httpClient.get('/study/path-stats'),
  getMastery: () => httpClient.get('/exam/mastery'),
  getLearningGuidance: () => httpClient.get('/study/learning-guidance'),
  submitDiagnosis: (payload) => httpClient.post('/learning/diagnosis', payload),
  saveDecision: (payload) => httpClient.post('/learning/decisions', payload),
}
