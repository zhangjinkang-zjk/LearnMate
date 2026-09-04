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

  async listAnnotations(sourceId, sourceType = 'generated') {
    return unwrap(await httpClient.get('/annotation', { params: { source_type: sourceType, source_id: sourceId } }))
  },

  async createAnnotation(resourceId, payload = {}) {
    return unwrap(await httpClient.post('/annotation', {
      source_type: payload.source_type || payload.sourceType || 'generated',
      source_id: payload.source_id || payload.sourceId || resourceId,
      selected_text: payload.selected_text || payload.selectedText || '',
      note_text: payload.note_text || payload.note || '',
      position: payload.position || null,
    }))
  },

  async updateAnnotation(annotationId, payload = {}) {
    return unwrap(await httpClient.put(`/annotation/${annotationId}`, { note_text: payload.note_text || payload.note || '' }))
  },

  async deleteAnnotation(annotationId) {
    return unwrap(await httpClient.delete(`/annotation/${annotationId}`))
  },
}
