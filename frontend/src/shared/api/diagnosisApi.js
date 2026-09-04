import httpClient from './httpClient'

const unwrap = (response) => response?.data?.data ?? response?.data ?? response

export const diagnosisApi = {
  async start(payload) {
    const response = await httpClient.post('/learning/diagnosis/start', payload)
    return unwrap(response)
  },
  async answer(payload) {
    const response = await httpClient.post('/learning/diagnosis/answer', payload)
    return unwrap(response)
  },
}
