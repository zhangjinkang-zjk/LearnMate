import httpClient from './httpClient'

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
