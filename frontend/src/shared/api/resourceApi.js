import httpClient from './httpClient'
import { streamJsonEvents } from './sseClient'

const unwrap = (response) => response?.data?.data ?? response?.data ?? response

function parseDownloadFilename(contentDisposition, fallback) {
  const header = String(contentDisposition || '')
  const encoded = header.match(/filename\*\s*=\s*UTF-8''([^;]+)/i)?.[1]
  if (encoded) {
    try { return decodeURIComponent(encoded) } catch { /* use the regular filename below */ }
  }

  const regular = header.match(/filename\s*=\s*"?([^";]+)"?/i)?.[1]
  if (regular) {
    try { return decodeURIComponent(regular) } catch { return regular }
  }
  return fallback
}

export const resourceApi = {
  async createGenerationTask({ topic, resourceTypes = ['document'], pptThemeId = '' } = {}) {
    const subject = String(topic || '').trim()
    if (!subject) throw new Error('请输入想生成的资料说明')

    const types = Array.from(new Set((Array.isArray(resourceTypes) ? resourceTypes : [])
      .map((type) => String(type || '').trim())
      .filter(Boolean)))
    if (!types.length) throw new Error('请选择资料类型')

    return unwrap(await httpClient.post('/resource/generate/task', {
      topic: subject,
      resource_types: types,
      ...(pptThemeId ? { ppt_theme_id: pptThemeId } : {}),
      save_to_chat_history: false,
    }))
  },

  async createPptTask({ topic, requirements = '', pptThemeId = 'minimal-white' }) {
    const subject = String(topic || '').trim()
    if (!subject) throw new Error('请输入 PPT 主题')

    const detail = String(requirements || '').trim()
    const effectiveTopic = detail ? `${subject}\n\n制作要求：${detail}` : subject
    return unwrap(await httpClient.post('/resource/generate/task', {
      topic: effectiveTopic,
      resource_types: ['ppt'],
      ppt_theme_id: pptThemeId,
      save_to_chat_history: false,
    }))
  },

  async getGenerationTask(taskId) {
    if (!taskId) throw new Error('生成任务标识无效')
    return unwrap(await httpClient.get(`/resource/generate/task/${taskId}`))
  },

  watchGenerationTask(taskId, onEvent, signal) {
    if (!taskId) throw new Error('生成任务标识无效')
    return streamJsonEvents(`/resource/generate/task/${taskId}/stream`, undefined, onEvent, {
      method: 'GET',
      signal,
    })
  },

  async get(resourceId) {
    if (!resourceId) throw new Error('资源标识无效')
    return unwrap(await httpClient.get(`/resource/${resourceId}`))
  },

  async list(visibility) {
    const response = await httpClient.get('/resource/list', { params: visibility ? { visibility } : undefined })
    return unwrap(response)
  },

  async favorite(resourceId) {
    return unwrap(await httpClient.post(`/resource/${resourceId}/favorite`))
  },

  async remove(resourceId) {
    if (!resourceId) throw new Error('资源标识无效')
    return unwrap(await httpClient.delete(`/resource/${resourceId}`))
  },

  async markRead(resourceId, durationSeconds = 1) {
    return unwrap(await httpClient.post(`/study/resource/${resourceId}/mark-read`, null, { params: { duration_seconds: durationSeconds } }))
  },

  async listAnnotations(sourceId, sourceType = 'generated') {
    return unwrap(await httpClient.get('/annotation', {
      params: { source_type: sourceType, source_id: sourceId },
    }))
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
    return unwrap(await httpClient.put(`/annotation/${annotationId}`, {
      note_text: payload.note_text || payload.note || '',
    }))
  },

  async deleteAnnotation(annotationId) {
    return unwrap(await httpClient.delete(`/annotation/${annotationId}`))
  },

  async download(resourceId) {
    if (!resourceId) throw new Error('资源标识无效')
    const response = await httpClient.get(`/resource/${resourceId}/download`, { responseType: 'blob' })
    const contentType = String(response.headers?.['content-type'] || '')
    if (contentType.toLowerCase().includes('application/json')) {
      let message = '资源下载失败'
      try {
        const payload = JSON.parse(await response.data.text())
        message = payload?.msg || payload?.detail || message
      } catch {
        // Keep the generic message when the error body is not valid JSON.
      }
      throw new Error(message)
    }
    return {
      blob: response.data,
      filename: parseDownloadFilename(response.headers?.['content-disposition'], `learning-resource-${resourceId}.md`),
      contentType,
    }
  },
}
