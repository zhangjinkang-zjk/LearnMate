import httpClient from './httpClient'

export const advancedLearningApi = {
  // A new ten-node milestone may perform one bounded agent generation before the snapshot is saved.
  getCurrentTask: () => httpClient.get('/learning/advanced/current', { timeout: 60000 }),
  openPracticeSession: (payload) => httpClient.post('/learning/advanced/practice/sessions', payload),
  getPracticeSession: (sessionId) => httpClient.get(`/learning/advanced/practice/sessions/${sessionId}`),
  savePracticeSession: (sessionId, payload) => httpClient.patch(`/learning/advanced/practice/sessions/${sessionId}`, payload),
  endPracticeSession: (sessionId) => httpClient.post(`/learning/advanced/practice/sessions/${sessionId}/end`),
  submitPracticeSession: (sessionId, payload) => httpClient.post(`/learning/advanced/practice/sessions/${sessionId}/submit`, payload),
}
