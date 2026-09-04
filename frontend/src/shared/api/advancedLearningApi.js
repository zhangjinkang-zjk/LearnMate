import httpClient from './httpClient'

export const advancedLearningApi = {
  // A new ten-node milestone may perform one bounded agent generation before the snapshot is saved.
  getCurrentTask: () => httpClient.get('/learning/advanced/current', { timeout: 60000 }),
}
