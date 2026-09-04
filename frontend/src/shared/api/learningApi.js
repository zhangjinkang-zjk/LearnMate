import httpClient from './httpClient'

export const learningApi = {
  getOverview: () => httpClient.get('/learning/overview'),
  submitDiagnosis: (payload) => httpClient.post('/learning/diagnosis', payload),
  saveDecision: (payload) => httpClient.post('/learning/decisions', payload),
}
