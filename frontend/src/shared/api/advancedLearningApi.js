import httpClient from './httpClient'

export const advancedLearningApi = {
  getCurrentTask: () => httpClient.get('/learning/advanced/current'),
}
