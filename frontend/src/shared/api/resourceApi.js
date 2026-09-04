import httpClient from './httpClient'

const unwrap = (response) => response?.data?.data ?? response?.data ?? response

export const resourceApi = {
  async list(visibility) {
    const response = await httpClient.get('/resource/list', { params: visibility ? { visibility } : undefined })
    return unwrap(response)
  },

  async favorite(resourceId) {
    return unwrap(await httpClient.post(`/resource/${resourceId}/favorite`))
  },

  async markRead(resourceId, durationSeconds = 1) {
    return unwrap(await httpClient.post(`/study/resource/${resourceId}/mark-read`, null, { params: { duration_seconds: durationSeconds } }))
  },
}
